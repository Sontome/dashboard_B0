const state = { data: null, report: [], roll: [], filtered: [], rollFiltered: [], contractPage: 1, rollPage: 1, pageSize: 75 };
const $ = (selector) => document.querySelector(selector);
const fmt = (number) => new Intl.NumberFormat("vi-VN").format(number || 0);
const date = (value) => value ? new Date(value + "T00:00:00").toLocaleDateString("vi-VN") : "";
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

async function init() {
  const response = await fetch("/api/months");
  const { months } = await response.json();
  $("#monthSelect").innerHTML = months.map((month) => `<option value="${month}">Tháng ${month.slice(5)}/${month.slice(0, 4)}</option>`).join("");
  if (months.length) await load(months[0]); else $("#loading").classList.add("hidden");
}

async function load(month) {
  $("#loading").classList.remove("hidden");
  try {
    const response = await fetch(`/api/dashboard?month=${month}`);
    if (!response.ok) throw new Error(await response.text());
    state.data = await response.json();
    state.report = state.data.report;
    state.roll = state.data.roll_b1;
    hydrate();
  } catch (error) {
    alert("Không tải được báo cáo: " + error.message);
  } finally {
    $("#loading").classList.add("hidden");
  }
}

function hydrate() {
  const data = state.data;
  const summary = data.summary;
  $("#liveDate").textContent = "CHỐT " + date(data.latest_date);
  const percentOfB0 = (value) => summary.b0 ? (value / summary.b0 * 100).toLocaleString("vi-VN", {minimumFractionDigits: 1, maximumFractionDigits: 1}) + "% trên tổng B0" : "0,0% trên tổng B0";
  const cards = [
    ["Hợp đồng B0", summary.b0, ""], ["Hợp đồng B1", summary.b1, ""],
    ["Đã thanh toán", summary.paid, ""], ["Đúng hạn", summary.on_time, percentOfB0(summary.on_time)],
    ["Roll B1", summary.roll_b1, percentOfB0(summary.roll_b1)], ["Tổng dư nợ", fmt(summary.outstanding) + " ₫", ""]
  ];
  $("#metrics").innerHTML = cards.map(([label, value, note]) => `<div class="metric"><span>${label}</span><strong>${typeof value === "number" ? fmt(value) : value}</strong>${note ? `<small>${note}</small>` : ""}</div>`).join("");

  const statuses = [...new Set(data.report.map((row) => row.status))].sort();
  $("#statusFilter").innerHTML = `<option value="attention">Chưa thanh toán & quá hạn</option><option value="">Tất cả trạng thái</option>` + statuses.map((status) => `<option value="${esc(status)}">${esc(status)}</option>`).join("");
  $("#rollStatusFilter").innerHTML = `<option value="">Tất cả trạng thái</option>` + [...new Set(data.roll_b1.map((row) => row.status))].sort().map((status) => `<option value="${esc(status)}">${esc(status)}</option>`).join("");
  const dates = [...new Set(data.report.map((row) => row.due_date).filter(Boolean))].sort();
  $("#dateFilter").innerHTML = `<option value="">Tất cả ngày phải đóng</option>` + dates.map((value) => `<option value="${value}">${date(value)}</option>`).join("");
  drawTrend(); renderDaily(); applyFilters(); applyRollFilter();
}

function applyFilters() {
  const query = $("#search").value.toLowerCase().trim();
  const status = $("#statusFilter").value;
  const dueDate = $("#dateFilter").value;
  state.filtered = state.report.filter((row) => {
    const matchesQuery = !query || `${row.contract_id} ${row.customer_name}`.toLowerCase().includes(query);
    const matchesStatus = !status || (status === "attention" ? row.status === "Chưa thanh toán" || row.status.endsWith("quá hạn") : row.status === status);
    return matchesQuery && matchesStatus && (!dueDate || row.due_date === dueDate);
  }).sort((a, b) => (a.due_date || "9999").localeCompare(b.due_date || "9999"));
  state.contractPage = 1;
  renderContracts();
}

function applyRollFilter() {
  const status = $("#rollStatusFilter").value;
  state.rollFiltered = state.roll.filter((row) => !status || row.status === status);
  state.rollPage = 1;
  renderRoll();
}

function badge(status) {
  const className = status.includes("quá hạn") ? "late" : status === "Chưa thanh toán" ? "unpaid" : "";
  return `<span class="status ${className}">${esc(status)}</span>`;
}

function renderContracts() {
  const rows = page(state.filtered, state.contractPage);
  $("#contractRows").innerHTML = rows.map((row) => `<tr><td><b>${esc(row.contract_id)}</b></td><td>${esc(row.customer_name)}</td><td>${esc(row.province)}</td><td>${badge(row.status)}</td><td>${date(row.due_date)}</td><td>${date(row.payment_date)}</td><td>${row.paid_dpd ?? ""}</td><td>${row.current_dpd ?? ""}</td><td>${fmt(row.outstanding)}</td></tr>`).join("");
  $("#contractCount").textContent = `${fmt(state.filtered.length)} kết quả`;
  pager("#contractPager", state.filtered.length, state.contractPage, (number) => { state.contractPage = number; renderContracts(); });
}

