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

## 一鍵環境檢測與自動安裝

本專案提供 `install.py`，會自動：

- 檢查 Python 版本是否符合（>=3.10）
- 檢查並升級 `pip`
- 檢查 `requirements.txt` 內套件（包含 `opencv-python`、`numpy`）
- 若缺少或版本不符，嘗試自動安裝/升級，並輸出檢查結果表格

執行方式：

```bash
python install.py
```

Windows PowerShell：

```powershell
python .\install.py
```

> 小提醒：`install.py` 執行完會停留在終端機，等待你按 Enter，方便查看結果。
> 若要在 CI 或自動化環境跳過停留，可設定：`NO_PAUSE_ON_EXIT=1`。


### 執行狀態顯示

- `app.py` 啟動後會持續在終端機顯示服務狀態（含任務數量與運行時間）。
- 若啟動失敗，會先顯示錯誤，再等待按 Enter，避免視窗一閃而過。
- 若執行環境不支援鍵盤輸入（無 stdin），會改為停留 10 秒後再結束，方便查看錯誤。
- 在 CI / 自動化若不希望停留，可設定：`NO_PAUSE_ON_EXIT=1`。

## Docker 一鍵啟動

```bash
docker build -t face-video-analyzer .
docker run --rm -p 5000:5000 face-video-analyzer
```

### Windows PowerShell 常見錯誤

若看到以下錯誤：

```powershell
docker : 無法辨識 'docker' 詞彙是否為 Cmdlet、函數、指令檔或可執行程式的名稱。
```

代表系統目前找不到 Docker CLI，常見原因與處理方式：

1. 尚未安裝 Docker Desktop（Windows）
   - 先安裝 Docker Desktop，安裝後重新開啟 PowerShell。
2. 已安裝但 PATH 尚未生效
   - 關閉全部 PowerShell 視窗再重開，或重新登入 Windows。
3. 公司電腦權限限制
   - 請聯絡 IT 開通 Docker Desktop / WSL2 權限。

可先用以下指令確認：

```powershell
docker --version
```

若暫時無法使用 Docker，請改用 Python 方式啟動（同樣可執行本專案）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python app.py
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
