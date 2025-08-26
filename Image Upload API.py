"""
圖片上傳API服務器 - 完整的獨立部署版本
可直接運行，無需額外依賴文件
"""

import os
import logging
import uuid
import base64
import io
import json
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

# 第三方套件
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image
import uvicorn
from openai import OpenAI
from langchain_openai import OpenAIEmbeddings
from astrapy import DataAPIClient
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== 內建的視覺模型類 ====================
class InlineVisionModel:
    """內建的視覺模型：同時執行 OCR 和圖片描述生成"""
    
    def __init__(self, api_key=None):
        self.client = None
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        
    def load_model(self):
        """初始化 OpenAI 客戶端"""
        try:
            if not self.api_key:
                raise ValueError("未設定 OpenAI API Key")
            
            logger.info("正在初始化 OpenAI 整合視覺客戶端...")
            self.client = OpenAI(api_key=self.api_key)
            logger.info("OpenAI 整合視覺客戶端初始化完成")
            
        except Exception as e:
            logger.error(f"初始化 OpenAI 整合視覺客戶端時發生錯誤: {str(e)}")
            raise

    def encode_image(self, image):
        """將 PIL 圖像編碼為 base64 字符串"""
        try:
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            img_buffer = io.BytesIO()
            image.save(img_buffer, format='JPEG', quality=95)
            img_buffer.seek(0)
            
            base64_image = base64.b64encode(img_buffer.read()).decode('utf-8')
            return base64_image
            
        except Exception as e:
            logger.error(f"編碼圖像時發生錯誤: {str(e)}")
            raise

    def process_image_from_pil(self, image: Image.Image) -> Dict[str, str]:
        """從 PIL 圖像同時進行 OCR、圖片描述生成和整合摘要"""
        if not self.client:
            self.load_model()
            
        try:
            # 編碼圖像
            base64_image = self.encode_image(image)
            
            # 使用 OpenAI 同時進行 OCR、圖片描述和整合摘要
            logger.info("正在調用 OpenAI GPT-4o 進行 OCR、圖片描述和整合摘要...")
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """請對這張圖片進行五項分析，並以 JSON 格式回傳：

1. OCR 文字辨識：提取圖片中所有可見的文字內容。
2. 圖片描述：用繁體中文簡潔地描述圖片的主要物件和場景。
3. 整合摘要：基於 OCR 文字和圖片描述，生成一個簡潔有力的重點摘要（50字以內）。
4. 重要時間：從圖片中提取任何明確提及的重要時間資訊，例如營業時間、活動日期、有效期限等。如果沒有，則回傳空字串。請勿包含圖片拍攝時間或手機狀態列的時間，必須精準判斷。
5. 重要地點：從圖片中提取任何明確提及的重要地點資訊，例如地址、餐廳名稱、景點名稱等。如果沒有，則回傳空字串。

整合摘要應該：
- 結合 OCR 文字和視覺元素的重點資訊
- 突出重要的內容（如品牌、地點、物件、活動、特定名稱如餐廳、店面等），但不要過度描述
- 用繁體中文表達
- 適合作為圖片的標籤或分類

如果圖片中有著名景點、特色美食、知名建築、品牌、遊戲等內容，請在描述和摘要中明確指出。

請嚴格按照以下 JSON 格式回傳：
{
    "ocr_text": "從圖片中提取的所有文字內容，保持原始換行格式",
    "caption": "圖片的繁體中文描述，例如：房間裡有一張桌子，桌上有筆記本電腦、書本和台燈",
    "summary": "整合摘要，例如：星巴克咖啡店內用餐區，顧客使用筆電工作",
    "important_time": "例如：週一至週五 09:00-18:00，如果沒有則回傳空字串",
    "important_location": "例如：台北101，如果沒有則回傳空字串"
}

如果圖片中沒有文字，ocr_text 請回傳空字串。"""
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1200,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            
            try:
                result = json.loads(content)
                ocr_text = result.get("ocr_text", "").strip()
                caption = result.get("caption", "").strip()
                summary = result.get("summary", "").strip()
                important_time = result.get("important_time", "").strip()
                important_location = result.get("important_location", "").strip()
                
                logger.info(f"成功處理圖片 - OCR: {len(ocr_text)} 字, 描述: {len(caption)} 字, 摘要: {len(summary)} 字, 重要時間: {important_time}, 重要地點: {important_location}")
                
                return {
                    "ocr_text": ocr_text,
                    "caption": caption,
                    "summary": summary,
                    "important_time": important_time,
                    "important_location": important_location,
                    "success": True
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析錯誤: {str(e)}")
                return {
                    "ocr_text": "",
                    "caption": "圖片處理",
                    "summary": "圖片內容",
                    "important_time": "",
                    "important_location": "",
                    "success": True
                }
                
        except Exception as e:
            logger.error(f"處理圖片時發生錯誤: {str(e)}")
            return {
                "ocr_text": "",
                "caption": "",
                "summary": "",
                "important_time": "",
                "important_location": "",
                "success": False,
                "error": str(e)
            }

# ==================== 內建的上傳服務類 ====================
class InlineMobileUploadService:
    """內建的手機上傳服務"""
    
    def __init__(self, 
                 astra_db_api_endpoint=None, 
                 astra_db_token=None, 
                 openai_api_key=None,
                 collection_name="image_vectors"):
        
        self.astra_db_api_endpoint = astra_db_api_endpoint
        self.astra_db_token = astra_db_token
        self.collection_name = collection_name
        
        # 初始化整合視覺模型
        self.vision_model = InlineVisionModel(api_key=openai_api_key)
        
        # 初始化向量化模型
        self.embeddings = OpenAIEmbeddings(
            openai_api_key=openai_api_key,
            model="text-embedding-3-small",
            dimensions=1536  # 使用1536維度以匹配AstraDB集合
        )
        
        # 初始化 AstraDB 客戶端和集合
        self.astra_client = None
        self.database = None
        self.collection = None
        
    def initialize_astradb(self):
        """初始化 AstraDB 連接"""
        try:
            logger.info("正在初始化 AstraDB 連接...")
            
            self.astra_client = DataAPIClient(self.astra_db_token)
            self.database = self.astra_client.get_database(self.astra_db_api_endpoint)
            
            collections = self.database.list_collections()
            collection_names = [col.name for col in collections]
            
            if self.collection_name not in collection_names:
                logger.info(f"創建新集合: {self.collection_name}")
                self.collection = self.database.create_collection(
                    name=self.collection_name,
                    definition={
                        'vector': {
                            'dimension': 1536,  # 使用1536維度以匹配現有圖片記錄
                            'metric': 'cosine'
                        }
                    }
                )
            else:
                logger.info(f"使用現有集合: {self.collection_name}")
                self.collection = self.database.get_collection(self.collection_name)
            
            logger.info("AstraDB 連接初始化完成")
            
        except Exception as e:
            logger.error(f"初始化 AstraDB 連接失敗: {str(e)}")
            raise
    
    def process_mobile_image(self, image: Image.Image, original_path: str, filename: str = None) -> Dict:
        """處理手機相簿圖片"""
        try:
            if not self.collection:
                self.initialize_astradb()
            
            logger.info(f"開始處理手機圖片: {filename}, 原始路徑: {original_path}")
            
            # 1. 確保圖片是 RGB 模式
            if image.mode in ('RGBA', 'LA', 'P'):
                logger.info(f"轉換圖片模式從 {image.mode} 到 RGB")
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                rgb_image.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = rgb_image
            
            # 2. 使用整合模型進行 OCR、Caption 和 Summary 生成
            logger.info("正在使用整合模型進行 OCR、圖片描述和摘要生成...")
            vision_result = self.vision_model.process_image_from_pil(image)
            
            if not vision_result.get("success"):
                error_msg = vision_result.get("error", "視覺處理失敗")
                logger.error(f"視覺處理失敗: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg
                }
            
            ocr_text = vision_result.get("ocr_text", "")
            caption_text = vision_result.get("caption", "")
            summary_text = vision_result.get("summary", "")
            important_time = vision_result.get("important_time", "")
            important_location = vision_result.get("important_location", "")
            
            # 3. 合併文字內容（用於向量化）
            combined_text = f"圖片描述：{caption_text}"
            if ocr_text.strip():
                combined_text += f"\n文字內容：{ocr_text}"
            
            # 4. 生成向量
            logger.info("正在生成向量...")
            embedding = self.embeddings.embed_query(combined_text)
            
            # 5. 準備文檔數據（存儲原始路徑，確保欄位一致）
            document_id = str(uuid.uuid4())
            document = {
                "_id": document_id,
                "$vector": embedding,
                "text": combined_text,
                "metadata": {
                    "document_id": document_id,
                    "filename": filename or f"image_{document_id[:8]}.jpg",
                    "ocr_text": ocr_text,
                    "caption": caption_text,
                    "summary": summary_text,
                    "important_time": important_time,
                    "important_location": important_location,
                    "original_path": original_path,  # 原始路徑（網路連結）
                    "image_path": f"image_storage/original/{filename or f'image_{document_id[:8]}.jpg'}",  # 虛擬本地路徑
                    "upload_time": datetime.now().isoformat(),
                    "content_type": "image"  # 使用與現有記錄一致的內容類型
                }
            }
            
            # 6. 存儲到 AstraDB
            logger.info("正在存儲到 AstraDB...")
            result = self.collection.insert_one(document)
            
            logger.info(f"手機圖片處理完成，文檔 ID: {document_id}")
            logger.info(f"原始路徑: {original_path}")
            
            # 7. 返回與原本資料庫存儲相同的格式
            return {
                "document_id": document_id,
                "ocr_text": ocr_text,
                "caption": caption_text,
                "summary": summary_text,
                "important_time": important_time,
                "important_location": important_location,
                "combined_text": combined_text,
                "original_path": original_path,
                "image_path": document["metadata"]["image_path"],
                "success": True,
                "storage_result": {
                    "database_document": document,
                    "inserted_id": document_id
                }
            }
            
        except Exception as e:
            logger.error(f"處理手機圖片時發生錯誤: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

# ==================== API 請求模型 ====================
class MobileImageUploadRequest(BaseModel):
    original_path: str  # 原始圖片網路連結
    filename: Optional[str] = None
    device_id: Optional[str] = None

# ==================== FastAPI 應用 ====================
app = FastAPI(
    title="手機相簿圖片上傳API",
    description="專門處理手機相簿圖片的AI分析和向量化存儲",
    version="1.0.0"
)

# 添加 CORS 支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化上傳服務
upload_service = InlineMobileUploadService(
    astra_db_api_endpoint=os.getenv('ASTRA_DB_API_ENDPOINT'),
    astra_db_token=os.getenv('ASTRA_DB_TOKEN'),
    openai_api_key=os.getenv('OPENAI_API_KEY'),
    collection_name=os.getenv('ASTRA_DB_COLLECTION_NAME', 'image_vectors')
)

# ==================== API 端點 ====================

@app.post("/api/upload-mobile-image")
async def upload_mobile_image(
    original_path: str = Form(...),
    filename: str = Form(None),
    device_id: str = Form(None),
    file: UploadFile = File(...)
):
    """
    上傳手機相簿圖片進行AI處理
    
    Args:
        original_path: 圖片的原始網路連結（前端提供，後端原樣存儲）
        filename: 原始文件名
        device_id: 設備識別ID（可選）
        file: 圖片文件
    
    Returns:
        處理結果，包含OCR、描述、摘要和資料庫存儲信息
    """
    try:
        # 讀取上傳的圖片
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))
        
        # 使用上傳服務處理圖片
        result = upload_service.process_mobile_image(
            image=image,
            original_path=original_path,  # 存儲原始網路路徑
            filename=filename or file.filename
        )
        
        if result["success"]:
            logger.info(f"圖片處理成功: {original_path}")
            return {
                "success": True,
                "message": "圖片處理完成",
                "data": result
            }
        else:
            logger.error(f"圖片處理失敗: {result.get('error')}")
            raise HTTPException(status_code=500, detail=result.get("error"))
            
    except Exception as e:
        logger.error(f"API 處理錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"處理圖片時發生錯誤: {str(e)}")

@app.get("/api/health")
async def health_check():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "mobile-upload-api"
    }

@app.get("/api/config")
async def get_config():
    """獲取配置信息"""
    return {
        "astra_db_configured": bool(os.getenv('ASTRA_DB_API_ENDPOINT')),
        "openai_configured": bool(os.getenv('OPENAI_API_KEY')),
        "collection_name": os.getenv('ASTRA_DB_COLLECTION_NAME', 'image_vectors')
    }

# ==================== 主程序 ====================
if __name__ == "__main__":
    # 檢查必要的環境變數
    required_env_vars = [
        'OPENAI_API_KEY',
        'ASTRA_DB_API_ENDPOINT',
        'ASTRA_DB_TOKEN'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ 缺少必要的環境變數: {', '.join(missing_vars)}")
        print("請在 .env 文件中設定以下環境變數:")
        for var in missing_vars:
            print(f"  {var}=your_value_here")
        exit(1)
    
    logger.info("🚀 啟動手機相簿圖片上傳API服務器...")
    
    # 啟動服務器
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        log_level="info"
    ) 
