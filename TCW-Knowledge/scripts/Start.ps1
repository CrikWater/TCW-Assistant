[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run .\scripts\Setup.ps1 first." }
& $Python -c "from backend.config import load_config; load_config()"
if ($LASTEXITCODE -ne 0) { throw "Application configuration is invalid." }
& "$PSScriptRoot\Start-Ollama.ps1"
$ConfigFile = "config\settings.json"
if (-not (Test-Path $ConfigFile)) { $ConfigFile = "config\settings.example.json" }
$Settings = Get-Content $ConfigFile -Raw | ConvertFrom-Json
$Url = "http://127.0.0.1:$($Settings.port)"
try {
    $existing = Invoke-RestMethod "$Url/api/status" -TimeoutSec 3
    Write-Host "TCW application is already running at $Url"
    if (-not $NoBrowser) { Start-Process $Url }
    return
} catch {}
New-Item -ItemType Directory -Force "logs" | Out-Null
$p = Start-Process -FilePath $Python -ArgumentList "-m","backend.cli","serve" -WorkingDirectory $ProjectRoot -PassThru -RedirectStandardOutput "$ProjectRoot\logs\app.stdout.log" -RedirectStandardError "$ProjectRoot\logs\app.stderr.log"
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-RestMethod "$Url/api/session" -TimeoutSec 2 | Out-Null
        Write-Host "TCW application: $Url"
        if (-not $NoBrowser) { Start-Process $Url }
        return
    } catch {}
    if ($p.HasExited) { throw "Application exited. Check logs\app.stderr.log." }
}
throw "Application did not become ready. Check logs\app.stderr.log."
