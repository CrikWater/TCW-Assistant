[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$ConfigFile = Join-Path $ProjectRoot "config\settings.json"
if (-not (Test-Path $ConfigFile)) { $ConfigFile = Join-Path $ProjectRoot "config\settings.example.json" }
$Settings = Get-Content $ConfigFile -Raw | ConvertFrom-Json
try {
    Invoke-RestMethod "$($Settings.ollama_url)/api/tags" -TimeoutSec 2 | Out-Null
    Write-Host "Reusing the running Ollama service. GPU/environment changes only apply after that service is restarted."
    return
} catch {}
$Ollama = (Get-Command ollama -ErrorAction Stop).Source
$env:OLLAMA_HOST = ([Uri]$Settings.ollama_url).Authority
$env:OLLAMA_NO_CLOUD = "1"
$env:OLLAMA_NUM_PARALLEL = [string]$Settings.ollama_num_parallel
$env:OLLAMA_MAX_LOADED_MODELS = "2"
if ($Settings.cuda_visible_devices) { $env:CUDA_VISIBLE_DEVICES = $Settings.cuda_visible_devices }
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$p = Start-Process -FilePath $Ollama -ArgumentList "serve" -PassThru -RedirectStandardOutput (Join-Path $LogDir "ollama.stdout.log") -RedirectStandardError (Join-Path $LogDir "ollama.stderr.log")
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try { Invoke-RestMethod "$($Settings.ollama_url)/api/tags" -TimeoutSec 2 | Out-Null; return } catch {}
    if ($p.HasExited) { throw "Ollama exited. Check logs\ollama.stderr.log." }
}
throw "Ollama did not become ready. Check its log."
