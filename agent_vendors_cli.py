#!/usr/bin/env python3
"""Interactive, small-surface configuration wizard for agent-vendors.yaml.

The wizard edits the provider registry in place.  It asks for write-only API
keys and model selections, then keeps each agent's existing provider binding.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import os
import subprocess
import sys
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
    tmp.replace(YAML_FILE)


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

# A short, provider-neutral list.  ``gpt`` is commonly a private gateway in
# this project, so it deliberately starts with the custom entry below rather
# than suggesting that it means OpenAI's hosted service.
COMMON_BASE_URL_PRESETS = (
    ("OpenAI 官方", "https://api.openai.com/v1", "openai-completions"),
    ("DeepSeek 官方", "https://api.deepseek.com", "openai-completions"),
    ("OpenRouter", "https://openrouter.ai/api/v1", "openai-completions"),
    ("SiliconFlow", "https://api.siliconflow.cn/v1", "openai-completions"),
)

PATH_LABELS = {
    "claude_settings": "Claude Code settings.json",
    "codex_config": "Codex config.toml",
    "pi_settings": "Pi settings.json",
    "dsh_settings": "DSH settings.yaml",
}

PLATFORM = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")


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
            print("请输入菜单编号，或输入 q 取消。")
            continue
        if 1 <= index <= count:
            return index
        print(f"请输入 1 到 {count} 之间的编号。")


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
        presets.extend(COMMON_BASE_URL_PRESETS)
    elif provider_id == "opencode-go":
        presets.append(("OpenCode Go 官方", "https://opencode.ai/zen/go/v1", "openai-completions"))
        presets.append(("自定义", "", current_api or "openai-completions"))
    else:
        presets.append(("自定义", "", current_api or "openai-completions"))
    print(f"\n{provider_id} provider 设置:")
    for i, (name, url, api) in enumerate(presets, 1):
        suffix = f" — {url}" if url else ""
        print(f"  {i}. {name}{suffix}")
    default = 1
    default_label = "当前配置" if current_url else presets[default - 1][0]
    index = choose_index(f"选择地址（回车={default_label}，q=取消）: ", len(presets), input_fn, default)
    name, url, api = presets[index - 1]
    if name == "自定义" or not url:
        url = input_fn("Base URL: ").strip()
        if not url:
            raise ValueError("自定义 Base URL 不能为空")
        while True:
            entered = input_fn(f"API 类型（openai-completions / openai-responses）[{api}]: ").strip()
            if not entered:
                break
            if entered in {"openai-completions", "openai-responses"}:
                api = entered
                break
            print("API 类型只能是 openai-completions 或 openai-responses。")
    return {"baseURL": url, "api": api}


def choose_models(provider_id: str, catalog: dict, input_fn=input) -> dict:
    ids = list(catalog)
    if not ids:
        raise ValueError(f"{provider_id} 没有可选模型")
    print(f"\n{provider_id} models（当前全部已勾选；输入编号切换选择）:")
    for i, mid in enumerate(ids, 1):
        label = (catalog[mid] or {}).get("name") or mid
        print(f"  {i:>2}. [x] {label} ({mid})")
    while True:
        answer = input_fn("保留哪些模型？回车/all=全部，输入编号如 1,3，none=不保留，q=取消: ").strip().lower()
        if answer in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        if not answer or answer == "all":
            selected = ids
        elif answer == "none":
            print(f"{provider_id} 至少要保留一个 model。")
            continue
        else:
            try:
                indexes = [int(x.strip()) for x in answer.split(",") if x.strip()]
            except ValueError:
                print("模型编号格式应为逗号分隔的数字，例如 1,3。")
                continue
            if any(i < 1 or i > len(ids) for i in indexes):
                print(f"模型编号必须在 1 到 {len(ids)} 之间。")
                continue
            selected = [ids[i - 1] for i in indexes]
            if not selected:
                print(f"{provider_id} 至少要保留一个 model。")
                continue
        return {mid: catalog[mid] for mid in selected}


def choose_one(label: str, provider_id: str, catalog: dict, current: str = "", input_fn=input) -> str:
    ids = list(catalog)
    if not ids:
        raise ValueError(f"{provider_id} 没有可选模型")
    print(f"\n{label}（provider: {provider_id}）:")
    for i, mid in enumerate(ids, 1):
        marker = "*" if mid == current else " "
        name = (catalog[mid] or {}).get("name") or mid
        print(f"  {i:>2}. [{marker}] {name} ({mid})")
    default = ids.index(current) + 1 if current in catalog else (
        ids.index(PREFERRED[provider_id]) + 1 if PREFERRED.get(provider_id) in catalog else 1
    )
    return ids[choose_index("选择一个 model 编号，回车保留当前/推荐值，q=取消: ", len(ids), input_fn, default) - 1]


def ask_key(provider_id: str) -> str:
    old = ((load_config().get("providers") or {}).get(provider_id) or {}).get("apiKey")
    hint = "已设置，回车保持原值" if old else "未设置，请输入"
    return getpass.getpass(f"{provider_id} API key（{hint}）: ").strip()


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
        prompt = f"{PATH_LABELS[key]} [{default}]，回车接受: "
    else:
        prompt = f"{PATH_LABELS[key]}（未探测到现有文件，请输入路径）: "
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
                p["wireApi"] = "responses" if p.get("api") == "openai-responses" else "chat"
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
    parser = argparse.ArgumentParser(description="配置 Agent Vendors provider 和 model")
    parser.add_argument("--yes", action="store_true", help="跳过最终确认")
    parser.add_argument("--dry-run", action="store_true", help="只显示同步预览，不写入")
    parser.add_argument("--no-sync", action="store_true", help="保存 YAML，但不执行同步")
    args = parser.parse_args()

    try:
        data = load_config()
        pids = provider_ids(data)
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
        print("\n已取消")
        return 130
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"配置失败: {exc}", file=sys.stderr)
        return 2
    print("\n将更新 provider: " + ", ".join(pids))
    for pid in pids:
        print(f"  {pid}: {len(selected[pid])} 个 model，API key {'更新' if keys[pid] else '保持原值'}")
        print(f"       baseURL={provider_settings[pid]['baseURL']} ({provider_settings[pid]['api']})")
    print("  agent defaults: " + ", ".join(f"{k}={v}" for k, v in choices.items()))
    path_summary = paths.get(PLATFORM, {})
    print("  config paths: " + ", ".join(f"{k}={v}" for k, v in path_summary.items() if k in PATH_LABELS))
    if not args.yes and input("应用以上配置？[Y/n] ").strip().lower() not in ("", "y", "yes"):
        print("已取消")
        return 0
    if args.dry_run:
        print("\n[dry-run] 不写入 YAML，也不会触发同步。")
        return 0
    save_config(out)
    print(f"已保存: {YAML_FILE}")
    if not args.no_sync:
        return run_sync(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
