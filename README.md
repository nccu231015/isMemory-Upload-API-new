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
| **YouTube** | `youtube.com/watch?v=...`、`youtube.com/shorts/...`、`youtu.be/...`、`youtube.com/live/...`、`youtube.com/embed/...`（含 `m.` / `music.` 子網域） |
| **TikTok** | `tiktok.com/@.../video/...`、`vm.tiktok.com/...` |
| **Instagram** | `instagram.com/reel/...`、`instagram.com/reels/...`、`instagram.com/p/...`（單圖／輪播貼文）、`instagram.com/tv/...`；分享連結的 `?stkn=`、`?igsh=` 等參數會自動移除 |
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
    "important_location": ["抽取的重要地點（最多 15 個）"],
    "region": "內容主要所在的城市或地區，用於輔助地圖查詢",
    "address": "解析出的絕對位置（若為空，則保留重要地點名稱）",
    "rating": 4.5,
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "priceRange": { "startPrice": { "currencyCode": "TWD", "units": "200" }, "endPrice": { "currencyCode": "TWD", "units": "600" } },
    "regularOpeningHours": { "weekdayDescriptions": ["星期一: 09:00 – 21:00", "..."] },
    "location": { "latitude": 25.033, "longitude": 121.564 },
    "websiteUri": "https://example.com",
    "nationalPhoneNumber": "02 1234 5678",
    "paymentOptions": { "acceptsCreditCards": true, "acceptsDebitCards": true, "acceptsCashOnly": false },
    "products": ["三層肉", "雞皮餃子", "兔兔玩偶"],
    "todos": ["需要事先線上預約"],
    "tips": ["假日人多建議早點去"],
    "all_location_details": [
      { "address": "澀谷橫丁", "rating": 4.1, "products": ["三層肉", "雞皮餃子"] },
      { "address": "唐吉訶德", "products": ["兔兔玩偶"] }
    ],
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

### 🎬 YouTube（一般影片與 Shorts）

| 欄位 | 內容 |
|---|---|
| `ocr_text` | 影片標題（作者濃縮的核心文案；description 雜訊多，刻意排除） |
| `caption` | Whisper 語音轉文字結果 |

**地點與商品抽取**：長影片（內容超過 2000 字）會先把逐字稿切段平行掃描，
每段只問「這段提到哪些具體場所、在那裡吃到買到什麼」，
再把候選清單交給主要分析挑選。
這樣可以避免單次呼叫在長內容上只回傳「東京」「澀谷」這類籠統地名。
商品會綁在 `all_location_details` 中各自的地點底下。
短影片內容集中，維持單次呼叫，不會產生額外費用。

**長影片支援**：下載後會先用 ffmpeg 轉成單聲道 16kHz / 32kbps 音訊，
超過 Whisper 單檔 25MB 上限時自動切段轉錄再合併，
因此數小時的影片也能完整轉錄（處理時間會隨長度增加）。
預設可接受的最長影片為 4 小時，可用 `YOUTUBE_MAX_DURATION_SECONDS` 調整。
進行中的直播不支援。

**抓取穩定性**：yt-dlp 需要 JavaScript runtime 才能解出 YouTube 的
signature / n-challenge，Docker 映像中已安裝 **Deno**，
並以 `yt-dlp-ejs` 套件提供 challenge solver。
若預設抽取流程被擋下，會自動改用其他 innertube client 重試。

---

### 🎵 TikTok

| 欄位 | 內容 |
|---|---|
| `ocr_text` | TikTok 文案（`desc`，作者撰寫的短文 + hashtag） |
| `caption` | Whisper 語音轉文字結果（長影片自動切段並行轉錄） |

> **說明**：直接以 yt-dlp 向 TikTok 取得影片與中繼資料，不依賴任何第三方 API。
> 需要 `curl_cffi` 提供 TLS 指紋偽裝，否則 TikTok 會拒絕網頁請求。

---

### 📸 Instagram Reels 與貼文（含輪播）

| 欄位 | 內容 |
|---|---|
| `ocr_text` | Instagram 貼文說明文字 |
| `caption` | 各媒體內容彙整：影片以 Whisper 語音轉錄，圖片以 GPT-4o 做 OCR 與描述；皆無結果時退回貼文說明 |

`raw_output` 另含 `media_items`、`video_count`、`image_count`、`processed_video_count`、`processed_image_count`、`transcription`、`video_analyses`、`image_analyses`，方便追查每一則媒體的處理結果。

