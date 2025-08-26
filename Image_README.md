# 圖片上傳 API 服務

## 簡介

這是一個專門用於處理圖片上傳、AI分析和向量化存儲的 API 服務。此 API 能夠從網路連結獲取圖片，使用 GPT-4o 進行圖片分析（包括OCR文字辨識、圖片描述生成、摘要生成、重要時間和地點識別），並將處理結果以向量形式存儲在 AstraDB 中，以便後續進行向量相似度檢索。

## 主要功能

- 接收網路圖片連結和圖片文件
- AI圖像分析（OCR、描述、摘要、重要時間/地點識別）
- 向量化處理（使用 OpenAI Embedding）
- 資料儲存至 AstraDB 向量資料庫
- 欄位結構與搜尋API完全相容

## 環境需求

- Python 3.8+
- FastAPI
- OpenAI API Key
- AstraDB 資料庫
- 其他依賴套件（見 requirements.txt）

## 環境設定

1. 安裝依賴：
```bash
pip install -r requirements.txt
```

2. 設定環境變數（建議使用 .env 檔案）：
```
OPENAI_API_KEY=your_openai_api_key
ASTRA_DB_API_ENDPOINT=your_astradb_endpoint
ASTRA_DB_TOKEN=your_astradb_token
ASTRA_DB_COLLECTION_NAME=image_vectors  # 可選，預設為 image_vectors
```

## 啟動服務

```bash
python image_upload_api.py
```

服務預設運行在 `http://0.0.0.0:8000`

## API 端點

### 1. 上傳圖片

**端點**：`POST /api/upload-mobile-image`

**請求參數**：
- `original_path`（必須，Form）：圖片的原始網路連結
- `filename`（可選，Form）：檔案名稱
- `device_id`（可選，Form）：設備識別碼
- `file`（必須，File）：圖片文件

**回應格式**：
```json
{
    "success": true,
    "message": "圖片處理完成",
    "data": {
        "document_id": "uuid-string",
        "ocr_text": "圖片中的文字內容",
        "caption": "圖片描述",
        "summary": "圖片摘要",
        "important_time": "重要時間資訊",
        "important_location": "重要地點資訊",
        "combined_text": "結合的文字內容",
        "original_path": "原始圖片網路連結",
        "image_path": "虛擬本地圖片路徑",
        "success": true,
        "storage_result": {
            "database_document": {
                // 完整資料庫文件
            },
            "inserted_id": "uuid-string"
        }
    }
}
```

### 2. 健康檢查

**端點**：`GET /api/health`

**回應格式**：
```json
{
    "status": "healthy",
    "timestamp": "2025-08-06T11:36:25.190891",
    "service": "mobile-upload-api"
}
```

### 3. 配置資訊

**端點**：`GET /api/config`

**回應格式**：
```json
{
    "astra_db_configured": true,
    "openai_configured": true,
    "collection_name": "image_vectors"
}
```

## 資料儲存結構

上傳的圖片資料將以以下結構存儲到 AstraDB：

```
{
    "_id": "唯一識別碼",
    "$vector": [向量值，維度為1536],
    "text": "結合的文字內容",
    "metadata": {
        "document_id": "唯一識別碼",
        "filename": "檔案名稱",
        "ocr_text": "圖片中的文字內容",
        "caption": "圖片描述",
        "summary": "圖片摘要",
        "important_time": "重要時間資訊",
        "important_location": "重要地點資訊",
        "original_path": "原始圖片網路連結",
        "image_path": "虛擬本地路徑",
        "upload_time": "上傳時間 ISO格式",
        "content_type": "image"
    }
}
```

## 使用範例

### 使用 cURL 上傳圖片

```bash
curl -X POST http://localhost:8000/api/upload-mobile-image \
  -F "original_path=https://example.com/image.jpg" \
  -F "filename=example.jpg" \
  -F "file=@/path/to/local/image.jpg"
```

### 使用 Python 上傳圖片

```python
import requests

url = "http://localhost:8000/api/upload-mobile-image"
files = {"file": open("local_image.jpg", "rb")}
data = {
    "original_path": "https://example.com/image.jpg",
    "filename": "example.jpg"
}

response = requests.post(url, files=files, data=data)
print(response.json())
```

## 注意事項

1. 圖片必須同時提供文件和原始路徑
2. 原始路徑將在資料庫中保留，並在搜索結果中被優先使用
3. API 生成的向量維度為 1536，與 AstraDB 集合保持一致
4. 需確保 OpenAI API 和 AstraDB 憑證設定正確

## 錯誤處理

服務遇到錯誤時會返回 HTTP 500 錯誤，並在響應體中提供詳細錯誤信息：

```json
{
    "detail": "處理圖片時發生錯誤: 錯誤訊息"
}
```