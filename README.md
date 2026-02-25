# 🎬 isMemory Upload API

智能多媒體內容分析 API：支援 YouTube、TikTok、Instagram、Threads、Medium 與圖片上傳；透過 OpenAI 進行轉錄/摘要/標題生成，並將結果以向量化方式寫入 AstraDB。

---

## API 端點總覽

| 方法 | 路徑 | 用途 |
|---|---|---|
| `POST` | `/api/process` | **通用端點**：自動判斷平台，支援所有 URL 或圖片上傳 |
| `GET` | `/api/health` | 健康檢查，回傳服務狀態 |
| `GET` | `/` | 根端點，回傳 API 基本資訊 |

---

## POST `/api/process` — 通用處理端點

請求格式：`multipart/form-data`

### 請求參數

| 欄位 | 類型 | 必要 | 說明 |
|---|---|---|---|
| `url` | `string` | ⚠️ 與 `file` 擇一 | 影片或文章連結 |
| `file` | `file` | ⚠️ 與 `url` 擇一 | 圖片檔案（jpg、png 等） |
| `store_in_db` | `bool` | 否，預設 `true` | 是否將結果寫入 AstraDB |
| `user_id` | `string` | 否 | 使用者識別碼，用於追蹤上傳者 |

### 平台自動判斷邏輯（傳入 `url` 時）

| 平台 | 支援的 URL 格式 |
|---|---|
| **YouTube** | `youtube.com/shorts/...`、`youtu.be/...` |
| **TikTok** | `tiktok.com/@.../video/...`、`vm.tiktok.com/...` |
| **Instagram** | `instagram.com/reel/...`、`instagram.com/reels/...` |
| **Threads** | `threads.net/...`、`threads.com/...` |
| **Medium** | `medium.com/...`、`*.medium.com/...` |

> 若 URL 無法識別，回傳 HTTP 400。

### 回應格式

```json
{
  "success": true,
  "source": "youtube",
  "raw_data": {
    // 各平台原始資料，格式依平台不同
  },
  "analysis": {
    "title": "AI 生成標題",
    "summary": "AI 生成摘要",
    "important_time": "抽取的重要時間",
    "important_location": "抽取的重要地點",
    "original_path": "原始 URL"
  },
  "db_storage": {
    // 資料庫寫入結果（store_in_db=true 時才有），否則為 null
  }
}
```


---

## GET `/api/health` — 健康檢查

無需請求參數。

### 回應格式

```json
{
  "status": "healthy",
  "service": "shorts-analysis-api",
  "astra_db": "connected",
  "has_openai_key": true
}
```

---

## 各模組 AI 輸入說明

每個模組會將內容整理為 `ai_input` 物件，再傳給 GPT-4o 分析。`ai_input` 結構如下：

```json
{
  "original_path": "原始 URL 或檔名",
  "ocr_text": "文字類內容",
  "caption": "語音轉文字或補充說明"
}
```

### 🎬 YouTube Shorts

| 欄位 | 內容 |
|---|---|
| `ocr_text` | 空字串（YouTube description 雜訊多，刻意排除） |
| `caption` | Whisper 語音轉文字結果 |

---

### 🎵 TikTok

| 欄位 | 內容 |
|---|---|
| `ocr_text` | TikTok 文案（`desc`，作者撰寫的短文 + hashtag） |
| `caption` | **優先**：TikTok 原生語音字幕（`voice_to_text`）；若無則 Whisper 轉錄 |

