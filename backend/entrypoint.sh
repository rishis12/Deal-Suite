#!/bin/bash
echo "=== Deal Suite API starting (/lbo + /ma) ==="
echo "Date: $(date)"

# Long keep-alive: a /generate run (fetch + LibreOffice recalculation +
# optional LLM call) can legitimately take 20-40+ seconds.
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --timeout-keep-alive 180
