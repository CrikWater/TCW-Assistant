[CmdletBinding()]
param([switch]$SkipModelPull)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11-3.13, then run this script again." }
    python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13), 'Use Python 3.11-3.13 or create .venv with py -3.12 -m venv .venv'"
    if ($LASTEXITCODE -ne 0) { throw "Python version check failed." }
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
}
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13), 'Existing .venv requires Python 3.11-3.13'"
if ($LASTEXITCODE -ne 0) { throw "Virtual environment Python version check failed." }
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
if (-not (Test-Path "config\settings.json")) { Copy-Item "config\settings.example.json" "config\settings.json" }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama was not found. Install the Windows application from https://ollama.com/download/windows, then reopen PowerShell." }
$Settings = Get-Content "config\settings.json" -Raw | ConvertFrom-Json
& $Python -c "from backend.config import load_config; load_config()"
if ($LASTEXITCODE -ne 0) { throw "Application configuration is invalid." }
$env:OLLAMA_HOST = ([Uri]$Settings.ollama_url).Authority
try { Invoke-RestMethod "$($Settings.ollama_url)/api/tags" -TimeoutSec 3 | Out-Null }
catch { & "$PSScriptRoot\Start-Ollama.ps1" }
if (-not $SkipModelPull) {
    $Installed = (Invoke-RestMethod "$($Settings.ollama_url)/api/tags" -TimeoutSec 10).models
    foreach ($Model in @($Settings.embedding_model, $Settings.generation_model)) {
        $Canonical = $Model
        if ($Model -notmatch ":") { $Canonical = "$($Model):latest" }
        if ($Installed.name -contains $Canonical) {
            Write-Host "Reusing installed model: $Model"
            continue
        }
        ollama pull $Model
        if ($LASTEXITCODE -ne 0) { throw "Model download failed: $Model" }
    }
}
# Public source checkouts contain no district corpus. Preserve an existing private
# manifest; initialize only a genuinely new checkout so uploads work normally.
$Manifest = Join-Path $ProjectRoot "data\corpus_manifest.json"
if (-not (Test-Path $Manifest)) {
    New-Item -ItemType Directory -Path (Split-Path $Manifest -Parent) -Force | Out-Null
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Manifest, '{"documents": []}', $Utf8NoBom)
    Write-Host "No curated corpus was supplied. Add approved documents through the Knowledge base page."
}
& $Python -m backend.cli audit
if ($LASTEXITCODE -ne 0) { throw "Source extraction audit failed." }
Write-Host "Setup complete. Run .\scripts\Start.ps1, then upload approved documents or index your existing curated corpus."
Write-Host "Model downloads require Internet access once. Normal document questions use local models only."
