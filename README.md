# agent-bootstrap

一个文件夹管住所有 coding agent。改 `vendors.yaml`，一条命令同步到 claude / codex / pi / zcode / dsh。

## 维护单元（就这两样）

- `bootstrap.py` — 同步脚本，只用标准库 + pyyaml
- `vendors.yaml` — 全局唯一真相（密钥在里面，已 gitignore）

整个文件夹拷到新电脑就能用，不用软链接（codex 的 `[projects.*]` 本机路径、原子重写断链等问题让软链接不可靠）。

## 日常：改一处，全跟着变

```powershell
notepad vendors.yaml     # 改 key、地址或默认模型
py bootstrap.py          # 同步全部 agent
py bootstrap.py --dry-run        # 只预览
py bootstrap.py --only claude pi # 只同步指定的
```

同步是补丁式的：只改各文件的 provider/key/model 段，主题、hooks、projects、packages 等个人设置不动。model 列表优先调 `/models` 实时发现，失败沿用本机已有。

## 换电脑：两步

```powershell
# 旧电脑：从本机现有配置反向生成 vendors.yaml
py bootstrap.py export

# 把整个文件夹拷到新电脑，运行
py bootstrap.py
```

其他命令：`check` 验配置 + 连通性（key 打掩码），`--no-probe` 跳过在线发现，`--config PATH` 指定 yaml 位置。
