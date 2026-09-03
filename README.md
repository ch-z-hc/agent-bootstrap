# agent-bootstrap

一个文件夹管住所有 coding agent。`vendors.yaml` 如实记录【本机】各 agent 的选择，跑 `.\sync.ps1` 原样同步；整个文件夹拷到新电脑再跑一次，新电脑就和这台一模一样。不用 pm2，不用 watch。

## 维护单元（就这三样）

- `bootstrap.py` — 同步脚本（标准库 + pyyaml）
- `vendors.yaml` — 全局唯一真相（密钥在里面，已 gitignore）
- `sync.ps1` — 一个命令入口

## 日常

```powershell
notepad vendors.yaml   # 改 key、地址或某个 agent 的默认模型
.\sync.ps1             # 生效（只改 provider/key/model 段，个人设置不动）
.\sync.ps1 --dry-run        # 只预览
.\sync.ps1 --only claude pi # 只同步指定的
```

各 agent 保持自己的模型（claude / pi / dsh 走 opencode，codex 走 gpt 代理，互不干扰）。model 列表在线时自动刷新，离线（`--no-probe`）沿用已有，绝不写空。

## 换电脑

```powershell
# 旧电脑：从本机现有配置生成 vendors.yaml
py bootstrap.py export

# 把整个文件夹拷到新电脑，运行
.\sync.ps1
```

其他：`check` 验配置 + 连通性（key 打掩码），`--config PATH` 指定 yaml 位置。
