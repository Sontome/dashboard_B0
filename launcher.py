from __future__ import annotations

import ctypes
import os
import sqlite3
import threading
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

import uvicorn

from api import DB, app


PORT = int(os.environ.get("B0PULSE_PORT", "8501"))
URL = f"http://127.0.0.1:{PORT}"
APP_TITLE = "B0 Pulse"

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_SETFONT = 0x0030
BN_CLICKED = 0
COLOR_WINDOW = 5
SW_SHOW = 5
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
BS_PUSHBUTTON = 0
SS_CENTER = 1
SS_LEFT = 0
CW_USEDEFAULT = -2147483648

ID_OPEN = 101
ID_REFRESH = 102
ID_STATUS_TIMER = 1

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SetWindowTextW.restype = wintypes.BOOL
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t
gdi32.CreateFontW.restype = wintypes.HANDLE

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class Launcher:
    def __init__(self) -> None:
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
        self.hwnd = None
        self.status = None
        self.summary = None
        self.months = None
        self.font = gdi32.CreateFontW(
            -18, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"
        )
        self.title_font = gdi32.CreateFontW(
            -28, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"
        )
        self._wndproc_ref = WNDPROC(self._wndproc)

    @staticmethod
    def _create_control(kind, text, style, x, y, width, height, parent, control_id=0):
        return user32.CreateWindowExW(
            0, kind, text, WS_VISIBLE | WS_CHILD | style, x, y, width, height,
            parent, control_id, kernel32.GetModuleHandleW(None), None,
        )

    def _set_font(self, control, title=False):
        user32.SendMessageW(control, WM_SETFONT, self.title_font if title else self.font, True)

    def _layout(self, hwnd):
        title = self._create_control("STATIC", "B0 PULSE", SS_CENTER, 30, 26, 600, 42, hwnd)
        self._set_font(title, True)
        subtitle = self._create_control(
            "STATIC", "Dashboard theo dõi hợp đồng B0 / B1", SS_CENTER,
            30, 70, 600, 28, hwnd,
        )
        self._set_font(subtitle)

        self.status = self._create_control(
            "STATIC", "Đang khởi động server...", SS_CENTER, 30, 116, 600, 30, hwnd
        )
        self._set_font(self.status)
        self.summary = self._create_control(
            "STATIC", "Dữ liệu hiện có: 0 tháng", SS_LEFT, 55, 174, 550, 30, hwnd
        )
        self._set_font(self.summary)
        self.months = self._create_control(
            "STATIC", "Chưa có dữ liệu", SS_LEFT, 55, 210, 550, 105, hwnd
        )
        self._set_font(self.months)

        open_button = self._create_control(
            "BUTTON", "Mở dashboard", BS_PUSHBUTTON, 55, 338, 265, 48, hwnd, ID_OPEN
        )
        refresh_button = self._create_control(
            "BUTTON", "Làm mới dữ liệu", BS_PUSHBUTTON, 340, 338, 265, 48, hwnd, ID_REFRESH
        )
        self._set_font(open_button)
        self._set_font(refresh_button)

        hint = self._create_control(
            "STATIC", "Giữ cửa sổ này mở trong khi sử dụng dashboard.", SS_CENTER,
            30, 412, 600, 28, hwnd,
        )
        self._set_font(hint)
        self.refresh_data()

    def refresh_data(self):
        rows = []
        if DB.exists():
            try:
                with sqlite3.connect(DB) as con:
                    rows = con.execute(
                        "SELECT substr(snapshot_date,1,7), count(DISTINCT snapshot_date) "
                        "FROM snapshots GROUP BY 1 ORDER BY 1 DESC"
                    ).fetchall()
            except sqlite3.Error:
                rows = []
        if self.summary:
            user32.SetWindowTextW(self.summary, f"Dữ liệu hiện có: {len(rows)} tháng")
            detail = "   |   ".join(
                f"{month[5:7]}/{month[:4]}: {days} ngày" for month, days in rows[:8]
            ) or "Chưa có dữ liệu. Mở dashboard để tải file Excel."
            user32.SetWindowTextW(self.months, detail)

    def _server_ready(self):
        try:
            with urllib.request.urlopen(URL + "/api/months", timeout=0.35) as response:
                return response.status == 200
        except Exception:
            return False

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND:
            control_id = wparam & 0xFFFF
            notification = (wparam >> 16) & 0xFFFF
            if notification == BN_CLICKED and control_id == ID_OPEN:
                webbrowser.open(URL)
                return 0
            if notification == BN_CLICKED and control_id == ID_REFRESH:
                self.refresh_data()
                return 0
        elif msg == WM_TIMER and wparam == ID_STATUS_TIMER:
            ready = self._server_ready()
            user32.SetWindowTextW(
                self.status, f"Sẵn sàng - {URL}" if ready else "Đang khởi động server..."
            )
            return 0
        elif msg == WM_DESTROY:
            self.server.should_exit = True
            user32.KillTimer(hwnd, ID_STATUS_TIMER)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        # Start the API first so slow Windows control initialization never delays it.
        threading.Thread(target=self.server.run, daemon=True).start()
        instance = kernel32.GetModuleHandleW(None)
        window_class = "B0PulseLauncherWindow"
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = instance
        wc.hCursor = user32.LoadCursorW(None, 32512)
        wc.hbrBackground = COLOR_WINDOW + 1
        wc.lpszClassName = window_class
        user32.RegisterClassW(ctypes.byref(wc))

        self.hwnd = user32.CreateWindowExW(
            0, window_class, APP_TITLE, WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT, CW_USEDEFAULT, 680, 510,
            None, None, instance, None,
        )
        self._layout(self.hwnd)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        user32.SetTimer(self.hwnd, ID_STATUS_TIMER, 1200, None)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    Launcher().run()
