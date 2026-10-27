[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Status","Index","Reindex","Rebuild","Validate","Backup","Audit","Tests","Logs")]
    [string]$Action,
    [string]$DocumentId,
    [switch]$ExerciseLifecycle
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
switch ($Action) {
    "Logs" { Get-Content "logs\events.jsonl" -Tail 50 -Wait; return }
    "Tests" { & $Python -m pytest -q }
    "Validate" {
        $Arguments = @("scripts\validate_live.py")
        if ($ExerciseLifecycle) { $Arguments += "--exercise-lifecycle" }
        & $Python @Arguments
    }
    default {
        $Arguments = @("-m","backend.cli",$Action.ToLower())
        if ($DocumentId) { $Arguments += @("--document-id",$DocumentId) }
        & $Python @Arguments
    }
}
if ($LASTEXITCODE -ne 0) { throw "$Action did not complete successfully." }
