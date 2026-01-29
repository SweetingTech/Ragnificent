#!/bin/bash
# Run the RAG Librarian API server

export PYTHONPATH="."
python -m app.cli --config config.yaml serve
