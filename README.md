# Agent Vendors Sync

将多个 coding agent 的 provider 和 model 配置集中到一个 YAML 文件，并同步到各 agent 的本地配置。

支持的目标包括 Claude、Codex、Pi、ZCode 和 DSH。修改 `~/.agents/agent-vendors.yaml` 后，可以手动同步，或运行 watcher 自动同步。

推荐使用内置的 CLI 配置向导：只选择 model、填写 API key，程序会自动收敛为 `gpt` 和 `opencode-go` 两个 provider，并修正各 agent 的引用。

## 安装

```powershell
git clone https://github.com/ch-z-hc/agent-vendors-sync.git
Copy-Item .\agent_vendors.py, .\sync-agent-vendors.ps1, .\watch-agent-vendors.py "$HOME\.agents\"
Copy-Item .\agent_vendors_cli.py, .\start-agent-vendors-cli.ps1 "$HOME\.agents\"
Copy-Item .\agent-vendors.example.yaml "$HOME\.agents\agent-vendors.yaml"
```

安装 Python 依赖（支持 Python 3.7+）：

```powershell
python -m pip install -r requirements.txt
```

## 使用

运行 CLI 配置向导：

```powershell
python "$HOME\.agents\agent_vendors_cli.py"
```

或使用包装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.agents\start-agent-vendors-cli.ps1"
```

向导会先让你确认 Claude Code、Codex、Pi、DSH 的配置文件路径（自动探测到的现有文件会作为默认值），再分别为 `gpt` 和 `opencode-go` 选择常用 Base URL，或输入自定义 Base URL 与 API 类型（`openai-completions` / `openai-responses`）。随后显示完整 model 目录（包括 `muse-spark-1.2-contributor`、Kimi、GLM、MiniMax、Qwen 等），可按编号勾选保留。最后逐项显示 Codex、Claude Code（Haiku / Sonnet / Opus / 默认）、Pi 和 DSH 的 model 选择。输入 API key 时直接回车可保留已有值。确认后移除其他 provider，并同步所有 agent。路径会写入 YAML 的 `paths` 节点，Windows / Linux 可以分别保存自己的路径。

先编辑 `~/.agents/agent-vendors.yaml`，然后预览变更：

```powershell
python "$HOME\.agents\agent_vendors.py" sync --dry-run
```

确认后应用：

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

也可以直接从仓库目录启动 watcher；它会调用同目录下的同步脚本：

```powershell
Start-Process python -ArgumentList ".\watch-agent-vendors.py" -WorkingDirectory "." -WindowStyle Hidden
```

watcher 使用 localhost 端口 `47653` 保证只运行一个实例，并将运行记录写入 `~/.agents/watch-agent-vendors.log`。

## 配置格式

从 [`agent-vendors.example.yaml`](agent-vendors.example.yaml) 开始。`providers` 定义 provider 和 model，`agents` 定义每个 agent 的默认 provider/model 以及目标特有选项。API key 可以通过 `apiKeyEnv` 从环境变量读取，也可以放在本机未提交的 YAML 中；示例中的 key 均为占位符。

如果已有各 agent 配置，也可以生成集中配置：

```powershell
python "$HOME\.agents\agent_vendors.py" init
```

`init` 默认不会覆盖已有 YAML；需要覆盖时显式加 `--force`。

## 设计参考

交互方式参考了 [One API](https://github.com/songquanpeng/one-api) 的渠道/模型表单、[Open WebUI](https://github.com/open-webui/open-webui) 的 provider-agnostic 设置，以及 [Claude Code Manager UI](https://github.com/Rylaispirit/claude-code-manager-ui) 的 local-first 和凭据不回显原则。本项目采用同样的本地监听、结构化表单和显式同步步骤，但不引入前端构建链或数据库。

## 安全提示

- 不要提交真实 API key、JWT、内网地址和运行日志。
- 应用同步前使用 `--dry-run` 检查差异。
- 同步会直接修改本机 agent 配置；需要回滚时请使用 Git 或系统文件历史。

## 许可证

MIT License，见 [`LICENSE`](LICENSE)。
