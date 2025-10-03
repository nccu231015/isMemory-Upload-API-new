# 使用包含Playwright依賴的基礎映像
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# 安裝額外的系統依賴
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製requirements並安裝Python依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式檔案
COPY app.py .
COPY ai_processor.py .
COPY astra_db_handler.py .
COPY youtube_module.py .
COPY tiktok_module.py .
COPY instagram_module.py .
COPY image_module.py .
COPY threads_module.py .
COPY medium_module.py .

# 創建必要目錄
RUN mkdir -p shorts_cache tiktok_videos

# 設定環境變數
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8080

# 健康檢查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# 啟動命令
CMD exec uvicorn app:app --host 0.0.0.0 --port $PORT
