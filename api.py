from __future__ import annotations

import io
import json
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import archive_file, build_contract_report, connect, load_snapshots, read_snapshot, reset_month, upsert_snapshot


SOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
APP_ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DB = APP_ROOT / "data" / "dashboard.db"
MONTHS_DIR = APP_ROOT / "data" / "months"
WEB = SOURCE_ROOT / "web"
CACHE_DIR = APP_ROOT / "data" / "cache"
CACHE_SCHEMA = 2

app = FastAPI(title="B0 Pulse", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


def _db_version() -> int:
    wal = DB.with_name(DB.name + "-wal")
    return max(DB.stat().st_mtime_ns if DB.exists() else 0, wal.stat().st_mtime_ns if wal.exists() else 0)


def _clean(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{key: _clean(value) for key, value in row.items()} for row in frame.to_dict("records")]


@lru_cache(maxsize=16)
def calculate_month(month: str, version: int) -> dict:
    cache_file = CACHE_DIR / f"v{CACHE_SCHEMA}-{month}-{version}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    con = connect(DB)
    try:
        snapshots = load_snapshots(con)
    finally:
        con.close()
    rows = snapshots[snapshots.snapshot_date.dt.strftime("%Y-%m").eq(month)].copy()
    if rows.empty:
        raise ValueError("Tháng chưa có dữ liệu")
    first = rows.sort_values("snapshot_date").groupby("contract_id", as_index=False).first()
    b0_ids = first.loc[first.dpd.le(0), "contract_id"]
    cohort = rows[rows.contract_id.isin(b0_ids)].copy()
    report = build_contract_report(cohort).sort_values(["due_date", "current_dpd"], ascending=[True, False])
    latest_date = cohort.snapshot_date.max()
    latest = cohort[cohort.snapshot_date.eq(latest_date)].copy()
    latest["bucket"] = latest.dpd.map(lambda x: "B0" if x <= 0 else "B1" if x <= 30 else "B2+")
    paid = report[report.status.str.startswith("Đã")]
    trend = cohort.assign(bucket=cohort.dpd.map(lambda x: "B0" if x <= 0 else "B1" if x <= 30 else "B2+"))
    trend = trend.groupby(["snapshot_date", "bucket"]).size().reset_index(name="count")
    roll_b1 = report[report.max_dpd.gt(0)].copy()
    matured = report[report.due_date.notna() & report.due_date.le(latest_date) & report.due_date.dt.strftime("%Y-%m").eq(month)].copy()
    matured["paid_on_due_date"] = matured.paid_dpd.eq(0)
    daily_on_time = matured.groupby("due_date").agg(total_due=("contract_id", "size"), paid_on_time=("paid_on_due_date", "sum")).reset_index()
    daily_on_time["rate"] = (daily_on_time.paid_on_time / daily_on_time.total_due * 100).round(1)
    result = {
        "month": month,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "summary": {
            "b0": int(latest.bucket.eq("B0").sum()),
            "b1": int(latest.bucket.eq("B1").sum()),
            "paid": int(len(paid)),
            "on_time": int(paid.status.str.endswith("đúng hạn").sum()),
            "late": int(paid.status.str.endswith("quá hạn").sum()),
            "outstanding": float(latest.outstanding.sum()),
            "roll_b1": int(len(roll_b1)),
        },
        "trend": _records(trend),
        "daily_on_time": _records(daily_on_time),
        "report": _records(report),
        "roll_b1": _records(roll_b1),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return result


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/months")
def months():
    con = connect(DB)
    try:
        values = [row[0] for row in con.execute(
            "SELECT DISTINCT substr(snapshot_date,1,7) FROM snapshots ORDER BY 1 DESC"
        ).fetchall()]
    finally:
        con.close()
    return {"months": values}


@app.get("/api/dashboard")
def dashboard(month: str):
    try:
        return calculate_month(month, _db_version())
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/import")
async def import_files(files: list[UploadFile] = File(...)):
    con = connect(DB)
    imported, errors = 0, []
    try:
        for uploaded in files:
            try:
                content = await uploaded.read()
                frame = read_snapshot(io.BytesIO(content), uploaded.filename or "upload.xlsx")
                imported += upsert_snapshot(con, frame)
                archive_file(uploaded.filename or "upload.xlsx", content, frame, MONTHS_DIR)
            except Exception as exc:
                errors.append(f"{uploaded.filename}: {exc}")
    finally:
        con.close()
    calculate_month.cache_clear()
    return {"imported": imported, "errors": errors}


@app.delete("/api/month/{month}")
def delete_month(month: str):
    con = connect(DB)
    try:
        removed = reset_month(con, month, MONTHS_DIR)
    finally:
        con.close()
    calculate_month.cache_clear()
    return {"removed": removed}
