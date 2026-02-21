# 員工線上打卡紀錄程式

這是一個使用 Python 標準函式庫實作的簡易員工出勤打卡系統，支援：

- 上班打卡 / 下班打卡
- 首頁顯示最近 50 筆打卡紀錄
- API 查詢所有紀錄 (`/api/records`)
- 使用 SQLite 儲存資料

## 啟動方式

```bash
python app.py
```

開啟瀏覽器：`http://127.0.0.1:5000`

## API 範例

```bash
curl -X POST http://127.0.0.1:5000/clock \
  -d "employee_id=E001" \
  -d "employee_name=王小明" \
  -d "event_type=check-in"

curl http://127.0.0.1:5000/api/records
```
