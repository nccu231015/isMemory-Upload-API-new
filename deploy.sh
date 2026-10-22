#!/bin/bash

# Google Cloud Run 部署腳本
# 使用方法: ./deploy.sh [PROJECT_ID]

set -e

# 載入 .env 檔案中的環境變數（如果存在）
if [ -f ".env" ]; then
    echo "📋 載入 .env 檔案..."
    export $(grep -v '^#' .env | xargs)
fi

# 設置 PROJECT_ID，預設為 crm-llm-api-463205
PROJECT_ID=${1:-"crm-llm-api-463205"}
SERVICE_NAME="upload-api"
REGION="asia-east1"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "🚀 開始部署到 Google Cloud Run..."
echo "專案ID: $PROJECT_ID"
echo "服務名稱: $SERVICE_NAME"
echo "區域: $REGION"
echo ""

# 1. 設置專案
echo "📋 設置 Google Cloud 專案..."
gcloud config set project $PROJECT_ID

# 2. 啟用必要的API
echo "🔧 啟用必要的 Google Cloud APIs..."
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com

# 3. 構建Docker映像
echo "🏗️ 構建 Docker 映像..."
docker build --platform linux/amd64 -t $IMAGE_NAME .

# 4. 推送映像到Google Container Registry
echo "📤 推送映像到 Container Registry..."
docker push $IMAGE_NAME

# 5. 部署到Cloud Run
echo "🚀 部署到 Cloud Run..."

# 只把「本機確實有值」的變數帶上去，並使用 --update-env-vars（合併）而非
# --set-env-vars（取代）。
# --set-env-vars 會刪除所有沒列出的變數，包含線上以 Secret Manager 掛載的
# YTDLP_COOKIES 與 GOOGLE_MAPS_API_KEY、TAVILY_API_KEY、IG_* 等，
# 沒有 .env 的機器上執行會直接清空線上設定。
ENV_VARS=""
for KEY in OPENAI_API_KEY ASTRA_DB_APPLICATION_TOKEN ASTRA_DB_TOKEN \
           ASTRA_DB_API_ENDPOINT CLOUDINARY_CLOUD_NAME CLOUDINARY_API_KEY \
           CLOUDINARY_API_SECRET MS_TOKEN GOOGLE_MAPS_API_KEY \
           TAVILY_API_KEY; do
    VALUE="${!KEY}"
    if [ -n "$VALUE" ]; then
        ENV_VARS="${ENV_VARS:+$ENV_VARS,}$KEY=$VALUE"
    fi
done

DEPLOY_ARGS=(
    --image "$IMAGE_NAME"
    --region "$REGION"
    --platform managed
    --allow-unauthenticated
    --memory 4Gi
    --cpu 2
    --timeout 3600
    --max-instances 10
)

if [ -n "$ENV_VARS" ]; then
    echo "🔑 更新環境變數（僅本機有值的項目，其餘保留線上設定）"
    DEPLOY_ARGS+=(--update-env-vars "$ENV_VARS")
else
    echo "🔑 本機沒有可用的環境變數，保留線上既有設定"
fi

gcloud run deploy $SERVICE_NAME "${DEPLOY_ARGS[@]}"

# 6. 獲取服務URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')

echo ""
echo "✅ 部署完成！"
echo "🌐 服務URL: $SERVICE_URL"
echo "🔍 健康檢查: $SERVICE_URL/api/health"
echo "📚 API文檔: $SERVICE_URL/docs"
echo ""
echo "💡 測試API:"
echo "curl $SERVICE_URL/api/health"
echo ""


