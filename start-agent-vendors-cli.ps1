# Run the interactive Agent Vendors CLI wizard.
param([string]$Py = "python")
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "agent_vendors_cli.py"
& $Py $script @args
exit $LASTEXITCODE
