#!/usr/bin/env python3
"""Interactive, small-surface configuration wizard for agent-vendors.yaml.

The wizard edits the provider registry in place.  It asks for write-only API
keys and model selections, then keeps each agent's existing provider binding.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import json
import os
import stat
import subprocess
import sys
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pathlib import Path

import yaml

HOME = Path.home()
YAML_FILE = Path(os.environ.get("AGENT_VENDORS_FILE", HOME / ".agents" / "agent-vendors.yaml"))
SYNC_SCRIPT = Path(__file__).resolve().with_name("agent_vendors.py")


def load_config() -> dict:
    if not YAML_FILE.exists():
        raise FileNotFoundError(f"配置文件不存在: {YAML_FILE}")
    data = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("配置根节点必须是对象")
    return data


def save_config(data: dict) -> None:
    YAML_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = YAML_FILE.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if YAML_FILE.exists():
        os.chmod(tmp, stat.S_IMODE(YAML_FILE.stat().st_mode))
    elif os.name != "nt":
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(YAML_FILE)


PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def validate_provider_id(provider_id: str) -> str:
    value = str(provider_id or "").strip()
    if not PROVIDER_ID_RE.fullmatch(value):
        raise ValueError("provider ID 只能包含字母、数字、下划线、点、冒号或短横线，且不能以符号开头")
    return value


def provider_references(data: dict, provider_id: str) -> list[str]:
    refs = []
    for name, agent in (data.get("agents") or {}).items():
        if not isinstance(agent, dict):
            continue
        direct = {agent.get("provider"), agent.get("defaultProvider")}
        listed = agent.get("providers")
        if isinstance(listed, list):
            direct.update(listed)
        elif isinstance(listed, dict):
            direct.update(listed)
        if provider_id in direct:
            refs.append(str(name))
    return refs


def discover_provider_models(base_url: str, api_key: str | None = None, opener=urlopen) -> dict[str, dict[str, str]]:
    """Discover model IDs from an OpenAI-compatible ``/models`` endpoint."""
    url = str(base_url or "").rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers, method="GET")
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except (OSError, ValueError, TypeError, HTTPError, URLError):
        return {}
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    result = {}
    for row in rows:
        if isinstance(row, str):
            mid, label = row, row
        elif isinstance(row, dict):
            mid = row.get("id") or row.get("slug") or row.get("name")
            label = row.get("name") or mid
        else:
            continue
        if mid:
            result[str(mid)] = {"name": str(label)}
    return result


def provider_add(data: dict, provider_id: str | None = None, input_fn=input, secret_fn=None) -> str:
    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("providers 必须是对象")
    provider_id = validate_provider_id(provider_id or input_fn("provider ID："))
    if provider_id in providers:
        raise ValueError(f"provider 已存在: {provider_id}")
    display = input_fn(f"显示名称 [{provider_id}]：").strip() or provider_id
    base = input_fn("Base URL：").strip().rstrip("/")
    if not base:
        raise ValueError("Base URL 不能为空")
    while True:
        api = input_fn("API 类型（openai-completions / openai-responses）[openai-completions]：").strip() or "openai-completions"
        if api in {"openai-completions", "openai-responses"}:
            break
        ui_warn("API 类型只能是 openai-completions 或 openai-responses。")
    env_name = input_fn("API key 环境变量（可回车跳过）：").strip()
    if secret_fn is None:
        secret_fn = getpass.getpass
    key = secret_fn("API key（可回车稍后配置）：").strip()
    query_mode = input_fn("model 来源（auto = 自动查询，manual = 手动，merge = 查询后补充）[auto]：").strip().lower() or "auto"
    if query_mode not in {"auto", "manual", "merge"}:
        raise ValueError("model 来源只能是 auto、manual 或 merge")
    models = {}
    if query_mode in {"auto", "merge"}:
        query_key = key or (os.environ.get(env_name) if env_name else None)
        models = discover_provider_models(base, query_key)
        if models:
            ui_ok(f"已查询到 {len(models)} 个 model")
        else:
            ui_warn("自动查询失败，请手动输入 model。")
    if query_mode == "manual" or query_mode == "merge" or not models:
        raw_models = input_fn("model ID（逗号分隔，可回车稍后配置）：").strip()
        for mid in (part.strip() for part in raw_models.split(",")):
            if mid:
                models.setdefault(mid, {"name": mid})
    entry = {"displayName": display, "baseURL": base, "api": api}
    if env_name:
        entry["apiKeyEnv"] = env_name
    if key:
        entry["apiKey"] = key
    if models:
        entry["models"] = models
    providers[provider_id] = entry
    return provider_id


def provider_remove(data: dict, provider_id: str, force: bool = False) -> None:
    providers = data.get("providers") or {}
    if not isinstance(providers, dict):
        raise ValueError("providers 必须是对象")
    provider_id = validate_provider_id(provider_id)
    if provider_id not in providers:
        raise ValueError(f"provider 不存在: {provider_id}")
    refs = provider_references(data, provider_id)
    if refs and not force:
        raise ValueError(f"provider 仍被 agent 使用： {', '.join(refs)}；请先改绑或使用 --force")
    del providers[provider_id]


def provider_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agent_vendors_cli.py provider", description="管理自定义 provider")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="列出 provider")
    add = sub.add_parser("add", help="新增 provider")
    add.add_argument("provider_id", nargs="?", help="provider ID；省略则交互输入")
    refresh = sub.add_parser("refresh", help="从 provider 的 /models 刷新 model 列表")
    refresh.add_argument("provider_id")
    refresh.add_argument("--merge", action="store_true", help="合并发现结果，不删除现有 model")
    remove = sub.add_parser("remove", help="删除 provider")
    remove.add_argument("provider_id")
    remove.add_argument("--force", action="store_true", help="即使仍被 agent 引用也删除")
    args = parser.parse_args(argv)
    data = load_config()
    if args.action != "list":
        ui_header("Provider 管理", f"操作： {args.action}")
    if args.action == "list":
        ui_header("Provider 管理", "已配置的 provider")
        providers = data.get("providers") or {}
        if not isinstance(providers, dict):
            raise ValueError("providers 必须是对象")
        rows = []
        for pid, provider in providers.items():
            provider = provider if isinstance(provider, dict) else {}
            rows.append((str(pid), str(provider.get("displayName") or pid), str(provider.get("baseURL") or "<empty>")))
        if not rows:
            ui_warn("暂无 provider。使用 `provider add <id>` 新增。")
            return 0
        widths = [max(len(row[i]) for row in rows + [("ID", "名称", "Base URL")]) for i in range(3)]
        print(f"  {'ID'.ljust(widths[0])}  {'名称'.ljust(widths[1])}  Base URL")
        print(f"  {'-' * widths[0]}  {'-' * widths[1]}  {'-' * widths[2]}")
        for pid, name, base in rows:
            print(f"  {pid.ljust(widths[0])}  {name.ljust(widths[1])}  {base}")
        return 0
    if args.action == "add":
        pid = provider_add(data, args.provider_id)
        save_config(data)
        ui_ok(f"已新增 provider： {pid}")
        return 0
    if args.action == "refresh":
        providers = data.get("providers") or {}
        if not isinstance(providers, dict) or args.provider_id not in providers:
            raise ValueError(f"provider 不存在: {args.provider_id}")
        provider = providers[args.provider_id] if isinstance(providers[args.provider_id], dict) else {}
        key = provider.get("apiKey") or (os.environ.get(str(provider["apiKeyEnv"])) if provider.get("apiKeyEnv") else None)
        models = discover_provider_models(str(provider.get("baseURL") or ""), key)
        if not models:
            raise ValueError("未查询到 model，请检查 Base URL、API key 或网关是否支持 /models")
        if args.merge:
            old = provider.get("models") if isinstance(provider.get("models"), dict) else {}
            old.update(models)
            provider["models"] = old
        else:
            provider["models"] = models
        save_config(data)
        ui_ok(f"已刷新 provider {args.provider_id}： {len(models)} 个 model")
        return 0
    provider_remove(data, args.provider_id, args.force)
    save_config(data)
    ui_ok(f"已删除 provider： {args.provider_id}")
    return 0


PREFERRED = {"gpt": "gpt-5.6-sol", "opencode-go": "deepseek-v4-pro"}
MODEL_EXTRAS = {
    "gpt": {
        "gpt-5.5": {"name": "GPT 5.5"},
        "gpt-5.6-sol": {"name": "GPT 5.6 Sol"},
        "gpt-4.1": {"name": "GPT 4.1"},
        "gpt-4o": {"name": "GPT 4o"},
        "o3": {"name": "o3"},
        "o4-mini": {"name": "o4-mini"},
    },
    "opencode-go": {
        # Models exposed by OpenCode Go and common compatible gateways.  The
        # catalog is intentionally static as a fallback, so a fresh machine
        # can choose a model before its local model cache has been created.
        "kimi-k3": {"name": "Kimi K3"},
        "kimi-k2.7-code": {"name": "Kimi K2.7 Code"},
        "kimi-k2.6": {"name": "Kimi K2.6"},
        "kimi-k2.5": {"name": "Kimi K2.5"},
        "glm-5.3": {"name": "GLM 5.3"},
        "glm-5.2": {"name": "GLM 5.2"},
        "glm-5.1": {"name": "GLM 5.1"},
        "glm-5": {"name": "GLM 5"},
        "mimo-v2-pro": {"name": "MiMo V2 Pro"},
        "mimo-v2-omni": {"name": "MiMo V2 Omni"},
        "mimo-v2.5-pro": {"name": "MiMo V2.5 Pro"},
        "mimo-v2.5": {"name": "MiMo V2.5"},
        "hy3-preview": {"name": "Hy3 Preview"},
        "hy3": {"name": "Hy3"},
        "muse-spark-1.2-contributor": {"name": "Muse Spark 1.2 Contributor"},
        "deepseek-v4-pro": {"name": "DeepSeek V4 Pro"},
        "deepseek-v4-flash": {"name": "DeepSeek V4 Flash"},
        "deepseek-v4-flash-vision-exp": {"name": "DeepSeek V4 Flash Vision Exp"},
        "glm-5.3-flash": {"name": "GLM 5.3 Flash"},
        "gpt-5.6-luna": {"name": "GPT 5.6 Luna"},
        "grok-4.5": {"name": "Grok 4.5"},
        "grok-4.6": {"name": "Grok 4.6"},
        "longcat-2.0": {"name": "LongCat 2.0"},
        "qwen3.6-plus": {"name": "Qwen 3.6 Plus"},
        "qwen3.7-max": {"name": "Qwen 3.7 Max"},
        "qwen3.7-plus": {"name": "Qwen 3.7 Plus"},
        "qwen3.8-max": {"name": "Qwen 3.8 Max"},
        "minimax-m3": {"name": "MiniMax M3"},
        "minimax-m2.7": {"name": "MiniMax M2.7"},
        "minimax-m2.5": {"name": "MiniMax M2.5"},
    },
}

# Presets are keyed by provider ID.  A generic ``gpt`` provider is commonly a
# private gateway, so it must not offer a DeepSeek (or another vendor) URL.
VENDOR_BASE_URL_PRESETS = {
    "openai": (("OpenAI 官方", "https://api.openai.com/v1", "openai-completions"),),
    "deepseek": (("DeepSeek 官方", "https://api.deepseek.com", "openai-completions"),),
    "openrouter": (("OpenRouter", "https://openrouter.ai/api/v1", "openai-completions"),),
    "siliconflow": (("SiliconFlow", "https://api.siliconflow.cn/v1", "openai-completions"),),
}

PROVIDER_ROLES = {
    "gpt": "Codex 的默认入口（GPT 或自建兼容网关）",
    "opencode-go": "Claude Code、Pi、ZCode 和 DSH 的共享入口",
}

PATH_LABELS = {
    "claude_settings": "Claude Code settings.json",
    "codex_config": "Codex config.toml",
    "pi_settings": "Pi settings.json",
    "dsh_settings": "DSH settings.yaml",
}

PLATFORM = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")

# Keep the UI dependency-free. ANSI colors are enabled only for interactive
# terminals and can be disabled with the standard NO_COLOR environment flag.
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
_ANSI = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "cyan": "\x1b[36m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "red": "\x1b[31m",
    "dim": "\x1b[2m",
}


def paint(text: str, color: str) -> str:
    if not _COLOR:
        return text
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def ui_header(title: str, subtitle: str | None = None) -> None:
    print()
    print(paint("=" * 58, "cyan"))
    print(paint(f"  {title}", "bold"))
    if subtitle:
        print(paint(f"  {subtitle}", "dim"))
    print(paint("=" * 58, "cyan"))


def ui_section(title: str) -> None:
    print(f"\n{paint(f'[{title}]', 'cyan')}")


def ui_ok(message: str) -> None:
    print(f"{paint('OK', 'green')}  {message}")


def ui_warn(message: str) -> None:
    print(f"{paint('提示', 'yellow')}  {message}")


def ui_error(message: str) -> None:
    print(f"{paint('错误', 'red')}  {message}", file=sys.stderr)


def model_catalog(data: dict, provider_id: str) -> dict:
    p = (data.get("providers") or {}).get(provider_id) or {}
    models = p.get("models") or {}
    if not isinstance(models, dict):
        models = {}
    merged = copy.deepcopy(models)
    # Codex keeps an additional local catalog.  Merge it even when the YAML
    # already contains models, otherwise newly installed models would be
    # hidden by the first (partial) source.
    if provider_id == "gpt":
        codex_catalog = Path.home() / ".codex" / "models.json"
        if codex_catalog.exists():
            try:
                payload = yaml.safe_load(codex_catalog.read_text(encoding="utf-8")) or {}
                rows = payload.get("models", []) if isinstance(payload, dict) else []
                for row in rows:
                    if isinstance(row, dict) and row.get("slug"):
                        slug = str(row["slug"])
                        merged.setdefault(slug, {"name": slug})
            except (OSError, AttributeError, TypeError, yaml.YAMLError):
                pass
    for mid, meta in MODEL_EXTRAS.get(provider_id, {}).items():
        merged.setdefault(mid, copy.deepcopy(meta))
    if merged:
        return merged
    current = ((data.get("agents") or {}).get("codex") or {}).get("defaultModel")
    if provider_id == "gpt":
        value = str(current or PREFERRED["gpt"])
        return {value: {"name": value}}
    return {}


def provider_ids(data: dict) -> list[str]:
    """Return the configured provider registry without imposing a fixed set."""
    providers = data.get("providers") or {}
    if not isinstance(providers, dict) or not providers:
        raise ValueError("至少需要配置一个 provider")
    return [str(pid) for pid in providers]


def provider_usage(data: dict, provider_id: str) -> list[str]:
    """Return agent names that currently reference a provider."""
    used_by = []
    for name, agent in (data.get("agents") or {}).items():
        if not isinstance(agent, dict):
            continue
        refs = {agent.get("provider"), agent.get("defaultProvider")}
        listed = agent.get("providers")
        if isinstance(listed, list):
            refs.update(listed)
        elif isinstance(listed, dict):
            refs.update(listed)
        if provider_id in refs:
            used_by.append(str(name))
    return used_by


def provider_label(data: dict, provider_id: str) -> str:
    provider = ((data.get("providers") or {}).get(provider_id) or {})
    if isinstance(provider, dict) and provider.get("displayName"):
        return str(provider["displayName"])
    return {"gpt": "GPT 兼容网关", "opencode-go": "OpenCode Go"}.get(provider_id, provider_id)


def choose_index(prompt: str, count: int, input_fn=input, default: int = 1) -> int:
    """Read a menu index with ccswitch-style retry instead of a traceback."""
    while True:
        answer = input_fn(prompt).strip().lower()
        if not answer:
            return default
        if answer in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        try:
            index = int(answer)
        except ValueError:
            ui_warn("请输入菜单编号，或输入 q = 取消。")
            continue
        if 1 <= index <= count:
            return index
        ui_warn(f"请输入 1 到 {count} 之间的编号。")


def choose_provider_settings(data: dict, provider_id: str, input_fn=input) -> dict[str, str]:
    current = ((data.get("providers") or {}).get(provider_id) or {})
    current_url = str(current.get("baseURL") or "")
    current_api = str(current.get("api") or current.get("defaultWireApi") or "")
    if not current_api:
        wire = str(current.get("wireApi") or "")
        current_api = "openai-responses" if wire == "responses" else "openai-completions"
    presets = []
    if current_url:
        presets.append(("当前配置", current_url, current_api))
    if provider_id == "gpt":
        # A GPT provider in this project is normally a user-supplied proxy.
        presets.append(("自定义", "", current_api or "openai-completions"))
    elif provider_id == "opencode-go":
        presets.append(("OpenCode Go 官方", "https://opencode.ai/zen/go/v1", "openai-completions"))
        presets.append(("自定义", "", current_api or "openai-completions"))
    elif provider_id in VENDOR_BASE_URL_PRESETS:
        presets.extend(VENDOR_BASE_URL_PRESETS[provider_id])
        presets.append(("自定义", "", current_api or "openai-completions"))
    else:
        presets.append(("自定义", "", current_api or "openai-completions"))
    label = provider_label(data, provider_id)
    role = PROVIDER_ROLES.get(provider_id, "自定义 provider")
    ui_section(f"{label}（{provider_id}）")
    print(paint(f"用途：{role}", "dim"))
    for i, (name, url, api) in enumerate(presets, 1):
        suffix = f" — {url}" if url else ""
        print(f"  {i:>2}. {name}{suffix}")
    default = 1
    default_label = "当前配置" if current_url else presets[default - 1][0]
    index = choose_index(f"选择地址（回车 = {default_label}，q = 取消）：", len(presets), input_fn, default)
    name, url, api = presets[index - 1]
    if name == "自定义" or not url:
        url = input_fn("Base URL：").strip()
        if not url:
            raise ValueError("自定义 Base URL 不能为空")
        while True:
            entered = input_fn(f"API 类型（openai-completions / openai-responses）[{api}]：").strip()
            if not entered:
                break
            if entered in {"openai-completions", "openai-responses"}:
                api = entered
                break
            ui_warn("API 类型只能是 openai-completions 或 openai-responses。")
    return {"baseURL": url, "api": api}


def choose_models(provider_id: str, catalog: dict, input_fn=input) -> dict:
    ids = list(catalog)
    if not ids:
        raise ValueError(f"{provider_id} 没有可选模型")
    ui_section(f"{provider_id} models")
    print(paint("当前全部已勾选；输入编号切换选择", "dim"))
    for i, mid in enumerate(ids, 1):
        label = (catalog[mid] or {}).get("name") or mid
        print(f"  {i:>2}. [x] {label} ({mid})")
    while True:
        answer = input_fn("保留哪些模型？回车 / all = 全部，输入编号如 1, 3，none = 不保留，q = 取消：").strip().lower()
        if answer in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        if not answer or answer == "all":
            selected = ids
        elif answer == "none":
            ui_warn(f"{provider_id} 至少要保留一个 model。")
            continue
        else:
            try:
                indexes = [int(x.strip()) for x in answer.split(",") if x.strip()]
            except ValueError:
                ui_warn("模型编号格式应为逗号分隔的数字，例如 1, 3。")
                continue
            if any(i < 1 or i > len(ids) for i in indexes):
                ui_warn(f"模型编号必须在 1 到 {len(ids)} 之间。")
                continue
            selected = [ids[i - 1] for i in indexes]
            if not selected:
                ui_warn(f"{provider_id} 至少要保留一个 model。")
                continue
        return {mid: catalog[mid] for mid in selected}


def choose_one(label: str, provider_id: str, catalog: dict, current: str = "", input_fn=input) -> str:
    ids = list(catalog)
    if not ids:
        raise ValueError(f"{provider_id} 没有可选模型")
    ui_section(f"{label}（provider: {provider_id}）")
    for i, mid in enumerate(ids, 1):
        marker = "*" if mid == current else " "
        name = (catalog[mid] or {}).get("name") or mid
        print(f"  {i:>2}. [{marker}] {name} ({mid})")
    default = ids.index(current) + 1 if current in catalog else (
        ids.index(PREFERRED[provider_id]) + 1 if PREFERRED.get(provider_id) in catalog else 1
    )
    return ids[choose_index("选择一个 model 编号，回车保留当前 / 推荐值，q = 取消：", len(ids), input_fn, default) - 1]


def ask_key(provider_id: str) -> str:
    old = ((load_config().get("providers") or {}).get(provider_id) or {}).get("apiKey")
    hint = "已设置，回车保持原值" if old else "未设置，请输入"
    return getpass.getpass(f"{provider_id} API key（{hint}）：").strip()


def path_candidates(key: str) -> list[Path]:
    home = Path.home()
    if os.name == "nt":
        roots = [home, home / "AppData" / "Roaming"]
    else:
        roots = [home, home / ".config"]
    suffixes = {
        "claude_settings": [(".claude", "settings.json"), (".config", "claude", "settings.json")],
        "codex_config": [(".codex", "config.toml"), (".config", "codex", "config.toml")],
        "pi_settings": [(".pi", "agent", "settings.json"), (".config", "pi", "agent", "settings.json")],
        "dsh_settings": [(".dsh", "settings.yaml"), (".config", "dsh", "settings.yaml")],
    }
    out = []
    for suffix in suffixes[key]:
        for root in roots:
            p = root.joinpath(*suffix)
            if p not in out and p.exists():
                out.append(p)
    return out


def choose_path(data: dict, key: str, input_fn=input) -> Path:
    path_map = data.get("paths") or {}
    if not isinstance(path_map, dict):
        path_map = {}
    if isinstance(path_map.get(PLATFORM), dict):
        configured = path_map[PLATFORM].get(key)
    else:
        configured = path_map.get(key)
        if isinstance(configured, dict):
            configured = configured.get(PLATFORM) or configured.get("default")
    candidates = path_candidates(key)
    default = Path(os.path.expandvars(os.path.expanduser(str(configured)))) if configured else (candidates[0] if candidates else None)
    if default:
        prompt = f"{PATH_LABELS[key]} [{default}]，回车接受："
    else:
        prompt = f"{PATH_LABELS[key]}（未探测到现有文件，请输入路径）："
    answer = input_fn(prompt).strip()
    if answer:
        return Path(os.path.expandvars(os.path.expanduser(answer))).resolve()
    if default:
        return default
    raise ValueError(f"必须提供 {PATH_LABELS[key]} 路径")


def choose_paths(data: dict, input_fn=input) -> dict[str, str]:
    current = {key: str(choose_path(data, key, input_fn)) for key in PATH_LABELS}
    old = data.get("paths") or {}
    # Store paths per platform so a shared YAML can be used on Windows and Linux.
    paths = copy.deepcopy(old) if isinstance(old, dict) and isinstance(old.get(PLATFORM), dict) else {}
    paths.setdefault(PLATFORM, {}).update(current)
    # Companion files live beside the selected primary file.  This also makes
    # a custom Windows or Linux Codex/Pi/DSH directory work consistently.
    paths[PLATFORM]["codex_models"] = str(Path(current["codex_config"]).with_name("models.json"))
    paths[PLATFORM]["codex_deepseek_config"] = str(Path(current["codex_config"]).with_name("deepseek.config.toml"))
    paths[PLATFORM]["pi_models"] = str(Path(current["pi_settings"]).with_name("models.json"))
    paths[PLATFORM]["dsh_credentials"] = str(Path(current["dsh_settings"]).with_name(".credentials.yaml"))
    return paths


def compact_agents(data: dict, models: dict[str, dict], choices: dict[str, str] | None = None) -> None:
    """Apply model choices without rewriting an agent's provider selection."""
    agents = data.setdefault("agents", {})
    choices = choices or {}
    for name, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        provider = str(agent.get("defaultProvider") or agent.get("provider") or "")
        catalog = models.get(provider) or {}
        if not catalog:
            continue

        def apply_choice(field: str, choice_key: str) -> None:
            value = choices.get(choice_key) or agent.get(field)
            if value not in catalog:
                preferred = PREFERRED.get(provider)
                value = preferred if preferred in catalog else next(iter(catalog))
            agent[field] = value

        if name == "codex":
            apply_choice("defaultModel", "codex.defaultModel")
        elif name == "claude":
            for field in ("defaultModel", "flashModel", "haikuModel", "sonnetModel", "opusModel"):
                apply_choice(field, f"claude.{field}")
        elif name == "pi":
            apply_choice("defaultModel", "pi.defaultModel")
        elif name == "dsh":
            apply_choice("defaultModel", "dsh.defaultModel")


