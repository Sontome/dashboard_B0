from __future__ import annotations

import os
import sqlite3
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import uvicorn

from api import DB, app


PORT = int(os.environ.get("B0PULSE_PORT", "8501"))
URL = f"http://127.0.0.1:{PORT}"
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"


class Launcher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("B0 Pulse")
        self.root.geometry("680x560")
        self.root.minsize(620, 500)
        self.root.configure(bg="#eef3ef")
        # A PyInstaller --windowed executable has no stdout/stderr.  Uvicorn's
        # default color formatter probes stderr.isatty(), which crashes while
        # constructing Config when stderr is None.  The GUI reports server
        # state itself, so Uvicorn does not need to install console logging.
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=PORT,
                log_level="warning",
                log_config=None,
                access_log=False,
            )
        )
        self._style()
        self._icon()
        self._layout()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", background="#ffffff", foreground="#183b34", fieldbackground="#ffffff", rowheight=31, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#e7f0eb", foreground="#365b51", relief="flat", font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#d9eee5")], foreground=[("selected", "#153e33")])
        style.configure("Primary.TButton", background="#24775f", foreground="white", padding=(17, 10), borderwidth=0, font=("Segoe UI Semibold", 10))
        style.map("Primary.TButton", background=[("active", "#195f4b")])
        style.configure("Soft.TButton", background="#ffffff", foreground="#28594b", padding=(14, 9), borderwidth=1, font=("Segoe UI Semibold", 9))

    def _icon(self):
        ico = ASSET_ROOT / "b0pulse.ico"
        png = ASSET_ROOT / "b0pulse-icon.png"
        try:
            self.root.iconbitmap(str(ico))
        except tk.TclError:
            pass
        try:
            self.logo = tk.PhotoImage(file=str(png)).subsample(12, 12)
        except tk.TclError:
            self.logo = None

    def card(self, parent, **kwargs):
        return tk.Frame(parent, bg="white", highlightthickness=1, highlightbackground="#d9e4de", bd=0, **kwargs)

    def _layout(self):
        shell = tk.Frame(self.root, bg="#eef3ef", padx=24, pady=22)
        shell.pack(fill="both", expand=True)

        header = self.card(shell, padx=20, pady=17)
        header.pack(fill="x")
        if self.logo:
            tk.Label(header, image=self.logo, bg="white").pack(side="left", padx=(0, 14))
        titles = tk.Frame(header, bg="white")
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text="B0 PULSE", bg="white", fg="#173e34", font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(titles, text="Dashboard thu hồi B0 / B1", bg="white", fg="#6d837b", font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Button(header, text="Mở dashboard", style="Primary.TButton", command=lambda: webbrowser.open(URL)).pack(side="right")

        status_card = self.card(shell, padx=18, pady=14)
        status_card.pack(fill="x", pady=(14, 14))
        self.light = tk.Canvas(status_card, width=16, height=16, bg="white", highlightthickness=0)
        self.light.pack(side="left", padx=(0, 10))
        self.dot = self.light.create_oval(2, 2, 14, 14, fill="#e3a330", outline="#f3d28c")
        status_text = tk.Frame(status_card, bg="white")
        status_text.pack(side="left", fill="x", expand=True)
        self.status = tk.Label(status_text, text="Đang khởi động…", bg="white", fg="#385a51", font=("Segoe UI Semibold", 10))
        self.status.pack(anchor="w")
        tk.Label(status_text, text=URL, bg="white", fg="#83978f", font=("Segoe UI", 8)).pack(anchor="w")
        ttk.Button(status_card, text="Làm mới dữ liệu", style="Soft.TButton", command=self.refresh_data).pack(side="right")

        data_card = self.card(shell, padx=18, pady=16)
        data_card.pack(fill="both", expand=True)
        tk.Label(data_card, text="DỮ LIỆU ĐÃ CÓ", bg="white", fg="#2b886c", font=("Segoe UI Semibold", 9)).pack(anchor="w")
        tk.Label(data_card, text="Danh sách tháng và ngày chốt", bg="white", fg="#173e34", font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(2, 12))
        columns = ("month", "days", "count")
        self.table = ttk.Treeview(data_card, columns=columns, show="headings", height=9)
        self.table.heading("month", text="Tháng")
        self.table.heading("days", text="Các ngày đã có dữ liệu")
        self.table.heading("count", text="Số ngày")
        self.table.column("month", width=100, anchor="center")
        self.table.column("days", width=400, anchor="w")
        self.table.column("count", width=70, anchor="center")
        scroll = ttk.Scrollbar(data_card, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        tk.Label(shell, text="Giữ cửa sổ này mở trong khi sử dụng dashboard.", bg="#eef3ef", fg="#758a82", font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 0))
        self.refresh_data()

    def refresh_data(self):
        for item in self.table.get_children():
            self.table.delete(item)
        if not DB.exists():
            return
        try:
            con = sqlite3.connect(DB)
            rows = con.execute("SELECT substr(snapshot_date,1,7), group_concat(DISTINCT snapshot_date), count(DISTINCT snapshot_date) FROM snapshots GROUP BY 1 ORDER BY 1 DESC").fetchall()
            con.close()
            for month, raw_dates, count in rows:
                days = sorted(value[-2:] for value in (raw_dates or "").split(","))
                label = f"Tháng {month[5:7]}/{month[:4]}"
                self.table.insert("", "end", values=(label, ", ".join(days), count))
        except sqlite3.Error:
            pass

    def start(self):
        threading.Thread(target=self.server.run, daemon=True).start()
        self.root.after(350, self.check_server)
        self.root.mainloop()

    def check_server(self):
        try:
            with urllib.request.urlopen(URL + "/api/months", timeout=0.5) as response:
                healthy = response.status == 200
        except Exception:
            healthy = False
        if healthy:
            self.light.itemconfig(self.dot, fill="#28a873", outline="#a5e3c9")
            self.status.config(text="Đang chạy")
        else:
            self.light.itemconfig(self.dot, fill="#e3a330", outline="#f3d28c")
            self.status.config(text="Đang khởi động…")
        self.root.after(1800, self.check_server)

    def close(self):
        self.server.should_exit = True
        self.root.destroy()


if __name__ == "__main__":
    Launcher().start()
