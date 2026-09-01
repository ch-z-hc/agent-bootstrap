# Sync all agent vendor configs from ~/.agents/agent-vendors.yaml
# Usage:
#   powershell -ExecutionPolicy Bypass -File ~/.agents/sync-agent-vendors.ps1          # apply
#   powershell -ExecutionPolicy Bypass -File ~/.agents/sync-agent-vendors.ps1 -DryRun  # preview
param(
  [switch]$DryRun,
  [switch]$NoBackup,
  [string]$Py = "python"
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyScript = Join-Path $scriptDir "agent_vendors.py"
if ($DryRun) {
  & $Py $pyScript sync --dry-run
} else {
  $argsList = @("sync")
  if ($NoBackup) { $argsList += "--no-backup" }
  & $Py $pyScript @argsList
}
exit $LASTEXITCODE