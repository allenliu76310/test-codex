# 影片人臉重複辨識工具

這是一個 Python Web 程式，提供「拖曳影片上傳」介面，並分析影片中的人臉是否重複出現。

## 功能

- 拖曳上傳影片（或點擊選擇檔案）
- 自動偵測人臉
- 分群判斷是否為同一人
- 顯示每位人物的出現次數與是否重複出現

## 安裝需求

建議使用 Python 3.10+

```bash
pip install -r requirements.txt
```

## 啟動方式

```bash
python app.py
```

開啟瀏覽器：`http://127.0.0.1:5000`

## 注意事項

- 目前使用 OpenCV Haar Cascade + 特徵向量相似度做人物分群，屬於輕量版本。
- 影片解析度、角度、光線、遮擋都會影響辨識結果。

## 測試常見問題排除

### 1) `ModuleNotFoundError: No module named 'cv2'`

代表 OpenCV 尚未安裝，請先安裝相依套件：

```bash
pip install -r requirements.txt
```

### 2) `pip install` 因公司網路/代理失敗

若環境需要代理，先設定代理再安裝：

```bash
export HTTPS_PROXY=http://<proxy-host>:<port>
export HTTP_PROXY=http://<proxy-host>:<port>
pip install -r requirements.txt
```

如果你在離線環境，建議在可連網機器先下載 wheel，再帶入目標機安裝。

### 3) 啟動服務可以成功，但分析時顯示缺少套件

新版程式允許「未安裝 OpenCV 也能先啟動 UI」，但按下分析時會回傳清楚錯誤訊息。
此時只要完成 `pip install -r requirements.txt`，重新啟動即可。
