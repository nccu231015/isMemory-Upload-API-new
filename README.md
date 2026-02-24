# 🎬 isMemory Upload API

智能多媒體內容分析 API：支援 YouTube、TikTok、Instagram、Threads、Medium 與圖片上傳；透過 OpenAI 進行轉錄/摘要/標題生成，並將結果以向量化方式寫入 AstraDB。

---

## 功能

- 自動平台判斷：YouTube / TikTok / Instagram / Threads / Medium
- 圖片上傳 + Cloudinary 儲存 + 視覺分析
- Whisper 語音轉文字、GPT-4o 摘要/標題/資訊抽取
- AstraDB 向量化儲存與檢索

---

## 端點

- `POST /api/process`（通用，支援 url 或 file）
- `POST /api/process/threads`（Threads 專用）
- `POST /api/process/medium`（Medium 專用）
- `GET /api/health`（健康檢查）

### 請求格式：`multipart/form-data`

| 欄位 | 類型 | 必要 | 說明 |
|---|---|---|---|
| `url` | string | 擇一 | 影片或文章網址 |
| `file` | file | 擇一 | 圖片檔案 |
| `store_in_db` | bool | 否 | 是否存入資料庫，預設 `true` |
| `user_id` | string | 否 | 使用者識別碼 |

---

## 各模組 AI 輸入說明

每個模組會將內容整理為 `ai_input` 物件，再傳給 GPT-4o 分析。

`ai_input` 結構如下：
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
| `ocr_text` | 空字串（排除 description 雜訊） |
| `caption` | Whisper 語音轉文字結果 |

> **說明**：YouTube description 通常含大量廣告/連結等雜訊，刻意排除，只保留語音內容。

---

### 🎵 TikTok

| 欄位 | 內容 |
|---|---|
| `ocr_text` | TikTok 文案（`desc`，作者寫的短文 + hashtag） |
| `caption` | **優先**：TikTok 原生語音字幕（`voice_to_text`）；若無，則 Whisper 轉錄 |

