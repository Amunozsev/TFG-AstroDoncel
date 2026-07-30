[CmdletBinding()]
param(
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot ".env"
$envExamplePath = Join-Path $repoRoot ".env.example"
$archivePath = Join-Path $repoRoot "data\archive"

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $dockerExe = $dockerCommand.Source
} else {
    $dockerExe = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
    if (-not (Test-Path -LiteralPath $dockerExe)) {
        throw "Docker was not found. Install Docker Desktop and open it before running this script."
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
    & $dockerExe info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is installed but its engine is not running. Start Docker Desktop and retry."
    }

    if (-not (Test-Path -LiteralPath $envPath)) {
        $bytes = New-Object byte[] 24
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $rng.GetBytes($bytes)
        } finally {
            $rng.Dispose()
        }
        $password = -join ($bytes | ForEach-Object { $_.ToString("x2") })
        $contents = [System.IO.File]::ReadAllText($envExamplePath)
        $contents = $contents.Replace("change-this-password", $password)
        [System.IO.File]::WriteAllText(
            $envPath,
            $contents,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Created .env with a random PostgreSQL password."
    }

    if ([System.IO.File]::ReadAllText($envPath).Contains("change-this-password")) {
        throw ".env still contains the example password. Replace both occurrences before deployment."
    }

    New-Item -ItemType Directory -Force $archivePath | Out-Null
    Invoke-Docker @("compose", "config", "--quiet")

    $upArguments = @("compose", "up", "-d")
    if (-not $NoBuild) {
        $upArguments += "--build"
    }
    Invoke-Docker $upArguments

    $portLine = $null
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $portOutput = & $dockerExe compose port web 80 2>$null
        $portExitCode = $LASTEXITCODE
        if ($portExitCode -eq 0 -and $portOutput) {
            $portLine = @($portOutput)[0]
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $portLine) {
        throw "Could not determine the published web port."
    }
    $webPort = ($portLine -split ":")[-1].Trim()
    $readyUrl = "http://127.0.0.1:$webPort/ready"

    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 3
            if ($response.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $ready) {
        & $dockerExe compose ps
        & $dockerExe compose logs --tail 100
        throw "The stack did not become ready at $readyUrl."
    }

    Invoke-Docker @("compose", "ps")
    Write-Host ""
    Write-Host "AstroDoncel is ready:"
    Write-Host "  Portal:  http://127.0.0.1:$webPort"
    Write-Host "  API:     http://127.0.0.1:$webPort/docs"
    Write-Host "  Status:  $readyUrl"
} finally {
    Pop-Location
}
