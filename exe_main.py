from __future__ import annotations

import os
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from api import app


PORT = int(os.environ.get("B0PULSE_PORT", "8501"))
URL = f"http://127.0.0.1:{PORT}"


def open_browser_when_ready() -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(URL + "/api/months", timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(URL)
                    return
        except Exception:
            time.sleep(0.25)


if __name__ == "__main__":
    print(f"B0 Pulse dang chay tai {URL}")
    print("Dong cua so nay hoac nhan Ctrl+C de tat ung dung.")
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
