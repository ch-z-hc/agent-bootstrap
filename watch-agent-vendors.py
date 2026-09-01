#!/usr/bin/env python3
"""Background watcher for ~/.agents/agent-vendors.yaml.

Re-runs agent_vendors.py sync whenever the central YAML changes.
Single instance is enforced by binding a localhost port.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
AGENTS = HOME / ".agents"
YAML_FILE = AGENTS / "agent-vendors.yaml"
# Resolve the synchronizer beside this watcher so the repository can be run
# directly from any directory without relying on a copied script in ~/.agents.
PY_SCRIPT = Path(__file__).resolve().with_name("agent_vendors.py")
LOG_FILE = AGENTS / "watch-agent-vendors.log"
PORT = 47653


def log(message: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")


def fingerprint() -> tuple[int, int]:
    st = YAML_FILE.stat()
    return st.st_mtime_ns, st.st_size


def main() -> None:
    # Single instance: bind a localhost port. Second instance exits.
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", PORT))
        lock.listen(1)
    except OSError:
        sys.exit(0)

    log(f"watch started: {YAML_FILE} -> {PY_SCRIPT}")
    last = fingerprint()

    while True:
        time.sleep(2)
        try:
            cur = fingerprint()
        except FileNotFoundError:
            continue
        if cur == last:
            continue

        # Debounce: wait for editor save bursts to settle.
        time.sleep(2)
        log("trigger: agent-vendors.yaml changed")
        try:
            proc = subprocess.run(
                [sys.executable, str(PY_SCRIPT), "sync", "--no-backup"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120,
            )
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                if proc.stdout:
                    f.write(proc.stdout)
                if proc.stderr:
                    f.write(proc.stderr)
            log(f"sync finished (rc={proc.returncode})")
        except Exception as e:  # noqa: BLE001 - keep the daemon alive
            log(f"sync error: {e}")
        finally:
            try:
                last = fingerprint()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()
