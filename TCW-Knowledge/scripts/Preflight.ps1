$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force "evidence\workstation" | Out-Null
$Cpu = Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
$Computer = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory
$Os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture
$Gpu = @()
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $Gpu = @(nvidia-smi --query-gpu=uuid,name,driver_version,memory.total,memory.used --format=csv,noheader,nounits)
}
$OllamaVersion = $null
if (Get-Command ollama -ErrorAction SilentlyContinue) { $OllamaVersion = @(ollama --version 2>&1 | ForEach-Object { "$_" }) }
$Report = [ordered]@{
    captured_at = (Get-Date).ToUniversalTime().ToString("o")
    cpu = $Cpu
    computer = $Computer
    operating_system = $Os
    gpu_csv_columns = "uuid,name,driver_version,memory.total_MiB,memory.used_MiB"
    gpu = $Gpu
    ollama_version = $OllamaVersion
    note = "Read-only inventory of this Windows machine. This does not constitute a completed model benchmark."
}
$Path = "evidence\workstation\preflight_$(Get-Date -Format yyyyMMdd_HHmmss).json"
$Report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $Path
Write-Host "Saved $Path"
$Report | ConvertTo-Json -Depth 8
