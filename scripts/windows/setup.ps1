Write-Host "Setting up RAG Librarian environment..."

# Create library structure
$LibraryRoot = "rag_library"
$Dirs = @(
    "$LibraryRoot/corpora/cyber_blue/inbox",
    "$LibraryRoot/corpora/writing_red/inbox",
    "$LibraryRoot/corpora/dm_green/inbox",
    "$LibraryRoot/state",
    "$LibraryRoot/cache/ocr",
    "$LibraryRoot/.locks"
)

foreach ($Dir in $Dirs) {
    if (-not (Test-Path $Dir)) {
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        Write-Host "Created $Dir"
    }
}

# Create corpus.yaml for each corpus
$Corpora = @("cyber_blue", "writing_red", "dm_green")
foreach ($Corpus in $Corpora) {
    $Path = "$LibraryRoot/corpora/$Corpus/corpus.yaml"
    if (-not (Test-Path $Path)) {
        $InboxPath = "$LibraryRoot/corpora/$Corpus/inbox"
        $Content = @"
corpus_id: $Corpus
description: "Content for $Corpus"
source_path: "$InboxPath"
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
"@
        Set-Content -Path $Path -Value $Content
        Write-Host "Created defaults for $Corpus"
    }
}

# Install dependencies
if (Test-Path "pyproject.toml") {
    Write-Host "Installing dependencies..."
    pip install .
}

Write-Host "Setup complete."
