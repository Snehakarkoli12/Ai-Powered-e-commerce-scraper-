# run.py
"""
Windows + Playwright + hot-reload solution.
Uses watchfiles.run_process to manage restarts.
Uses loop="none" to prevent uvicorn overriding our ProactorEventLoop.
"""
import sys
import os


PORT = 8000


def _free_port(port: int):
    """Kill any process currently listening on *port* (Windows only)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return  # port is already free
    except OSError:
        return

    # Port is occupied — try to free it
    import subprocess
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port} "',
            shell=True, text=True, stderr=subprocess.DEVNULL,
        )
        pids = set()
        for line in out.strip().splitlines():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
        for pid in pids:
            if pid <= 4:
                continue  # skip System / Idle
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
                print(f"🔌  Killed PID {pid} occupying port {port}")
            except Exception:
                pass
    except Exception as exc:
        print(f"⚠  Could not free port {port}: {exc}")


def _server():
    """
    Worker function — runs in each spawned subprocess.
    Policy MUST be set here, before uvicorn touches the event loop.
    """
    import sys
    import asyncio

    # Step 0: Free port if another process is lingering
    _free_port(PORT)

    # Step 1: Force ProactorEventLoop BEFORE uvicorn loads
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)

    import uvicorn

    # Step 2: loop="none" → tells uvicorn: DO NOT call asyncio_setup()
    # asyncio_setup() is what forces SelectorEventLoop on Windows
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=PORT,
        loop="none",        # ← CRITICAL: prevents uvicorn overriding our policy
        reload=False,       # watchfiles handles restarts, not uvicorn
        log_level="info",
    )


if __name__ == "__main__":
    # Hot-reload: watchfiles watches app/ and respawns _server() on .py changes
    # Each restart spawns a fresh subprocess → policy set cleanly
    if "--no-reload" in sys.argv:
        _server()
    else:
        try:
            from watchfiles import run_process
            print("🔄  Hot-reload active — watching app/")
            print(f"📡  Server → http://127.0.0.1:{PORT}")
            run_process(
                "app",                          # Watch this directory
                target=_server,
                watch_filter=lambda _, p: p.endswith(".py") or p.endswith(".yaml"),
            )
        except ImportError:
            # watchfiles not installed — fallback to no-reload
            print("⚠ watchfiles not found — running without hot-reload")
            _server()
