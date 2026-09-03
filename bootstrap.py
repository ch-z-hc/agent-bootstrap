#!/usr/bin/env python3
"""agent-bootstrap: give a new PC your agents config in one command.

Old PC:  py bootstrap.py export     -> writes bootstrap.env (keys + urls + models)
New PC:  copy bootstrap.env over, then:  py bootstrap.py
         (add --dry-run to preview, --only claude,codex to limit scope)

Only stdlib is used. DSH sync additionally needs pyyaml (skipped with a hint otherwise).
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

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("AGENT_HOME") or Path.home())
ENV_DEFAULT = HERE / "bootstrap.env"

OPENCODE_ROOT = "https://opencode.ai/zen/go"
OPENCODE_V1 = OPENCODE_ROOT + "/v1"

# (key in bootstrap.env, default)
FIELDS = [
    ("GPT_BASE_URL", ""),
    ("GPT_API_KEY", ""),
    ("GPT_MODEL", "gpt-5.6-sol"),
    ("OPENCODE_API_KEY", ""),
    ("OPENCODE_BASE_URL", OPENCODE_V1),
    ("CLAUDE_MODEL", "deepseek-v4-flash-vision-exp"),
    ("CLAUDE_SONNET", "deepseek-v4-pro"),
    ("CLAUDE_OPUS", "glm-5.3-flash"),
    ("PI_PROVIDER", "opencode-go-responses"),
    ("PI_MODEL", "muse-spark-1.3-contributor"),
]
REQUIRED = ("GPT_BASE_URL", "GPT_API_KEY", "OPENCODE_API_KEY")

AGENTS = ("claude", "codex", "pi", "zcode", "dsh")


def mask(s):
    s = str(s or "")
    return f"{s[:3]}...{s[-3:]}" if len(s) > 10 else ("<empty>" if not s else "<secret>")


def load_env(path):
    env = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k, d in FIELDS:
        env.setdefault(k, d)
    return env


def check_env(env, quiet=False):
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing and not quiet:
        print("[bootstrap] missing required fields:", ", ".join(missing))
    return missing


def fetch_models(base_url, api_key, timeout=10):
    """GET <base>/models (tries with/without /v1). Returns [ids] or []."""
    base = (base_url or "").rstrip("/")
    candidates = [base + "/models"] if base.endswith("/v1") else [base + "/v1/models", base + "/models"]
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            items = data.get("data") if isinstance(data, dict) else data
            ids = [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]
            if ids:
                return ids
        except Exception:
            continue
    return []


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if path.exists():
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
    tmp.replace(path)


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
            lines.append("")
            lines.append(f"[{nested_prefix}{sec}]")
            lines.extend(f"{k} = {toml_str(v)}" for k, v in missing)
            return True, "\n".join(lines) + "\n"
    for idx in sorted(insert_at, reverse=True):
        lines[idx:idx] = insert_at[idx]
    return True, "\n".join(lines) + "\n" if lines else ""


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
    tmp.replace(path)


# ---------------------------------------------------------------- sync pieces

def setup_claude(env, dry_run, out):
    p = HOME / ".claude" / "settings.json"
    root = OPENCODE_ROOT  # pi-style clients append /v1/messages themselves
    cm, son, opu = env["CLAUDE_MODEL"], env["CLAUDE_SONNET"], env["CLAUDE_OPUS"]

    def mut(d):
        e = d.setdefault("env", {})
        e["ANTHROPIC_AUTH_TOKEN"] = env["OPENCODE_API_KEY"]
        e.pop("ANTHROPIC_API_KEY", None)
        e["ANTHROPIC_BASE_URL"] = root
        e["ANTHROPIC_MODEL"] = cm
        e["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = cm
        e["ANTHROPIC_DEFAULT_SONNET_MODEL"] = son
        e["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opu
        e["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = "1000000"
        d["model"] = cm

    changed, new = patch_json(p, mut)
    out.append(("claude", str(p), changed))
    if changed and not dry_run:
        save_json(p, json.loads(new))


def setup_codex(env, dry_run, out):
    p = HOME / ".codex" / "config.toml"
    updates = {
        None: {"model": env["GPT_MODEL"], "model_provider": "gpt"},
        "gpt": {"base_url": env["GPT_BASE_URL"].rstrip("/"), "wire_api": "responses",
                "experimental_bearer_token": env["GPT_API_KEY"]},
    }
    _, new = patch_toml(p, updates)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    changed = new != old
    out.append(("codex", str(p), changed))
    if changed and not dry_run:
        write_text(p, new)


def pi_models_payload(env, discovered_oc, discovered_gpt):
    oc_base = env["OPENCODE_BASE_URL"].rstrip("/")
    gpt_base = env["GPT_BASE_URL"].rstrip("/")
    mp = HOME / ".pi" / "agent" / "models.json"
    keep = {}
    if mp.exists():
        try:
            keep = json.loads(mp.read_text(encoding="utf-8")).get("providers", {})
        except Exception:
            keep = {}

    def entry(name, base, api, key, models):
        if not models:
            old = (keep.get(name) or {}).get("models") or []
            models = [m.get("id") for m in old if isinstance(m, dict) and m.get("id")]
        return {"name": name, "baseUrl": base, "apiKey": key, "api": api,
                "models": [{"id": m, "name": m} for m in models]}

    oc_models = discovered_oc or [m.get("id") for m in (keep.get("opencode-go") or {}).get("models", []) if isinstance(m, dict)]
    gpt_models = discovered_gpt or [m.get("id") for m in (keep.get("gpt") or {}).get("models", []) if isinstance(m, dict)]
    if env["GPT_MODEL"] not in gpt_models:
        gpt_models = [env["GPT_MODEL"]] + gpt_models
    resp_models = [m.get("id") for m in (keep.get("opencode-go-responses") or {}).get("models", []) if isinstance(m, dict)]
    if not resp_models:
        resp_models = [m for m in oc_models if "muse-spark" in m] or oc_models[:2]
    return {
        "opencode-go": entry("opencode-go", oc_base, "openai-completions", env["OPENCODE_API_KEY"], oc_models),
        "gpt": entry("gpt", gpt_base, "openai-responses", env["GPT_API_KEY"], gpt_models),
        "opencode-go-responses": entry("opencode-go-responses", oc_base, "openai-responses", env["OPENCODE_API_KEY"], resp_models),
    }


def setup_pi(env, dry_run, out, discovered_oc, discovered_gpt):
    sp = HOME / ".pi" / "agent" / "settings.json"

    def mut(d):
        d["defaultProvider"] = env["PI_PROVIDER"]
        d["defaultModel"] = env["PI_MODEL"]

    changed, new = patch_json(sp, mut)
    out.append(("pi settings", str(sp), changed))
    if changed and not dry_run:
        save_json(sp, json.loads(new))
    mp = HOME / ".pi" / "agent" / "models.json"
    payload = pi_models_payload(env, discovered_oc, discovered_gpt)

    def mut2(d):
        ps = d.setdefault("providers", {})
        ps.update(payload)

    changed2, new2 = patch_json(mp, mut2)
    out.append(("pi models", str(mp), changed2))
    if changed2 and not dry_run:
        save_json(mp, json.loads(new2))


def setup_zcode(env, dry_run, out):
    p = HOME / ".zcode" / "v2" / "config.json"
    oc_v1, oc_root, gpt = env["OPENCODE_BASE_URL"].rstrip("/"), OPENCODE_ROOT, env["GPT_BASE_URL"].rstrip("/")
    want = {
        "opencode-go": (oc_v1, env["OPENCODE_API_KEY"]),
        "opencode-go-responses": (oc_v1, env["OPENCODE_API_KEY"]),
        "opencode-go-anthropic": (oc_root, env["OPENCODE_API_KEY"]),
        "gpt": (gpt, env["GPT_API_KEY"]),
    }

    def mut(d):
        pm = d.setdefault("provider", {})
        for key, (base, api_key) in want.items():
            e = pm.setdefault(key, {})
            e.setdefault("name", "OpenCode Go" if key.startswith("opencode") else "GPT Proxy")
            e["kind"] = e.get("kind") or "openai-compatible"
            if e.get("enabled") is None:
                e["enabled"] = True
            o = e.setdefault("options", {})
            o["baseURL"] = base
            o["apiKey"] = api_key

    if not p.exists():
        out.append(("zcode", str(p), "skip (not installed)"))
        return
    changed, new = patch_json(p, mut)
    out.append(("zcode", str(p), changed))
    if changed and not dry_run:
        save_json(p, json.loads(new))


def setup_dsh(env, dry_run, out):
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

    oc_models = rows(fetch_models(env["OPENCODE_BASE_URL"], env["OPENCODE_API_KEY"]) or [env["CLAUDE_MODEL"]])
    gpt_models = rows(fetch_models(env["GPT_BASE_URL"], env["GPT_API_KEY"]) or [env["GPT_MODEL"]])
    data.setdefault("agent-default-model", {}).update({"provider": "opencode-go", "model": env["CLAUDE_MODEL"]})
    llm = data.setdefault("llm-pi-ai", {}).setdefault("providers", {})
    llm["gpt"] = {"displayName": "GPT Proxy", "apiKeyEnv": "GPT_API_KEY", "api": "openai-responses",
                  "baseURL": env["GPT_BASE_URL"].rstrip("/"), "models": gpt_models}
    llm["opencode-go"] = {"displayName": "OpenCode Go", "apiKeyEnv": "OPENCODE_GO_API_KEY",
                          "api": "openai-completions", "baseURL": env["OPENCODE_BASE_URL"].rstrip("/"), "models": oc_models}
    old = sp.read_text(encoding="utf-8")
    new = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    out.append(("dsh settings", str(sp), new != old))
    if new != old and not dry_run:
        write_text(sp, new)
    creds = yaml.safe_load(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    refs = (creds or {}).setdefault("refs", {})
    refs["GPT_API_KEY"] = env["GPT_API_KEY"]
    refs["OPENCODE_GO_API_KEY"] = env["OPENCODE_API_KEY"]
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


def cmd_export(args):
    env = {}
    cl = read_json(HOME / ".claude" / "settings.json").get("env", {})
    env["OPENCODE_API_KEY"] = cl.get("ANTHROPIC_AUTH_TOKEN") or cl.get("ANTHROPIC_API_KEY") or ""
    env["CLAUDE_MODEL"] = cl.get("ANTHROPIC_MODEL") or "deepseek-v4-flash-vision-exp"
    env["CLAUDE_SONNET"] = cl.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or env["CLAUDE_MODEL"]
    env["CLAUDE_OPUS"] = cl.get("ANTHROPIC_DEFAULT_OPUS_MODEL") or env["CLAUDE_MODEL"]
    tx = (HOME / ".codex" / "config.toml").read_text(encoding="utf-8") if (HOME / ".codex" / "config.toml").exists() else ""
    m = re.search(r"model\s*=\s*\"([^\"]+)\"", tx)
    env["GPT_MODEL"] = m.group(1) if m else "gpt-5.6-sol"
    sec = re.search(r"\[model_providers\.gpt\](.*?)(?=^\[|\Z)", tx, re.S | re.M)
    sec = sec.group(1) if sec else ""
    b = re.search(r"base_url\s*=\s*\"([^\"]+)\"", sec)
    t = re.search(r"experimental_bearer_token\s*=\s*\"([^\"]+)\"", sec)
    env["GPT_BASE_URL"] = b.group(1) if b else ""
    env["GPT_API_KEY"] = t.group(1) if t else ""
    pi_s = read_json(HOME / ".pi" / "agent" / "settings.json")
    env["PI_PROVIDER"] = pi_s.get("defaultProvider") or "opencode-go-responses"
    env["PI_MODEL"] = pi_s.get("defaultModel") or "muse-spark-1.3-contributor"
    pi_m = read_json(HOME / ".pi" / "agent" / "models.json").get("providers", {})
    env["OPENCODE_BASE_URL"] = ((pi_m.get("opencode-go") or {}).get("baseUrl") or OPENCODE_V1).rstrip("/")
    if not env["OPENCODE_API_KEY"]:
        env["OPENCODE_API_KEY"] = (pi_m.get("opencode-go") or {}).get("apiKey") or ""
    dest = Path(args.env)
    if dest.exists() and not args.force:
        print(f"[export] {dest} exists; use --force to overwrite")
        return
    lines = ["# agent-bootstrap: copy to new PC as bootstrap.env, then: py bootstrap.py", ""]
    for k, d in FIELDS:
        lines.append(f"{k}={env.get(k) or d}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[export] wrote {dest}")
    for k, _ in FIELDS:
        print(f"  {k}={mask(env.get(k))}")


def cmd_setup(args):
    env = load_env(args.env)
    if check_env(env):
        return
    only = set(args.only) if args.only else set(AGENTS)
    print(f"[bootstrap] gpt={mask(env['GPT_API_KEY'])}@{env['GPT_BASE_URL']} "
          f"opencode={mask(env['OPENCODE_API_KEY'])} models={env['GPT_MODEL']}/{env['CLAUDE_MODEL']}/{env['PI_MODEL']}")
    doc, dgpt = [], []
    if not args.no_probe:
        doc = fetch_models(env["OPENCODE_BASE_URL"], env["OPENCODE_API_KEY"])
        dgpt = fetch_models(env["GPT_BASE_URL"], env["GPT_API_KEY"])
        print(f"[bootstrap] probe: opencode-go {len(doc)} models, gpt {len(dgpt)} models")
    out = []
    if "claude" in only:
        setup_claude(env, args.dry_run, out)
    if "codex" in only:
        setup_codex(env, args.dry_run, out)
    if "pi" in only:
        setup_pi(env, args.dry_run, out, doc, dgpt)
    if "zcode" in only:
        setup_zcode(env, args.dry_run, out)
    if "dsh" in only:
        setup_dsh(env, args.dry_run, out)
    print("[bootstrap] DRY-RUN -- nothing written" if args.dry_run else "[bootstrap] done:")
    for name, path, changed in out:
        flag = "~" if str(changed).startswith("skip") else ("*" if changed else "=")
        print(f"  {flag} {name}: {path}")


def cmd_check(args):
    env = load_env(args.env)
    print(f"[check] {args.env} ({'found' if Path(args.env).exists() else 'NOT FOUND'})")
    for k, _ in FIELDS:
        print(f"  {k}={mask(env.get(k))}{'' if k in REQUIRED else ' (optional)'}")
    if check_env(env, quiet=True):
        print("[check] MISSING required fields -- setup would refuse to run")
        return
    if not args.no_probe:
        for label, base, key in (("opencode-go", env["OPENCODE_BASE_URL"], env["OPENCODE_API_KEY"]),
                                 ("gpt", env["GPT_BASE_URL"], env["GPT_API_KEY"])):
            ids = fetch_models(base, key)
            print(f"  probe {label}: {'OK ' + str(len(ids)) + ' models' if ids else 'FAILED (url/key?)'}")


def main():
    ap = argparse.ArgumentParser(description="agent-bootstrap: one-command agent setup for a new PC")
    ap.add_argument("--env", default=str(ENV_DEFAULT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", choices=list(AGENTS), default=None)
    ap.add_argument("--no-probe", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("setup", help="write agent configs (default)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--only", nargs="*", choices=list(AGENTS), default=None)
    s.add_argument("--no-probe", action="store_true")
    e = sub.add_parser("export", help="generate bootstrap.env from this PC")
    e.add_argument("--force", action="store_true")
    c = sub.add_parser("check", help="verify env + connectivity")
    c.add_argument("--no-probe", action="store_true")
    args = ap.parse_args()
    if args.cmd == "export":
        cmd_export(args)
    elif args.cmd == "check":
        cmd_check(args)
    else:
        cmd_setup(args)


if __name__ == "__main__":
    main()
