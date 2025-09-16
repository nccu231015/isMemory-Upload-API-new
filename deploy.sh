#!/bin/bash

# Google Cloud Run 部署腳本
# 使用方法: ./deploy.sh [PROJECT_ID]

set -e

# 檢查是否提供了PROJECT_ID
if [ -z "$1" ]; then
    echo "使用方法: ./deploy.sh [PROJECT_ID]"
    echo "例如: ./deploy.sh my-project-123"
    exit 1
fi

PROJECT_ID=$1
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
docker build -t $IMAGE_NAME .

# 4. 推送映像到Google Container Registry
echo "📤 推送映像到 Container Registry..."
docker push $IMAGE_NAME

# 5. 部署到Cloud Run
echo "🚀 部署到 Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 4Gi \
    --cpu 2 \
    --timeout 3600 \
    --max-instances 10 \
    --set-env-vars "OPENAI_API_KEY=$OPENAI_API_KEY,ASTRA_DB_APPLICATION_TOKEN=$ASTRA_DB_APPLICATION_TOKEN,ASTRA_DB_TOKEN=$ASTRA_DB_TOKEN,ASTRA_DB_API_ENDPOINT=$ASTRA_DB_API_ENDPOINT,CLOUDINARY_CLOUD_NAME=$CLOUDINARY_CLOUD_NAME,CLOUDINARY_API_KEY=$CLOUDINARY_API_KEY,CLOUDINARY_API_SECRET=$CLOUDINARY_API_SECRET,X_API_KEY=$X_API_KEY,MS_TOKEN=$MS_TOKEN"

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
