#!/usr/bin/env python3
"""Agent vendor config centralization for DSH.

Commands:
    init        Build ~/.dsh/agent-vendors.yaml from existing agent configs.
    sync        Update Claude/Codex/Pi/ZCode/DSH from agent-vendors.yaml.

Examples:
    python agent_vendors.py init
    python agent_vendors.py sync --dry-run
    python agent_vendors.py sync
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import time
import tomllib
from pathlib import Path

import yaml

HOME = Path(os.path.expanduser("~"))
AGENTS_DIR = HOME / ".agents"
DSH = HOME / ".dsh"
VENDORS_FILE = AGENTS_DIR / "agent-vendors.yaml"
BACKUP_ROOT = AGENTS_DIR / "backups" / "agent-vendors"
HOME_POSIX = str(HOME).replace("\\", "/")

# Target file locations
TARGETS = {
    "claude_settings": HOME / ".claude" / "settings.json",
    "codex_config": HOME / ".codex" / "config.toml",
    "codex_deepseek_config": HOME / ".codex" / "deepseek.config.toml",
    "pi_settings": HOME / ".pi" / "agent" / "settings.json",
    "pi_models": HOME / ".pi" / "agent" / "models.json",
    "zcode_config": HOME / ".zcode" / "v2" / "config.json",
    "dsh_settings": DSH / "settings.yaml",
    "dsh_credentials": DSH / ".credentials.yaml",
}


def mask(value: str | None) -> str:
    """Show only a hint of a secret."""
    if not value:
        return "<empty>"
    s = str(value)
    if len(s) <= 8:
        return "<secret>"
    return f"{s[:4]}...{s[-4:]}"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def load_yaml(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    tmp.replace(path)


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / f"{path.name}.{stamp}"
    shutil.copy2(path, dest)
    return dest


# --------------------------------------------------------------------------
# Init: build agent-vendors.yaml from current configs
# --------------------------------------------------------------------------

def read_toml(path: Path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def extract_claude():
    data = load_json(TARGETS["claude_settings"])
    env = data.get("env", {}) if isinstance(data, dict) else {}
    return {
        "name": "claude",
        "provider": "deepseek",
        "apiKey": env.get("ANTHROPIC_AUTH_TOKEN"),
        "baseURL": env.get("ANTHROPIC_BASE_URL"),
        "flashModel": (env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") or "").replace("[1m]", ""),
        "defaultModel": (env.get("ANTHROPIC_MODEL") or "").replace("[1m]", ""),
        "maxContextTokens": env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS"),
    }


def extract_codex():
    cfg = read_toml(TARGETS["codex_config"])
    top = {
        "model": cfg.get("model"),
        "model_provider": cfg.get("model_provider"),
        "model_reasoning_effort": cfg.get("model_reasoning_effort"),
        "providers": {},
    }
    providers = cfg.get("model_providers", {}) or {}
    for name, p in providers.items():
        top["providers"][name] = {
            "name": p.get("name"),
            "base_url": p.get("base_url"),
            "wire_api": p.get("wire_api"),
            "apiKey": p.get("experimental_bearer_token"),
        }
    deepseek_cfg = None
    if TARGETS["codex_deepseek_config"].exists():
        deepseek_cfg = read_toml(TARGETS["codex_deepseek_config"])
    return {
        "name": "codex",
        "top": top,
        "deepseek_profile": deepseek_cfg,
    }


def extract_pi():
    settings = load_json(TARGETS["pi_settings"])
    models = load_json(TARGETS["pi_models"])
    providers = models.get("providers", {}) or {}
    return {
        "name": "pi",
        "defaultProvider": settings.get("defaultProvider"),
        "defaultModel": settings.get("defaultModel"),
        "defaultThinkingLevel": settings.get("defaultThinkingLevel"),
        "providers": providers,
    }


def extract_zcode():
    cfg = load_json(TARGETS["zcode_config"])
    providers = cfg.get("provider", {}) or {}
    out = {}
    for key, p in providers.items():
        out[key] = {
            "name": p.get("name"),
            "kind": p.get("kind"),
            "options": copy.deepcopy(p.get("options") or {}),
            "enabled": p.get("enabled"),
            "source": p.get("source"),
            "models": list((p.get("models") or {}).keys()),
        }
    return {"name": "zcode", "providers": out}


def extract_dsh():
    settings = load_yaml(TARGETS["dsh_settings"])
    creds = load_yaml(TARGETS["dsh_credentials"])
    llm_pi = settings.get("llm-pi-ai", {}) or {}
    llm_ds = settings.get("llm-deepseek", {}) or {}
    default = settings.get("agent-default-model", {}) or {}
    return {
        "name": "dsh",
        "defaultProvider": default.get("provider"),
        "defaultModel": default.get("model"),
        "llmPiAiProviders": llm_pi.get("providers", {}) or {},
        "llmDeepseekModels": llm_ds.get("models", []) or [],
        "credentials": (creds or {}).get("refs", {}) or {},
    }


def resolve_deepseek_provider(claude, codex, pi, dsh):
    # Prefer the key used consistently by Claude/Codex/Pi.
    keys = []
    if claude.get("apiKey"):
        keys.append(claude["apiKey"])
    if codex["top"]["providers"].get("deepseek", {}).get("apiKey"):
        keys.append(codex["top"]["providers"]["deepseek"]["apiKey"])
    if pi["providers"].get("deepseek", {}).get("apiKey"):
        keys.append(pi["providers"]["deepseek"]["apiKey"])
    # DSH may carry a separate key; collect it but do not let it win over a
    # three-way consensus.
    dsh_key = dsh["credentials"].get("DEEPSEEK_API_KEY")
    main_key = keys[0] if keys else dsh_key

    pi_ds = pi["providers"].get("deepseek", {})
    return {
        "displayName": "DeepSeek",
        "apiKey": main_key,
        "baseURL": "https://api.deepseek.com",
        "defaultWireApi": "responses",
        "models": {
            "deepseek-v4-flash": {
                "name": "DeepSeek V4 Flash",
                "reasoning": True,
                "contextWindow": 1000000,
                "maxTokens": 8192,
                "input": ["text"],
            },
            "deepseek-v4-pro": {
                "name": "DeepSeek V4 Pro",
                "reasoning": True,
                "contextWindow": 1000000,
                "maxTokens": 8192,
                "input": ["text"],
            },
        },
        "_initHints": {
            "claudeKey": mask(claude.get("apiKey")),
            "codexKey": mask(codex["top"]["providers"].get("deepseek", {}).get("apiKey")),
            "piKey": mask(pi_ds.get("apiKey")),
            "dshKey": mask(dsh_key),
            "consensusCount": len(keys),
        },
    }


def resolve_opencode_provider(zcode, dsh):
    # ZCode has a live opencode-go provider; DSH also declares it.
    z = zcode["providers"].get("opencode-go", {})
    z_opts = z.get("options") or {}
    z_key = z_opts.get("apiKey")
    d_key = dsh["credentials"].get("OPENCODE_GO_API_KEY")
    return {
        "displayName": "OpenCode Go",
        "apiKey": z_key or d_key,
        "baseURL": z_opts.get("baseURL") or "https://opencode.ai/zen/go/v1",
        "api": "openai-completions",
        "_initHints": {
            "zcodeKey": mask(z_key),
            "dshKey": mask(d_key),
        },
    }


def provider_models_from_dsh_variant(name, display, base_url, api, models_rows):
    m = {}
    for row in models_rows or []:
        mid = row.get("id") if isinstance(row, dict) else row
        mname = row.get("name") if isinstance(row, dict) else None
        m[mid] = {"name": mname or mid}
    return {
        "displayName": display,
        "apiKeyRef": "opencode-go" if name != "opencode-go" else None,
        "baseURL": base_url,
        "api": api,
        "models": m,
    }


def build_vendors(force=False):
    if VENDORS_FILE.exists() and not force:
        print(f"[init] {VENDORS_FILE} already exists; use --force to overwrite")
        return False

    claude = extract_claude()
    codex = extract_codex()
    pi = extract_pi()
    zcode = extract_zcode()
    dsh = extract_dsh()

    providers = {}

    # DeepSeek (unified across Claude/Codex/Pi/DSH)
    deepseek = resolve_deepseek_provider(claude, codex, pi, dsh)
    hints = deepseek.pop("_initHints", {})
    providers["deepseek"] = deepseek

    # Codex local GPT proxy
    gpt = codex["top"]["providers"].get("gpt") or {}
    providers["gpt"] = {
        "displayName": "GPT Proxy",
        "apiKey": gpt.get("apiKey"),
        "baseURL": gpt.get("base_url"),
        "wireApi": gpt.get("wire_api") or "responses",
    }

    # DSH llm-pi-ai provider variants
    dsh_pi = dsh["llmPiAiProviders"]
    xiaomi = dsh_pi.get("xiaomi", {}) or {}
    providers["xiaomi"] = {
        "displayName": "MiMo",
        "apiKey": dsh["credentials"].get("XIAOMI_API_KEY"),
        "apiKeyEnv": xiaomi.get("apiKeyEnv") or "XIAOMI_API_KEY",
    }

    opencode_core = resolve_opencode_provider(zcode, dsh)
    hints_oc = opencode_core.pop("_initHints", {})
    providers["opencode-go"] = opencode_core

    for variant, info, api in [
        ("opencode-go-responses", "OpenCode Go (Responses)", "openai-responses"),
        ("opencode-go-anthropic", "OpenCode Go (Anthropic)", "anthropic-messages"),
    ]:
        row = dsh_pi.get(variant, {}) or {}
        providers[variant] = provider_models_from_dsh_variant(
            variant, info, row.get("baseURL") or "https://opencode.ai/zen/go/v1",
            row.get("api") or info, row.get("models") or [],
        )

    # ZCode built-in/custom providers (only custom/visible ones)
    for key, p in zcode["providers"].items():
        if key in providers:
            # opencode-go already merged, keep ZCode's live endpoint if set
            providers[key]["baseURL"] = (p.get("options") or {}).get("baseURL") or providers[key].get("baseURL")
            continue
        opts = p.get("options") or {}
        providers[key] = {
            "displayName": p.get("name") or key,
            "apiKey": opts.get("apiKey"),
            "baseURL": opts.get("baseURL"),
            "kind": p.get("kind"),
            "apiKeyRequired": opts.get("apiKeyRequired"),
            "zcodeSource": p.get("source"),
            "zcodeEnabled": p.get("enabled"),
        }

    # Agent mappings
    agents = {
        "claude": {
            "enabled": True,
            "provider": "deepseek",
            "providers": ["deepseek", "opencode-go-anthropic"],
            "defaultModel": claude["defaultModel"] or "deepseek-v4-pro",
            "flashModel": claude["flashModel"] or "deepseek-v4-flash",
            "maxContextTokens": int(claude["maxContextTokens"]) if str(claude.get("maxContextTokens") or "").isdigit() else 1000000,
            "baseURL": claude["baseURL"],
        },
        "codex": {
            "enabled": True,
            "defaultProvider": codex["top"].get("model_provider") or "gpt",
            "defaultModel": codex["top"].get("model") or "gpt-5.6-sol",
            "defaultModelReasoningEffort": codex["top"].get("model_reasoning_effort"),
            "providers": {
                name: {
                    "provider": name,
                    "baseURL": p.get("base_url"),
                    "apiKey": p.get("apiKey"),
                    "wireApi": p.get("wire_api"),
                }
                for name, p in codex["top"]["providers"].items()
            },
            "deepseekProfile": {
                "provider": "deepseek",
                "model": (codex["deepseek_profile"] or {}).get("model") or "deepseek-v4-pro",
                "modelProvider": (codex["deepseek_profile"] or {}).get("model_provider") or "deepseek",
                "modelReasoningEffort": (codex["deepseek_profile"] or {}).get("model_reasoning_effort") or "high",
                "modelCatalogJson": (codex["deepseek_profile"] or {}).get("model_catalog_json")
                or f"{HOME_POSIX}/.codex/models.deepseek.json",
            },
        },
        "pi": {
            "enabled": True,
            "provider": pi["defaultProvider"] or "deepseek",
            "providers": ["deepseek", "opencode-go", "opencode-go-responses", "opencode-go-anthropic", "xiaomi"],
            "defaultModel": pi["defaultModel"] or "deepseek-v4-pro",
            "defaultThinkingLevel": pi["defaultThinkingLevel"] or "high",
            "baseURL": (pi["providers"].get(pi["defaultProvider"] or "deepseek", {}) or {}).get("baseUrl"),
            "api": (pi["providers"].get(pi["defaultProvider"] or "deepseek", {}) or {}).get("api"),
        },
        "agent": {
            "enabled": True,
            "kind": "pi-wrapper",
            "note": "agent command is a pi-based wrapper sharing ~/.pi/agent configuration with pi",
        },
        "zcode": {
            "enabled": True,
            "defaultProvider": "opencode-go",
            "providers": {
                key: {
                    "provider": key,
                    "name": p.get("name"),
                    "kind": p.get("kind"),
                    "baseURL": (p.get("options") or {}).get("baseURL"),
                    "apiKey": (p.get("options") or {}).get("apiKey"),
                    "apiKeyRequired": (p.get("options") or {}).get("apiKeyRequired"),
                    "enabled": p.get("enabled"),
                }
                for key, p in zcode["providers"].items()
            },
        },
        "dsh": {
            "enabled": True,
            "defaultProvider": dsh["defaultProvider"] or "opencode-go",
            "defaultModel": dsh["defaultModel"] or "deepseek-v4-flash",
            "llmPiAiProviders": list(dsh_pi.keys()),
            "llmDeepseekModels": [
                m.get("id") if isinstance(m, dict) else m for m in dsh["llmDeepseekModels"]
            ],
            "credentials": {
                "DEEPSEEK_API_KEY": "deepseek.apiKey",
                "OPENCODE_GO_API_KEY": "opencode-go.apiKey",
                "XIAOMI_API_KEY": "xiaomi.apiKey",
            },
        },
    }

    # Add DSH provider model lists from settings into provider definitions
    for variant in ("opencode-go", "opencode-go-responses", "opencode-go-anthropic"):
        row = dsh_pi.get(variant, {}) or {}
        row_models = row.get("models") or []
        models = {}
        for m in row_models:
            mid = m.get("id") if isinstance(m, dict) else m
            mname = m.get("name") if isinstance(m, dict) else None
            models[mid] = {"name": mname or mid}
        if variant in providers and models:
            providers[variant]["models"] = models

    vendors = {
        "version": 1,
        "providers": providers,
        "agents": agents,
    }
    save_yaml(VENDORS_FILE, vendors)
    print(f"[init] wrote {VENDORS_FILE}")
    print("[init] deepseek consensus:", hints)
    print("[init] opencode-go key from zcode/dsh:", hints_oc)
    return True


# --------------------------------------------------------------------------
# Sync helpers
# --------------------------------------------------------------------------

def resolve_provider(providers, name):
    """Return (provider dict, resolved api key)."""
    p = providers.get(name) or {}
    key = p.get("apiKey")
    if not key and p.get("apiKeyEnv"):
        key = os.environ.get(p["apiKeyEnv"])
    if not key and p.get("apiKeyRef"):
        ref = p["apiKeyRef"]
        key = (providers.get(ref) or {}).get("apiKey")
        if not key:
            ref_provider = providers.get(ref) or {}
            if ref_provider.get("apiKeyEnv"):
                key = os.environ.get(ref_provider["apiKeyEnv"])
    return p, key


SECRET_RE = re.compile(
    r'(?i)((?:api[_-]?key|token|secret|password|authorization|experimental_bearer_token)\s*["\']?\s*[:=]\s*)(["\']?)([^\s"\',\}=]+)'
)


def mask_line(line: str) -> str:
    def repl(m):
        return f"{m.group(1)}{m.group(2)}<redacted>{m.group(2)}"
    return SECRET_RE.sub(repl, line)


def diff_texts(old: str, new: str) -> list[str]:
    import difflib
    return [mask_line(x) for x in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=1)]


def with_newlines(text: str, sample: str) -> str:
    nl = "\r\n" if "\r\n" in sample else "\n"
    return text.replace("\r\n", "\n").replace("\n", nl)


def write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def update_json(path: Path, mutator, dry_run: bool, name: str, no_backup: bool, changes: list) -> None:
    if not path.exists():
        return
    old = path.read_text(encoding="utf-8")
    data = json.loads(old)
    mutator(data)
    new = with_newlines(json.dumps(data, ensure_ascii=False, indent=2) + "\n", old)
    if new == old:
        return
    changes.append(f"[{name}] {path.name}")
    for line in diff_texts(old, new):
        changes.append(f"    {line}")
    if not dry_run:
        if not no_backup:
            backup(path)
        write_text(path, new)


def update_yaml(path: Path, mutator, dry_run: bool, name: str, no_backup: bool, changes: list) -> None:
    if not path.exists():
        return
    old = path.read_text(encoding="utf-8")
    data = yaml.safe_load(old)
    if not isinstance(data, dict):
        data = {}
    mutator(data)
    new = with_newlines(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False), old)
    if new == old:
        return
    changes.append(f"[{name}] {path.name}")
    for line in diff_texts(old, new):
        changes.append(f"    {line}")
    if not dry_run:
        if not no_backup:
            backup(path)
        write_text(path, new)


def update_toml(path: Path, mutator, dry_run: bool, name: str, no_backup: bool, changes: list) -> None:
    if not path.exists():
        return
    old = path.read_text(encoding="utf-8")
    lines = old.splitlines()
    new_lines, changed = mutator(lines)
    if not changed:
        return
    new = with_newlines("\n".join(new_lines) + "\n", old)
    changes.append(f"[{name}] {path.name}")
    for line in diff_texts(old, new):
        changes.append(f"    {line}")
    if not dry_run:
        if not no_backup:
            backup(path)
        write_text(path, new)


def toml_ensure(line: str) -> str:
    """Normalize simple TOML assignments to double-quoted strings."""
    m = re.match(r'^(\s*)([A-Za-z0-9_-]+)\s*=\s*(.*)$', line)
    if m:
        indent, key, val = m.groups()
        val = val.strip()
        if val and not ((val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'"))):
            # quote bare strings (integers/bools/arrays untouched)
            if val not in ("true", "false") and not re.match(r'^[+-]?\d+$', val) and not val.startswith("["):
                val = f'"{val}"'
        return f"{indent}{key} = {val}"
    return line


def set_toml_values(lines: list[str], updates: dict[str, dict[str, object]]) -> tuple[list[str], bool]:
    """updates maps section->{key: value}; section None means top-level."""
    out = lines[:]
    changed = False
    # track existing sections; first pass locate and replace
    current_section = None
    found = {None: False}
    for key in updates:
        found[key] = False
    for i, line in enumerate(out):
        sm = re.match(r'^\[([^\]]+)\]\s*$', line.strip())
        if sm:
            current_section = sm.group(1)
            continue
        if current_section is None:
            section_key = None
        else:
            # match [model_providers.<name>]
            m = re.match(r'^model_providers\.(.+)$', current_section)
            section_key = m.group(1) if m else current_section
        if section_key in updates:
            km = re.match(r'^(\s*)([A-Za-z0-9_-]+)\s*=\s*(.*)$', line.strip())
            if km:
                key = km.group(2)
                if key in updates[section_key]:
                    new_line = toml_ensure(f"{km.group(1)}{key} = {updates[section_key][key]}")
                    if new_line != line:
                        out[i] = new_line
                        changed = True
                    found[section_key] = True
    # append missing sections/keys
    for section_key, kv in updates.items():
        if found[section_key]:
            continue
        if section_key is None:
            for key, value in kv.items():
                if not any(re.match(rf'^\s*{key}\s*=', l) for l in out):
                    out.append(toml_ensure(f"{key} = {value}"))
                    changed = True
        else:
            # append new section at end
            out.append("")
            out.append(f"[model_providers.{section_key}]")
            for key, value in kv.items():
                out.append(toml_ensure(f"{key} = {value}"))
            changed = True
    return out, changed


def sync_claude(vendors: dict, dry_run: bool, no_backup: bool, changes: list) -> None:
    a = vendors["agents"].get("claude") or {}
    if not a.get("enabled", True):
        return
    providers = vendors["providers"]
    provider = a.get("provider") or "deepseek"
    p, key = resolve_provider(providers, provider)
    if not key:
        print("[sync][claude] no api key for provider", provider)
        return
    api = p.get("api") or p.get("defaultWireApi") or ""
    if provider == "opencode-go-anthropic":
        # Claude Code appends /v1/messages itself; use root, not .../zen/go/v1.
        base = a.get("baseURL") or "https://opencode.ai/zen/go"
    elif provider == "deepseek" or api in ("anthropic-messages", "anthropic"):
        base = a.get("baseURL") or p.get("baseURL") or ""
        if provider == "deepseek" and not base.endswith("/anthropic"):
            base = (base.rstrip("/") + "/anthropic") if base else "https://api.deepseek.com/anthropic"
    else:
        base = a.get("baseURL") or ((p.get("baseURL") or "") + "/anthropic")

    model_ids = list((p.get("models") or {}).keys())
    default = a.get("defaultModel") or (model_ids[0] if model_ids else "deepseek-v4-pro")
    flash = a.get("flashModel") or (model_ids[-1] if len(model_ids) > 1 else (model_ids[0] if model_ids else default))
    use_suffix = provider == "deepseek" and "[1m]" not in str(default)
    max_ctx = int(a.get("maxContextTokens") or 1000000)

    def fmt(model):
        return f"{model}[1m]" if use_suffix else model

    def mut(data):
        env = data.setdefault("env", {})
        if provider == "opencode-go-anthropic":
            env["ANTHROPIC_API_KEY"] = key
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
        else:
            env["ANTHROPIC_AUTH_TOKEN"] = key
            env.pop("ANTHROPIC_API_KEY", None)
        env["ANTHROPIC_BASE_URL"] = base
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = fmt(flash)
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = fmt(default)
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = fmt(default)
        env["ANTHROPIC_MODEL"] = fmt(default)
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(max_ctx)

    update_json(TARGETS["claude_settings"], mut, dry_run, "claude", no_backup, changes)


def sync_codex(vendors: dict, dry_run: bool, no_backup: bool, changes: list) -> None:
    a = vendors["agents"].get("codex") or {}
    if not a.get("enabled", True):
        return
    providers = vendors["providers"]

    # Main config.toml
    def build_updates() -> dict:
        updates = {None: {}}
        if a.get("defaultModel"):
            updates[None]["model"] = a["defaultModel"]
        if a.get("defaultProvider"):
            updates[None]["model_provider"] = a["defaultProvider"]
        if a.get("defaultModelReasoningEffort"):
            updates[None]["model_reasoning_effort"] = a["defaultModelReasoningEffort"]
        if a.get("defaultProvider") == "deepseek":
            catalog = (a.get("deepseekProfile") or {}).get("modelCatalogJson") or f"{HOME_POSIX}/.codex/models.deepseek.json"
            updates[None]["model_catalog_json"] = catalog
        else:
            updates[None]["model_catalog_json"] = f"{HOME_POSIX}/.codex/models.json"
        for pname, entry in (a.get("providers") or {}).items():
            gp = providers.get(pname) or {}
            _, gkey = resolve_provider(providers, pname)
            key = entry.get("apiKey") or gkey
            base = entry.get("baseURL") or gp.get("baseURL")
            wire = entry.get("wireApi") or gp.get("wireApi") or gp.get("defaultWireApi") or "responses"
            if pname not in updates:
                updates[pname] = {}
            if key is not None:
                updates[pname]["experimental_bearer_token"] = key
            if base is not None:
                updates[pname]["base_url"] = base
            if wire is not None:
                updates[pname]["wire_api"] = wire
            if entry.get("name"):
                updates[pname]["name"] = entry["name"]
        return updates

    def mut(lines):
        return set_toml_values(lines, build_updates())

    update_toml(TARGETS["codex_config"], mut, dry_run, "codex", no_backup, changes)

    # deepseek profile
    prof = a.get("deepseekProfile") or {}
    if prof:
        def mut2(lines):
            updates = {None: {}}
            if prof.get("model"):
                updates[None]["model"] = prof["model"]
            if prof.get("modelProvider"):
                updates[None]["model_provider"] = prof["modelProvider"]
            if prof.get("modelReasoningEffort"):
                updates[None]["model_reasoning_effort"] = prof["modelReasoningEffort"]
            if prof.get("modelCatalogJson"):
                updates[None]["model_catalog_json"] = prof["modelCatalogJson"]
            return set_toml_values(lines, updates)
        update_toml(TARGETS["codex_deepseek_config"], mut2, dry_run, "codex deepseek profile", no_backup, changes)


def sync_pi(vendors: dict, dry_run: bool, no_backup: bool, changes: list) -> None:
    a = vendors["agents"].get("pi") or {}
    if not a.get("enabled", True):
        return
    providers = vendors["providers"]
    provider_names = a.get("providers") or [a.get("provider") or "deepseek"]
    provider = a.get("provider") or provider_names[0] or "deepseek"
    default = a.get("defaultModel") or "deepseek-v4-pro"
    overrides = a.get("providerOverrides") or {}

    def pi_info(name):
        p, key = resolve_provider(providers, name)
        if not key:
            print(f"[sync][pi] no api key for provider {name}, skipping")
            return None
        ov = overrides.get(name) or {}
        api = ov.get("api") or p.get("api") or p.get("defaultWireApi") or "openai-completions"
        base = ov.get("baseURL") or p.get("baseURL") or ""
        if name == "deepseek":
            # Match Pi's internal DeepSeek model-store entry.
            base = ov.get("baseURL") or a.get("baseURL") or "https://api.deepseek.com"
            api = ov.get("api") or "openai-completions"
        elif name == "xiaomi":
            base = base or "https://api.xiaomimimo.com/v1"
            api = api or "openai-completions"
        elif name == "opencode-go-anthropic":
            # Pi's anthropic-messages client appends /v1/messages itself,
            # so the base must be the root, not .../zen/go/v1.
            base = ov.get("baseURL") or "https://opencode.ai/zen/go"
            api = ov.get("api") or "anthropic-messages"
        return p, key, base, api

    def mut_settings(data):
        data["defaultProvider"] = provider
        data["defaultModel"] = default
        if a.get("defaultThinkingLevel"):
            data["defaultThinkingLevel"] = a["defaultThinkingLevel"]

    update_json(TARGETS["pi_settings"], mut_settings, dry_run, "pi settings", no_backup, changes)

    def pi_model_entry(mid, m, name, api, base):
        return {
            "id": mid,
            "name": m.get("name") or mid,
            "reasoning": bool(m.get("reasoning", False)),
            "input": m.get("input") or ["text"],
            "cost": m.get("cost") or {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": int(m.get("contextWindow") or 1000000),
            "maxTokens": int(m.get("maxTokens") or 8192),
        }

    def mut_models(data):
        ps = data.setdefault("providers", {})
        for key in list(ps.keys()):
            if key not in provider_names:
                del ps[key]
        for name in provider_names:
            info = pi_info(name)
            if info is None:
                continue
            p, key, base, api = info
            pd = ps.setdefault(name, {})
            if not pd.get("name"):
                pd["name"] = p.get("displayName") or name
            pd["baseUrl"] = base
            pd["apiKey"] = key
            pd["api"] = api
            models = p.get("models") or {}
            if models:
                pd["models"] = [pi_model_entry(mid, m, name, api, base) for mid, m in models.items()]
            elif not pd.get("models"):
                pd["models"] = []

    update_json(TARGETS["pi_models"], mut_models, dry_run, "pi models", no_backup, changes)


def sync_zcode(vendors: dict, dry_run: bool, no_backup: bool, changes: list) -> None:
    a = vendors["agents"].get("zcode") or {}
    if not a.get("enabled", True):
        return
    providers = vendors["providers"]

    def mut(data):
        pmap = data.setdefault("provider", {})
        for key, entry in (a.get("providers") or {}).items():
            gp, gkey = resolve_provider(providers, key)
            existing = pmap.get(key)
            if existing is None:
                existing = {}
                pmap[key] = existing
            # Never overwrite a real key with an empty central value.
            central_key = entry.get("apiKey")
            if central_key is None or central_key == "":
                central_key = gkey
            existing_key = (existing.get("options") or {}).get("apiKey")
            if central_key:
                existing.setdefault("options", {})["apiKey"] = central_key
            elif existing_key:
                # keep existing sensitive credential; central didn't supply one
                pass
            if entry.get("name"):
                existing["name"] = entry["name"]
            if entry.get("kind") or gp.get("kind"):
                existing["kind"] = entry.get("kind") or gp.get("kind")
            opts = existing.setdefault("options", {})
            base = entry.get("baseURL") or gp.get("baseURL")
            if base:
                opts["baseURL"] = base
            req = entry.get("apiKeyRequired")
            if req is not None:
                opts["apiKeyRequired"] = req
            elif gp.get("apiKeyRequired") is not None:
                opts["apiKeyRequired"] = gp["apiKeyRequired"]
            en = entry.get("enabled")
            if en is not None:
                existing["enabled"] = en
            if gp.get("zcodeSource"):
                existing["source"] = gp["zcodeSource"]
            elif existing.get("source"):
                gp["zcodeSource"] = existing["source"]
            # Sync the provider model list to match the central YAML when it
            # declares models for this provider.
            ymodels = gp.get("models")
            if isinstance(ymodels, dict):
                current_models = existing.get("models")
                if not isinstance(current_models, dict):
                    current_models = {}
                new_models = {}
                for mid, m in ymodels.items():
                    old = current_models.get(mid)
                    if isinstance(old, dict):
                        if m.get("name"):
                            old["name"] = m["name"]
                        new_models[mid] = old
                    else:
                        new_models[mid] = {
                            "name": m.get("name") or mid,
                            "zcode": {"modified": False, "priority": 0},
                        }
                existing["models"] = new_models

    update_json(TARGETS["zcode_config"], mut, dry_run, "zcode", no_backup, changes)


def sync_dsh(vendors: dict, dry_run: bool, no_backup: bool, changes: list) -> None:
    a = vendors["agents"].get("dsh") or {}
    if not a.get("enabled", True):
        return
    providers = vendors["providers"]
    pi_names = a.get("llmPiAiProviders") or []
    ds_models = a.get("llmDeepseekModels") or []

    def mut_settings(data):
        data.setdefault("agent-default-model", {})
        data["agent-default-model"]["provider"] = a.get("defaultProvider") or "opencode-go"
        data["agent-default-model"]["model"] = a.get("defaultModel") or "deepseek-v4-flash"
        llm_pi = data.setdefault("llm-pi-ai", {})
        new_providers = {}
        for name in pi_names:
            p, _ = resolve_provider(providers, name)
            if name == "xiaomi":
                xm_models = [{"id": mid, "name": (m.get("name") or mid)} for mid, m in (p.get("models") or {}).items()]
                xm_row = {"apiKeyEnv": p.get("apiKeyEnv") or "XIAOMI_API_KEY"}
                if xm_models:
                    xm_row["models"] = xm_models
                new_providers[name] = xm_row
                continue
            api_env = "OPENCODE_GO_API_KEY" if name.startswith("opencode-go") else p.get("apiKeyEnv") or (name.upper().replace("-", "_") + "_API_KEY")
            models = [{"id": mid, "name": (m.get("name") or mid)} for mid, m in (p.get("models") or {}).items()]
            row = {
                "displayName": p.get("displayName") or name,
                "apiKeyEnv": api_env,
            }
            if p.get("api"):
                row["api"] = p["api"]
            if p.get("baseURL"):
                row["baseURL"] = p["baseURL"]
            if models:
                row["models"] = models
            new_providers[name] = row
        llm_pi["providers"] = new_providers

        deep_mods = []
        ds_p, _ = resolve_provider(providers, "deepseek")
        for mid in ds_models:
            m = (ds_p.get("models") or {}).get(mid) or {}
            deep_mods.append({"id": mid, "name": m.get("name") or mid})
        data.setdefault("llm-deepseek", {})["models"] = deep_mods

    update_yaml(TARGETS["dsh_settings"], mut_settings, dry_run, "dsh settings", no_backup, changes)

    def mut_creds(data):
        refs = data.setdefault("refs", {})
        mapping = a.get("credentials") or {}
        for env_name, ref_path in mapping.items():
            # ref_path like "deepseek.apiKey" / "opencode-go.apiKey"
            parts = ref_path.split(".")
            if len(parts) == 2 and parts[1] == "apiKey":
                p, key = resolve_provider(providers, parts[0])
                if key is not None:
                    refs[env_name] = key

    update_yaml(TARGETS["dsh_credentials"], mut_creds, dry_run, "dsh credentials", no_backup, changes)


def cmd_init(args):
    build_vendors(force=args.force)


def cmd_sync(args):
    if not VENDORS_FILE.exists():
        print(f"[sync] missing {VENDORS_FILE}; run init first")
        return
    vendors = load_yaml(VENDORS_FILE)
    changes: list[str] = []
    sync_claude(vendors, args.dry_run, args.no_backup, changes)
    sync_codex(vendors, args.dry_run, args.no_backup, changes)
    sync_pi(vendors, args.dry_run, args.no_backup, changes)
    sync_zcode(vendors, args.dry_run, args.no_backup, changes)
    sync_dsh(vendors, args.dry_run, args.no_backup, changes)

    if not changes:
        print("[sync] no changes")
        return
    if args.dry_run:
        print("[sync] DRY-RUN - would change:")
    else:
        print("[sync] applied:")
    for line in changes:
        print(line)


def main():
    parser = argparse.ArgumentParser(description="Agent vendor config centralization")
    sub = parser.add_subparsers(dest="command", required=True)
    init_p = sub.add_parser("init", help="build agent-vendors.yaml from existing configs")
    init_p.add_argument("--force", action="store_true", help="overwrite existing agent-vendors.yaml")
    sync_p = sub.add_parser("sync", help="sync agent configs from agent-vendors.yaml")
    sync_p.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    sync_p.add_argument("--no-backup", action="store_true", help="do not create backups")
    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    else:
        cmd_sync(args)


if __name__ == "__main__":
    main()
