# 雲端餐飲 POS 系統（手機點餐 + 即時銷售圖表）

這是一個可快速啟動的雲端餐飲 POS 範例系統，提供：

- 服務人員可用手機操作的點餐介面
- 即時銷售數據後台（KPI + 圖表）
- REST API（菜單、建立訂單、即時銷售統計）

> 技術棧：Flask + SQLite + Chart.js

## 功能特色

### 1) 服務人員手機點餐
- 響應式介面，手機可直接操作
- 可選擇桌號、服務人員、備註
- 加入/移除餐點、即時計算小計
- 送出訂單後寫入資料庫

### 2) 即時銷售後台
- 今日營收
- 今日訂單數
- 平均客單價
- 近一小時營收
- 每小時營收折線圖
- 熱銷品項 Top 5 長條圖
- 每 5 秒自動更新

## 安裝與啟動

### 安裝

```bash
pip install -r requirements.txt
```

### 啟動

```bash
python app.py
```

啟動後預設網址：

- 點餐台：<http://127.0.0.1:8000/waiter>
- 銷售後台：<http://127.0.0.1:8000/dashboard>

## API 範例

### 取得菜單

```bash
curl http://127.0.0.1:8000/api/menu
```

### 建立訂單

```bash
curl -X POST http://127.0.0.1:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{
    "table_no": "A12",
    "staff_name": "Amy",
    "note": "少冰",
    "items": [
      {"menu_item_id": 1, "quantity": 1},
      {"menu_item_id": 5, "quantity": 2}
    ]
  }'
```

### 取得即時銷售資料

```bash
curl http://127.0.0.1:8000/api/sales/realtime
```

## 專案結構

- `app.py`：Flask 主程式（頁面 + API + 資料庫初始化）
- `requirements.txt`：依賴套件
- `pos.db`：SQLite 資料庫（啟動後自動建立）
