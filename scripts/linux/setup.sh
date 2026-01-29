#!/bin/bash
# Setup script for RAG Librarian on Linux/macOS

echo "Setting up RAG Librarian environment..."

# Create library structure
LIBRARY_ROOT="rag_library"
DIRS=(
    "$LIBRARY_ROOT/corpora/cyber_blue/inbox"
    "$LIBRARY_ROOT/corpora/writing_red/inbox"
    "$LIBRARY_ROOT/corpora/dm_green/inbox"
    "$LIBRARY_ROOT/state"
    "$LIBRARY_ROOT/cache/ocr"
    "$LIBRARY_ROOT/.locks"
)

for DIR in "${DIRS[@]}"; do
    if [ ! -d "$DIR" ]; then
        mkdir -p "$DIR"
        echo "Created $DIR"
    fi
done

# Create corpus.yaml for each corpus
CORPORA=("cyber_blue" "writing_red" "dm_green")
for CORPUS in "${CORPORA[@]}"; do
    PATH_FILE="$LIBRARY_ROOT/corpora/$CORPUS/corpus.yaml"
    if [ ! -f "$PATH_FILE" ]; then
        INBOX_PATH="$LIBRARY_ROOT/corpora/$CORPUS/inbox"
        cat > "$PATH_FILE" << EOF
corpus_id: $CORPUS
description: "Content for $CORPUS"
source_path: "$INBOX_PATH"
retain_on_missing: true
models:
  answer:
    provider: "ollama"
    model: "llama3"
chunking:
  default:
    strategy: "pdf_sections"
    max_tokens: 700
    overlap_tokens: 80
EOF
        echo "Created defaults for $CORPUS"
    fi
done

# Install dependencies
if [ -f "pyproject.toml" ]; then
    echo "Installing dependencies..."
    pip install .
fi

echo "Setup complete."
