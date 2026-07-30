[CmdletBinding()]
param(
    [switch]$DatabaseOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $dockerExe = $dockerCommand.Source
} else {
    $dockerExe = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
    if (-not (Test-Path -LiteralPath $dockerExe)) {
        throw "Docker was not found."
    }
}

function Invoke-Docker {
    param([string[]]$Arguments)
    & $script:dockerExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repoRoot
try {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = Join-Path $repoRoot "backups\$timestamp"
    New-Item -ItemType Directory -Force $backupDir | Out-Null

    Invoke-Docker @(
        "compose", "exec", "-T", "db", "sh", "-c",
        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=/tmp/astrodoncel.dump'
    )
    Invoke-Docker @("compose", "cp", "db:/tmp/astrodoncel.dump", (Join-Path $backupDir "postgres.dump"))
    Invoke-Docker @("compose", "exec", "-T", "db", "rm", "-f", "/tmp/astrodoncel.dump")

    if (-not $DatabaseOnly) {
        Invoke-Docker @("compose", "exec", "-T", "api", "tar", "-czf", "/tmp/app-data.tar.gz", "-C", "/data", ".")
        Invoke-Docker @("compose", "cp", "api:/tmp/app-data.tar.gz", (Join-Path $backupDir "app-data.tar.gz"))
        Invoke-Docker @("compose", "exec", "-T", "api", "rm", "-f", "/tmp/app-data.tar.gz")
    }

    $checksumLines = Get-ChildItem -LiteralPath $backupDir -File |
        Sort-Object Name |
        ForEach-Object {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            "$hash  $($_.Name)"
        }
    [System.IO.File]::WriteAllLines(
        (Join-Path $backupDir "SHA256SUMS.txt"),
        $checksumLines,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "Backup created at $backupDir"
} finally {
    Pop-Location
}