> **說明**：自行抓取 Instagram 貼文，不依賴第三方爬蟲服務。依序嘗試：① 公開嵌入頁（免登入，支援 Reels、單圖、輪播）② 站內 API（需設定 `IG_SESSIONID`，可取得關閉嵌入或需登入的貼文）③ yt-dlp（僅影片）。全部失敗時回傳錯誤，不會把錯誤訊息當成內容做摘要。
>
> **輪播貼文**：媒體位於 `edge_sidecar_to_children`，支援影片與圖片混合（例如第一則是影片、其餘是圖片）。
> 影片與圖片以非同步並行處理，數量上限見 `IG_MAX_VIDEOS`（預設 3）與 `IG_MAX_IMAGES`（預設 20，即 Instagram 輪播上限）。
>
> **無聲影片**：Instagram 輪播中的影片常常沒有音訊軌，`video_url` 只給純視訊軌。
> 系統會先用 `ffprobe` 檢查音訊軌，沒有聲音就略過 Whisper，改抽一張畫面（失敗時退回封面圖）交給 GPT-4o 做 OCR 與描述，
> 在 `caption` 中以 `【影片畫面】` 標示，避免這則媒體完全沒有內容。
>
> 圖片與影片畫面分析需要 `OPENAI_API_KEY`。

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
| `GOOGLE_MAPS_API_KEY` | ✅ | Google Maps Places API 金鑰（用於地點轉換為地址） |
| `ASTRA_DB_API_ENDPOINT` | ✅ | AstraDB 端點 |
| `ASTRA_DB_TOKEN` | ✅ | AstraDB Token（優先） |
| `ASTRA_DB_APPLICATION_TOKEN` | 備選 | 與 `ASTRA_DB_TOKEN` 擇一 |
| `ASTRA_DB_COLLECTION_NAME` | 否 | 預設：`image_vectors` |
| `CLOUDINARY_CLOUD_NAME` | ✅（圖片） | Cloudinary 設定 |
| `CLOUDINARY_API_KEY` | ✅（圖片） | Cloudinary 設定 |
| `CLOUDINARY_API_SECRET` | ✅（圖片） | Cloudinary 設定 |
| `IG_MAX_VIDEOS` | 否 | Instagram 輪播單篇最多處理的影片數，預設 `3` |
| `IG_MAX_IMAGES` | 否 | Instagram 輪播單篇最多處理的圖片數，預設 `20` |
| `IG_SESSIONID` | 否 | Instagram 已登入帳號的 `sessionid` cookie，嵌入頁拿不到貼文時使用；多個帳號以逗號分隔，失效時自動換下一個。建議使用專用帳號，約一年或登出／改密碼後需更新 |
| `MS_TOKEN` | — | 已棄用（TikTok 改用 yt-dlp 直接抓取） |
| `TIKTOK_COOKIES_FILE` | 否（TikTok） | TikTok cookies 檔案路徑，僅在被要求驗證時需要 |
| `YTDLP_IMPERSONATE` | 否 | 強制指定 TLS 指紋偽裝目標，例如 `chrome` |
| `WHISPER_PARALLEL_WORKERS` | 否 | 長音檔並行轉錄的執行緒數，預設 `4` |
| `YTDLP_COOKIES_CONTENT` | 否（YouTube） | YouTube cookies（Netscape 格式全文或 base64）。部署在資料中心 IP 時，YouTube 可能要求「確認你不是機器人」，帶 cookies 是最有效的解法 |
| `YTDLP_COOKIES_FILE` | 否（YouTube） | cookies 檔案路徑，優先於 `YTDLP_COOKIES_CONTENT` |
| `YTDLP_PROXY` | 否（YouTube） | yt-dlp 代理，例如 `http://user:pass@host:port` |
| `YTDLP_YOUTUBE_CLIENTS` | 否 | 覆寫 fallback 的 innertube client 順序，逗號分隔 |
| `YOUTUBE_MAX_DURATION_SECONDS` | 否 | 可處理的最長影片秒數，預設 `14400`（4 小時） |
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

# YouTube 一般影片
curl -X POST http://localhost:8080/api/process \
  -F "url=https://www.youtube.com/watch?v=dQw4w9WgXcQ" \
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

