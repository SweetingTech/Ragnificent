param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$templatePath = Join-Path $ProjectRoot "docs\voltron-repository-docs.corpus.yaml"
$corpusDirectory = Join-Path $ProjectRoot "rag_library\corpora\voltron-repository-docs"
$targetPath = Join-Path $corpusDirectory "corpus.yaml"

if (-not (Test-Path -LiteralPath $templatePath)) {
  throw "Missing repository-docs corpus template: $templatePath"
}

if ((Test-Path -LiteralPath $targetPath) -and -not $Force) {
  Write-Host "Repository-docs corpus already exists: $targetPath"
  Write-Host "No change made. Re-run with -Force only after reviewing the template diff."
  exit 0
}

New-Item -ItemType Directory -Path $corpusDirectory -Force | Out-Null
Copy-Item -LiteralPath $templatePath -Destination $targetPath -Force

$hash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Installed repository-docs corpus configuration: $targetPath"
Write-Host "Template SHA-256: $hash"
Write-Host "The source-receipt API remains fail-closed until the container has the configured read-only documentation snapshot mount."
