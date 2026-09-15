#!/usr/bin/env python3
"""agent-bootstrap: give a new PC your agents config in one command.

Old PC:  py bootstrap.py export     -> writes vendors.yaml (keys + urls + models)
New PC:  copy this folder over, then:  py bootstrap.py
         (add --dry-run to preview, --only claude,codex to limit scope)

Requires the pyyaml package for reading vendors.yaml and syncing YAML-based agents.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import urllib.request
from pathlib import Path

# Keep provider replies with emoji or other non-console characters from
# crashing verification on Windows' legacy console encodings.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("AGENT_HOME") or Path.home())
CONFIG_DEFAULT = HERE / "vendors.yaml"

try:
    import yaml
except ImportError:
    yaml = None


class ConfigError(ValueError):
    """A user-facing vendors.yaml error."""

DEFAULT_MODEL = "qwen3.8-flash"
DEFAULT_CODEX_REASONING = "xhigh"

REQUIRED = ("BAI_API_KEY",)
DISPLAY = [("BAI_API_KEY", True), ("BAI_BASE_URL", False),
           ("CODEX_PROVIDER", False), ("CODEX_MODEL", False), ("CODEX_REASONING", False),
           ("CLAUDE_MODEL", False), ("CLAUDE_SONNET", False), ("CLAUDE_OPUS", False),
           ("PI_PROVIDER", False), ("PI_MODEL", False),
           ("DSH_PROVIDER", False), ("DSH_MODEL", False)]

AGENTS = ("claude", "codex", "pi", "zcode", "dsh")

# Known OpenCode model specs. Without these, pi falls back to a 128k context
# window and 16k max output, because a bare models.json entry replaces the
# remote pi.dev catalog metadata. Values mirror the remote catalog.
OPENCODE_MODEL_SPECS = {
    "kimi-k3": (1048576, 131072, True, ["text", "image"]),
    "kimi-k2.7-code": (262144, 262144, True, ["text", "image"]),
    "kimi-k2.6": (262144, 65536, True, ["text", "image"]),
    "glm-5.3": (1000000, 131072, True, ["text"]),
    "glm-5.2": (1000000, 131072, True, ["text"]),
    "glm-5.1": (202752, 32768, True, ["text"]),
    "mimo-v2.5-pro": (1048576, 128000, True, ["text"]),
    "mimo-v2.5": (1000000, 128000, True, ["text", "image"]),
    "hy3": (256000, 128000, True, ["text"]),
    "deepseek-v4-pro": (1000000, 384000, True, ["text"]),
    "deepseek-v4-flash": (1000000, 384000, True, ["text"]),
    "deepseek-v4.1-flash": (1000000, 384000, True, ["text"]),
    "deepseek-flash": (1000000, 384000, True, ["text"]),
    "deepseek-v4-flash-vision-exp": (1000000, 384000, True, ["text", "image"]),
    "glm-5.3-flash": (1000000, 131072, True, ["text", "image"]),
    "grok-4.6": (500000, 500000, True, ["text", "image"]),
    "hy4-preview": (1024000, 64000, True, ["text"]),
    "longcat-2.0": (1000000, 131072, True, ["text"]),
    "qwen3.6-plus": (1000000, 65536, True, ["text", "image"]),
    "qwen3.7-max": (1000000, 65536, True, ["text"]),
    "qwen3.7-plus": (1000000, 65536, True, ["text", "image"]),
    "qwen3.8-max": (1000000, 131072, True, ["text", "image"]),
    "muse-spark-1.2-contributor": (1048576, 131072, True, ["text", "image"]),
    "muse-spark-1.3-contributor": (1048576, 131072, True, ["text", "image"]),
    "omen-alpha": (500000, 128000, True, ["text", "image"]),
    "qwen3.8-flash": (1000000, 131072, True, ["text", "image"]),
    "gpt-5.6-luna": (1050000, 128000, True, ["text", "image"]),
    "minimax-m3": (1000000, 131072, True, ["text", "image"]),
    "minimax-m2.7": (204800, 131072, True, ["text"]),
}


def mask(s):
    s = str(s or "")
    if not s:
        return "<empty>"
    # anything this short is a provider/model name, not a credential
    return f"{s[:3]}...{s[-3:]}" if len(s) > 10 else s


def need_yaml():
    if yaml is None:
        print("[bootstrap] need pyyaml: py -m pip install pyyaml")
        sys.exit(2)


def load_vendors(path):
    """Central vendors.yaml -> flat internal dict. The ONLY source of truth."""
    need_yaml()
    p = Path(path)
    if not p.exists():
        v = {}
    else:
        try:
            v = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"cannot read {p}: {exc}") from exc
    v = v or {}
    if not isinstance(v, dict):
        raise ConfigError(f"{p} must contain a YAML mapping at the top level")

    def section(name):
        value = v.get(name)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ConfigError(f"{p}: section '{name}' must be a YAML mapping")
        return value

    def text(section_data, name, default=""):
        value = section_data.get(name, default)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ConfigError(f"{p}: '{name}' must be a string")
        return value

    b = section("bai")
    ax = section("aizex")
    cl, co = section("claude"), section("codex")
    pi, dh = section("pi"), section("dsh")
    bai_key_env = text(b, "api_key_env")
    bai_key = text(b, "api_key") or (os.environ.get(bai_key_env, "") if bai_key_env else "")
    bai_url = (text(b, "base_url") or "https://api.b.ai/v1").rstrip("/")
    ax_key_env = text(ax, "api_key_env")
    ax_key = text(ax, "api_key") or (os.environ.get(ax_key_env, "") if ax_key_env else "")
    ax_url = (text(ax, "base_url") or "https://ca.memofun.net/v1").rstrip("/")
    return {
        "BAI_API_KEY": bai_key,
        "BAI_API_KEY_REF": f"${bai_key_env}" if bai_key_env else bai_key,
        "BAI_BASE_URL": bai_url,
        "CODEX_PROVIDER": text(co, "provider") or "bai",
        "CODEX_MODEL": text(co, "model") or DEFAULT_MODEL,
        "CODEX_REASONING": text(co, "reasoning_effort") or DEFAULT_CODEX_REASONING,
        "CLAUDE_MODEL": text(cl, "model") or DEFAULT_MODEL,
        "CLAUDE_SONNET": text(cl, "sonnet") or text(cl, "model") or DEFAULT_MODEL,
        "CLAUDE_OPUS": text(cl, "opus") or text(cl, "model") or DEFAULT_MODEL,
        "PI_PROVIDER": text(pi, "provider") or "bai",
        "PI_MODEL": text(pi, "model") or DEFAULT_MODEL,
        "PI_HTTP_PROXY": text(pi, "http_proxy"),
        "DSH_PROVIDER": text(dh, "provider") or "bai",
        "DSH_MODEL": text(dh, "model") or DEFAULT_MODEL,
        "AIZEX_BASE_URL": ax_url,
        "AIZEX_API_KEY": ax_key,
        "AIZEX_API_KEY_REF": f"${ax_key_env}" if ax_key_env else text(ax, "api_key"),
        # provider name -> key / url, so codex can be pointed at either upstream
        "PROVIDER_KEYS": {"bai": bai_key, "aizex": ax_key},
        "PROVIDER_URLS": {"bai": bai_url, "aizex": ax_url},
    }


def check_env(env, quiet=False):
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing and not quiet:
        print("[bootstrap] missing required fields:", ", ".join(missing))
    return missing


UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_models(base_url, api_key, timeout=10):
    """GET <base>/models (tries with/without /v1). Returns [ids] or []."""
    base = (base_url or "").rstrip("/")
    candidates = [base + "/models"] if base.endswith("/v1") else [base + "/v1/models", base + "/models"]
    for url in candidates:
        try:
            heads = dict(UA)
            heads["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(url, headers=heads)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            items = data.get("data") if isinstance(data, dict) else data
            ids = [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]
            if ids:
                return ids
        except Exception:
            continue
    return []


RETIRED_PROVIDERS = ("gpt", "opencode-go", "opencode-go-responses", "opencode-go-anthropic", "deepseek")


def prune_providers(mapping, names=RETIRED_PROVIDERS):
    """Drop provider entries whose upstream is gone (opencode / gpt proxy / deepseek)."""
    gone = [k for k in list(mapping) if k in names]
    for k in gone:
        del mapping[k]
    return gone


def _lock_down(path):
    """New files holding secrets: user-only on posix."""
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if path.exists():
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
    tmp.replace(path)
    if new_file:
        _lock_down(path)


def patch_json(path, mut):
    old = path.read_text(encoding="utf-8") if path.exists() else "{}"
    data = json.loads(old) if old.strip() else {}
    mut(data)
    new = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    changed = new != (old if old.endswith("\n") or not old.strip() else old + "\n")
    return changed, new


def toml_str(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_str(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def patch_toml(path, updates, nested_prefix="model_providers."):
    """updates: {section|None: {key: value}}. Preserves all other content."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    found = {s: set() for s in updates}
    cur = None
    for i, line in enumerate(lines):
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            cur = m.group(1)
            continue
        sec = None if cur is None else re.sub(r"^" + re.escape(nested_prefix), "", cur)
        km = re.match(r"^(\s*)([A-Za-z0-9_-]+)(\s*=.*)$", line)
        if km and sec in updates and km.group(2) in updates[sec]:
            new_line = f"{km.group(1)}{km.group(2)} = {toml_str(updates[sec][km.group(2)])}"
            if new_line != line:
                lines[i] = new_line
            found[sec].add(km.group(2))
    # locate section end offsets
    bounds, cur, first = {}, None, len(lines)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            if cur is None:
                first = min(first, i)
            bounds[cur] = i
            raw = m.group(1)
            cur = re.sub(r"^model_providers\.", "", raw)
            bounds.setdefault(cur, len(lines))
    bounds[cur] = len(lines)
    insert_at = {}
    new_sections = []
    for sec, kv in updates.items():
        missing = [(k, v) for k, v in kv.items() if k not in found[sec]]
        if not missing:
            continue
        if sec is None:
            insert_at.setdefault(first if first < len(lines) else len(lines), []).extend(
                f"{k} = {toml_str(v)}" for k, v in missing)
        elif sec in bounds:
            insert_at.setdefault(bounds[sec], []).extend(f"{k} = {toml_str(v)}" for k, v in missing)
        else:
            new_sections.append(f"[{nested_prefix}{sec}]")
            new_sections.extend(f"{k} = {toml_str(v)}" for k, v in missing)
    for idx in sorted(insert_at, reverse=True):
        lines[idx:idx] = insert_at[idx]
    if new_sections:
        lines.append("")
        lines.extend(new_sections)
    return True, "\n".join(lines) + "\n" if lines else ""


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
    tmp.replace(path)
    if new_file:
        _lock_down(path)


