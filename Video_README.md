# 短影音分析工具

此專案提供YouTube Shorts和TikTok短影音的分析功能，能夠提取影片文字內容和字幕，並通過AI進行摘要生成和重要資訊提取。

## 功能特點

- 支援YouTube Shorts和TikTok短影片連結處理
- 提取影片描述、標題和字幕內容
- 使用OpenAI GPT-4o生成精簡摘要
- 提取重要時間和地點資訊
- 簡潔易用的網頁界面

## 系統需求

- Python 3.8+
- FFmpeg
- 網絡連接
- OpenAI API金鑰
- TikTok MS_TOKEN (可選，用於提升TikTok API穩定性)

## 安裝步驟

1. 複製專案到本地

```
git clone https://github.com/your-username/shorts-analysis-tool.git
cd shorts-analysis-tool
```

2. 安裝依賴套件

```
pip install -r requirements.txt
```

3. 安裝playwright相關依賴(TikTokApi需要)

```
playwright install
```

4. 建立環境變數檔案

複製`.env.example`為`.env`並填入您的API金鑰:

```
cp .env.example .env
```

編輯`.env`檔案，填入您的OpenAI API金鑰和其他設定

## 使用方法

1. 啟動服務器

```
python app.py
```

2. 開啟瀏覽器，訪問 http://localhost:8000/

3. 輸入YouTube Shorts或TikTok影片連結，選擇對應平台

4. 點擊「分析影片」按鈕

5. 等待系統處理並顯示結果

## 系統架構

- `app.py`: FastAPI主應用
- `youtube_module.py`: YouTube影片處理模組
- `tiktok_module.py`: TikTok影片處理模組
- `ai_processor.py`: AI分析處理模組
- `frontend/`: 前端界面檔案

## 技術堆疊

- FastAPI: Web服務框架
- TikTokApi: TikTok資料提取
- yt-dlp: YouTube影片下載
- OpenAI: AI處理和語音轉文字
- FFmpeg: 音頻處理
- HTML/CSS/JavaScript: 前端界面

## 注意事項

- 請確保API金鑰的安全，不要將含有實際金鑰的`.env`檔案提交到版本控制系統
- 遵守YouTube和TikTok的服務條款和使用政策
- 目前系統僅支持YouTube Shorts和TikTok短影片，不支持一般YouTube影片或其他平台