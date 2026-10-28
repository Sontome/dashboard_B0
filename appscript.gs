function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Cập Nhật') // tên menu hiển thị trên thanh
    .addItem('Refresh', 'mergeSheetsFiltered') // nút gọi function
    .addToUi();
}
function markExistingSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const config = ss.getSheetByName("Config");
  if (!config) return;

  const sheetNames = ss.getSheets().map(s => s.getName()); // danh sách tên sheet hiện có
  const days = config.getRange("B2:B32").getValues();      // cột B2:B32 chứa số ngày
  const output = [];

  days.forEach(day => {
    const dayValue = day[0];
    if (dayValue && sheetNames.includes(dayValue.toString())) {
      output.push(["X"]); // tồn tại sheet → đánh dấu X
    } else {
      output.push([""]);  // không tồn tại → để trống
    }
  });

  // Ghi kết quả ra cột C2:C32
  config.getRange(2, 3, output.length, 1).setValues(output);
}
function mergeSheetsFiltered() {
  markExistingSheets();
  
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const config = ss.getSheetByName("Config");
  const target = ss.getSheetByName("Tổng hợp");
  target.clearContents();
  if (!config || !target) return;

  const sheetStatus = config.getRange("B2:C32").getValues(); // B = ngày, C = X hay trống
  const merged = [];

  sheetStatus.forEach(row => {
    const day = row[0];
    const mark = row[1];
    if (mark === "X") {
      const sheetName = day.toString();
      const sheet = ss.getSheetByName(sheetName);
      if (sheet) {
        const lastRow = sheet.getLastRow();
        if (lastRow >= 2) { // nếu có dữ liệu từ hàng 2 trở đi
          const data = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();

          // Lọc cột O (index 14 trong A:O) = "B0" hoặc "B1"
          const filtered = data.filter(r =>
            (r[14] === "B0" || r[14] === "B1") 
          );

          // Chỉ lấy cột A, E, O (index 0, 4, 14)
          filtered.forEach(r => merged.push([r[0], r[4],r[13], r[14],r[12],r[35]]));
        }
      }
    }
  });

  // Xóa dữ liệu cũ và ghi dữ liệu mới
  
  if (merged.length > 0) {
    target.getRange(1, 1, merged.length, merged[0].length).setValues(merged);
  }
}