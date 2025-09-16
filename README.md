# 🎬 isMemory Upload API

智能多媒體內容分析 API：支援 YouTube、TikTok、Instagram、Threads 與圖片上傳；透過 OpenAI 進行轉錄/摘要/標題生成，並將結果以向量化方式寫入 AstraDB。

## 功能
- 自動平台判斷：YouTube / TikTok / Instagram / Threads
- 圖片上傳 + Cloudinary 儲存 + 視覺分析
- Whisper 語音轉文字、GPT-4o 摘要/標題/資訊抽取
- AstraDB 向量化儲存與檢索

## 端點
- POST `/api/process`（通用，支援 url 或 file）
- POST `/api/process/threads`（Threads 專用）
- GET `/api/health`（健康檢查）

請求格式：`multipart/form-data`
- `url`（可選，影片或文章網址）
- `file`（可選，圖片檔案）
- `store_in_db`（可選，true/false，預設 true）

## 快速開始（本機）
```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
uvicorn app:app --host 0.0.0.0 --port 8000
```

## 環境變數（必要）
- OPENAI_API_KEY
- ASTRA_DB_API_ENDPOINT
- ASTRA_DB_TOKEN（優先）或 ASTRA_DB_APPLICATION_TOKEN
- ASTRA_DB_COLLECTION_NAME（預設：image_vectors）
- CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET（圖片上傳）
- X_API_KEY（Instagram 抓取）
- MS_TOKEN（TikTok 抓取，可選）

## 測試 cURL
YouTube Shorts：
```bash
curl -X POST http://localhost:8000/api/process \
  -F 'url=https://www.youtube.com/shorts/xNSo6xoFsYc' -F 'store_in_db=true'
```

TikTok：
```bash
curl -X POST http://localhost:8000/api/process \
  -F 'url=https://www.tiktok.com/@someuser/video/1234567890' -F 'store_in_db=true'
```

Instagram Reels：
```bash
curl -X POST http://localhost:8000/api/process \
  -F 'url=https://www.instagram.com/reels/ABC123/' -F 'store_in_db=true'
```

Threads（通用端點）：
```bash
curl -X POST http://localhost:8000/api/process \
  -F 'url=https://www.threads.net/@username/post/ABCDEFG' -F 'store_in_db=true'
```

Threads（專用端點）：
```bash
curl -X POST http://localhost:8000/api/process/threads \
  -F 'url=https://www.threads.net/@username/post/ABCDEFG' -F 'store_in_db=true'
```

圖片上傳：
```bash
curl -X POST http://localhost:8000/api/process \
  -F 'file=@/absolute/path/to/image.jpg' -F 'store_in_db=true'
```

健康檢查：
```bash
curl http://localhost:8000/api/health
```

## 寫入資料重點
- content_type：
  - `short_video`（youtube/tiktok/instagram）
  - `image`
  - `article`（threads）
- metadata 共通欄位：`title`、`summary`、`important_time`、`important_location`、`original_path`、`upload_time`
- 依內容型別擴充：
  - image：`filename`
  - short_video/article：`source_type`
- `$vector` 為 OpenAI Embeddings（text-embedding-3-small）

## 注意事項
- TikTok 下載內建最多 5 次重試；每次嘗試不同方式（no_wm / default）。
- Threads 文章以原文 `text` 作為 `ocr_text` 與 `caption`，AI 只補 `summary/title/important_*`。
- 需要安裝 Playwright Chromium：`python -m playwright install --with-deps chromium`。

—
版本：2.0.0
