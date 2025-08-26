import os
import json
from openai import OpenAI
from typing import Dict

class AIProcessor:
    def __init__(self, api_key=None):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    
    def process_video_text(self, input_data: Dict) -> Dict:
        """使用LLM處理文字資訊"""
        original_path = input_data.get("original_path", "")
        ocr_text = input_data.get("ocr_text", "")
        caption = input_data.get("caption", "")
        
        # 準備系統提示詞
        system_prompt = """請對提供的短影音文字內容進行五項分析，並以 JSON 格式回傳：

1. ocr_text：保留原有的文字內容
2. caption：保留原有的字幕內容
3. summary：基於文字內容和字幕，生成一個簡潔有力的重點摘要（50字以內）
4. important_time：從文字中提取任何明確提及的重要時間資訊，例如營業時間、活動日期、有效期限等。如果沒有，則回傳空字串。
5. important_location：從文字中提取任何明確提及的重要地點資訊，例如地址、餐廳名稱、景點名稱等。如果沒有，則回傳空字串。

摘要應該：
- 結合文字內容和字幕的重點資訊
- 突出重要的內容（如品牌、地點、物件、活動、特定名稱如餐廳、店面等）
- 用繁體中文表達
- 適合作為短影音的標籤或分類

如果內容中有著名景點、特色美食、知名建築、品牌、遊戲等內容，請在摘要中明確指出。

請嚴格按照以下 JSON 格式回傳：
{
    "ocr_text": "原始的文字內容，保持原始格式",
    "caption": "原始的字幕內容",
    "summary": "整合摘要，例如：星巴克咖啡店內用餐區，顧客使用筆電工作",
    "important_time": "例如：週一至週五 09:00-18:00，如果沒有則回傳空字串",
    "important_location": "例如：台北101，如果沒有則回傳空字串",
    "original_path": "保留原始連結"
}"""
        
        try:
            # 呼叫LLM進行處理
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"文字內容：{ocr_text}\n\n字幕內容：{caption}\n\n原始連結：{original_path}"}
                ],
                max_tokens=1200,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            result["original_path"] = original_path
            
            return result
            
        except Exception as e:
            print(f"AI處理錯誤: {e}")
            return {
                "ocr_text": ocr_text,
                "caption": caption,
                "summary": "無法產生摘要",
                "important_time": "",
                "important_location": "",
                "original_path": original_path
            }