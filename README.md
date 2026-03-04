# 影片人臉重複辨識工具

這是一個 Python Web 程式，提供拖曳上傳影片、非同步分析、進度追蹤、取消任務、以及 JSON/CSV 匯出功能。

## 功能

- 拖曳上傳影片（或點擊選擇檔案）
- 分析進度條（百分比與狀態文字）
- 可在分析中取消任務
- 分析完成可匯出 JSON / CSV 報告
- 偵測人臉並判斷是否為重複出現的人

## 安裝需求

建議使用 Python 3.10+

```bash
pip install -r requirements.txt
```

## 建議安裝步驟（避免環境衝突）

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 啟動方式

```bash
python app.py
```

開啟瀏覽器：`http://127.0.0.1:5000`

## Docker 一鍵啟動

```bash
docker build -t face-video-analyzer .
docker run --rm -p 5000:5000 face-video-analyzer
```

## API 簡介

- `POST /analyze`：上傳影片，建立任務（回傳 `task_id`）
- `GET /api/task/<task_id>`：查詢狀態/進度/結果
- `POST /api/task/<task_id>/cancel`：取消任務
- `GET /api/task/<task_id>/export?format=json|csv`：匯出報告

## 測試常見問題排除

### 1) `ModuleNotFoundError: No module named 'cv2'`

代表 OpenCV 尚未安裝：

```bash
pip install -r requirements.txt
```

### 2) `pip install` 因網路/代理失敗

```bash
export HTTPS_PROXY=http://<proxy-host>:<port>
export HTTP_PROXY=http://<proxy-host>:<port>
pip install -r requirements.txt
```

若為離線環境，建議先於可連網機器下載 wheel 再離線安裝。

### 3) 服務可啟動但分析失敗

若缺少依賴，程式會在分析時回傳明確錯誤訊息。安裝 `requirements.txt` 依賴後重啟即可。
