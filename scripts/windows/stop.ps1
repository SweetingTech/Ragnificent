# Navigate to the project root (two levels up from scripts/windows/)
$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot"

$Port = 8008

# Get all PIDs listening on the port
$Connections = netstat -ano | Select-String ":$Port\s"

if (-not $Connections) {
    Write-Host "No process found listening on port $Port."
    exit 0
}

$DirectPIDs = $Connections | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Where-Object { $_ -match '^\d+$' -and [int]$_ -gt 0 } | Sort-Object -Unique

# Collect direct PIDs + all their child processes (uvicorn spawns worker children)
$AllPIDs = @()
foreach ($ProcessId in $DirectPIDs) {
    $AllPIDs += $ProcessId
    # Add any children of this process
    $Children = Get-WmiObject Win32_Process | Where-Object {
        $_.ParentProcessId -eq [int]$ProcessId -and $_.ProcessId -gt 0
    }
    foreach ($Child in $Children) {
        $AllPIDs += [string]$Child.ProcessId
    }
}

$AllPIDs = $AllPIDs | Sort-Object -Unique

foreach ($ProcessId in $AllPIDs) {
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($Process -and $Process.Name -ne "Idle") {
        Write-Host "Stopping $($Process.Name) (PID $ProcessId)..."
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Milliseconds 500

# Verify port is free
$Still = netstat -ano | Select-String ":$Port\s"
if ($Still) {
    Write-Host "WARNING: Some processes may still be running on port $Port."
} else {
    Write-Host "Server stopped."
}
