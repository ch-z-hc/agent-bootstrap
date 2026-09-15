---
name: agent-bootstrap-sync
description: Sync coding-agent model configs from a single YAML source of truth. USE WHENEVER user asks to change/switch models or providers for Codex, Pi, Claude Code, DSH, ZCode, mentions 改模型, 换模型, 改配置, 切 provider, 同步配置, vendors.yaml, agent-bootstrap, or wants all agents on the same model. Even if they name only one agent file, route through this skill instead of editing agent configs directly.
---

# Agent Bootstrap Sync

Use `~/agent-bootstrap/vendors.yaml` as the single source of truth for vendor,
endpoint, credential-reference, model, and per-agent settings. Edit that file,
then run the bootstrap sync; do not hand-edit generated agent config files.

## Source of truth

`~/agent-bootstrap/vendors.yaml` — edit here, then sync. (Note: `~/.agents/backups/` only holds old backups, not the live file.)

```yaml
bai:
  base_url: https://api.b.ai/v1
  api_key_env: BAI_API_KEY
aizex:
  base_url: https://ca.memofun.net/v1
  api_key_env: AIZEX_API_KEY
codex:
  provider: bai
  model: qwen3.8-flash        # sync SKIPS codex, see Rules
claude:
  model: qwen3.8-flash
  sonnet: qwen3.8-flash
  opus: qwen3.8-flash
pi:
  provider: bai
  model: qwen3.8-flash
  http_proxy: http://127.0.0.1:7897
dsh:
  provider: bai
  model: qwen3.8-flash
```

One upstream only: **b.ai**. Every other upstream ever configured here has been dropped and is
out of scope — do not re-add, probe, or recommend one. The sync prunes their leftovers from
agent files via `RETIRED_PROVIDERS` in `bootstrap.py`.

Provider sections are ordinary YAML mappings. A provider may define `base_url`,
`api_key_env` (preferred) or `api_key`, API type, and any provider-specific
options supported by `bootstrap.py`. Keep credentials out of documentation and
prefer environment variables.

## Workflow

Run every step with `py` (Windows Git Bash has no `python3`):

1. If `vendors.yaml` is missing, regenerate from this PC — never hand-write keys:
   `py ~/agent-bootstrap/bootstrap.py export --force`
2. Confirm exact model IDs against the live catalog before editing:
   `py ~/agent-bootstrap/bootstrap.py check` → expect `probe bai: OK 47 models`.
   A model existing in `/models` does NOT mean it is callable (balance) — ping it with
   `verify`, or POST `/v1/chat/completions` with `max_tokens=5` first.
3. Edit only `vendors.yaml`.
4. Preview: `py ~/agent-bootstrap/bootstrap.py --dry-run --only <agents>`
   (`<agents>` subset of: `claude codex pi zcode dsh`.)
5. Apply: `py ~/agent-bootstrap/bootstrap.py --only <agents>`
   Omit `--only` only when the user wants every agent synced.
6. Verify: `py ~/agent-bootstrap/bootstrap.py verify` — expect `ALL OK` with both
   `bai openai (pi/dsh/zcode path)` and `bai anthropic (claude path)` OK. Spot-check
   (`~/.pi/agent/settings.json` → `defaultProvider`/`defaultModel`; `~/.pi/agent/models.json`
   → `providers` contains **only** `bai`; `~/.claude/settings.json` → `env.ANTHROPIC_BASE_URL`).

## Rules

- Keys and URLs come from `export` or the user, never invented. `bootstrap.py` has no network
  fallback for a bad key — a `401 Invalid or expired api_key` means the key, not the config.
- Codex is configured from the `codex.provider` and `codex.model` entries and
  the matching provider section; `wire_api` must be `responses` for current Codex.
- `pi`/`dsh` model must exist in bai's `/models` list; sync probes it live and prepends missing IDs.
- New models need a spec in `bootstrap.py` `OPENCODE_MODEL_SPECS` (still the table name, also used
  for bai) or pi falls back to 128k/16k windows. `qwen3.8-flash` = `(1000000, 131072, True, ["text", "image"])`.
  qwen-family entries additionally get a `compat` block (`thinkingFormat: qwen`, no
  `reasoning_effort`/`store`/`developer` role) — bai rejects those fields.
- If `bootstrap.py` lacks a field the user needs, extend the script (`load_vendors` + `setup_*` +
  `cmd_export` + `cmd_verify` mapping) rather than hand-editing agent files — otherwise the next
  sync overwrites the manual fix.
- New PC migration: copy the whole `agent-bootstrap/` folder (plus `vendors.yaml`), set
  `BAI_API_KEY` in the environment (or use inline `api_key`), install `pyyaml`, run sync once.

## Quick examples

- "全部换到 bai 的 qwen3.8-flash": set every `provider/model` in YAML, then `--only claude pi zcode dsh`.
- "只看会改什么不动手": `--dry-run`.
- "这个模型真能用吗": `py bootstrap.py verify`, or curl `POST /v1/chat/completions` `max_tokens=5`
  — `/models` returning an ID says nothing about balance.
