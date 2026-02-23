FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/Drugsheets

COPY bnf-mcp/pyproject.toml bnf-mcp/pyproject.toml
RUN cd bnf-mcp && uv pip install --system --no-cache -r pyproject.toml

COPY bnf-mcp/generate.py bnf-mcp/generate.py
COPY bnf-mcp/app.py bnf-mcp/app.py
COPY Knowledge_base/ Knowledge_base/

RUN mkdir -p output

WORKDIR /app/Drugsheets/bnf-mcp

EXPOSE 8080

CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
