# Navigate to the project root (two levels up from scripts/windows/)
$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot"

function Get-VectorDbUrl {
    $configPath = Join-Path $ProjectRoot "config.yaml"
    if (-not (Test-Path $configPath)) {
        return $null
    }

    $content = Get-Content $configPath
    $inVectorDb = $false
    foreach ($line in $content) {
        if ($line -match '^vector_db:\s*$') {
            $inVectorDb = $true
            continue
        }
        if ($inVectorDb -and $line -match '^[^\s]') {
            break
        }
        if ($inVectorDb -and $line -match '^\s+url:\s*(.+?)\s*$') {
            return $Matches[1].Trim()
        }
    }

    return $null
}

function Ensure-DockerDesktop {
    $dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dockerDesktop) {
        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop | Out-Null
        return $true
    }
    return $false
}

function Ensure-Qdrant {
    $vectorDbUrl = Get-VectorDbUrl
    if (-not $vectorDbUrl) {
        Write-Host "Could not determine vector_db.url from config.yaml. Skipping Qdrant startup."
        return
    }

    if ($vectorDbUrl -notmatch '^http://(localhost|127\.0\.0\.1):6333/?$') {
        Write-Host "vector_db.url is '$vectorDbUrl' - assuming external Qdrant and skipping local startup."
        return
    }

    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        Write-Warning "Docker CLI not found. Qdrant was not auto-started."
        return
    }

    $composeArgs = @('compose', 'up', '-d', 'qdrant')
    $probeArgs = @('ps')

    & docker @probeArgs *> $null
    if ($LASTEXITCODE -ne 0) {
        $startedDesktop = Ensure-DockerDesktop
        if ($startedDesktop) {
            $deadline = (Get-Date).AddMinutes(2)
            do {
                Start-Sleep -Seconds 2
                & docker @probeArgs *> $null
                if ($LASTEXITCODE -eq 0) { break }
            } while ((Get-Date) -lt $deadline)
        }
    }

    & docker @probeArgs *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Docker daemon is not available. Qdrant was not auto-started."
        return
    }

    Write-Host "Ensuring Qdrant is running..."
    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to start Qdrant with 'docker compose up -d qdrant'."
    }
}

Ensure-Qdrant

$env:PYTHONPATH = "."
python watcher.py
