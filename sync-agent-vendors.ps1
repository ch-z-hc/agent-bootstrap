# Sync all agent vendor configs from ~/.agents/agent-vendors.yaml
# Usage:
#   powershell -ExecutionPolicy Bypass -File ~/.agents/sync-agent-vendors.ps1          # apply
#   powershell -ExecutionPolicy Bypass -File ~/.agents/sync-agent-vendors.ps1 -DryRun  # preview
#   powershell -ExecutionPolicy Bypass -File ~/.agents/sync-agent-vendors.ps1 -Prune   # remove unmanaged entries
param(
  [switch]$DryRun,
  [switch]$Prune,
  [string]$Py = "python"
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyScript = Join-Path $scriptDir "agent_vendors.py"
$syncArgs = @("sync")
if ($DryRun) { $syncArgs += "--dry-run" }
if ($Prune) { $syncArgs += "--prune" }
& $Py $pyScript @syncArgs
exit $LASTEXITCODE
