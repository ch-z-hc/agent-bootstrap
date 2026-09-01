# Agent Vendors Sync

将多个 coding agent 的 provider 和 model 配置集中到一个 YAML 文件，并同步到各 agent 的本地配置。

支持的目标包括 Claude、Codex、Pi、ZCode 和 DSH。修改 `~/.agents/agent-vendors.yaml` 后，可以手动同步，或运行 watcher 自动同步。

## 安装

```powershell
git clone https://github.com/<your-account>/agent-vendors-sync.git
Copy-Item .\agent_vendors.py, .\sync-agent-vendors.ps1, .\watch-agent-vendors.py "$HOME\.agents\"
Copy-Item .\agent-vendors.example.yaml "$HOME\.agents\agent-vendors.yaml"
```

安装 Python 依赖：

```powershell
python -m pip install pyyaml
```

## 使用

先编辑 `~/.agents/agent-vendors.yaml`，然后预览变更：

```powershell
python "$HOME\.agents\agent_vendors.py" sync --dry-run
```

确认后应用（默认会在 `~/.agents/backups/agent-vendors` 创建备份）：

```powershell
python "$HOME\.agents\agent_vendors.py" sync
```

也可以使用 PowerShell 包装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.agents\sync-agent-vendors.ps1" -DryRun
powershell -ExecutionPolicy Bypass -File "$HOME\.agents\sync-agent-vendors.ps1"
```

后台监听 YAML 变化：

```powershell
Start-Process python -ArgumentList "$HOME\.agents\watch-agent-vendors.py" -WindowStyle Hidden
```

watcher 使用 localhost 端口 `47653` 保证只运行一个实例，并将运行记录写入 `~/.agents/watch-agent-vendors.log`。

## 配置格式

从 [`agent-vendors.example.yaml`](agent-vendors.example.yaml) 开始。`providers` 定义 provider 和 model，`agents` 定义每个 agent 的默认 provider/model 以及目标特有选项。API key 可以通过 `apiKeyEnv` 从环境变量读取，也可以放在本机未提交的 YAML 中；示例中的 key 均为占位符。

如果已有各 agent 配置，也可以生成集中配置：

```powershell
python "$HOME\.agents\agent_vendors.py" init
```

`init` 默认不会覆盖已有 YAML；需要覆盖时显式加 `--force`。

## 安全提示

- 不要提交真实 API key、JWT、内网地址、备份和运行日志。
- 应用同步前使用 `--dry-run` 检查差异。
- 同步会修改本机 agent 配置；备份只保存在本机。

## 许可证

MIT License，见 [`LICENSE`](LICENSE)。
