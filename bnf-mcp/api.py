"""
PICS Drug Sheet Generator — FastAPI Web App
Wraps generate.py engine with SSE streaming and file download endpoints.
"""

import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, StreamingResponse

from generate import generate_drugsheet, generate_epma_json, generate_review_markdown, search_drug_names

app = FastAPI(title="PICS Drug Sheet Generator")

# ---------------------------------------------------------------------------
# In-memory result store (UUID -> {data, created_at})
# Results expire after 30 minutes
# ---------------------------------------------------------------------------
_results: dict[str, dict] = {}
_TTL_SECONDS = 30 * 60


def _cleanup_expired():
    """Remove results older than TTL."""
    now = time.time()
    expired = [k for k, v in _results.items() if now - v["created_at"] > _TTL_SECONDS]
    for k in expired:
        del _results[k]


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------
def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/search")
async def api_search(q: str = ""):
    """Search BNF drug list for matching drug names."""
    if len(q.strip()) < 2:
        return {"results": []}
    matches = search_drug_names(q.strip(), max_results=10)
    return {"results": [{"name": m["name"], "slug": m.get("slug", "")} for m in matches]}


@app.post("/api/generate")
async def api_generate(
    drug_name: str = Form(...),
    drug_form: str = Form(None),
    pdfs: list[UploadFile] = File(None),
):
    """Generate a drug sheet with SSE progress streaming."""

    async def event_stream():
        progress_messages = []

        def progress_callback(msg: str):
            progress_messages.append(msg)

        # Build uploaded_pdfs list
        uploaded_pdfs = []
        if pdfs:
            for pdf_file in pdfs:
                if pdf_file.filename and pdf_file.size and pdf_file.size > 0:
                    content = await pdf_file.read()
                    uploaded_pdfs.append({"bytes": content, "name": pdf_file.filename})

        # Send initial progress
        yield _sse_event("progress", {"message": "Starting generation...", "percent": 0})

        # Progress steps with approximate percentages
        step_percents = {
            "Processing uploaded documents...": 5,
            "Gathering data from BNF, EMC, and Formulary...": 10,
            "Checking controlled drug status...": 40,
            "Mapping drug classes...": 50,
            "Analyzing contraindications and ICD-10 mappings...": 60,
            "Analyzing interactions...": 70,
            "Extracting unconditional messages...": 75,
            "Extracting result warnings...": 80,
            "Extracting forms, routes, and dose limits...": 85,
            "Compiling formulary details...": 90,
            "Done!": 100,
        }

        last_sent = 0

        def streaming_callback(msg: str):
            nonlocal last_sent
            progress_callback(msg)
            # We can't yield from here directly, so we track messages
            # and the polling loop below will pick them up.

        # Run generation in a background task so we can stream progress
        loop = asyncio.get_event_loop()
        gen_task = asyncio.create_task(
            generate_drugsheet(
                drug_name=drug_name,
                drug_form=drug_form if drug_form else None,
                uploaded_pdfs=uploaded_pdfs if uploaded_pdfs else None,
                progress_callback=streaming_callback,
            )
        )

        # Poll for progress messages while generation runs
        while not gen_task.done():
            await asyncio.sleep(0.3)
            while len(progress_messages) > last_sent:
                msg = progress_messages[last_sent]
                pct = step_percents.get(msg, min(last_sent * 10, 95))
                yield _sse_event("progress", {"message": msg, "percent": pct})
                last_sent += 1

        # Flush remaining progress messages
        while len(progress_messages) > last_sent:
            msg = progress_messages[last_sent]
            pct = step_percents.get(msg, 100)
            yield _sse_event("progress", {"message": msg, "percent": pct})
            last_sent += 1

        # Get result (may raise)
        try:
            drugsheet = gen_task.result()
        except Exception as e:
            yield _sse_event("error", {"message": str(e)})
            return

        # Generate outputs
        review_md = generate_review_markdown(drugsheet)
        epma_json = generate_epma_json(drugsheet)

        # Store for download
        _cleanup_expired()
        result_id = str(uuid.uuid4())
        _results[result_id] = {
            "drugsheet": drugsheet,
            "markdown": review_md,
            "epma_json": epma_json,
            "drug_name": drug_name,
            "created_at": time.time(),
        }

        # Send complete event
        yield _sse_event(
            "complete",
            {
                "id": result_id,
                "drug_name": drug_name,
                "markdown": review_md,
                "epma_json": epma_json,
                "raw_data": drugsheet,
                "human_review_flags": drugsheet.get("human_review_flags", []),
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download/{result_id}/markdown")
async def download_markdown(result_id: str):
    """Download the human-review markdown file."""
    _cleanup_expired()
    result = _results.get(result_id)
    if not result:
        return PlainTextResponse("Result not found or expired", status_code=404)

    drug_name = result["drug_name"].replace(" ", "_")
    return Response(
        content=result["markdown"],
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{drug_name}_drugsheet.md"'
        },
    )


@app.get("/api/download/{result_id}/json")
async def download_json(result_id: str):
    """Download the EPMA JSON file."""
    _cleanup_expired()
    result = _results.get(result_id)
    if not result:
        return PlainTextResponse("Result not found or expired", status_code=404)

    drug_name = result["drug_name"].replace(" ", "_")
    content = json.dumps(result["epma_json"], indent=2, default=str)
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{drug_name}_epma.json"'
        },
    )


# ---------------------------------------------------------------------------
# Static files — serve frontend (must be mounted LAST)
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
