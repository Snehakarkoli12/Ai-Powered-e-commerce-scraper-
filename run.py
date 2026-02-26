# run.py
"""
Windows + Playwright + hot-reload solution.
Uses watchfiles.run_process to manage restarts.
Uses loop="none" to prevent uvicorn overriding our ProactorEventLoop.
"""
import sys
import os


def _server():
    """
    Worker function — runs in each spawned subprocess.
    Policy MUST be set here, before uvicorn touches the event loop.
    """
    import sys
    import asyncio

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
        port=8000,
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
            print("📡  Server → http://127.0.0.1:8000")
            run_process(
                "app",                          # Watch this directory
                target=_server,
                watch_filter=lambda _, p: p.endswith(".py") or p.endswith(".yaml"),
            )
        except ImportError:
            # watchfiles not installed — fallback to no-reload
            print("⚠ watchfiles not found — running without hot-reload")
            _server()
