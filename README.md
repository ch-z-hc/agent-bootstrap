# agent-bootstrap

把几台机器上多个 coding agent 的模型配置收敛到**一个 YAML**：改 `vendors.yaml`，跑一条命令，Codex / Pi / Claude Code / DSH / ZCode 的配置文件就同步成一致；换电脑时拷过去再跑一次即可。

[![license: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

它只管 provider、API key、默认模型和相关环境变量；主题、键位、项目信任列表、MCP、插件等个人设置一律不碰。

## 技术栈

| 项 | 说明 |
| --- | --- |
| 语言 | Python 3.7+，单文件 `bootstrap.py`（约 840 行） |
| 依赖 | 只有 `pyyaml`（读 YAML）；网络用标准库 `urllib`，不装 requests |
| 运行环境 | Windows（`py`）与 Linux/macOS（`python3` / `sync.sh`）；跨平台差异只在 `codex_auth_command()` 一处 |
| 被管理对象 | `~/.codex/config.toml`、`~/.pi/agent/*.json`、`~/.claude/settings.json`、`~/.dsh/*.yaml`、`~/.zcode/v2/config.json` |

## 架构

一条流水线：`vendors.yaml` 是唯一输入，各 agent 的配置文件是唯一输出，中间没有任何状态。

| 阶段 | 代码 | 做什么 |
| --- | --- | --- |
| 读入 | `load_vendors()` | `vendors.yaml` → 扁平 env 字典；解析 `api_key_env`、补默认值、校验类型（不合规就抛 `ConfigError`） |
| 探测 | `fetch_models()` | 拉 bai 的 `/models`，在线时刷新模型清单，离线时沿用本机已有列表 |
| 落地 | `setup_claude` / `setup_codex` / `setup_pi` / `setup_zcode` / `setup_dsh` | 每个 agent 一个函数，各自决定写哪些键 |
| 写入 | `patch_json()` / `patch_toml()` / `write_text()` | 逐键替换，保留未知字段与注释；先写临时文件再替换，保留权限 |
| 回读 | `cmd_export()` | 从当前机器的 agent 配置反向生成 `vendors.yaml` |
| 自检 | `cmd_check()` / `cmd_verify()` | 配置与网络；两条真实调用路径各发一次最小请求 |

四条设计约束：

- **只改认识的键**。手写在 agent 配置里的东西不会被抹掉，所以 `~/.codex/config.toml` 的 `notify`、`[projects.*]`、MCP、插件等同步后原样保留。
- **没装的 agent 自动跳过**。目标文件不存在就输出 `skip (not installed)`，不会凭空创建目录。
- **清理已停用的上游**。`RETIRED_PROVIDERS` 里的 provider 会从 agent 文件里被剪掉，避免留下还能选中的死人模型。
- **凭据不靠手抄**。`export` 能把 key（含 codex 的 `[model_providers.<p>.auth]`）、URL、模型、推理强度全部读回 `vendors.yaml`。

## 快速开始

```powershell
py -m pip install pyyaml
Copy-Item vendors.example.yaml vendors.yaml   # 填 base_url + key（api_key 或 api_key_env）
py bootstrap.py --dry-run --only codex pi     # 先看要动什么
py bootstrap.py --only codex pi               # 再真动
py bootstrap.py verify                        # 真发一次请求，两条协议都验
```

Linux / macOS 用 `./sync.sh` 代替 `py bootstrap.py`。目标 agent 没安装时会跳过，不会凭空创建配置文件。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `py bootstrap.py --dry-run` | 只显示将要修改的内容，不写文件 |
| `py bootstrap.py --only claude codex pi zcode dsh` | 只同步指定 agent |
| `py bootstrap.py --no-probe` | 跳过在线模型列表探测 |
| `py bootstrap.py check` | 校验 `vendors.yaml` 并探测 `/models`；不通或配置缺失时返回非零 |
| `py bootstrap.py verify` | 向 openai / anthropic 两条真实调用路径各发一次最小请求，并核对默认模型在目录里 |
| `py bootstrap.py export --force` | 从本机 agent 配置反向生成 `vendors.yaml` |

参数也能写在子命令后面，例如 `python3 bootstrap.py check --config ./vendors.yaml --no-probe`。

## vendors.yaml 字段

| 段 | 字段 | 说明 |
| --- | --- | --- |
| 厂商段（`bai`、`aizex`） | `base_url`、`api_key` 或 `api_key_env` | key 二选一；`api_key_env` 指向已设置的环境变量 |
| `codex` | `provider`、`model`、`reasoning_effort` | 省略 `reasoning_effort` 则为 `xhigh`；`wire_api` 固定 `responses` |
| `claude` | `model`、`sonnet`、`opus` | 默认模型与三个角色模型 |
| `pi` | `provider`、`model`、`http_proxy` | `http_proxy` 会写进 `~/.pi/agent/settings.json` |
| `dsh` | `provider`、`model` | 同 pi |

当前上游：**b.ai**（claude / pi / dsh / zcode）与 **aizex**（codex）。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `bootstrap.py` | 全部逻辑：load / setup / export / check / verify |
| `vendors.yaml` | 唯一真相，含明文 key（已 gitignore，勿提交） |
| `vendors.example.yaml` | 模板，带字段注释 |
| `sync.sh` / `sync.ps1` | 一行入口 |
| `skills/agent-bootstrap-sync/SKILL.md` | 给 coding agent 的操作规范：改配置走 `vendors.yaml`，别手改生成物 |

## 主要功能

- 一次同步多个 agent：provider、key、默认模型、推理强度、pi 代理。
- codex 的 key 写进 `[model_providers.<p>.auth]`（Windows 用 `cmd /c echo`，其它用 `echo`），换机能复现 —— 那是 codex 拿到第三方 key 的唯一途径。
- pi 的模型清单在线刷新；探测失败时沿用本机列表，不会写空。缺 `OPENCODE_MODEL_SPECS` 条目的新模型会退回 128k 窗口 / 16k 输出。
- qwen 系列自动补 `compat` 块（`thinkingFormat: qwen`、不带 `reasoning_effort` / `store` / `developer`），因为上游会拒这些字段。
- `pi models-store.json` 里的陈旧 provider 一并剪掉，避免缓存里还能选到已停用的模型。

## 开发流程

1. 改 `bootstrap.py` 或 `skills/…/SKILL.md`。`vendors.yaml` 是本机私有、每台一份，不入库。
2. `py bootstrap.py --dry-run --only <agents>` 预览 → 实际同步 → `verify`。
3. `master` 单分支，直接 push；其它机器 `git pull` 后再跑一次 sync。
4. 需要新字段时**改脚本**（`load_vendors` + `setup_*` + `cmd_export` + `cmd_verify` 四处对齐），别手改 agent 配置文件 —— 下次同步会覆盖手工修复。

## 编码规范

- 只用标准库 + PyYAML，保持 3.7 兼容（无 `match`、无新式类型注解）。
- 写文件统一走 `write_text` / `save_json`：先写临时文件再替换，保留原权限；新建的含密钥文件在 posix 上自动 `0600`。
- 任何密钥在输出与日志里一律 `mask()`（前 3 后 3）。
- 每个 `setup_*` 都接受 `dry_run`，把动作追加到 `out` 列表，由 `cmd_setup` 统一打印 `* / = / ~`（改动 / 无变化 / 跳过）。

## 测试

没有自动化测试；用三条命令自检：

- `check` 看配置与网络；`verify` 看两条真实调用路径与默认模型；`--dry-run` 看改动面。
- `verify` 期望 `ALL OK`，且 `bai openai`、`bai anthropic` 两行都 OK；`/models` 里有某个 id 不代表能调用（余额），所以还要 `verify` 真发一次。
- 已实测：3 台机器（Windows ×2、Ubuntu ×1）× 各 agent 段；反复 sync 后 `--dry-run` 只剩 `patch_toml` 的已知无害标记（该函数恒返回 changed，内容实际未变）。
- 改 `bootstrap.py` 后先 `--dry-run`，在一台机器上 `verify` 通过，再推给其它机器。

## 迁移到新电脑

旧机器：

```powershell
py bootstrap.py export --force       # 生成 vendors.yaml
```

把整个目录（含 `vendors.yaml`）拷到新机器，然后：

```powershell
py -m pip install pyyaml
py bootstrap.py                      # 一次落地
```

`vendors.yaml` 里用 `api_key_env` 的机器要先设好环境变量，或直接改成内联 `api_key`。

## 安全

`vendors.yaml` 含明文 API key，已在 `.gitignore` 里；`_*.yaml` / `*.bak` 一并忽略，避免临时副本被 `git add -A` 带走。不要把它提交到任何仓库或发给别人。Windows 上靠系统文件权限保护，posix 上由脚本 `0600`。

## Contributing

自己用为主，欢迎直接提 PR：单个改动、附 `--dry-run` 输出。新增 agent 时请同时补 `setup_<agent>()`、`cmd_export` 回读、`cmd_verify` 检查项，以及 README 的字段表。

## License

[MIT](LICENSE)
