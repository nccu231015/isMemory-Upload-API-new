from fastapi import FastAPI, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import os
import json
from typing import Dict

from youtube_module import process_youtube_short
from tiktok_module import process_tiktok_video
from instagram_module import process_instagram_reel
from ai_processor import AIProcessor
from astra_db_handler import AstraDBHandler

# 載入環境變數
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="短影音分析API",
    description="處理YouTube Shorts和TikTok短影音的內容分析",
    version="1.0.0"
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

# 掛載前端靜態文件
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.post("/api/process")
async def process_video(url: str = Form(...), source: str = Form(...), store_in_db: bool = Form(True)):
    """處理短影音連結"""
    print(f"API接收到的參數: url='{url}' (長度: {len(url) if url else 'None'}), source='{source}', store_in_db={store_in_db}")
    
    if not url:
        raise HTTPException(status_code=400, detail="請提供有效的影片連結")
    
    try:
        if source.lower() == "youtube":
            # 處理YouTube Shorts
            result = process_youtube_short(url)
        elif source.lower() == "tiktok":
            # 處理TikTok影片
            result = await process_tiktok_video(url)
        elif source.lower() == "instagram":
            # 處理Instagram Reels
            result = await process_instagram_reel(url)
        else:
            raise HTTPException(status_code=400, detail="不支援的來源平台，請選擇YouTube、TikTok或Instagram")
        
        # AI處理
        ai_result = ai_processor.process_video_text(result["ai_input"])
        
        # 存儲到AstraDB (如果設置了store_in_db)
        db_result = None
        if store_in_db:
            db_result = db_handler.store_video_data(ai_result, source.lower())
            
        return {
            "success": True,
            "source": source,
            "raw_data": result["raw_output"],
            "analysis": ai_result,
            "db_storage": db_result
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"處理影片時發生錯誤: {str(e)}")

@app.get("/")
async def read_index():
    """提供前端頁面"""
    return FileResponse('frontend/index.html')

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
    
@app.get("/api/search")
async def search_videos(query: str, limit: int = 5):
    """搜索相似影片"""
    if not query:
        raise HTTPException(status_code=400, detail="請提供有效的搜索查詢")
    
    try:
        results = db_handler.search_similar_videos(query, limit)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索影片時發生錯誤: {str(e)}")
        
@app.delete("/api/records/{document_id}")
async def delete_record(document_id: str):
    """刪除指定ID的記錄"""
    if not document_id:
        raise HTTPException(status_code=400, detail="請提供有效的文檔ID")
    
    try:
        result = db_handler.delete_record(document_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "刪除文檔失敗"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刪除文檔時發生錯誤: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # 確保前端目錄存在
    os.makedirs("frontend", exist_ok=True)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)