# 一个命令同步所有 agent：.\sync.ps1 [--dry-run] [--only claude pi] [--no-probe]
py "$PSScriptRoot\bootstrap.py" @args
