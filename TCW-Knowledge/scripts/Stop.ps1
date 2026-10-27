$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$PidFile = Join-Path $ProjectRoot "logs\app-process.json"
if (-not (Test-Path $PidFile)) { Write-Host "No TCW application process record found."; return }
$Record = Get-Content $PidFile -Raw | ConvertFrom-Json
$Process = Get-CimInstance Win32_Process -Filter "ProcessId=$($Record.pid)"
if (-not $Process) { Remove-Item $PidFile; Write-Host "TCW application is stopped."; return }
$ExpectedPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($Process.ExecutablePath -ne $ExpectedPython -or $Process.CommandLine -notmatch "backend.cli.*serve") {
    throw "PID no longer identifies this TCW application. Refusing to stop another process."
}
$ConfigFile = Join-Path $ProjectRoot "config\settings.json"
if (-not (Test-Path $ConfigFile)) { $ConfigFile = Join-Path $ProjectRoot "config\settings.example.json" }
$Settings = Get-Content $ConfigFile -Raw | ConvertFrom-Json
$Url = "http://127.0.0.1:$($Settings.port)"
$Token = (Get-Content (Join-Path $ProjectRoot "logs\session-token") -Raw).Trim()
Invoke-RestMethod "$Url/api/shutdown" -Method Post -Headers @{"X-TCW-Token"=$Token} -ContentType "application/json" -Body "{}" -TimeoutSec 10 | Out-Null
Wait-Process -Id $Record.pid -Timeout 30 -ErrorAction SilentlyContinue
if (Get-Process -Id $Record.pid -ErrorAction SilentlyContinue) { throw "TCW has not stopped yet. Check logs; no process was force-killed." }
Remove-Item $PidFile -ErrorAction SilentlyContinue
Remove-Item (Join-Path $ProjectRoot "logs\session-token") -ErrorAction SilentlyContinue
Write-Host "TCW application stopped. Shared Ollama service was left running."