def proposed(data: dict, selected: dict[str, dict], keys: dict[str, str], choices: dict[str, str] | None = None, paths: dict[str, str] | None = None, provider_settings: dict[str, dict[str, str]] | None = None) -> dict:
    out = copy.deepcopy(data)
    providers = out.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        out["providers"] = providers
    for pid, models_for_provider in selected.items():
        p = providers.setdefault(pid, {})
        if not isinstance(p, dict):
            p = {}
            providers[pid] = p
        if keys.get(pid):
            p["apiKey"] = keys[pid]
        p["models"] = models_for_provider
        if provider_settings and pid in provider_settings:
            p.update(provider_settings[pid])
            if pid == "gpt":
                # Codex currently accepts the Responses wire API only.
                p["wireApi"] = "responses"
        if pid == "opencode-go" and p.get("baseURL") and not p.get("anthropicBaseURL"):
            # OpenCode Go exposes OpenAI at /v1 but Claude's Messages API at
            # the parent path.  Persist the derived endpoint so every agent
            # uses the same, unambiguous provider definition.
            base = str(p["baseURL"]).rstrip("/")
            p["anthropicBaseURL"] = base[:-3].rstrip("/") if base.endswith("/v1") else base
    if paths:
        out["paths"] = paths
    compact_agents(out, selected, choices)
    return out


