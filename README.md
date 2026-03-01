# 員工線上打卡紀錄程式

## 功能

- 員工 / 管理員雙身分登入
- 只有管理員可：
  - 編輯使用者資訊
  - 修改打卡紀錄
  - 下載打卡紀錄（Excel `.xls`）
- 管理員每次修改打卡紀錄都會寫入稽核紀錄
- 員工可打卡、查詢自己的打卡紀錄
- 首頁顯示大字即時日期時間（每秒更新）

## 預設管理員

- 帳號：`ADMIN`
- 密碼：`admin123`

> 上線前請改為安全密碼（本專案為示範版本）

## 啟動
這是一個使用 Python 標準函式庫實作的簡易員工出勤打卡系統，支援：

- 上班打卡 / 下班打卡
- 首頁顯示最近 50 筆打卡紀錄
- API 查詢所有紀錄 (`/api/records`)
- 使用 SQLite 儲存資料

## 啟動方式

```bash
python app.py
```

瀏覽器開啟：`http://127.0.0.1:5000/login`

## 測試重點

1. 先用管理員登入，檢查可看到「管理員功能區」
2. 編輯使用者資訊（`/admin/user/update`）
3. 修改打卡紀錄（`/admin/attendance/update`），確認稽核紀錄有新增
4. 下載 Excel（`/export.xls`）
5. 用員工登入，確認無法使用管理員端點
開啟瀏覽器：`http://127.0.0.1:5000`

## API 範例

```bash
curl -X POST http://127.0.0.1:5000/clock \
  -d "employee_id=E001" \
  -d "employee_name=王小明" \
  -d "event_type=check-in"

curl http://127.0.0.1:5000/api/records
```
