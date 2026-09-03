# agent-bootstrap

把本机几个 coding agent 的模型和 API 配置集中到一个文件里。

平时只改 `vendors.yaml`，然后运行一次同步命令；换电脑时，把这个目录复制过去，再运行同一条命令即可。

## 适合谁

如果你同时使用 Claude Code、Codex、Pi、ZCode 或 DSH，并且不想分别修改它们各自的配置文件，这个脚本可以帮你维护一份配置。

它主要同步 provider、API key 和默认模型，并设置 agent 正常连接所需的环境变量；不会改动主题、hooks、项目列表等其他个人设置。

## 3 分钟开始

### 1. 安装依赖

脚本需要 Python 3 和 `pyyaml`：

```powershell
py -m pip install pyyaml
```

Linux / macOS：

```sh
python3 -m pip install pyyaml
```

### 2. 创建配置文件

复制示例文件：

```powershell
Copy-Item vendors.example.yaml vendors.yaml
```

Linux / macOS：

```sh
cp vendors.example.yaml vendors.yaml
```

编辑 `vendors.yaml`，至少填写这三项：

```yaml
gpt:
  base_url: http://your-gpt-proxy:8081
  api_key: sk-...

opencode:
  api_key: sk-...
```

其他模型和 provider 可以继续使用示例中的默认值，也可以按需修改。

### 3. 预览并同步

先预览：

```powershell
py bootstrap.py --dry-run --no-probe
```

确认输出无误后正式同步：

```powershell
py bootstrap.py
```

Linux / macOS 可以使用入口脚本：

```sh
./sync.sh --dry-run --no-probe
./sync.sh
```

目标 agent 没有安装时会跳过，不会凭空创建配置文件。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `py bootstrap.py --dry-run` | 只显示将要修改的内容，不写文件 |
| `py bootstrap.py --only claude pi` | 只同步指定的 agent |
| `py bootstrap.py --no-probe` | 跳过在线模型列表探测 |
| `py bootstrap.py check` | 检查配置，并探测两个 provider 的 `/models` 接口 |
| `py bootstrap.py verify` | 向三个实际调用路径发送一次最小请求 |
| `py bootstrap.py export --force` | 从当前电脑的 agent 配置反向生成 `vendors.yaml` |

参数也可以写在子命令后面。例如：

```sh
python3 bootstrap.py check --config ./vendors.yaml --no-probe
```

`check` 在在线探测失败、配置缺失或格式错误时会返回非零退出码，方便接入脚本和 CI。

## 配置文件说明

完整字段可以参考 [`vendors.example.yaml`](vendors.example.yaml)：

- `gpt`：Codex 使用的 GPT 代理地址和 key。
- `opencode`：Claude Code、Pi、ZCode、DSH 使用的 OpenCode 地址和 key。
- `codex.model`：Codex 默认模型。
- `claude.model`、`sonnet`、`opus`：Claude Code 的默认模型及三个角色模型。
- `pi.provider`、`pi.model`：Pi 的默认 provider 和模型。
- `dsh.provider`、`dsh.model`：DSH 的默认 provider 和模型。

模型列表在线时会自动刷新；网络不可用时沿用本机已有列表，不会把列表写成空值。

## 从旧电脑迁移

在旧电脑上执行：

```powershell
py bootstrap.py export
```

如果目标文件已经存在，需要显式加 `--force`：

```powershell
py bootstrap.py export --force
```

把 `vendors.yaml` 和本目录一起复制到新电脑，安装依赖后运行同步命令即可。

## 安全提醒

`vendors.yaml` 包含明文 API key，文件已加入 `.gitignore`，不要提交到公开仓库或发给别人。

Linux / macOS 上由脚本新建的密钥文件会设置为仅当前用户可读写。Windows 上请使用系统文件权限保护这些文件。

## 支持的配置位置

脚本会在这些文件存在时更新它们：

| Agent | 配置文件 |
| --- | --- |
| Claude Code | `~/.claude/settings.json` |
| Codex | `~/.codex/config.toml` |
| Pi | `~/.pi/agent/settings.json`、`models.json` |
| ZCode | `~/.zcode/v2/config.json` |
| DSH | `~/.dsh/settings.yaml`、`.credentials.yaml` |

## License

[MIT](LICENSE)