function renderRoll() {
  const rows = page(state.rollFiltered, state.rollPage);
  $("#rollRows").innerHTML = rows.map((row) => `<tr><td><b>${esc(row.contract_id)}</b></td><td>${esc(row.customer_name)}</td><td>${esc(row.province)}</td><td>${date(row.due_date)}</td><td><b>${row.max_dpd ?? ""}</b></td><td>${badge(row.status)}</td><td>${fmt(row.outstanding)}</td></tr>`).join("");
  $("#rollCount").textContent = `${fmt(state.rollFiltered.length)} hợp đồng Roll B1`;
  pager("#rollPager", state.rollFiltered.length, state.rollPage, (number) => { state.rollPage = number; renderRoll(); });
}

function renderDaily() {
  $("#dailyRows").innerHTML = state.data.daily_on_time.map((row) => `<tr><td><b>${date(row.due_date)}</b></td><td>${fmt(row.total_due)}</td><td>${fmt(row.paid_on_time)}</td><td><div class="rate-bar"><div class="rate-track"><div class="rate-fill" style="width:${row.rate}%"></div></div><b>${row.rate}%</b></div></td></tr>`).join("");
}

function page(rows, number) { return rows.slice((number - 1) * state.pageSize, number * state.pageSize); }
function pager(selector, total, current, go) {
  const pages = Math.max(1, Math.ceil(total / state.pageSize));
  $(selector).innerHTML = `<button ${current <= 1 ? "disabled" : ""}>‹</button><span>Trang ${current}/${pages}</span><button ${current >= pages ? "disabled" : ""}>›</button>`;
  const buttons = $(selector).querySelectorAll("button");
  buttons[0].onclick = () => go(current - 1); buttons[1].onclick = () => go(current + 1);
}

function drawTrend() {
  const data = state.data.trend, dates = [...new Set(data.map((row) => row.snapshot_date))].sort();
  const colors = { B0: "#339476", B1: "#e89835", "B2+": "#c95852" }, width = 1000, height = 200, padding = 25;
  const maximum = Math.max(...data.map((row) => row.count), 1); let paths = "";
  for (const bucket of ["B0", "B1", "B2+"]) {
    const values = Object.fromEntries(data.filter((row) => row.bucket === bucket).map((row) => [row.snapshot_date, row.count]));
    const points = dates.map((day, index) => `${padding + index * (width - 2 * padding) / Math.max(dates.length - 1, 1)},${height - padding - (values[day] || 0) * (height - 2 * padding) / maximum}`).join(" ");
    paths += `<polyline points="${points}" fill="none" stroke="${colors[bucket]}" stroke-width="3"/>`;
  }
  const labels = dates.map((value) => `<span>${value.slice(8,10)}/${value.slice(5,7)}</span>`).join("");
  $("#trendChart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><line x1="${padding}" y1="${height-padding}" x2="${width-padding}" y2="${height-padding}" stroke="#dfe7e1"/>${paths}</svg><div class="x-axis">${labels}</div>`;
  $("#legend").innerHTML = Object.entries(colors).map(([label, color]) => `<span><i style="background:${color}"></i>${label}</span>`).join("");
}

function csv(rows, name) {
  const columns = ["contract_id","customer_name","province","status","due_date","payment_date","paid_dpd","max_dpd","current_dpd","outstanding"];
  const quote = (value) => `"${String(value ?? "").replaceAll('"','""')}"`;
  const body = "\ufeff" + [columns.join(","), ...rows.map((row) => columns.map((column) => quote(row[column])).join(","))].join("\n");
  const anchor = document.createElement("a"); anchor.href = URL.createObjectURL(new Blob([body], {type:"text/csv"})); anchor.download = name; anchor.click(); URL.revokeObjectURL(anchor.href);
}

$("#monthSelect").onchange = (event) => load(event.target.value);
$("#refreshBtn").onclick = () => load($("#monthSelect").value);
$("#search").oninput = applyFilters; $("#statusFilter").onchange = applyFilters; $("#dateFilter").onchange = applyFilters;
$("#rollStatusFilter").onchange = applyRollFilter;
$("#exportContracts").onclick = () => csv(state.filtered, `hop-dong-${$("#monthSelect").value}.csv`);
$("#exportRoll").onclick = () => csv(state.rollFiltered, `roll-b1-${$("#monthSelect").value}.csv`);
$("#uploadBtn").onclick = async () => { const files = $("#fileInput").files; if (!files.length) return alert("Hãy chọn file Excel"); const form = new FormData(); [...files].forEach((file) => form.append("files", file)); $("#uploadMessage").textContent = "Đang nhập dữ liệu…"; const response = await fetch("/api/import", {method:"POST", body:form}); const result = await response.json(); $("#uploadMessage").textContent = `Đã nhập ${fmt(result.imported)} dòng${result.errors.length ? " • " + result.errors.join("; ") : ""}`; await init(); };
$("#resetBtn").onclick = async () => { const month = $("#monthSelect").value; if (!month || !confirm(`Reset toàn bộ dữ liệu tháng ${month}?`)) return; const response = await fetch(`/api/month/${month}`, {method:"DELETE"}); const result = await response.json(); alert(`Đã xóa ${fmt(result.removed)} dòng`); location.reload(); };

init();