> **說明**：透過 [douyin.wtf Hybrid API](https://douyin.wtf/docs) 取得影片資料，不需要 MS_TOKEN 或 Playwright。TikTok 文案屬於高價值內容，一起傳入 AI 分析。

---

### 📸 Instagram Reels

| 欄位 | 內容 |
|---|---|
| `ocr_text` | Instagram 貼文說明（`edge_media_to_caption` 的文字） |
| `caption` | **優先**：Whisper 語音轉錄；若無音頻，則使用貼文說明 |

> **說明**：透過 [ScrapeCreators API](https://api.scrapecreators.com) 取得影片資料與下載連結，需設定 `X_API_KEY`。

---

### 🧵 Threads

| 欄位 | 內容 |
|---|---|
| `ocr_text` | 貼文全文（作者的文字內容） |
| `caption` | 同上（貼文全文） |

> **說明**：Threads 為純文字，`ocr_text` 與 `caption` 皆為貼文原文，AI 負責補充 `summary`、`title`、`important_time`、`important_location`。

---

### 📰 Medium

| 欄位 | 內容 |
|---|---|
| `ocr_text` | 文章全文（由 Tavily Extract API 提取並清理） |
| `caption` | 空字串 |

> **說明**：Medium 文章為長篇文字，`ocr_text` 傳入完整內文，AI 負責摘要與資訊抽取。

---

### 🖼️ 圖片

| 欄位 | 內容 |
|---|---|
| `ocr_text` | GPT-4o Vision 辨識出的圖片文字（若無文字則空字串） |
| `caption` | GPT-4o Vision 產生的圖片描述 |

> **說明**：圖片先上傳至 Cloudinary，再以 GPT-4o Vision 進行 OCR 與內容描述，兩者皆為 AI 自行生成。

---

## 快速開始（本機）

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## 快速開始（Docker）

```bash
# 複製並填寫環境變數
cp .env.example .env  # 填寫各項 API Key

# 啟動服務（含 Cloudflare Tunnel）
docker-compose up -d --build
```

---

## 環境變數

| 變數 | 必要 | 說明 |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API 金鑰 |
| `ASTRA_DB_API_ENDPOINT` | ✅ | AstraDB 端點 |
| `ASTRA_DB_TOKEN` | ✅ | AstraDB Token |
| `ASTRA_DB_APPLICATION_TOKEN` | 備選 | 與 `ASTRA_DB_TOKEN` 擇一 |
| `ASTRA_DB_COLLECTION_NAME` | 否 | 預設：`image_vectors` |
| `CLOUDINARY_CLOUD_NAME` | ✅ (圖片) | Cloudinary 設定 |
| `CLOUDINARY_API_KEY` | ✅ (圖片) | Cloudinary 設定 |
| `CLOUDINARY_API_SECRET` | ✅ (圖片) | Cloudinary 設定 |
| `X_API_KEY` | ✅ (Instagram) | ScrapeCreators API 金鑰 |
| `MS_TOKEN` | 否 | 已棄用（TikTok 改用 douyin.wtf） |
| `PORT` | 否 | 預設 `8080` |

---

## 測試 cURL

```bash
# YouTube Shorts
curl -X POST http://localhost:8080/api/process \
  -F 'url=https://www.youtube.com/shorts/xNSo6xoFsYc' \
  -F 'store_in_db=false'

# TikTok
curl -X POST http://localhost:8080/api/process \
  -F 'url=https://www.tiktok.com/@user/video/1234567890' \
  -F 'store_in_db=false'

# Instagram Reels
curl -X POST http://localhost:8080/api/process \
  -F 'url=https://www.instagram.com/reel/ABC123/' \
  -F 'store_in_db=false'

# Threads
curl -X POST http://localhost:8080/api/process \
  -F 'url=https://www.threads.net/@username/post/ABCDEFG' \
  -F 'store_in_db=false'

# Medium
curl -X POST http://localhost:8080/api/process \
  -F 'url=https://medium.com/@username/article-title-123abc' \
  -F 'store_in_db=false'

# 圖片
curl -X POST http://localhost:8080/api/process \
  -F 'file=@/path/to/image.jpg' \
  -F 'store_in_db=false'

# 健康檢查
curl http://localhost:8080/api/health
```

---

## 資料庫寫入格式

| 欄位 | 說明 |
|---|---|
| `content_type` | `short_video`（youtube/tiktok/instagram）、`image`、`article`（threads/medium） |
| `document_id` | 唯一識別碼 |
| `user_id` | 上傳者識別碼 |
| `title` | AI 生成標題 |
| `summary` | AI 生成摘要 |
| `important_time` | AI 抽取的重要時間 |
| `important_location` | AI 抽取的重要地點 |
| `original_path` | 原始 URL 或檔名 |
| `upload_time` | 上傳時間 |
| `$vector` | OpenAI Embeddings（text-embedding-3-small） |

---

## 注意事項

- **TikTok** 改用 `douyin.wtf` Hybrid API，不再需要 `MS_TOKEN` 或 Playwright。
- **Instagram** 需要有效的 `X_API_KEY`（ScrapeCreators），URL 支援 `/reel/` 與 `/reels/` 格式。
- **Threads / Medium** 為文章類型，`content_type` 寫入為 `article`。
- **圖片** 需設定 Cloudinary 環境變數才能上傳。

---

## 更新紀錄

### v2.4.0
- TikTok 模組改用 `douyin.wtf` Hybrid API，移除 TikTokApi / Playwright 依賴
- 優先使用 TikTok 原生 `voice_to_text` 字幕（節省 Whisper 費用）
- TikTok 文案（`desc`）納入 AI 分析

### v2.3.0
- 修正 Instagram URL 雙重編碼問題
- 更新 Playwright 至 v1.58.0

### v2.2.0
- 新增 `user_id` 參數支援，可追蹤上傳者
- 所有 API 端點支援 `user_id` 參數（可選）
- 資料庫 metadata 自動儲存 `user_id`
