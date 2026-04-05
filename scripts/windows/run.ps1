# Navigate to the project root (two levels up from scripts/windows/)
$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot"

$env:PYTHONPATH = "."
python watcher.py
