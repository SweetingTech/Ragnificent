#!/bin/bash
# Run the RAG Librarian API server

set -euo pipefail

VECTOR_DB_URL="$(awk '
  /^vector_db:[[:space:]]*$/ { in_vector=1; next }
  in_vector && /^[^[:space:]]/ { in_vector=0 }
  in_vector && /^[[:space:]]+url:[[:space:]]*/ {
    sub(/^[[:space:]]+url:[[:space:]]*/, "", $0)
    print $0
    exit
  }
' config.yaml 2>/dev/null || true)"

if [[ "$VECTOR_DB_URL" =~ ^http://(localhost|127\.0\.0\.1):6333/?$ ]]; then
  if command -v docker >/dev/null 2>&1; then
    if docker ps >/dev/null 2>&1; then
      echo "Ensuring Qdrant is running..."
      docker compose up -d qdrant || echo "Warning: failed to start Qdrant with docker compose."
    else
      echo "Warning: Docker daemon is not available. Qdrant was not auto-started."
    fi
  else
    echo "Warning: Docker CLI not found. Qdrant was not auto-started."
  fi
fi

export PYTHONPATH="."
python -m app.cli --config config.yaml serve
