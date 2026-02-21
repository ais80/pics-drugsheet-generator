#!/bin/bash
echo "=========================================="
echo "  PICS Drug Sheet Generator"
echo "  Non-infusion Drugsheet v3.6"
echo "=========================================="
echo ""
echo "Starting application..."

cd "$(dirname "$0")/bnf-mcp"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
else
    echo "ERROR: Virtual environment not found."
    echo "Run: cd bnf-mcp && uv venv && uv add streamlit pdfplumber fastmcp beautifulsoup4 requests httpx pandas openpyxl xlrd python-docx"
    exit 1
fi

echo "Opening browser..."
xdg-open "http://localhost:8501" 2>/dev/null || open "http://localhost:8501" 2>/dev/null &

streamlit run app.py --server.port 8501 --server.headless true
