import os
import uuid
import base64
import io
import json
from datetime import datetime
from typing import Dict, Optional
from PIL import Image
from openai import OpenAI
import cloudinary
import cloudinary.uploader
from cloudinary import CloudinaryImage

def upload_image_to_cloudinary(image: Image.Image, filename: str = None) -> str:
    """上傳圖片到Cloudinary並返回URL"""
    try:
        # 配置Cloudinary
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET")
        )
        
        # 將PIL Image轉換為bytes
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)
        
        # 生成唯一的public_id
        public_id = f"uploaded_images/{uuid.uuid4().hex[:12]}_{filename or 'image'}"
        
        print(f"正在上傳圖片到Cloudinary: {public_id}")
        
        # 上傳到Cloudinary
        upload_result = cloudinary.uploader.upload(
            img_buffer.getvalue(),
            public_id=public_id,
            folder="uploaded_images",
            resource_type="image",
            format="jpg",
            quality="auto:good",
            fetch_format="auto"
        )
        
        cloudinary_url = upload_result.get('secure_url')
        print(f"圖片成功上傳到Cloudinary: {cloudinary_url}")
        
        return cloudinary_url
        
    except Exception as e:
        print(f"上傳圖片到Cloudinary時發生錯誤: {str(e)}")
        raise

def process_image_upload(image: Image.Image, filename: str = None, original_path: str = "") -> Dict:
    """處理上傳的圖片"""
    try:
        print(f"開始處理圖片: {filename}, 原始路徑: {original_path}")
        
        # 1. 確保圖片是 RGB 模式
        if image.mode in ('RGBA', 'LA', 'P'):
            print(f"轉換圖片模式從 {image.mode} 到 RGB")
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            rgb_image.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = rgb_image
        
        # 2. 上傳圖片到Cloudinary獲取URL
        cloudinary_url = upload_image_to_cloudinary(image, filename)
        print(f"圖片已上傳到Cloudinary: {cloudinary_url}")
        
        # 3. 使用OpenAI進行圖片分析
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # 編碼圖像
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)
        base64_image = base64.b64encode(img_buffer.read()).decode('utf-8')
        
        print("正在調用 OpenAI GPT-4o 進行圖片分析...")
        response = client.chat.completions.create(
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
4. 重要時間：從圖片中提取任何明確提及的重要時間資訊，例如營業時間、活動日期、有效期限等。如果沒有，則回傳空字串。
5. 重要地點：從圖片中提取任何明確提及的重要地點資訊，例如地址、餐廳名稱、景點名稱等。如果沒有，則回傳空字串。

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
            max_tokens=4096,  # OpenAI gpt-4o 最大輸出token限制
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
            
            print(f"成功處理圖片 - OCR: {len(ocr_text)} 字, 描述: {len(caption)} 字, 摘要: {len(summary)} 字")
            
            # 準備標準化輸出格式（與影片處理模組一致）
            output = {
                "filename": filename or "uploaded_image.jpg",
                "ocr_text": ocr_text,
                "caption": caption,
                "summary": summary,
                "important_time": important_time,
                "important_location": important_location
            }
            
            # 轉換為AI處理需要的格式（與影片處理模組一致）
            ai_input = {
                "original_path": cloudinary_url,  # 使用Cloudinary URL作為原始路徑
                "filename": filename or "uploaded_image.jpg",  # 添加filename給資料庫使用
                "ocr_text": ocr_text,
                "caption": caption
            }
            
            return {
                "raw_output": output,
                "ai_input": ai_input
            }
            
        except json.JSONDecodeError as e:
            print(f"JSON 解析錯誤: {str(e)}")
            # 返回預設值
            output = {
                "filename": filename or "uploaded_image.jpg",
                "ocr_text": "",
                "caption": "圖片處理",
                "summary": "圖片內容",
                "important_time": "",
                "important_location": ""
            }
            
            ai_input = {
                "original_path": original_path or f"uploaded_image_{filename}",
                "ocr_text": "",
                "caption": "圖片處理"
            }
            
            return {
                "raw_output": output,
                "ai_input": ai_input
            }
            
    except Exception as e:
        print(f"處理圖片時發生錯誤: {str(e)}")
        # 返回錯誤格式
        return {
            "raw_output": {"error": str(e)},
            "ai_input": {
                "original_path": original_path or f"error_{filename}",
                "ocr_text": "",
                "caption": f"圖片處理錯誤: {str(e)}"
            }
        }
