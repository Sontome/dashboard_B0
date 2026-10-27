from __future__ import annotations

import io
import re
import sqlite3
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pandas as pd


COLS = {
    "Ngày chốt": "snapshot_date",
    "Mã hợp đồng sau giải ngân": "contract_id",
    "Họ Tên KH": "customer_name",
    "Ngày phải đóng tiền": "due_date",
    "Ngày trễ (DPD)": "dpd",
    "Nhóm nợ": "source_bucket",
    "Dư nợ đang cho vay": "outstanding",
    "Tỉnh thành đơn vay": "province",
    "Quận huyện đơn vay": "district",
}
REQUIRED = {"Ngày chốt", "Mã hợp đồng sau giải ngân", "Ngày phải đóng tiền", "Ngày trễ (DPD)"}


def excel_date(value) -> pd.Timestamp | pd.NaT:
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).normalize()
    try:
        number = float(value)
        if 20_000 < number < 80_000:
            return pd.Timestamp("1899-12-30") + pd.to_timedelta(number, unit="D")
    except (TypeError, ValueError):
        pass
    return pd.to_datetime(value, dayfirst=True, errors="coerce").normalize()


def date_from_filename(name: str, year: int | None = None) -> pd.Timestamp | pd.NaT:
    match = re.search(r"(?<!\d)(\d{1,2})[.\-_](\d{1,2})(?:[.\-_](\d{2,4}))?", name)
    if not match:
        return pd.NaT
    day, month, found_year = match.groups()
    y = int(found_year) if found_year else (year or datetime.now().year)
    if y < 100:
        y += 2000
    try:
        return pd.Timestamp(y, int(month), int(day))
    except ValueError:
        return pd.NaT


