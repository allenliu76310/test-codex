# 中文手寫字辨識轉 Excel 工具

這是一個 Python 程式，用來將「中文手寫文字」的圖片或 PDF 檔案轉成 Excel（`.xlsx`）。
程式會依 OCR 偵測到的文字框位置，盡量把文字放到對應的儲存格區域，以保留原本版面。

## 功能

- 支援輸入：圖片（png/jpg/jpeg/bmp/tif/tiff）與 PDF
- 使用 EasyOCR 進行中文手寫文字辨識
- 輸出為 Excel（每頁一個工作表）
- 依文字框位置映射到儲存格，並嘗試合併儲存格維持版型
- 可調整信心值門檻，過濾低可信度辨識結果

## 安裝需求

建議使用 Python 3.10+

```bash
pip install -r requirements.txt
```

## 使用方式

```bash
python app.py <輸入檔案> <輸出檔案.xlsx>
```

範例：

```bash
python app.py samples/handwriting.pdf output/result.xlsx
python app.py samples/note.jpg output/result.xlsx --confidence-threshold 0.3
```

### 可用參數

- `--languages`: OCR 語言代碼（預設 `ch_tra en`）
- `--gpu`: 若有 CUDA 可開啟 GPU 推論
- `--confidence-threshold`: 文字信心值門檻（預設 `0.2`）

## 注意事項

- 「盡量維持格式」是透過「文字框位置映射 + 儲存格合併」達成，無法保證 100% 還原。
- 手寫字的準確率會受字跡、拍攝角度、解析度、光線影響。
- 若是掃描品質較差，建議先做影像前處理（去噪、增強對比）再辨識。
