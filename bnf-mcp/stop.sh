#!/bin/bash
# Stop the PICS Drug Sheet Generator
if lsof -t -i:8000 >/dev/null 2>&1; then
    kill $(lsof -t -i:8000) 2>/dev/null
    echo "Drug Sheet Generator stopped."
else
    echo "Server is not running."
fi
