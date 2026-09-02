# Agent Vendors Sync

将多个 coding agent 的 provider 和 model 配置集中到一个 YAML 文件，并同步到各 agent 的本地配置。

支持 Claude Code、Codex、Pi、ZCode 和 DSH。项目现在以 CLI 为主入口；不会启动 Web 页面，也不会自动创建备份文件。

CLI 会保留 YAML 中已有的 provider 注册表，只编辑现有 provider 的 API key、Base URL、API 类型和 model；不会强制合并或删除 provider。

## 安装（Windows）

```powershell
git clone https://github.com/ch-z-hc/agent-vendors-sync.git
Copy-Item .\agent_vendors.py, .\sync-agent-vendors.ps1, .\watch-agent-vendors.py "$HOME\.agents\"
Copy-Item .\agent_vendors_cli.py, .\start-agent-vendors-cli.ps1 "$HOME\.agents\"
Copy-Item .\agent-vendors.example.yaml "$HOME\.agents\agent-vendors.yaml"
```

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

项目使用 Python 3.10 或更高版本。Linux / macOS 可直接用 `python3` 替换上面的 `python`，并将目标目录替换为 `~/.agents`。

## 使用

运行 CLI 配置向导：

```powershell
python "$HOME\.agents\agent_vendors_cli.py"
```

或使用包装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.agents\start-agent-vendors-cli.ps1"
```

新增或管理 provider：

```powershell
python "$HOME\.agents\agent_vendors_cli.py" provider list
python "$HOME\.agents\agent_vendors_cli.py" provider add my-gateway
python "$HOME\.agents\agent_vendors_cli.py" provider refresh my-gateway
python "$HOME\.agents\agent_vendors_cli.py" provider refresh my-gateway --merge
python "$HOME\.agents\agent_vendors_cli.py" provider remove my-gateway
```

`provider add` 会交互填写显示名、Base URL、API 类型、API key 来源和 model。model 默认会请求兼容 OpenAI 的 `GET /models` 自动发现，也可以选择纯手动输入，或在自动发现后补充自定义 model。删除仍被 agent 使用的 provider 会被拒绝，确认改绑后再使用 `--force`。

`provider refresh <id>` 会重新查询并替换该 provider 的 model 列表；加上 `--merge` 则只追加 / 更新查询结果，不删除现有 model。

向导会先让你确认 Claude Code、Codex、Pi、DSH 的配置文件路径（自动探测到的现有文件会作为默认值），再逐个编辑 YAML 中已有的 provider。`gpt` 默认从自定义入口开始，适合代理或自建网关；常用厂商预设只用于方便填写 Base URL。provider 不会被强制合并或删除，agent 也会继续使用各自原来的 provider。随后显示 model 目录，可按编号勾选保留；最后逐项显示各 agent 的 model 选择。输入 API key 时直接回车可保留已有值。确认后同步所有 agent。路径会写入 YAML 的 `paths` 节点，Windows / Linux 可以分别保存自己的路径。

常用参数：

```powershell
python "$HOME\.agents\agent_vendors_cli.py" --dry-run  # 只预览，不写入
python "$HOME\.agents\agent_vendors_cli.py" --yes      # 跳过最终确认
python "$HOME\.agents\agent_vendors_cli.py" --no-sync  # 保存 YAML，但不同步 agent
```

model 列表由 YAML 中已有 model、Codex 本地 `models.json`（如果存在）和内置常见模型合并而成；因此新安装的 model 也可以先在 CLI 中选中，再写入 YAML。

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

从 [`agent-vendors.example.yaml`](agent-vendors.example.yaml) 开始。`providers` 定义 provider 和 model，`agents` 只负责选择 provider/model 以及目标特有选项。API key 可以通过 `apiKeyEnv` 从环境变量读取，也可以放在本机未提交的 YAML 中；示例中的 key 均为占位符。`baseURL` 是 OpenAI 兼容接口地址；需要 Claude Code 时可在同一 provider 下配置 `anthropicBaseURL`（也支持 `endpoints.anthropic-messages`），这样同一份凭据和 model 不会因为协议不同而串地址。OpenCode Go 未配置该字段时会自动将 `/v1` 去掉作为 Anthropic 地址。

如果已有各 agent 配置，也可以生成集中配置：

```powershell
python "$HOME\.agents\agent_vendors.py" init
```

`init` 默认不会覆盖已有 YAML；需要覆盖时显式加 `--force`。

如果要使用另一份 YAML，可设置环境变量：

```powershell
$env:AGENT_VENDORS_FILE = "D:\path\agent-vendors.yaml"
python .\agent_vendors_cli.py --dry-run
```

`paths.windows`、`paths.linux` 和 `paths.macos` 可以分别保存不同系统的配置文件地址。CLI 会自动探测常见位置，也允许手动输入不存在或自定义路径。

Claude Code 当前通过 `opencode-go` provider 写入 `ANTHROPIC_*` 环境变量；Codex 使用 `gpt`，Pi / DSH / ZCode 会按 YAML 中的 provider 和 model 同步。

## 设计参考

交互方式参考了 [cc-switch-helper](https://github.com/luckybilly/cc-switch-helper) 的交互菜单，以及 [One API](https://github.com/songquanpeng/one-api) 的渠道/模型表单。本项目使用本地 YAML 和 CLI，不引入前端构建链或数据库。

## 安全提示

- 不要提交真实 API key、JWT、内网地址和运行日志。
- 应用同步前使用 `--dry-run` 检查差异。
- 同步会直接修改本机 agent 配置；需要回滚时请使用 Git 或系统文件历史。

## 许可证

MIT License，见 [`LICENSE`](LICENSE)。
