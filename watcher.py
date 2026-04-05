"""
Full-restart file watcher for Ragnificent.

Watches app/, config.yaml, models_catalog.yaml, and all templates/static files.
On any change, kills the running uvicorn process and starts a fresh one.
This guarantees a clean slate — no stale imports, no half-loaded modules.

Usage (via run.ps1):
    python watcher.py
"""
import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Load .env before anything else
ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

WATCH_DIRS = [
    ROOT / "app",
]
WATCH_EXTENSIONS = {".py", ".html", ".yaml", ".css", ".js"}
IGNORE_DIRS = {"__pycache__", ".git", "rag_library", ".claude"}
IGNORE_SUFFIXES = {".pyc", ".sqlite", ".lock", ".tmp"}

SERVER_CMD = [sys.executable, "-m", "app.cli", "--config", "config.yaml", "serve"]

# -----------------------------------------------------------------------

def snapshot(dirs):
    """Return a dict of {path: mtime} for all watched files."""
    state = {}
    for d in dirs:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix in WATCH_EXTENSIONS:
                # Skip ignored directories anywhere in the path
                if any(part in IGNORE_DIRS for part in f.parts):
                    continue
                if f.suffix in IGNORE_SUFFIXES:
                    continue
                try:
                    state[str(f)] = f.stat().st_mtime
                except OSError:
                    pass
    # Also watch root-level yaml files
    for p in ROOT.glob("*.yaml"):
        try:
            state[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return state


def start_server():
    print("\n[watcher] Starting server...", flush=True)
    proc = subprocess.Popen(SERVER_CMD, cwd=str(ROOT))
    return proc


def stop_server(proc):
    if proc and proc.poll() is None:
        print("[watcher] Stopping server...", flush=True)
        if sys.platform == "win32":
            # On Windows, kill the whole process tree
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    time.sleep(0.5)  # brief pause so the port is released


def changed(old, new):
    """Return list of changed/added/removed paths."""
    all_keys = set(old) | set(new)
    diff = []
    for k in all_keys:
        if old.get(k) != new.get(k):
            diff.append(k)
    return diff


def main():
    print("[watcher] Ragnificent file watcher started.", flush=True)
    print(f"[watcher] Watching: {', '.join(str(d) for d in WATCH_DIRS)} + root *.yaml", flush=True)
    print("[watcher] Extensions:", ", ".join(sorted(WATCH_EXTENSIONS)), flush=True)
    print("[watcher] Press Ctrl+C to stop.\n", flush=True)

    current_snapshot = snapshot(WATCH_DIRS)
    proc = start_server()

    try:
        while True:
            time.sleep(1)

            # If server died unexpectedly, restart it
            if proc.poll() is not None:
                print("[watcher] Server exited unexpectedly — restarting...", flush=True)
                time.sleep(1)
                current_snapshot = snapshot(WATCH_DIRS)
                proc = start_server()
                continue

            new_snapshot = snapshot(WATCH_DIRS)
            diff = changed(current_snapshot, new_snapshot)
            if diff:
                # Show what changed (limit to 5 lines)
                for p in diff[:5]:
                    rel = Path(p).relative_to(ROOT) if Path(p).is_relative_to(ROOT) else p
                    print(f"[watcher] Changed: {rel}", flush=True)
                if len(diff) > 5:
                    print(f"[watcher] ...and {len(diff) - 5} more", flush=True)

                stop_server(proc)
                current_snapshot = new_snapshot
                proc = start_server()

    except KeyboardInterrupt:
        print("\n[watcher] Shutting down...", flush=True)
        stop_server(proc)
        print("[watcher] Done.", flush=True)


if __name__ == "__main__":
    main()