def read_snapshot(file: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    name = filename or getattr(file, "name", "upload.xlsx")
    raw = pd.read_excel(file, sheet_name=0, engine="openpyxl")
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = REQUIRED - set(raw.columns)
    if missing:
        raise ValueError("Thiếu cột bắt buộc: " + ", ".join(sorted(missing)))
    keep = [c for c in COLS if c in raw.columns]
    df = raw[keep].rename(columns=COLS).copy()
    df["contract_id"] = df["contract_id"].astype("string").str.strip().str.upper()
    df = df[df["contract_id"].str.match(r"^TC-", na=False)]
    df["snapshot_date"] = df["snapshot_date"].map(excel_date)
    fallback = date_from_filename(name)
    if df["snapshot_date"].isna().all() and pd.notna(fallback):
        df["snapshot_date"] = fallback
    df["due_date"] = df["due_date"].map(excel_date)
    df["dpd"] = pd.to_numeric(df["dpd"], errors="coerce")
    if "outstanding" in df:
        df["outstanding"] = pd.to_numeric(df["outstanding"], errors="coerce").fillna(0)
    for col in ("customer_name", "source_bucket", "province", "district"):
        if col not in df:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    if df["snapshot_date"].isna().any():
        raise ValueError("Không xác định được Ngày chốt trong một số dòng")
    df["source_file"] = name
    return df.drop_duplicates(["snapshot_date", "contract_id"], keep="last")


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Streamlit may rerun one session on a different worker thread. The
    # connection is cached by the UI, so allow that connection to follow the
    # session instead of tying it to the thread that first created it.
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
        snapshot_date TEXT NOT NULL, contract_id TEXT NOT NULL,
        customer_name TEXT, due_date TEXT, dpd REAL, source_bucket TEXT,
        outstanding REAL, province TEXT, district TEXT, source_file TEXT,
        imported_at TEXT NOT NULL,
        PRIMARY KEY(snapshot_date, contract_id)
        )"""
    )
    return con


def upsert_snapshot(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = df.copy()
    rows["snapshot_date"] = rows["snapshot_date"].dt.strftime("%Y-%m-%d")
    rows["due_date"] = rows["due_date"].dt.strftime("%Y-%m-%d")
    rows["imported_at"] = datetime.now().isoformat(timespec="seconds")
    columns = ["snapshot_date", "contract_id", "customer_name", "due_date", "dpd",
               "source_bucket", "outstanding", "province", "district", "source_file", "imported_at"]
    rows = rows.reindex(columns=columns)
    sql = f"INSERT OR REPLACE INTO snapshots ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    con.executemany(sql, rows.where(pd.notna(rows), None).itertuples(index=False, name=None))
    con.commit()
    return len(rows)


def load_snapshots(con: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM snapshots ORDER BY snapshot_date, contract_id", con)
    if df.empty:
        return df
    for col in ("snapshot_date", "due_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["dpd"] = pd.to_numeric(df["dpd"], errors="coerce")
    df["outstanding"] = pd.to_numeric(df["outstanding"], errors="coerce").fillna(0)
    return df


def bucket(dpd) -> str:
    if pd.isna(dpd):
        return "Không rõ"
    return "B0" if float(dpd) <= 0 else "B1" if float(dpd) <= 30 else "B2+"


def build_contract_report(snapshots: pd.DataFrame) -> pd.DataFrame:
    """One result per contract for its first observed B0 obligation in the period."""
    if snapshots.empty:
        return pd.DataFrame()
    records: list[dict] = []
    final_snapshot_date = snapshots["snapshot_date"].max()
    for contract, group in snapshots.sort_values(["contract_id", "snapshot_date"]).groupby("contract_id"):
        g = group.reset_index(drop=True)
        paid_record = None
        for i in range(1, len(g)):
            prev, curr = g.iloc[i - 1], g.iloc[i]
            due_advanced = pd.notna(prev.due_date) and pd.notna(curr.due_date) and curr.due_date > prev.due_date
            sign_reset = pd.notna(prev.dpd) and pd.notna(curr.dpd) and prev.dpd >= 0 and curr.dpd < 0
            if due_advanced or sign_reset:
                paid_record = _cycle_record(g.iloc[:i], paid=True, paid_row=prev, detected_on=curr.snapshot_date)
                break
        if paid_record is not None:
            records.append(paid_record)
        elif g.iloc[-1].snapshot_date < final_snapshot_date:
            # The contract is absent from a later raw snapshot: treat its last
            # observed B0 obligation as settled/closed at that last DPD.
            records.append(_cycle_record(g, paid=True, paid_row=g.iloc[-1],
                                         detected_on=_next_snapshot(snapshots, g.iloc[-1].snapshot_date),
                                         settled=True))
        else:
            records.append(_cycle_record(g, paid=False))
    return pd.DataFrame(records).sort_values(["status", "current_dpd", "contract_id"], ascending=[True, False, True])


def _next_snapshot(snapshots: pd.DataFrame, after: pd.Timestamp):
    later = snapshots.loc[snapshots.snapshot_date.gt(after), "snapshot_date"]
    return later.min() if not later.empty else pd.NaT


def _cycle_record(segment: pd.DataFrame, paid: bool, paid_row=None, detected_on=None, settled: bool = False) -> dict:
    first, last = segment.iloc[0], segment.iloc[-1]
    dpds = segment["dpd"].dropna()
    paid_dpd = float(paid_row.dpd) if paid and pd.notna(paid_row.dpd) else None
    current_dpd = float(last.dpd) if pd.notna(last.dpd) else None
    if paid:
        if settled:
            status = "Đã tất toán đúng hạn" if paid_dpd is not None and paid_dpd <= 0 else "Đã tất toán quá hạn"
        else:
            status = "Đã trả đúng hạn" if paid_dpd is not None and paid_dpd <= 0 else "Đã trả quá hạn"
    else:
        status = "Chưa đến hạn" if current_dpd is not None and current_dpd < 0 else "Chưa thanh toán"
    initial_dpd = float(first.dpd) if pd.notna(first.dpd) else None
    return {
        "contract_id": last.contract_id,
        "customer_name": last.customer_name,
        "province": last.province,
        "district": last.district,
        "initial_bucket": bucket(initial_dpd),
        "current_bucket": bucket(current_dpd),
        "status": status,
        "first_seen": first.snapshot_date,
        "last_seen": last.snapshot_date,
        "due_date": first.due_date,
        "payment_date": paid_row.snapshot_date if paid else pd.NaT,
        "detected_on": detected_on if paid else pd.NaT,
        "paid_dpd": paid_dpd,
        "max_dpd": float(dpds.max()) if not dpds.empty else None,
        "current_dpd": current_dpd,
        "outstanding": float(last.outstanding or 0),
    }


def archive_file(name: str, content: bytes, df: pd.DataFrame, archive_root: str | Path) -> Path:
    month = df["snapshot_date"].iloc[0].strftime("%Y-%m")
    folder = Path(archive_root) / month
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / Path(name).name
    destination.write_bytes(content)
    return destination


def import_many(con: sqlite3.Connection, files: list[tuple[str, bytes]], archive_root: str | Path | None = None) -> tuple[int, list[str]]:
    total, errors = 0, []
    for name, content in files:
        try:
            df = read_snapshot(io.BytesIO(content), name)
            total += upsert_snapshot(con, df)
            if archive_root:
                archive_file(name, content, df, archive_root)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return total, errors


def reset_month(con: sqlite3.Connection, month: str, archive_root: str | Path | None = None) -> int:
    """Delete one YYYY-MM reporting period and only its matching archive folder."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Tháng không hợp lệ")
    count = con.execute("SELECT COUNT(*) FROM snapshots WHERE substr(snapshot_date, 1, 7) = ?", (month,)).fetchone()[0]
    con.execute("DELETE FROM snapshots WHERE substr(snapshot_date, 1, 7) = ?", (month,))
    con.commit()
    if archive_root:
        root = Path(archive_root).resolve()
        target = (root / month).resolve()
        if target.parent == root and target.name == month and target.exists():
            shutil.rmtree(target)
    return int(count)
