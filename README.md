# agent-bootstrap

一个文件夹管住所有 coding agent。`vendors.yaml` 如实记录【本机】各 agent 的选择，跑一次同步命令原样生效；整个文件夹拷到新电脑再跑一次，两台即一致。不用 pm2，不用 watch。

## 维护单元（就这几样）

- `bootstrap.py` — 同步脚本（标准库 + pyyaml）
- `vendors.yaml` — 全局唯一真相（密钥明文在里面，已 gitignore）
- `sync.ps1` / `sync.sh` — Windows / Linux 单命令入口

## 日常

```powershell
notepad vendors.yaml   # 改 key、地址或某个 agent 的默认模型
.\sync.ps1             # Windows 生效
```

```sh
vim vendors.yaml  # 改 key、地址或某个 agent 的默认模型
./sync.sh         # Linux/macOS 生效
```

通用参数：`--dry-run` 只预览，`--only claude pi` 只同步指定的，`--no-probe` 跳过在线发现。

只配**已安装**的 agent：目标配置文件不存在就跳过，不会凭空新建。各 agent 保持自己的模型（claude / pi / dsh 走 opencode，codex 走 gpt 代理，互不干扰）。只改 provider/key/model 段，主题、hooks、projects 等个人设置不动。model 列表在线时自动刷新，离线沿用已有，绝不写空。Linux 上新建的密钥文件权限为仅自己可读写。

## 换电脑

```sh
# 旧电脑：从本机现有配置生成 vendors.yaml
python3 bootstrap.py export   # Windows 用 py bootstrap.py export

# 把整个文件夹拷到新电脑，运行
./sync.sh                     # Windows 用 .\sync.ps1
```

其他：`check` 验配置 + 连通性（key 打掩码），`--config PATH` 指定 yaml 位置。