# ---------------------------------------------------------------- sync pieces

def setup_claude(env, dry_run, out):
    p = HOME / ".claude" / "settings.json"
    if not p.exists():
        out.append(("claude", str(p), "skip (not installed)"))
        return
    # b.ai serves the Anthropic protocol at <root>/v1/messages; clients append the path.
    root = re.sub(r"/v1$", "", env["BAI_BASE_URL"].rstrip("/"))
    cm, son, opu = env["CLAUDE_MODEL"], env["CLAUDE_SONNET"], env["CLAUDE_OPUS"]

    def mut(d):
        e = d.setdefault("env", {})
        # gateway only accepts x-api-key; ANTHROPIC_API_KEY is sent as x-api-key,
        # while ANTHROPIC_AUTH_TOKEN would go out as Bearer and 401.
        e["ANTHROPIC_API_KEY"] = env["BAI_API_KEY"]
        e.pop("ANTHROPIC_AUTH_TOKEN", None)
        e["ANTHROPIC_BASE_URL"] = root
        e["ANTHROPIC_MODEL"] = cm
        e["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = cm
        e["ANTHROPIC_DEFAULT_SONNET_MODEL"] = son
        e["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opu
        e["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = "1000000"
        # third-party model ids fail client-side session-title validation
        # (cosmetic [claude-code:unrecognized_model]); silence it at the source.
        e["CLAUDE_CODE_DISABLE_TERMINAL_TITLE"] = "1"
        d["model"] = cm

    changed, new = patch_json(p, mut)
    out.append(("claude", str(p), changed))
    if changed and not dry_run:
        save_json(p, json.loads(new))


def _codex_catalog_path(p):
    """Path of codex's local model catalog (model_catalog_json), default under .codex."""
    try:
        tx = p.read_text(encoding="utf-8") if p.exists() else ""
    except OSError:
        tx = ""
    m = re.search(r'model_catalog_json\s*=\s*"([^"]+)"', tx)
    return Path(m.group(1)) if m else HOME / ".codex" / "models.json"


def ensure_codex_catalog(path, model):
    """Make sure `model` has a metadata entry in codex's local catalog.

    Clones the same-family entry (e.g. gpt-5.6-sol for gpt-5.6-luna) so metadata
    stays accurate; returns (changed, new_data). Models without a same-family
    template are left alone — codex's fallback metadata still works.
    """
    if not path.exists():
        return False, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    ms = data.get("models")
    if not isinstance(ms, list):
        return False, None
    if any(isinstance(m, dict) and m.get("slug") == model for m in ms):
        return False, None

    def family(s):
        return s.rsplit(".", 1)[0] if "." in str(s) else str(s)

    tmpl = None
    for m in ms:
        if isinstance(m, dict) and isinstance(m.get("slug"), str) and family(m["slug"]) == family(model):
            tmpl = m
            break
    if tmpl is None:
        return False, None
    import copy
    entry = copy.deepcopy(tmpl)
    entry["slug"] = model
    entry["display_name"] = model
    entry["description"] = model
    spec = OPENCODE_MODEL_SPECS.get(model)
    if spec:
        entry["context_window"] = spec[0]
        entry["max_context_window"] = spec[0]
    ms.append(entry)
    return True, data


def codex_auth_command(key):
    """How codex gets its provider key: it runs this command and reads stdout.

    Written into `[model_providers.<provider>.auth]`, because codex has no other
    way of picking up a third-party key and `experimental_bearer_token` puts the
    key in plain sight next to the base URL.
    """
    if os.name == "nt":
        return {"command": "cmd", "args": ["/c", "echo", key]}
    return {"command": "echo", "args": [key]}


def setup_codex(env, dry_run, out):
    p = HOME / ".codex" / "config.toml"
    if not p.exists():
        out.append(("codex", str(p), "skip (not installed)"))
        return
    provider = env["CODEX_PROVIDER"]
    updates = {None: {"model": env["CODEX_MODEL"], "model_reasoning_effort": env["CODEX_REASONING"],
                      "model_provider": provider, "approval_policy": "on-request"},
               provider: {"base_url": env["PROVIDER_URLS"].get(provider) or env["AIZEX_BASE_URL"],
                          "wire_api": "responses",
                          "requires_openai_auth": False, "supports_websockets": True}}
    key = env["PROVIDER_KEYS"].get(provider, "")
    if key:
        updates[provider + ".auth"] = codex_auth_command(key)
    changed, new = patch_toml(p, updates)
    if changed and not dry_run:
        write_text(p, new)
    out.append(("codex", str(p), changed))


def bai_models_payload(env, discovered_bai):
    mp = HOME / ".pi" / "agent" / "models.json"
    keep = {}
    if mp.exists():
        try:
            keep = json.loads(mp.read_text(encoding="utf-8")).get("providers", {})
        except Exception:
            keep = {}
    old = (keep.get("bai") or {}).get("models") or []
    ids = discovered_bai or [m.get("id") for m in old if isinstance(m, dict) and m.get("id")]
    if env["PI_MODEL"] not in ids:
        ids = [env["PI_MODEL"]] + ids

    models = []
    for m in ids:
        e = {"id": m, "name": m}
        spec = OPENCODE_MODEL_SPECS.get(m)
        if spec:
            e["contextWindow"], e["maxTokens"], e["reasoning"], e["input"] = spec
        if m.startswith("qwen"):
            e["compat"] = {
                "maxTokensField": "max_tokens",
                "supportsStore": False,
                "supportsDeveloperRole": False,
                "supportsReasoningEffort": False,
                "thinkingFormat": "qwen",
            }
        models.append(e)
    return {"bai": {"name": (keep.get("bai") or {}).get("name") or "bai",
                    "baseUrl": env["BAI_BASE_URL"], "apiKey": env["BAI_API_KEY_REF"],
                    "api": "openai-completions", "models": models}}


def setup_pi(env, dry_run, out, discovered_bai):
    sp = HOME / ".pi" / "agent" / "settings.json"
    if not sp.exists():
        out.append(("pi", str(sp), "skip (not installed)"))
        return

    def mut(d):
        d["defaultProvider"] = env["PI_PROVIDER"]
        d["defaultModel"] = env["PI_MODEL"]
        if env.get("PI_HTTP_PROXY"):
            d["httpProxy"] = env["PI_HTTP_PROXY"]

    changed, new = patch_json(sp, mut)
    out.append(("pi settings", str(sp), changed))
    if changed and not dry_run:
        save_json(sp, json.loads(new))
    mp = HOME / ".pi" / "agent" / "models.json"
    payload = bai_models_payload(env, discovered_bai)

    def mut2(d):
        ps = d.setdefault("providers", {})
        ps.update(payload)
        prune_providers(ps)

    changed2, new2 = patch_json(mp, mut2)
    out.append(("pi models", str(mp), changed2))
    if changed2 and not dry_run:
        save_json(mp, json.loads(new2))
    # pi caches one catalog block per provider; stale keys keep dead models selectable
    st = HOME / ".pi" / "agent" / "models-store.json"
    if st.exists():
        def mut3(d):
            prune_providers(d)

        changed3, new3 = patch_json(st, mut3)
        out.append(("pi models store", str(st), changed3))
        if changed3 and not dry_run:
            save_json(st, json.loads(new3))


def setup_zcode(env, dry_run, out):
    p = HOME / ".zcode" / "v2" / "config.json"
    if not p.exists():
        out.append(("zcode", str(p), "skip (not installed)"))
        return

    def mut(d):
        pm = d.setdefault("provider", {})
        e = pm.setdefault("bai", {})
        e["name"] = e.get("name") or "B.AI"
        e["kind"] = e.get("kind") or "openai-compatible"
        if e.get("enabled") is None:
            e["enabled"] = True
        o = e.setdefault("options", {})
        o["baseURL"] = env["BAI_BASE_URL"].rstrip("/")
        o["apiKey"] = env["BAI_API_KEY"]
        prune_providers(pm)

    changed, new = patch_json(p, mut)
    out.append(("zcode", str(p), changed))
    if changed and not dry_run:
        save_json(p, json.loads(new))


def setup_dsh(env, dry_run, out, discovered_bai):
    try:
        import yaml
    except ImportError:
        out.append(("dsh", "~/.dsh", "skip (pip install pyyaml to enable)"))
        return
    sp = HOME / ".dsh" / "settings.yaml"
    cp = HOME / ".dsh" / ".credentials.yaml"
    if not sp.exists():
        out.append(("dsh", str(sp), "skip (not installed)"))
        return
    data = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}

    def rows(models):
        return [{"id": m, "name": m} for m in models]

    # 无探测结果时沿用文件里已有的清单，绝不写成单个模型
    keep = ((data.get("llm-pi-ai") or {}).get("providers") or {})
    old_ids = [m.get("id") for m in ((keep.get("bai") or {}).get("models") or []) if isinstance(m, dict)]
    bai_ids = discovered_bai or old_ids or [env["DSH_MODEL"]]
    if env["DSH_MODEL"] not in bai_ids:
        bai_ids = [env["DSH_MODEL"]] + bai_ids
    data.setdefault("agent-default-model", {}).update({"provider": env["DSH_PROVIDER"], "model": env["DSH_MODEL"]})
    llm = data.setdefault("llm-pi-ai", {}).setdefault("providers", {})
    llm["bai"] = {"displayName": "B.AI", "apiKeyEnv": "BAI_API_KEY", "api": "openai-completions",
                  "baseURL": env["BAI_BASE_URL"], "models": rows(bai_ids)}
    prune_providers(llm)
    old = sp.read_text(encoding="utf-8")
    new = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    out.append(("dsh settings", str(sp), new != old))
    if new != old and not dry_run:
        write_text(sp, new)
    creds = yaml.safe_load(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    refs = (creds or {}).setdefault("refs", {})
    refs["BAI_API_KEY"] = env["BAI_API_KEY"]
    for stale in ("GPT_API_KEY", "OPENCODE_GO_API_KEY", "DEEPSEEK_API_KEY"):
        refs.pop(stale, None)
    new_c = yaml.safe_dump(creds, allow_unicode=True, sort_keys=False)
    old_c = cp.read_text(encoding="utf-8") if cp.exists() else ""
    out.append(("dsh credentials", str(cp), new_c != old_c))
    if new_c != old_c and not dry_run:
        write_text(cp, new_c)


# ---------------------------------------------------------------- export

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def codex_provider_setting(tx, provider, field):
    """Read one string key out of codex's `[model_providers.<provider>]` block."""
    sec = re.search(r"\[model_providers\." + re.escape(provider) + r"\](.*?)(?=\n\[|\Z)", tx, re.S)
    if not sec:
        return ""
    m = re.search(r"^" + re.escape(field) + r"\s*=\s*\"([^\"]*)\"", sec.group(1), re.M)
    return m.group(1) if m else ""


def codex_auth_key(tx, provider):
    """Read a provider's api key back out of its codex `[...auth]` command block."""
    sec = re.search(r"\[model_providers\." + re.escape(provider) + r"\.auth\](.*?)(?=\n\[|\Z)", tx, re.S)
    if not sec:
        return ""
    args = re.search(r"^args\s*=\s*\[(.*?)\]", sec.group(1), re.M | re.S)
    if not args:
        return ""
    try:
        values = json.loads("[" + args.group(1) + "]")
    except Exception:
        return ""
    last = values[-1] if values else ""
    return last if isinstance(last, str) and len(last) > 8 else ""


def cmd_export(args):
    need_yaml()
    env = {}
    cl = read_json(HOME / ".claude" / "settings.json").get("env", {})
    env["CLAUDE_MODEL"] = cl.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    env["CLAUDE_SONNET"] = cl.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or env["CLAUDE_MODEL"]
    env["CLAUDE_OPUS"] = cl.get("ANTHROPIC_DEFAULT_OPUS_MODEL") or env["CLAUDE_MODEL"]
    tx = (HOME / ".codex" / "config.toml").read_text(encoding="utf-8") if (HOME / ".codex" / "config.toml").exists() else ""
    m = re.search(r"^model\s*=\s*\"([^\"]+)\"", tx, re.M)
    env["CODEX_MODEL"] = m.group(1) if m else DEFAULT_MODEL
    mp = re.search(r"^model_provider\s*=\s*\"([^\"]+)\"", tx, re.M)
    env["CODEX_PROVIDER"] = mp.group(1) if mp else "bai"
    mr = re.search(r"^model_reasoning_effort\s*=\s*\"([^\"]*)\"", tx, re.M)
    env["CODEX_REASONING"] = mr.group(1) if mr else DEFAULT_CODEX_REASONING
    prov = env["CODEX_PROVIDER"]
    env["CODEX_PROVIDER_KEY"] = codex_auth_key(tx, prov)
    env["CODEX_PROVIDER_BASE_URL"] = codex_provider_setting(tx, prov, "base_url")
    pi_s = read_json(HOME / ".pi" / "agent" / "settings.json")
    env["PI_PROVIDER"] = pi_s.get("defaultProvider") or "bai"
    env["PI_MODEL"] = pi_s.get("defaultModel") or DEFAULT_MODEL
    env["PI_HTTP_PROXY"] = pi_s.get("httpProxy") or ""
    pi_m = read_json(HOME / ".pi" / "agent" / "models.json").get("providers", {})
    bai = pi_m.get("bai") or {}
    env["BAI_BASE_URL"] = (bai.get("baseUrl") or "https://api.b.ai/v1").rstrip("/")
    bai_key = bai.get("apiKey") or ""
    env["BAI_API_KEY"] = os.environ.get(bai_key[1:], "") if isinstance(bai_key, str) and bai_key.startswith("$") else bai_key
    env["BAI_API_KEY_REF"] = bai_key if isinstance(bai_key, str) and bai_key.startswith("$") else ""
    if not env["BAI_API_KEY"] and not env["BAI_API_KEY_REF"]:
        env["BAI_API_KEY"] = cl.get("ANTHROPIC_API_KEY") or ""
    try:
        dh = (yaml.safe_load((HOME / ".dsh" / "settings.yaml").read_text(encoding="utf-8")) or {})
        dh = dh.get("agent-default-model", {}) or {}
    except Exception:
        dh = {}
    env["DSH_PROVIDER"] = dh.get("provider") or "bai"
    env["DSH_MODEL"] = dh.get("model") or DEFAULT_MODEL
    dest = Path(args.config)
    if dest.exists() and not args.force:
        print(f"[export] {dest} exists; use --force to overwrite")
        return 2
    bai_sec = {"base_url": env["BAI_BASE_URL"]}
    if env["BAI_API_KEY_REF"]:
        bai_sec["api_key_env"] = env["BAI_API_KEY_REF"][1:]
    elif env["BAI_API_KEY"]:
        bai_sec["api_key"] = env["BAI_API_KEY"]
    data = {
        "bai": bai_sec,
        "codex": {"provider": env["CODEX_PROVIDER"], "model": env["CODEX_MODEL"],
                  "reasoning_effort": env["CODEX_REASONING"]},
        "claude": {"model": env["CLAUDE_MODEL"], "sonnet": env["CLAUDE_SONNET"], "opus": env["CLAUDE_OPUS"]},
        "pi": {"provider": env["PI_PROVIDER"], "model": env["PI_MODEL"],
               **({"http_proxy": env["PI_HTTP_PROXY"]} if env["PI_HTTP_PROXY"] else {})},
        "dsh": {"provider": env["DSH_PROVIDER"], "model": env["DSH_MODEL"]},
    }
    # codex keeps its key in an auth command, not in an env var: record both the
    # key and the base url in the provider section so a new PC can reproduce them.
    if prov and prov not in data:
        sec = {}
        if env["CODEX_PROVIDER_BASE_URL"]:
            sec["base_url"] = env["CODEX_PROVIDER_BASE_URL"]
        if env["CODEX_PROVIDER_KEY"]:
            sec["api_key"] = env["CODEX_PROVIDER_KEY"]
        if sec:
            items = list(data.items())
            data = dict(items[:1] + [(prov, sec)] + items[1:])
    elif env["CODEX_PROVIDER_KEY"] and not data[prov].get("api_key") \
            and not data[prov].get("api_key_env"):
        data[prov]["api_key"] = env["CODEX_PROVIDER_KEY"]
    write_text(dest, "# agent-bootstrap: single source of truth. Edit here, run: py bootstrap.py\n"
               + yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    print(f"[export] wrote {dest}")
    for k, _ in DISPLAY:
        print(f"  {k}={mask(env.get(k))}")
    return 0


def cmd_setup(args):
    env = load_vendors(args.config)
    if check_env(env):
        return 2
    only = set(args.only) if args.only else set(AGENTS)
    print(f"[bootstrap] config={args.config} bai={mask(env['BAI_API_KEY'])}@{env['BAI_BASE_URL']} "
          f"models={env['CODEX_MODEL']}/{env['CLAUDE_MODEL']}/{env['PI_MODEL']}")
    dbai = []
    if not args.no_probe:
        dbai = fetch_models(env["BAI_BASE_URL"], env["BAI_API_KEY"])
        print(f"[bootstrap] probe: bai {len(dbai)} models" +
              (" (offline? keeping existing lists)" if not dbai else ""))
    out = []
    if "claude" in only:
        setup_claude(env, args.dry_run, out)
    if "codex" in only:
        setup_codex(env, args.dry_run, out)
    if "pi" in only:
        setup_pi(env, args.dry_run, out, dbai)
    if "zcode" in only:
        setup_zcode(env, args.dry_run, out)
    if "dsh" in only:
        setup_dsh(env, args.dry_run, out, dbai)
    print("[bootstrap] DRY-RUN -- nothing written" if args.dry_run else "[bootstrap] done:")
    for name, path, changed in out:
        flag = "~" if str(changed).startswith("skip") else ("*" if changed else "=")
        print(f"  {flag} {name}: {path}")
    return 0


def post_json(url, headers, payload, timeout=30):
    data = json.dumps(payload).encode()
    heads = {"Content-Type": "application/json"}
    heads.update(UA)
    heads.update(headers)
    try:
        req = urllib.request.Request(url, data=data, headers=heads)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, str(e)[:200]


def snippet(res):
    try:
        ch = res.get("choices", [{}])[0]
        msg = ch.get("message", {}).get("content")
        if msg:
            return str(msg).strip().replace("\n", " ")[:80]
        txt = res.get("content", [{}])[0].get("text", "")
        return str(txt).strip().replace("\n", " ")[:80]
    except Exception:
        return ""


def cmd_verify(args):
    env = load_vendors(args.config)
    if check_env(env):
        return
    print("[verify] live tests (max_tokens=5 each):")
    bai_root = re.sub(r"/v1$", "", env["BAI_BASE_URL"].rstrip("/"))
    tests = [
        ("bai openai (pi/dsh/zcode path)", env["BAI_BASE_URL"] + "/chat/completions",
         {"Authorization": f"Bearer {env['BAI_API_KEY']}"},
         {"model": env["PI_MODEL"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}),
        ("bai anthropic (claude path)", bai_root + "/v1/messages",
         {"x-api-key": env["BAI_API_KEY"], "anthropic-version": "2023-06-01"},
         {"model": env["CLAUDE_MODEL"], "max_tokens": 5,
          "messages": [{"role": "user", "content": "ping"}]}),
    ]
    allok = True
    for label, url, heads, payload in tests:
        ok, res = post_json(url, heads, payload)
        allok = allok and ok
        print(f"  {'OK ' if ok else 'FAIL'} {label}" + (f" -> {snippet(res)}" if ok else f": {res}"))
    print("[verify] defaults in live catalog:")
    ids = fetch_models(env["BAI_BASE_URL"], env["BAI_API_KEY"])
    for label, model in (("codex", env["CODEX_MODEL"]), ("claude", env["CLAUDE_MODEL"]),
                         ("pi", env["PI_MODEL"]), ("dsh", env["DSH_MODEL"])):
        if not ids:
            print(f"  SKIP {label}: bai catalog unreachable")
            allok = False
            continue
        okm = model in ids
        allok = allok and okm
        print(f"  {'OK ' if okm else 'WARN'} {label} default {model}" +
              (" in catalog" if okm else " NOT in catalog -- agent may fall back, run sync with probe"))
    print("[verify] agent files:")
    checks = [
        ("claude", HOME / ".claude" / "settings.json"),
        ("codex", HOME / ".codex" / "config.toml"),
        ("pi", HOME / ".pi" / "agent" / "settings.json"),
        ("zcode", HOME / ".zcode" / "v2" / "config.json"),
        ("dsh", HOME / ".dsh" / "settings.yaml"),
    ]
    for name, path in checks:
        print(f"  {'found' if path.exists() else 'not installed':<14} {name}: {path}")
    print("[verify] ALL OK" if allok else "[verify] SOME FAILED -- fix vendors.yaml / network, rerun")
    return 0 if allok else 1


def cmd_check(args):
    env = load_vendors(args.config)
    print(f"[check] {args.config} ({'found' if Path(args.config).exists() else 'NOT FOUND'})")
    for k, req in DISPLAY:
        print(f"  {k}={mask(env.get(k))}{'' if req else ' (optional)'}")
    if check_env(env, quiet=True):
        print("[check] MISSING required fields -- setup would refuse to run")
        return 2
    failed = False
    if not args.no_probe:
        for label, base, key in (("bai", env["BAI_BASE_URL"], env["BAI_API_KEY"]),):
            if not key:
                continue
            ids = fetch_models(base, key)
            if not ids:
                failed = True
            print(f"  probe {label}: {'OK ' + str(len(ids)) + ' models' if ids else 'FAILED (url/key?)'}")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="agent-bootstrap: one-command agent setup for a new PC")
    ap.add_argument("--config", default=str(CONFIG_DEFAULT), help="vendors.yaml path (default: next to script)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", choices=list(AGENTS), default=None)
    ap.add_argument("--no-probe", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("setup", help="write agent configs (default)")
    s.add_argument("--config", default=argparse.SUPPRESS, help="vendors.yaml path")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--only", nargs="*", choices=list(AGENTS), default=None)
    s.add_argument("--no-probe", action="store_true")
    e = sub.add_parser("export", help="generate vendors.yaml from this PC")
    e.add_argument("--config", default=argparse.SUPPRESS, help="output vendors.yaml path")
    e.add_argument("--force", action="store_true")
    c = sub.add_parser("check", help="verify vendors.yaml + /models probe")
    c.add_argument("--config", default=argparse.SUPPRESS, help="vendors.yaml path")
    c.add_argument("--no-probe", action="store_true")
    v = sub.add_parser("verify", help="live ping each provider (max_tokens=5)")
    v.add_argument("--config", default=argparse.SUPPRESS, help="vendors.yaml path")
    args = ap.parse_args()
    try:
        if args.cmd == "export":
            code = cmd_export(args)
        elif args.cmd == "check":
            code = cmd_check(args)
        elif args.cmd == "verify":
            code = cmd_verify(args)
        else:
            code = cmd_setup(args)
    except ConfigError as exc:
        print(f"[bootstrap] config error: {exc}", file=sys.stderr)
        code = 2
    raise SystemExit(code or 0)


if __name__ == "__main__":
    main()
