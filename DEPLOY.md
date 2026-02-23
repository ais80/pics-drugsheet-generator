# PICS Drug Sheet Generator — Setup & Deployment Guide

## Quick Start (any computer)

### Option 1: Streamlit Cloud (easiest — already deployed)

The app is live at: **https://picsdrugsheetgenerator.streamlit.app**

Nothing to install. Works on any locked-down PC with a browser.

To redeploy after code changes, push to GitHub and Streamlit Cloud auto-updates:
```bash
git add -A && git commit -m "your message" && git push origin master
```

### Option 2: Run locally (requires Python 3.12+)

```bash
cd Drugsheets/bnf-mcp
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501

### Option 3: Clone from GitHub (any new computer)

```bash
git clone https://github.com/ais80/pics-drugsheet-generator.git
cd pics-drugsheet-generator/bnf-mcp
pip install -r requirements.txt
streamlit run app.py
```

---

## Project Structure

```
Drugsheets/
├── bnf-mcp/
│   ├── app.py              ← Streamlit web app (the deployed app)
│   ├── generate.py         ← Core engine (scrapes BNF/EMC/Formulary, runs analysis)
│   ├── requirements.txt    ← Python dependencies for Streamlit Cloud
│   ├── pyproject.toml      ← Full dependency spec (with optional dev deps)
│   ├── api.py              ← FastAPI alternative backend (for Cloud Run)
│   ├── static/             ← FastAPI frontend (alternative to Streamlit)
│   ├── server.py           ← BNF-Pro MCP server
│   ├── emc_server.py       ← EMC SmPC MCP server
│   ├── dmd_server.py       ← dm+d MCP server
│   └── formulary_server.py ← Birmingham Formulary MCP server
├── Knowledge base/         ← Source Excel files (drug classes, ICD-10, forms/routes)
│   └── cleaned/            ← Cleaned versions
├── Dockerfile              ← Docker build for Cloud Run deployment
├── .dockerignore
├── requirements.txt        ← Root-level deps (backup)
├── CLAUDE.md               ← Project documentation for AI assistants
└── DEPLOY.md               ← This file
```

---

## Transferring to Another Computer

### Via Google Drive
1. Copy the entire `Drugsheets/` folder to Google Drive
2. On the new PC, download it
3. Open a terminal in `Drugsheets/bnf-mcp/` and run:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

### Via GitHub
```bash
git clone https://github.com/ais80/pics-drugsheet-generator.git
cd pics-drugsheet-generator/bnf-mcp
pip install -r requirements.txt
streamlit run app.py
```

### Via USB / zip
Just copy the folder. All dependencies are listed in `requirements.txt` — run `pip install -r requirements.txt` on the new machine.

---

## Streamlit Cloud Deployment

The app is deployed via https://share.streamlit.io connected to the GitHub repo.

**Settings:**
- Repository: `ais80/pics-drugsheet-generator`
- Branch: `master`
- Main file path: `bnf-mcp/app.py`

**To update:** Push changes to GitHub. Streamlit Cloud auto-redeploys.

**To redeploy manually:** Go to https://share.streamlit.io > your app > "Reboot app"

---

## Google Cloud Run Deployment (alternative)

For a Docker-based deployment (heavier, but more control):

### 1. Rename Knowledge base folder (Docker can't handle spaces)
```bash
mv "Knowledge base" Knowledge_base
```

### 2. Build and deploy
```bash
export PROJECT_ID="pics-drugsheet"
gcloud services enable cloudbuild.googleapis.com run.googleapis.com

gcloud builds submit --tag gcr.io/$PROJECT_ID/pics-drugsheet-generator .

gcloud run deploy pics-drugsheet-generator \
    --image gcr.io/$PROJECT_ID/pics-drugsheet-generator \
    --platform managed --region europe-west2 \
    --allow-unauthenticated --memory 1Gi --cpu 1 \
    --timeout 300 --max-instances 5 --min-instances 0 --port 8080
```

---

## Development

### Install dev dependencies (includes MCP servers, docx support)
```bash
cd Drugsheets/bnf-mcp
pip install -e ".[dev]"
```

### Run MCP servers locally
```bash
uv run server.py        # BNF-Pro
uv run emc_server.py    # EMC SmPC
uv run dmd_server.py    # dm+d
uv run formulary_server.py  # Birmingham Formulary
```

### Push changes
```bash
cd Drugsheets
git add -A
git commit -m "description of changes"
git push origin master
```
Streamlit Cloud auto-redeploys after push.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| Streamlit Cloud deploy fails | Check `bnf-mcp/requirements.txt` has all deps |
| Knowledge base not found | Ensure `Knowledge base/` folder is present with Excel files |
| Generation times out | BNF/EMC websites may be slow — retry |
| Progress bar stuck | Check terminal for errors |
