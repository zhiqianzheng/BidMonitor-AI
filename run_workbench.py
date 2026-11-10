"""Launch the persistent local workbench and open its browser interface."""
import argparse
import json
import logging
import os
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path


def main():
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    os.chdir(root)
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
            existing = json.load(response)
        if existing.get("app") == "bidmonitor-workbench":
            if not args.no_browser:
                webbrowser.open(url)
            return
    except Exception:
        pass
    (root / "data").mkdir(exist_ok=True)
    if getattr(sys, "frozen", False):
        os.environ.setdefault("BIDMONITOR_DB", str(root / "data" / "bids.db"))
    logging.basicConfig(filename=root / "data/workbench.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    if not args.no_browser:
        def open_when_ready():
            for _ in range(60):
                try:
                    with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                        if json.load(response).get("app") == "bidmonitor-workbench":
                            webbrowser.open(url)
                            return
                except Exception:
                    threading.Event().wait(.5)
        threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn
    from server.workbench_app import app
    print(f"BidMonitor is running: {url}", flush=True)
    print("Keep this window open. Close it or press Ctrl+C to stop.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, loop="asyncio", http="h11", ws="none",
                log_config=None, access_log=False)


if __name__ == "__main__":
    main()
