# agent-bootstrap

新电脑一条命令配好所有 coding agent。只需要 3 个值：`GPT_BASE_URL`、`GPT_API_KEY`、`OPENCODE_API_KEY`。

## 换电脑流程（两步）

旧电脑导出：

```powershell
py bootstrap.py export
```

把生成的 `bootstrap.env` 拷到新电脑，再运行：

```powershell
py bootstrap.py
```

## 命令

| 命令 | 说明 |
|---|---|
| `py bootstrap.py` | 写入全部 agent 配置（默认） |
| `py bootstrap.py --dry-run` | 只预览，不写入 |
| `py bootstrap.py --only claude codex` | 只配指定的 agent |
| `py bootstrap.py --no-probe` | 跳过 `/models` 自动发现（离线用） |
| `py bootstrap.py check` | 检查 env + 连通性（key 只显示掩码） |
| `py bootstrap.py export [--force]` | 从本机反向生成 `bootstrap.env` |

覆盖 5 个 agent：claude（`~/.claude/settings.json` 的 env 段）、codex（`~/.codex/config.toml`）、pi（settings + models）、zcode（只改 4 个自有 provider，`builtin:*` 不动）、dsh（需 `pip install pyyaml`，否则自动跳过）。

只改配置，不管主题、hooks、projects 等其他个人设置。model 列表优先用 `/models` 接口实时发现，失败时沿用本机已有列表。

`bootstrap.env` 含密钥，已加入 `.gitignore`，不要提交。
