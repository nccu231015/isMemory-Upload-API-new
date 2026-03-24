import os
import json
import requests
from openai import OpenAI
from typing import Dict


class AIProcessor:
    def __init__(self, api_key=None):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

    def _search_address_with_google_maps(self, location_name: str) -> Dict:
        """
        透過 Google Maps Places API (New) 的 text search，將地點名稱轉換為詳細資訊。
        """
        if not self.google_maps_api_key or not location_name.strip():
            return {}

        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.google_maps_api_key,
            "X-Goog-FieldMask": "places.formattedAddress,places.rating,places.priceLevel,places.priceRange,places.regularOpeningHours,places.location,places.websiteUri,places.nationalPhoneNumber,places.paymentOptions",
        }
        payload = {"textQuery": location_name, "languageCode": "zh-TW"}

        try:
            print(f"正在透過 Google Maps API 查詢地點詳細資訊: {location_name}")
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                places = data.get("places", [])
                if places:
                    place = places[0]
                    # 返回第一個匹配的地點資訊
                    return {
                        "address": place.get("formattedAddress", ""),
                        "rating": place.get("rating"),
                        "priceLevel": place.get("priceLevel"),
                        "priceRange": place.get("priceRange"),
                        "regularOpeningHours": place.get("regularOpeningHours"),
                        "location": place.get("location"),
                        "websiteUri": place.get("websiteUri"),
                        "nationalPhoneNumber": place.get("nationalPhoneNumber"),
                        "paymentOptions": place.get("paymentOptions"),
                    }
                else:
                    print(f"⚠️ 找不到該地點的資訊: {location_name}")
            else:
                print(
                    f"⚠️ Google Maps API 查詢失敗: {response.status_code} - {response.text}"
                )
        except Exception as e:
            print(f"⚠️ 查詢 Google Maps API 時發生錯誤: {e}")

        return {}

    def process_video_text(self, input_data: Dict) -> Dict:
        """使用LLM處理文字資訊"""
        original_path = input_data.get("original_path", "")
        ocr_text = input_data.get("ocr_text", "")
        caption = input_data.get("caption", "")

        # 準備系統提示詞
        system_prompt = """請對提供的短影音文字內容進行六項分析，並以 JSON 格式回傳：

1. ocr_text：保留原有的文字內容
2. caption：保留原有的字幕內容
3. summary：基於文字內容和字幕，生成一個簡潔有力的重點摘要（50字以內）
4. title：生成一個吸引人的標題（20字以內），要能準確反映內容主題，適合作為影片或圖片的標題
5. important_time：從文字中提取任何明確提及的重要時間資訊，例如營業時間、活動日期、有效期限等。如果沒有，則回傳空字串。
6. important_location：從文字中提取任何明確提及的重要地點資訊，例如景點名稱、餐廳名稱、品牌名等。如果有多個地點，請用「/」隔開（例如：A咖啡廳 / B咖啡廳 / C咖啡廳）。如果沒有，則回傳空字串。
7. address：請判斷提取出來的 `important_location` 是否本身就是一個「完整的詳細地址」（例如：台北市信義區市府路45號）。
   - 如果是完整地址，請將該相同內容填入此欄位。
   - 如果不是完整地址（只是地點名稱，例如：台北101、台中洲際棒球場）或者沒有提取出任何地點，請填入「空字串」。

摘要應該：
- 結合文字內容和字幕的重點資訊
- 突出重要的內容（如品牌、地點、物件、活動、特定名稱如餐廳、店面等）
- 用繁體中文表達
- 適合作為短影音的標籤或分類

標題應該：
- 簡潔有力，20字以內
- 準確反映內容的主要主題
- 吸引人且易於理解
- 用繁體中文表達
- 適合作為影片或圖片的標題

如果內容中有著名景點、特色美食、知名建築、品牌、遊戲等內容，請在摘要和標題中明確指出。

請嚴格按照以下 JSON 格式回傳：
{
    "ocr_text": "原始的文字內容，保持原始格式",
    "caption": "原始的字幕內容",
    "summary": "整合摘要，例如：星巴克咖啡店內用餐區，顧客使用筆電工作",
    "title": "吸引人的標題，例如：星巴克咖啡店工作日常",
    "important_time": "例如：週一至週五 09:00-18:00，如果沒有則回傳空字串",
    "important_location": "例如：台北101 / 象山步道，如果沒有則回傳空字串",
    "address": "如果 important_location 就是完整地址則填入；若只是名稱則回傳空字串",
    "original_path": "保留原始連結"
}"""

        try:
            # 更徹底的文字清理，移除所有可能導致JSON錯誤的字符
            import re

            def clean_text(text):
                if not text:
                    return ""
                # 移除特殊字符和控制字符
                text = re.sub(
                    r"[^\w\s\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff.,!?()【】「」：；。，！？（）]",
                    " ",
                    text,
                )
                # 移除多餘空格
                text = re.sub(r"\s+", " ", text)
                return text.strip()

            clean_ocr_text = clean_text(ocr_text)[:800]  # 限制長度避免超出token限制
            clean_caption = clean_text(caption)[:400]

            # 呼叫LLM進行處理
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"文字內容：{clean_ocr_text}\n\n字幕內容：{clean_caption}\n\n原始連結：{original_path}",
                    },
                ],
                max_tokens=4096,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            response_content = response.choices[0].message.content
            print(f"AI回應內容: {response_content[:200]}...")  # 調試用

            result = json.loads(response_content)
            result["original_path"] = original_path

            # 確保所有必要的欄位都存在
            required_fields = [
                "ocr_text",
                "caption",
                "summary",
                "title",
                "important_time",
                "important_location",
                "address",
            ]
            for field in required_fields:
                if field not in result:
                    if field in ["important_location", "address"]:
                        result[field] = []
                    else:
                        result[field] = ""

            # 處理 Google Maps 詳細資訊查詢的自動補充邏輯
            # 優先用店名（important_location）查詢，能帶出評分、營業時間等完整細節
            # 若無店名才退而使用 address（純地址，只能抓到座標）
            search_query = result.get("important_location") or result.get("address")
            
            if search_query:
                locations = [
                    loc.strip()
                    for loc in search_query.replace("｜｜｜", "/").split("/")
                    if loc.strip()
                ]
                
                addresses = []
                all_details = []
                
                for loc in locations:
                    details = self._search_address_with_google_maps(loc)
                    if details and details.get("address"):
                        # 找到詳細資訊
                        addresses.append(details["address"])
                        all_details.append(details)
                    else:
                        # 找不到詳細資訊則保留原始查詢字串
                        addresses.append(loc)
                        all_details.append({"address": loc})

                # 更新欄位為陣列格式 (即使只有一個也是 array)
                result["important_location"] = locations
                result["address"] = addresses
                result["all_location_details"] = all_details

                # 將第一個地點的詳細資訊拉到頂層以便相容舊有的單一地點顯示邏輯
                if all_details:
                    d = all_details[0]
                    result["rating"] = d.get("rating")
                    result["priceLevel"] = d.get("priceLevel")
                    result["priceRange"] = d.get("priceRange")
                    result["regularOpeningHours"] = d.get("regularOpeningHours")
                    result["location"] = d.get("location")
                    result["websiteUri"] = d.get("websiteUri")
                    result["nationalPhoneNumber"] = d.get("nationalPhoneNumber")
                    result["paymentOptions"] = d.get("paymentOptions")

            return result

        except json.JSONDecodeError as e:
            print("=" * 80)
            print("❌ JSON解析錯誤詳細資訊:")
            print(f"錯誤訊息: {e}")
            print(f"錯誤位置: line {e.lineno}, column {e.colno}")
            print(f"錯誤字符位置: {e.pos}")
            print("完整AI回應內容:")
            print("-" * 40)
            if "response" in locals():
                full_response = response.choices[0].message.content
                print(full_response)
                print("-" * 40)
                print(f"回應長度: {len(full_response)} 字符")

                # 顯示錯誤位置附近的內容
                if e.pos < len(full_response):
                    start = max(0, e.pos - 50)
                    end = min(len(full_response), e.pos + 50)
                    print(f"錯誤位置附近內容 (位置 {e.pos}):")
                    print(f"'{full_response[start:end]}'")
                    print(" " * (e.pos - start) + "^" + " <- 錯誤位置")
            else:
                print("無法獲取AI回應內容")
            print("=" * 80)

            return {
                "ocr_text": ocr_text,
                "caption": caption,
                "summary": "JSON解析失敗",
                "title": "標題生成失敗",
                "important_time": "",
                "important_location": [],
                "address": [],
                "original_path": original_path,
            }
        except Exception as e:
            print(f"AI處理錯誤: {e}")
            return {
                "ocr_text": ocr_text,
                "caption": caption,
                "summary": "無法產生摘要",
                "title": "無法產生標題",
                "important_time": "",
                "important_location": [],
                "address": [],
                "original_path": original_path,
            }