> **說明**：透過 [douyin.wtf Hybrid API](https://douyin.wtf/docs) 取得影片資料，不需要 MS_TOKEN 或 Playwright。

---

### 📸 Instagram Reels

| 欄位 | 內容 |
|---|---|
| `ocr_text` | Instagram 貼文說明文字 |
| `caption` | Whisper 語音轉錄；若無音頻則使用貼文說明 |

> **說明**：透過 [ScrapeCreators API](https://api.scrapecreators.com) 取得影片資料，需設定 `X_API_KEY`。

---

### 🧵 Threads

| 欄位 | 內容 |
|---|---|
| `ocr_text` | 貼文全文 |
| `caption` | 貼文全文（同上） |

> **說明**：Threads 為純文字，`ocr_text` 與 `caption` 皆為貼文原文，AI 負責補充 `summary`、`title` 等。

---

### 📰 Medium

| 欄位 | 內容 |
|---|---|
| `ocr_text` | 文章全文（由 Tavily Extract API 提取並清理） |
| `caption` | 空字串 |

---

### 🖼️ 圖片

| 欄位 | 內容 |
|---|---|
| `ocr_text` | GPT-4o Vision 辨識出的圖片文字（若無文字則空字串） |
| `caption` | GPT-4o Vision 產生的圖片描述 |

---

## 快速開始

### 本機開發

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```

### Docker（含 Cloudflare Tunnel）

```bash
cp .env.example .env   # 填寫各項 API Key
docker-compose up -d --build
```

---

## 環境變數

| 變數 | 必要 | 說明 |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API 金鑰（Whisper + GPT-4o） |
| `ASTRA_DB_API_ENDPOINT` | ✅ | AstraDB 端點 |
| `ASTRA_DB_TOKEN` | ✅ | AstraDB Token（優先） |
| `ASTRA_DB_APPLICATION_TOKEN` | 備選 | 與 `ASTRA_DB_TOKEN` 擇一 |
| `ASTRA_DB_COLLECTION_NAME` | 否 | 預設：`image_vectors` |
| `CLOUDINARY_CLOUD_NAME` | ✅（圖片） | Cloudinary 設定 |
| `CLOUDINARY_API_KEY` | ✅（圖片） | Cloudinary 設定 |
| `CLOUDINARY_API_SECRET` | ✅（圖片） | Cloudinary 設定 |
| `X_API_KEY` | ✅（Instagram） | ScrapeCreators API 金鑰 |
| `MS_TOKEN` | — | 已棄用（TikTok 改用 douyin.wtf） |
| `TAVILY_API_KEY` | ✅（Medium） | Tavily Extract API 金鑰 |
| `PORT` | 否 | 預設 `8080` |

---

## 測試 cURL

```bash
# YouTube Shorts
curl -X POST http://localhost:8080/api/process \
  -F "url=https://www.youtube.com/shorts/xNSo6xoFsYc" \
  -F "user_id=user_001" \
  -F "store_in_db=false"

# TikTok
curl -X POST http://localhost:8080/api/process \
  -F "url=https://www.tiktok.com/@someuser/video/7339393672959757570" \
  -F "store_in_db=false"

# Instagram Reels
curl -X POST http://localhost:8080/api/process \
  -F "url=https://www.instagram.com/reel/ABC123/" \
  -F "store_in_db=false"

# Threads
curl -X POST http://localhost:8080/api/process \
  -F "url=https://www.threads.net/@username/post/ABCDEFG" \
  -F "store_in_db=false"

# Medium
curl -X POST http://localhost:8080/api/process \
  -F "url=https://medium.com/@username/article-123abc" \
  -F "store_in_db=false"

# 圖片上傳
curl -X POST http://localhost:8080/api/process \
  -F "file=@/path/to/image.jpg" \
  -F "store_in_db=false"

# 健康檢查
curl http://localhost:8080/api/health
```

---

## 資料庫寫入說明

### content_type 對應

| 平台 | content_type |
|---|---|
| YouTube / TikTok / Instagram | `short_video` |
| 圖片 | `image` |
| Threads / Medium | `article` |

### 共通 metadata 欄位

| 欄位 | 說明 |
|---|---|
| `document_id` | UUID，唯一識別碼 |
| `user_id` | 上傳者識別碼 |
| `title` | AI 生成標題 |
| `summary` | AI 生成摘要 |
| `important_time` | AI 抽取的重要時間 |
| `important_location` | AI 抽取的重要地點 |
| `original_path` | 原始 URL 或檔名 |
| `upload_time` | 上傳時間（ISO 8601） |
| `source_type` | 平台名稱（short_video / article 類型才有） |
| `filename` | 原始檔名（image 類型才有） |
| `$vector` | OpenAI Embeddings（text-embedding-3-small） |

---

## 更新紀錄

### v2.4.0
- TikTok 模組改用 `douyin.wtf` Hybrid API，移除 TikTokApi / Playwright 依賴
- 優先使用 TikTok 原生 `voice_to_text` 字幕（節省 Whisper 費用）
- TikTok 文案（`desc`）納入 AI 分析（`ocr_text`）

### v2.3.0
- 修正 Instagram URL 雙重編碼問題（改用 `urllib.parse.quote`）
- 標準化 Instagram URL `/reels/` → `/reel/`
- 更新 Playwright 至 v1.58.0

### v2.2.0
- 新增 `user_id` 參數支援，可追蹤上傳者
- 所有 API 端點支援 `user_id` 參數（可選）
- 資料庫 metadata 自動儲存 `user_id`
