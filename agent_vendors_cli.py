#!/usr/bin/env python3
"""Interactive, small-surface configuration wizard for agent-vendors.yaml.

Only GPT and OpenCode Go are kept.  The wizard asks for write-only API keys and
model selections, then rewrites agent references so the next sync is coherent.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

HOME = Path.home()
YAML_FILE = Path(os.environ.get("AGENT_VENDORS_FILE", HOME / ".agents" / "agent-vendors.yaml"))
SYNC_SCRIPT = Path(__file__).resolve().with_name("agent_vendors.py")
BACKUP_DIR = HOME / ".agents" / "backups" / "agent-vendors"


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


def backup_config() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"agent-vendors.yaml.{stamp}"
    if dest.exists():
        dest = BACKUP_DIR / f"agent-vendors.yaml.{stamp}.{os.getpid()}"
    shutil.copy2(YAML_FILE, dest)
    return dest


KEEP = ("gpt", "opencode-go")
PREFERRED = {"gpt": "gpt-5.6-sol", "opencode-go": "deepseek-v4-pro"}

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
    if isinstance(models, dict) and models:
        return copy.deepcopy(models)
    if provider_id == "gpt":
        # GPT historically had no top-level catalog; use Codex's local catalog
        # when available, then fall back to its current default.
        codex_catalog = Path.home() / ".codex" / "models.json"
        if codex_catalog.exists():
            try:
                rows = yaml.safe_load(codex_catalog.read_text(encoding="utf-8")).get("models", [])
                slugs = [str(row.get("slug")) for row in rows if isinstance(row, dict) and row.get("slug")]
                if slugs:
                    return {slug: {"name": slug} for slug in slugs}
            except (OSError, AttributeError, yaml.YAMLError):
                pass
        current = ((data.get("agents") or {}).get("codex") or {}).get("defaultModel")
        return {str(current or "gpt-5.6-sol"): {"name": str(current or "gpt-5.6-sol")}}
    return {}


def choose_models(provider_id: str, catalog: dict, input_fn=input) -> dict:
    ids = list(catalog)
    if not ids:
        raise ValueError(f"{provider_id} 没有可选模型")
    print(f"\n{provider_id} models（当前全部已勾选；输入编号切换选择）:")
    for i, mid in enumerate(ids, 1):
        label = (catalog[mid] or {}).get("name") or mid
        print(f"  {i:>2}. [x] {label} ({mid})")
    answer = input_fn("保留哪些模型？回车=全部，输入编号如 1,3，输入 all=全部，none=不保留: ").strip().lower()
    if not answer or answer == "all":
        selected = ids
    elif answer == "none":
        selected = []
    else:
        try:
            indexes = [int(x.strip()) for x in answer.split(",") if x.strip()]
            selected = [ids[i - 1] for i in indexes if 1 <= i <= len(ids)]
        except ValueError as exc:
            raise ValueError("模型编号格式应为逗号分隔的数字，例如 1,3") from exc
    if not selected:
        raise ValueError(f"{provider_id} 至少要保留一个 model")
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
    answer = input_fn("选择一个 model 编号，回车保留当前/推荐值: ").strip()
    if not answer:
        if current in catalog:
            return current
        preferred = PREFERRED.get(provider_id)
        return preferred if preferred in catalog else ids[0]
    try:
        index = int(answer)
    except ValueError as exc:
        raise ValueError("model 编号必须是数字") from exc
    if not 1 <= index <= len(ids):
        raise ValueError("model 编号超出范围")
    return ids[index - 1]


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
    """Make every supported agent refer only to the two retained providers."""
    agents = data.setdefault("agents", {})
    choices = choices or {}
    def keep_or_first(agent: dict, field: str, catalog: dict[str, dict], provider_id: str) -> str:
        old = str(agent.get(field) or "")
        preferred = PREFERRED.get(provider_id, "")
        return preferred if preferred in catalog else old if old in catalog else next(iter(catalog))

    gpt_model = choices.get("codex.defaultModel") or keep_or_first(agents.get("codex") or {}, "defaultModel", models["gpt"], "gpt")
    for name, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        if name == "codex":
            agent["defaultProvider"] = "gpt"
            agent["defaultModel"] = gpt_model
            agent.pop("deepseekProfile", None)
            agent["providers"] = {"gpt": {"provider": "gpt", "baseURL": data["providers"]["gpt"].get("baseURL", ""), "wireApi": "responses"}}
        elif name == "claude":
            agent["provider"] = "opencode-go"
            agent["defaultModel"] = choices.get("claude.defaultModel") or keep_or_first(agent, "defaultModel", models["opencode-go"], "opencode-go")
            agent["flashModel"] = choices.get("claude.flashModel") or keep_or_first(agent, "flashModel", models["opencode-go"], "opencode-go")
            agent["haikuModel"] = choices.get("claude.haikuModel") or agent["flashModel"]
            agent["flashModel"] = agent["haikuModel"]
            agent["opusModel"] = choices.get("claude.opusModel") or agent["defaultModel"]
            agent["sonnetModel"] = choices.get("claude.sonnetModel") or agent["defaultModel"]
            agent["baseURL"] = data["providers"]["opencode-go"].get("baseURL", "")
            agent["providers"] = ["opencode-go"]
        elif name == "pi":
            agent["provider"] = "opencode-go"
            agent["defaultModel"] = choices.get("pi.defaultModel") or keep_or_first(agent, "defaultModel", models["opencode-go"], "opencode-go")
            agent["baseURL"] = data["providers"]["opencode-go"].get("baseURL", "")
            agent["providers"] = list(KEEP)
        elif name == "dsh":
            agent["defaultProvider"] = "opencode-go"
            agent["defaultModel"] = choices.get("dsh.defaultModel") or keep_or_first(agent, "defaultModel", models["opencode-go"], "opencode-go")
            agent["llmPiAiProviders"] = list(KEEP)
            agent["llmDeepseekModels"] = []
            agent["credentials"] = {"GPT_API_KEY": "gpt.apiKey", "OPENCODE_GO_API_KEY": "opencode-go.apiKey"}
        elif name == "zcode":
            old = agent.get("providers") or {}
            agent["defaultProvider"] = "opencode-go"
            agent["providers"] = {
                pid: {
                    "provider": pid,
                    "name": data["providers"][pid].get("displayName") or pid,
                    "kind": "openai-compatible",
                    "baseURL": data["providers"][pid].get("baseURL", ""),
                    "enabled": bool((old.get(pid) or {}).get("enabled", True)),
                }
                for pid in KEEP
            }


def proposed(data: dict, selected: dict[str, dict], keys: dict[str, str], choices: dict[str, str] | None = None, paths: dict[str, str] | None = None) -> dict:
    out = copy.deepcopy(data)
    providers = out.setdefault("providers", {})
    out["providers"] = {pid: copy.deepcopy(providers.get(pid) or {}) for pid in KEEP}
    for pid in KEEP:
        p = out["providers"][pid]
        if keys.get(pid):
            p["apiKey"] = keys[pid]
        p["models"] = selected[pid]
    if paths:
        out["paths"] = paths
    compact_agents(out, selected, choices)
    return out


def choose_agent_models(data: dict, selected: dict[str, dict], input_fn=input) -> dict[str, str]:
    agents = data.get("agents") or {}
    out: dict[str, str] = {}
    codex = agents.get("codex") or {}
    out["codex.defaultModel"] = choose_one("Codex 默认 model", "gpt", selected["gpt"], str(codex.get("defaultModel") or ""), input_fn)
    claude = agents.get("claude") or {}
    out["claude.defaultModel"] = choose_one("Claude Code 默认 model", "opencode-go", selected["opencode-go"], str(claude.get("defaultModel") or ""), input_fn)
    out["claude.haikuModel"] = choose_one("Claude Code Haiku model", "opencode-go", selected["opencode-go"], str(claude.get("haikuModel") or claude.get("flashModel") or ""), input_fn)
    out["claude.sonnetModel"] = choose_one("Claude Code Sonnet model", "opencode-go", selected["opencode-go"], str(claude.get("sonnetModel") or claude.get("defaultModel") or ""), input_fn)
    out["claude.opusModel"] = choose_one("Claude Code Opus model", "opencode-go", selected["opencode-go"], str(claude.get("opusModel") or claude.get("defaultModel") or ""), input_fn)
    pi = agents.get("pi") or {}
    out["pi.defaultModel"] = choose_one("Pi 默认 model", "opencode-go", selected["opencode-go"], str(pi.get("defaultModel") or ""), input_fn)
    dsh = agents.get("dsh") or {}
    out["dsh.defaultModel"] = choose_one("DSH 默认 model", "opencode-go", selected["opencode-go"], str(dsh.get("defaultModel") or ""), input_fn)
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
    parser = argparse.ArgumentParser(description="只保留 gpt / opencode-go 的 Agent Vendors CLI 配置向导")
    parser.add_argument("--yes", action="store_true", help="跳过最终确认")
    parser.add_argument("--dry-run", action="store_true", help="只显示同步预览，不写入")
    parser.add_argument("--no-sync", action="store_true", help="保存 YAML，但不执行同步")
    args = parser.parse_args()

    data = load_config()
    paths = choose_paths(data)
    keys = {pid: ask_key(pid) for pid in KEEP}
    selected = {pid: choose_models(pid, model_catalog(data, pid)) for pid in KEEP}
    choices = choose_agent_models(data, selected)
    out = proposed(data, selected, keys, choices, paths)
    print("\n将保留 provider: gpt, opencode-go")
    for pid in KEEP:
        print(f"  {pid}: {len(selected[pid])} 个 model，API key {'更新' if keys[pid] else '保持原值'}")
    print("  agent defaults: " + ", ".join(f"{k}={v}" for k, v in choices.items()))
    path_summary = paths.get(PLATFORM, {})
    print("  config paths: " + ", ".join(f"{k}={v}" for k, v in path_summary.items() if k in PATH_LABELS))
    if not args.yes and input("应用以上配置？[Y/n] ").strip().lower() not in ("", "y", "yes"):
        print("已取消")
        return 0
    if args.dry_run:
        print("\n[dry-run] 不写入 YAML，也不会触发同步。")
        return 0
    backup = backup_config()
    save_config(out)
    print(f"已保存，备份: {backup}")
    if not args.no_sync:
        return run_sync(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
