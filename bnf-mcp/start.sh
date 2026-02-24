#!/bin/bash
# Start the PICS Drug Sheet Generator (FastAPI)
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$PATH"

# Check if already running
if lsof -t -i:8000 >/dev/null 2>&1; then
    echo "Server is already running on http://127.0.0.1:8000"
    echo "Opening browser..."
    xdg-open http://127.0.0.1:8000 2>/dev/null &
    exit 0
fi

echo "Starting PICS Drug Sheet Generator..."
echo ""

# Open browser after a short delay
(sleep 2 && xdg-open http://127.0.0.1:8000 2>/dev/null) &

# Run server (stays in foreground so terminal stays open)
uvicorn api:app --host 127.0.0.1 --port 8000
