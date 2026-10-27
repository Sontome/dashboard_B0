from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from core import archive_file, build_contract_report, connect, import_many, load_snapshots, read_snapshot, reset_month, upsert_snapshot


ROOT = Path(__file__).parent
DB = ROOT / "data" / "dashboard.db"
MONTHS_DIR = ROOT / "data" / "months"
st.set_page_config(page_title="B0 Pulse", page_icon="◉", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&display=swap');
html, body, [class*="css"] {font-family: 'Manrope', sans-serif}
.stApp {background: #f5f7f4; color:#17322d}
[data-testid="stSidebar"] {background:#123b35}
[data-testid="stSidebar"] * {color:#f4fbf7!important}
[data-testid="stHeader"], header[data-testid="stHeader"], #MainMenu, footer {display:none!important}
.stApp > header {display:none!important}
.hero {padding:24px 28px;border-radius:20px;background:linear-gradient(120deg,#103d36,#1d6a57);color:white;margin-bottom:20px}
.hero h1{margin:0;font-size:32px}.hero p{opacity:.8;margin:7px 0 0}
[data-testid="stMetric"] {background:white;border:1px solid #e0e8e3;padding:16px;border-radius:16px;box-shadow:0 4px 16px #17322d0c}
.badge {display:inline-block;padding:5px 10px;background:#dff3e9;color:#176349;border-radius:99px;font-size:12px;font-weight:700}
.block-container {padding-top:2rem;max-width:1450px}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def db():
    return connect(DB)


@st.cache_resource(show_spinner=False)
def cached_snapshots(db_version: int):
    del db_version
    local_con = connect(DB)
    try:
        return load_snapshots(local_con)
    finally:
        local_con.close()


@st.cache_resource(show_spinner="Đang tính báo cáo tháng…")
def cached_month_data(month: str, db_version: int):
    all_rows = cached_snapshots(db_version)
    rows = all_rows[all_rows.snapshot_date.dt.strftime("%Y-%m").eq(month)].copy()
    if rows.empty:
        return rows, rows, pd.DataFrame()
    first = rows.sort_values("snapshot_date").groupby("contract_id", as_index=False).first()
    b0_ids = first.loc[first.dpd.le(0), "contract_id"]
    cohort = rows[rows.contract_id.isin(b0_ids)].copy()
    return rows, cohort, build_contract_report(cohort)


def money(v):
    return f"{v:,.0f} ₫".replace(",", ".")


def display_table(df):
    shown = df.copy()
    rename = {"contract_id":"Mã hợp đồng", "customer_name":"Khách hàng", "province":"Tỉnh/TP",
              "initial_bucket":"Nhóm đầu", "current_bucket":"Nhóm hiện tại", "status":"Trạng thái",
              "due_date":"Ngày phải đóng", "payment_date":"Ngày thanh toán", "paid_dpd":"DPD khi trả",
              "max_dpd":"DPD cao nhất", "current_dpd":"DPD hiện tại", "outstanding":"Dư nợ"}
    cols = [c for c in rename if c in shown]
    shown = shown[cols].rename(columns=rename)
    st.dataframe(shown, width="stretch", hide_index=True,
                 column_config={"Dư nợ": st.column_config.NumberColumn(format="%,.0f ₫"),
                                "Ngày phải đóng": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                "Ngày thanh toán": st.column_config.DateColumn(format="DD/MM/YYYY")})


con = db()
db_version = DB.stat().st_mtime_ns if DB.exists() else 0
snapshots = cached_snapshots(db_version)
available_months = sorted(snapshots.snapshot_date.dt.strftime("%Y-%m").unique(), reverse=True) if not snapshots.empty else []

with st.sidebar:
    st.markdown("## ◉ B0 PULSE")
    st.caption("Theo dõi thu hồi B0 / B1")
    st.markdown("---")
    page = st.radio("Điều hướng", ["Tổng quan", "Danh sách hợp đồng", "Nhập dữ liệu"], label_visibility="collapsed")
    selected_month = st.selectbox(
        "Tháng báo cáo",
        available_months,
        format_func=lambda value: pd.Timestamp(value + "-01").strftime("Tháng %m/%Y"),
    ) if available_months else None
    st.markdown("---")
    if not snapshots.empty:
        month_snapshots = snapshots[snapshots.snapshot_date.dt.strftime("%Y-%m").eq(selected_month)]
        st.caption(f"Dữ liệu mới nhất: {month_snapshots.snapshot_date.max():%d/%m/%Y}")
        st.caption(f"{month_snapshots.snapshot_date.nunique()} ngày • {month_snapshots.contract_id.nunique():,} hợp đồng")

month_snapshots, cohort_snapshots, report = cached_month_data(selected_month, db_version) if selected_month else (snapshots.iloc[0:0], snapshots.iloc[0:0], pd.DataFrame())

if page == "Nhập dữ liệu":
    st.markdown('<div class="hero"><span class="badge">DATA INBOX</span><h1>Thêm dữ liệu theo ngày</h1><p>Tải một hoặc nhiều file 01.10.xlsx, 02.10.xlsx… Hệ thống tự cập nhật nếu ngày đã tồn tại.</p></div>', unsafe_allow_html=True)
    uploads = st.file_uploader("Chọn file Excel", type=["xlsx"], accept_multiple_files=True)
    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("Nhập file đã chọn", type="primary", width="stretch", disabled=not uploads):
            count, errors = import_many(con, [(f.name, f.getvalue()) for f in uploads], MONTHS_DIR)
            if count:
                st.success(f"Đã nhập/cập nhật {count:,} dòng.")
            for error in errors:
                st.error(error)
            cached_snapshots.clear()
            cached_month_data.clear()
            st.rerun()
    with c2:
        local = sorted(ROOT.glob("[0-9][0-9].[0-9][0-9].xlsx"))
        if st.button(f"Nhập {len(local)} file ngày trong thư mục", width="stretch", disabled=not local):
            count = 0
            progress = st.progress(0)
            for i, path in enumerate(local):
                content = path.read_bytes()
                frame = read_snapshot(path)
                count += upsert_snapshot(con, frame)
                archive_file(path.name, content, frame, MONTHS_DIR)
                progress.progress((i + 1) / len(local))
            st.success(f"Đã nhập/cập nhật {count:,} dòng từ {len(local)} file.")
            cached_snapshots.clear()
            cached_month_data.clear()
            st.rerun()
    st.info("Quy tắc: nếu DPD hôm trước là 3 và hôm sau về âm, hệ thống ghi nhận thanh toán quá hạn tại DPD 3. File cùng ngày được nhập lại sẽ thay thế dữ liệu cũ của ngày đó.")
    if not snapshots.empty:
        st.markdown("---")
        st.subheader("Reset dữ liệu tháng")
        st.warning("Reset chỉ xóa dữ liệu và file lưu trữ của tháng đang chọn; các tháng khác được giữ nguyên.")
        confirm_reset = st.checkbox(f"Tôi xác nhận reset tháng {selected_month}")
        if st.button("Reset tháng đang chọn", disabled=not confirm_reset):
            removed = reset_month(con, selected_month, MONTHS_DIR)
            st.success(f"Đã xóa {removed:,} dòng của tháng {selected_month}. Bạn có thể nhập lại toàn bộ file tháng này.")
            cached_snapshots.clear()
            cached_month_data.clear()
            st.rerun()
        history = month_snapshots.groupby(["snapshot_date", "source_file"]).size().reset_index(name="Số dòng").sort_values("snapshot_date", ascending=False)
        st.subheader("Lịch sử dữ liệu")
        st.dataframe(history.rename(columns={"snapshot_date":"Ngày chốt", "source_file":"Tên file"}), width="stretch", hide_index=True)

elif snapshots.empty:
    st.markdown('<div class="hero"><h1>B0 Pulse</h1><p>Dashboard theo dõi hợp đồng B0 / B1</p></div>', unsafe_allow_html=True)
    st.warning("Chưa có dữ liệu. Mở mục “Nhập dữ liệu” để bắt đầu.")

else:
    latest_date = month_snapshots.snapshot_date.max()
    latest = cohort_snapshots[cohort_snapshots.snapshot_date.eq(latest_date)].copy()
    latest["bucket"] = latest.dpd.apply(lambda x: "B0" if x <= 0 else "B1" if x <= 30 else "B2+")
    paid = report[report.status.str.startswith("Đã")]
    if page == "Tổng quan":
        st.markdown(f'<div class="hero"><span class="badge">LIVE • {latest_date:%d/%m/%Y}</span><h1>Tổng quan thu hồi B0 / B1</h1><p>Bức tranh hiện tại và hiệu quả thanh toán trong toàn bộ kỳ dữ liệu.</p></div>', unsafe_allow_html=True)
        b0 = int((latest.bucket == "B0").sum()); b1 = int((latest.bucket == "B1").sum())
        ontime = int(paid.status.str.endswith("đúng hạn").sum()); late = int(paid.status.str.endswith("quá hạn").sum())
        cols = st.columns(5)
        for col, label, value, hint in zip(cols, ["Hợp đồng B0", "Hợp đồng B1", "Đã thanh toán", "Đúng hạn", "Tổng dư nợ"],
                [b0, b1, len(paid), ontime, money(latest.outstanding.sum())],
                ["DPD ≤ 0", "DPD 1–30", f"{late:,} quá hạn", f"{ontime/max(len(paid),1):.1%} tỷ lệ", "Tại ngày mới nhất"]):
            col.metric(label, f"{value:,}" if isinstance(value, int) else value, hint)
        left, right = st.columns([1.3, 1])
        with left:
            st.subheader("Xu hướng B0 / B1")
            trend = cohort_snapshots.assign(bucket=cohort_snapshots.dpd.apply(lambda x: "B0" if x <= 0 else "B1" if x <= 30 else "B2+"))
            trend = trend.groupby(["snapshot_date", "bucket"]).size().reset_index(name="Hợp đồng")
            fig = px.area(trend, x="snapshot_date", y="Hợp đồng", color="bucket", color_discrete_map={"B0":"#2e8b70","B1":"#f0a23b","B2+":"#cf554f"})
            fig.update_layout(margin=dict(l=0,r=0,t=10,b=0), legend_title="", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch")
        with right:
            st.subheader("Kết quả thanh toán")
            counts = report.status.value_counts().rename_axis("Trạng thái").reset_index(name="Hợp đồng")
            fig = px.pie(counts, names="Trạng thái", values="Hợp đồng", hole=.62, color="Trạng thái",
                         color_discrete_map={"Đã trả đúng hạn":"#2e8b70","Đã trả quá hạn":"#f0a23b","Chưa đến hạn":"#8ebaae","Chưa thanh toán":"#cf554f"})
            fig.update_layout(margin=dict(l=0,r=0,t=10,b=0), legend=dict(orientation="h"), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch")
        st.subheader("Cần chú ý hôm nay")
        risk = report[(report.status == "Chưa thanh toán") & (report.current_dpd >= 0)].head(12)
        display_table(risk)
    else:
        st.markdown('<div class="hero"><span class="badge">CONTRACT EXPLORER</span><h1>Danh sách hợp đồng</h1><p>Lọc, tra cứu và xuất báo cáo chi tiết.</p></div>', unsafe_allow_html=True)
        a, b, c = st.columns([1.4, 1, 1])
        query = a.text_input("Tìm mã TC / tên khách hàng")
        status_options = sorted(report.status.unique())
        status_default = [x for x in ["Chưa thanh toán", "Đã trả quá hạn", "Đã tất toán quá hạn"] if x in status_options]
        statuses = b.multiselect("Trạng thái", status_options, default=status_default)
        due_options = sorted(d for d in report.due_date.dropna().dt.date.unique())
        selected_dates = c.multiselect("Ngày phải đóng", due_options, default=[], format_func=lambda d: d.strftime("%d/%m/%Y"))
        filtered = report[report.status.isin(statuses)]
        if selected_dates:
            filtered = filtered[filtered.due_date.dt.date.isin(selected_dates)]
        if query:
            mask = filtered.contract_id.str.contains(query, case=False, na=False) | filtered.customer_name.str.contains(query, case=False, na=False)
            filtered = filtered[mask]
        filtered = filtered.sort_values(["due_date", "current_dpd", "contract_id"], ascending=[True, False, True], na_position="last")
        st.caption(f"{len(filtered):,} kết quả")
        display_table(filtered)
        st.download_button("Tải báo cáo CSV", filtered.to_csv(index=False).encode("utf-8-sig"), "bao-cao-b0-b1.csv", "text/csv")
