# Navigate to the project root (two levels up from scripts/windows/)
$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot"

Write-Host "Setting up RAG Librarian environment..."

# Create library structure
$LibraryRoot = "rag_library"
$Dirs = @(
    "$LibraryRoot/corpora/cyber_blue/inbox",
    "$LibraryRoot/corpora/writing_red/inbox",
    "$LibraryRoot/corpora/dm_green/inbox",
    "$LibraryRoot/corpora/general/inbox",
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

# Create top-level ingest drop folder
if (-not (Test-Path "ingest")) {
    New-Item -ItemType Directory -Force -Path "ingest" | Out-Null
    Write-Host "Created ingest/ (drop files here for general ingestion)"
}

# Create corpus.yaml for the named corpora
$Corpora = @("cyber_blue", "writing_red", "dm_green")
foreach ($Corpus in $Corpora) {
    $Path = "$LibraryRoot/corpora/$Corpus/corpus.yaml"
    if (-not (Test-Path $Path)) {
        $Content = @"
corpus_id: $Corpus
description: "Content for $Corpus"
retain_on_missing: true
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

# Create general corpus if missing
$GeneralPath = "$LibraryRoot/corpora/general/corpus.yaml"
if (-not (Test-Path $GeneralPath)) {
    $Content = @"
corpus_id: general
description: >
  General-purpose ingest corpus.
  Drop files in the top-level ingest/ folder, or pass any source_path
  to POST /api/ingest/run to process files from any directory.
retain_on_missing: true
source_path: "ingest"
chunking:
  default:
    strategy: "pdf_sections"
    max_tokens: 700
    overlap_tokens: 80
models:
  answer:
    provider: "ollama"
    base_url: "http://localhost:11434"
    model: "llama3"
"@
    Set-Content -Path $GeneralPath -Value $Content
    Write-Host "Created defaults for general"
}

# Install dependencies
if (Test-Path "pyproject.toml") {
    Write-Host "Installing dependencies..."
    pip install .
}

Write-Host "Setup complete."
