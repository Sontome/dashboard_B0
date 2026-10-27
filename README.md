# B0 Pulse — Dashboard hợp đồng B0/B1

Ứng dụng FastAPI với giao diện HTML/JavaScript thay thế báo cáo Google Sheets khi dữ liệu ngày đã lớn. Bộ lọc và phân trang chạy trên trình duyệt nên không làm Python chạy lại sau mỗi thao tác.

## Chạy ứng dụng

```powershell
python -m pip install -r requirements.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8501
```

Mở `http://localhost:8501`. Chọn một hoặc nhiều file dạng `01.10.xlsx` tại thanh bên để thêm dữ liệu.

Trên Windows cũng có thể nhấp đúp `run_dashboard.bat`.

## Đóng gói EXE

Chạy `build_exe.bat`. File hoàn chỉnh nằm tại `dist/B0Pulse.exe`. Khi mở EXE, FastAPI tự chạy ở cổng 8501 và trình duyệt tự mở. Thư mục `data` được tạo/đọc cạnh file EXE để dữ liệu không mất khi nâng cấp chương trình.

Dashboard chỉ tính báo cáo một lần khi mở tháng. Sau đó việc tìm kiếm, lọc ngày, lọc trạng thái, phân trang và xuất CSV đều diễn ra ngay trên trình duyệt. Bảng **Roll B1** gồm các hợp đồng khởi đầu B0 nhưng có DPD cao nhất trong tháng lớn hơn 0.

Bảng **Tỷ lệ thanh toán B0 đúng ngày** thống kê theo ngày phải đóng đã đến hạn: số TC có `DPD tại thanh toán = 0`, tổng TC đến hạn và tỷ lệ phần trăm.

## Quy tắc nghiệp vụ chính

- `DPD < 0`: chưa tới hạn; `DPD = 0`: tới hạn; `DPD > 0`: quá hạn.
- B0 là `DPD <= 0`, B1 là `1–30`, B2+ là trên 30.
- Báo cáo chỉ theo dõi cohort hợp đồng có DPD ở lần xuất hiện đầu tiên trong tháng thuộc B0.
- Một chu kỳ được xem là đã thanh toán khi ngày phải đóng chuyển sang kỳ kế tiếp, hoặc DPD từ không âm chuyển về âm.
- DPD thanh toán lấy ở snapshot ngay trước lúc reset. Ví dụ `3 → -27` được ghi là **đã trả quá hạn, DPD 3**.
- Nếu mã TC không còn trong một raw ngày sau, hệ thống ghi nhận đã tất toán tại DPD của ngày cuối cùng mã đó còn xuất hiện.
- Mỗi mã TC chỉ có một kết quả cho nghĩa vụ B0 đầu tiên trong tháng; kỳ mới sau khi đã đóng tiền không sinh thêm dòng “chưa đến hạn”.
- Dữ liệu lưu trong `data/dashboard.db`; nhập lại cùng ngày và cùng mã hợp đồng sẽ cập nhật bản ghi, không nhân đôi.
- File nguồn được lưu theo thư mục `data/months/YYYY-MM`; có thể chọn tháng cũ trên thanh bên để xem lại.
- Nút reset chỉ xóa tháng đang chọn để nhập lại và tính lại, không ảnh hưởng các tháng khác.

Lưu ý: hợp đồng biến mất khỏi file ngày sau không tự động được coi là đã thanh toán, vì cũng có thể là tất toán, chuyển nhóm hoặc thiếu dữ liệu nguồn.
