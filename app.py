from fastapi import FastAPI, HTTPException, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from mangum import Mangum
import asyncio
import os
import json
import uuid
import base64
import io
from datetime import datetime
from typing import Dict, Optional
from PIL import Image

from youtube_module import process_youtube_short
from tiktok_module import process_tiktok_video
from instagram_module import process_instagram_reel
from image_module import process_image_upload
from ai_processor import AIProcessor
from astra_db_handler import AstraDBHandler
import re
from urllib.parse import urlparse

# 載入環境變數
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="短影音分析API",
    description="智能處理YouTube Shorts、TikTok和Instagram Reels短影音的內容分析，支援自動平台檢測",
    version="2.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化AI處理器
ai_processor = AIProcessor()

# 初始化AstraDB處理器
db_handler = AstraDBHandler()

def detect_video_platform(url: str) -> str:
    """
    根據URL自動檢測影片平台
    
    Args:
        url: 影片連結
    
    Returns:
        str: 平台名稱 ("youtube", "tiktok", "instagram") 或 "unknown"
    """
    if not url or not url.strip():
        return "unknown"
    
    url = url.strip().lower()
    
    # YouTube Shorts 檢測
    # 支援格式：
    # - https://www.youtube.com/shorts/xNSo6xoFsYc
    # - https://youtube.com/shorts/xNSo6xoFsYc
    # - https://youtu.be/xNSo6xoFsYc (可能是shorts)
    if ('youtube.com' in url and '/shorts/' in url) or 'youtu.be' in url:
        return "youtube"
    
    # TikTok 檢測
    # 支援格式：
    # - https://www.tiktok.com/@username/video/1234567890
    # - https://tiktok.com/@username/video/1234567890
    # - https://vm.tiktok.com/shortlink
    if 'tiktok.com' in url:
        if '/video/' in url or '@' in url or 'vm.tiktok.com' in url:
            return "tiktok"
    
    # Instagram Reels 檢測
    # 支援格式：
    # - https://www.instagram.com/reels/DNxk7Qj5qnq/
    # - https://instagram.com/reels/DNxk7Qj5qnq/
    if 'instagram.com' in url and '/reels/' in url:
        return "instagram"
    
    return "unknown"

# 注意：Vercel部署時不支援靜態檔案掛載，僅供本地開發使用
# app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.post("/api/process")
async def process_media(
    url: Optional[str] = Form(None), 
    store_in_db: bool = Form(True),
    file: Optional[UploadFile] = File(None)
):
    """處理短影音連結或圖片上傳 - 自動檢測類型"""
    print(f"API接收到的參數: url='{url}', file={file.filename if file else None}, store_in_db={store_in_db}")
    
    # 判斷處理類型：有檔案就是圖片，有URL就是影片
    if file:
        # 圖片處理邏輯
        print("檢測到圖片上傳，啟動圖片處理流程")
        
        # 檢查檔案類型
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="請上傳有效的圖片檔案")
        
        try:
            # 讀取圖片
            image_bytes = await file.read()
            image = Image.open(io.BytesIO(image_bytes))
            
            # 處理圖片 - 使用圖片模組
            result = process_image_upload(image, file.filename, f"uploaded_image_{file.filename}")
            
            # AI處理
            ai_result = ai_processor.process_video_text(result["ai_input"])
            
            # 存儲到AstraDB (如果設置了store_in_db)
            db_result = None
            if store_in_db:
                db_result = db_handler.store_video_data(ai_result, "image")
            
            return {
                "success": True,
                "source": "image",
                "raw_data": result["raw_output"],
                "analysis": ai_result,
                "db_storage": db_result
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"處理圖片時發生錯誤: {str(e)}")
    
    elif url:
        # 影片處理邏輯（原有邏輯）
        print("檢測到影片連結，啟動影片處理流程")
        
        if not url.strip():
            raise HTTPException(status_code=400, detail="請提供有效的影片連結")
        
        # 自動檢測影片平台
        detected_source = detect_video_platform(url)
        print(f"自動檢測到的平台: {detected_source}")
        
        if detected_source == "unknown":
            raise HTTPException(status_code=400, detail="無法識別的影片連結格式，請確認連結是否為YouTube Shorts、TikTok或Instagram Reels")
        
        try:
            if detected_source == "youtube":
                # 處理YouTube Shorts
                result = process_youtube_short(url)
            elif detected_source == "tiktok":
                # 處理TikTok影片
                result = await process_tiktok_video(url)
            elif detected_source == "instagram":
                # 處理Instagram Reels
                result = await process_instagram_reel(url)
            else:
                raise HTTPException(status_code=400, detail=f"不支援的平台: {detected_source}")
            
            # AI處理
            ai_result = ai_processor.process_video_text(result["ai_input"])
            
            # 存儲到AstraDB (如果設置了store_in_db)
            db_result = None
            if store_in_db:
                db_result = db_handler.store_video_data(ai_result, detected_source)
                
            return {
                "success": True,
                "source": detected_source,
                "raw_data": result["raw_output"],
                "analysis": ai_result,
                "db_storage": db_result
            }
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"處理影片時發生錯誤: {str(e)}")
    
    else:
        raise HTTPException(status_code=400, detail="請提供影片連結或上傳圖片檔案")

@app.get("/")
async def root():
    """API根端點"""
    return {
        "message": "isMemory Upload API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }

@app.get("/api/health")
async def health_check():
    """健康檢查端點"""
    # 檢查AstraDB連接
    db_status = "connected" if db_handler.initialize_connection() else "disconnected"
    
    return {
        "status": "healthy",
        "service": "shorts-analysis-api",
        "astra_db": db_status,
        "has_openai_key": bool(os.getenv("OPENAI_API_KEY"))
    }



# Vercel 無伺服器函數處理器
handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn
    # 確保前端目錄存在
    os.makedirs("frontend", exist_ok=True)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)