# Instagram 輪播貼文（影片＋圖片混合，可直接貼分享連結）
curl -X POST http://localhost:8080/api/process \
  -F "url=https://www.instagram.com/p/ABC123/?stkn=xxxx" \
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
| `important_location` | AI 抽取的重要地點（地名） |
| `address` | Google Maps API 解析出的絕對地址 |
| `rating` | Google Maps 地點評分 |
| `priceLevel` | Google Maps 價位等級（如 PRICE_LEVEL_MODERATE） |
| `priceRange` | Google Maps 具體價位範圍 |
| `regularOpeningHours` | Google Maps 營業時間與週摘要 |
| `location` | Google Maps 經緯度座標（latitude/longitude） |
| `websiteUri` | Google Maps 地點官方網站 |
| `nationalPhoneNumber` | Google Maps 地點電話號碼 |
| `paymentOptions` | Google Maps 支付方式 (信用卡/現金等) |
| `all_location_details` | 多個地點時的詳細資訊列表 |
| `original_path` | 原始 URL 或檔名 |
| `upload_time` | 上傳時間（ISO 8601） |
| `source_type` | 平台名稱（short_video / article 類型才有） |
| `filename` | 原始檔名（image 類型才有） |
| `$vector` | OpenAI Embeddings（text-embedding-3-small） |

---

## 更新紀錄

### v2.9.0
- 修正 Instagram Reels 嵌入頁只給封面、不給影片網址時，影片語音完全不會被轉錄的問題：改用站內 API / yt-dlp 補上影片網址，並保留嵌入頁的文案與輪播結構
- 地點上限由短內容 5 個／長內容 10 個統一提高為 15 個；說明欄以清單列出的景點（`▶︎`、`📍`、編號）必須全部列入，超過上限時優先保留推薦景點，其次才是住宿
- 不再列入航空公司、租車行、交通業者等非目的地
- 送給模型的文字保留換行與清單符號（先前會被清成單行並移除 `📍` 等符號，清單結構消失）
- 長內容逐段掃描候選地點時一併掃描貼文說明欄，避免說明欄列出的店名被排除
- 新增 `region` 欄位：店名太通用時（例如「時苑」）以地區輔助 Google Maps 查詢，避免查到其他縣市的同名地點（地圖查詢由前端處理，前端查詢時請將 `region` 附加在地點名稱後）

### v2.8.0
- 修正 Instagram `/p/` 貼文連結無法辨識的問題（先前僅支援 `/reel/`、`/reels/`，`/p/` 會回傳 400）
- 新增 `/tv/` 支援，並自動移除分享連結參數（`?stkn=`、`?igsh=`、`?img_index=`）
- 支援輪播貼文（`edge_sidecar_to_children`）：影片以 Whisper 轉錄、圖片以 GPT-4o 做 OCR 與描述，並行處理後彙整
- 修正無聲影片會讓轉錄整個失敗的問題：先以 `ffprobe` 檢查音訊軌，無聲時改抽畫面做 OCR／描述
- ffmpeg 轉檔失敗時保留 stderr 訊息，不再只回報 exit status
- 圖片處理上限由 10 提高到 20（Instagram 輪播上限），可用 `IG_MAX_VIDEOS` / `IG_MAX_IMAGES` 調整
- `raw_output` 新增 `media_items`、`video_count`、`image_count`、`processed_*_count`、`transcription`、`video_analyses`、`image_analyses`

### v2.7.0
- **地點資料格式統一**：`address` 與 `important_location` 欄位全面改為陣列（Array `[]`）格式，即使單一地點亦維持陣列結構。
- **Google Maps 支付資訊**：新增 `paymentOptions` 欄位，可自動獲取該地點的支付方式支援狀況（如是否接受信用卡、行動支付或僅收現金）。

### v2.6.0
- **Google Maps 資訊擴充**：`address` 查詢現在會一併獲取 `rating`、`priceLevel`、`priceRange`、`regularOpeningHours`、`location` (經緯度)、`websiteUri` 與 `nationalPhoneNumber`。
- **語言規則強化**：AI 分析結果嚴格限定為 **繁體中文與英文**，若原始內容包含韓文、日文等其他語言，將自動翻譯為繁體中文。
- **地址自動補充優化**：若有複數地點（使用 `/` 隔開），系統會分別查詢並儲存於 `all_location_details` 列表中。

### v2.5.0
- AI 分析模型調整與 `gpt-4o` 優化。
- 新增 `address` 欄位：從 `important_location` 提取後呼叫 Google Maps Places API 轉為絕對地址，並存入 Astra DB。

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
