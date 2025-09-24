#!/bin/bash

# Dashboard startup script
export INGEST_KEY="super-long-random-string-12345"
export USE_INGEST=true
export VERBOSE_INGEST=${VERBOSE_INGEST:-0}  # Default to quiet mode
export FLASK_APP=dashboard.py

echo "🚀 Starting E-Trike Dashboard..."
echo "✅ INGEST_KEY: ${INGEST_KEY:0:10}..."
echo "✅ USE_INGEST: $USE_INGEST"
echo "✅ VERBOSE_INGEST: $VERBOSE_INGEST"
echo ""

flask run