def choose_agent_models(data: dict, selected: dict[str, dict], input_fn=input) -> dict[str, str]:
    agents = data.get("agents") or {}
    out: dict[str, str] = {}

    def choose_for(agent_name: str, field: str, label: str, fallback_field: str | None = None) -> None:
        agent = agents.get(agent_name) or {}
        provider = str(agent.get("defaultProvider") or agent.get("provider") or "")
        catalog = selected.get(provider) or {}
        if not provider or not catalog:
            return
        current = str(agent.get(field) or (agent.get(fallback_field) if fallback_field else "") or "")
        out[f"{agent_name}.{field}"] = choose_one(label, provider, catalog, current, input_fn)

    choose_for("codex", "defaultModel", "Codex 默认 model")
    choose_for("claude", "defaultModel", "Claude Code 默认 model")
    choose_for("claude", "haikuModel", "Claude Code Haiku model", "flashModel")
    choose_for("claude", "sonnetModel", "Claude Code Sonnet model", "defaultModel")
    choose_for("claude", "opusModel", "Claude Code Opus model", "defaultModel")
    choose_for("pi", "defaultModel", "Pi 默认 model")
    choose_for("dsh", "defaultModel", "DSH 默认 model")
    return out


def run_sync(dry_run: bool) -> int:
    args = [sys.executable, str(SYNC_SCRIPT), "sync"]
    if dry_run:
        args.append("--dry-run")
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "provider":
        try:
            return provider_command(sys.argv[2:])
        except (OSError, ValueError, yaml.YAMLError) as exc:
            ui_error(f"配置失败：{exc}")
            return 2
    parser = argparse.ArgumentParser(description="配置 Agent Vendors provider 和 model")
    parser.add_argument("--yes", action="store_true", help="跳过最终确认")
    parser.add_argument("--dry-run", action="store_true", help="只显示同步预览，不写入")
    parser.add_argument("--no-sync", action="store_true", help="保存 YAML，但不执行同步")
    args = parser.parse_args()

    try:
        data = load_config()
        pids = provider_ids(data)
        ui_header("Agent Vendors", "配置向导")
        ui_section("Provider 概览")
        for pid in pids:
            usage = provider_usage(data, pid)
            users = "、".join(usage) if usage else "暂无 agent"
            print(f"  {provider_label(data, pid)}（{pid}）")
            print(f"       用途：{PROVIDER_ROLES.get(pid, '自定义 provider')}；使用中：{users}")
        paths = choose_paths(data)
        provider_settings = {pid: choose_provider_settings(data, pid) for pid in pids}
        keys = {pid: ask_key(pid) for pid in pids}
        selected = {}
        for pid in pids:
            catalog = model_catalog(data, pid)
            selected[pid] = choose_models(pid, catalog) if catalog else (
                copy.deepcopy(((data.get("providers") or {}).get(pid) or {}).get("models") or {})
            )
        choices = choose_agent_models(data, selected)
        out = proposed(data, selected, keys, choices, paths, provider_settings)
    except KeyboardInterrupt:
        ui_warn("已取消")
        return 130
    except (OSError, ValueError, yaml.YAMLError) as exc:
        ui_error(f"配置失败：{exc}")
        return 2
    ui_header("配置预览", "请确认以下变更")
    ui_section("变更预览")
    print("将更新 provider：" + ", ".join(pids))
    for pid in pids:
        key_status = paint("更新", "green") if keys[pid] else paint("保持原值", "dim")
        print(f"  {pid}: {len(selected[pid])} 个 model，API key {key_status}")
        print(f"       Base URL = {provider_settings[pid]['baseURL']} ({provider_settings[pid]['api']})")
    ui_section("Agent 默认模型")
    for key, value in choices.items():
        print(f"  {key} = {value}")
    ui_section("配置路径")
    path_summary = paths.get(PLATFORM, {})
    for key, value in path_summary.items():
        if key in PATH_LABELS:
            print(f"  {PATH_LABELS[key]} = {value}")
    if not args.yes and input("\n应用以上配置？ [Y/n] ").strip().lower() not in ("", "y", "yes"):
        ui_warn("已取消")
        return 0
    if args.dry_run:
        ui_warn("dry-run 模式：不写入 YAML，也不会触发同步。")
        return 0
    save_config(out)
    ui_ok(f"已保存：{YAML_FILE}")
    if not args.no_sync:
        return run_sync(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
