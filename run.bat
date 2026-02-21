@echo off
title PICS Drug Sheet Generator
echo ==========================================
echo   PICS Drug Sheet Generator
echo   Non-infusion Drugsheet v3.6
echo ==========================================
echo.
echo Starting application...
echo.

cd /d "%~dp0bnf-mcp"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo ERROR: Virtual environment not found.
    echo Run: cd bnf-mcp ^&^& uv venv ^&^& uv add streamlit pdfplumber fastmcp beautifulsoup4 requests httpx pandas openpyxl xlrd python-docx
    pause
    exit /b 1
)

echo Opening browser...
start "" "http://localhost:8501"

streamlit run app.py --server.port 8501 --server.headless true

pause
