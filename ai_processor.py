import os
import json
from concurrent.futures import ThreadPoolExecutor
import requests
from openai import OpenAI
from typing import Dict


# 寫入資料庫／參與向量化的原文欄位長度上限。
# 分析用的輸入可以更長（見 process_video_text），
# 但存進 AstraDB 的原文需要有界，避免超出 embedding 輸入上限與欄位長度限制。
MAX_STORED_TEXT_CHARS = 1500


class AIProcessor:
    def __init__(self, api_key=None):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

    def _search_address_with_google_maps(self, location_name: str) -> Dict:
        """
        透過 Google Maps Places API (New) 的 text search，將地點名稱轉換為詳細資訊。
        """
        if not location_name.strip():
            return {}
        if not self.google_maps_api_key:
            # 之前這裡是無聲 return，導致「地點查不到詳細資訊」看起來像模型抽錯，
            # 實際上是根本沒帶到金鑰。
            print(
                "⚠️ 未設定 GOOGLE_MAPS_API_KEY，無法補上地址／評分／營業時間，"
                f"地點只會保留原始名稱: {location_name}"
            )
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

    def _extract_place_candidates(self, text: str) -> Dict:
        """逐段掃描長逐字稿，先把「候選地點」撈出來

        單一次呼叫要同時做摘要、下標題又要抽地點時，
        模型會傾向給出「澀谷」「東京」這種籠統的大範圍地名。
        改成把逐字稿切成小段、每段只問一件事（這段提到哪些具體場所），
        模型就會注意到「澀谷橫丁」「六本木三景花園飯店」這類真正有用的名字。
        """
        empty = {"places": [], "products_by_place": {}, "loose_products": []}
        if not text or not text.strip():
            return empty

        segment_size = 1200
        segments = [
            text[i : i + segment_size] for i in range(0, len(text), segment_size)
        ]
        # 太長的內容不無限制展開，控制成本
        segments = segments[:20]

        system_prompt = """你是一個地點與商品擷取器。從使用者提供的影片逐字稿片段中，
找出「明確提到的具體場所名稱」，以及在該場所吃到／買到的東西。

規則：
- 只找專有名稱：店名、餐廳、咖啡廳、居酒屋、飯店、商場、市場、景點、展館、公園、神社。
- 不要回傳國家、城市、行政區、商圈這類大範圍地名。
- 不要回傳機場、車站等純交通節點。
- 不要回傳一般名詞（例如「藥妝店」「便利商店」「餐廳」），除非有品牌或店名。
- 逐字稿是語音辨識結果，專有名詞可能有同音錯字。
  請輸出你判斷「最合理的正確寫法」，例如聽起來像「澀谷橫濱」但實際應為「澀谷橫丁」。
- 沒有找到就回傳空陣列。

商品的部分：
- products 放在該場所實際吃到、喝到或買到的東西（餐點、飲料、伴手禮、商品）。
- 用影片中的講法，保持簡短，例如「三層肉」「雞皮餃子」「兔兔玩偶」。
- 只是路過看到、沒有消費的不要列。
- 判斷不出屬於哪個場所的商品，放進 loose_products。

只回傳 JSON：
{"places": [{"name": "場所名", "products": ["商品1", "商品2"]}], "loose_products": ["商品3"]}"""

        def scan(segment: str) -> list:
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": segment},
                    ],
                    max_tokens=300,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                data = json.loads(response.choices[0].message.content)
                return data
            except Exception as exc:
                print(f"⚠️ 候選地點掃描失敗: {exc}")
                return {}

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(scan, segments))

        # 依出現順序去重，並把同一個場所在不同段落提到的商品合併起來
        ordered = []
        seen = set()
        products_by_place = {}
        loose_products = []

        def add_products(bucket: list, items) -> None:
            for item in items or []:
                text = str(item).strip()
                if text and text not in bucket:
                    bucket.append(text)

        for data in results:
            if not isinstance(data, dict):
                continue
            for entry in data.get("places") or []:
                if isinstance(entry, str):
                    name, items = entry.strip(), []
                elif isinstance(entry, dict):
                    name = str(entry.get("name", "")).strip()
                    items = entry.get("products") or []
                else:
                    continue
                if not name:
                    continue
                key = name.lower()
                if key not in seen:
                    seen.add(key)
                    ordered.append(name)
                    products_by_place[name] = []
                add_products(products_by_place[name], items)
            add_products(loose_products, data.get("loose_products"))

        if ordered:
            print(f"🔎 逐段掃描找到 {len(ordered)} 個候選地點: {' / '.join(ordered[:12])}")
        total_products = sum(len(v) for v in products_by_place.values()) + len(loose_products)
        if total_products:
            print(f"🛍️ 逐段掃描找到 {total_products} 個候選商品")

        return {
            "places": ordered,
            "products_by_place": products_by_place,
            "loose_products": loose_products,
        }

    def process_video_text(self, input_data: Dict) -> Dict:
        """使用LLM處理文字資訊"""
        original_path = input_data.get("original_path", "")
        ocr_text = input_data.get("ocr_text", "")
        caption = input_data.get("caption", "")

        # 長影片（例如數十分鐘的 vlog）會走訪很多地方，
        # 摘要與地點數量都需要放寬，否則模型只會回傳籠統的大範圍地名。
        content_length = len(ocr_text or "") + len(caption or "")
        is_long_form = content_length > 2000
        summary_limit = 120 if is_long_form else 50
        # 短貼文也常在說明欄列出一整串景點（例如「分享10個私房景點」），
        # 上限太低會只留下最前面的住宿或交通，真正推薦的景點反而被截掉。
        max_locations = 15

        # 長影片先做一次「逐段候選抽取」，把具體店名撈出來再交給主要分析。
        # 短影片內容集中，單次呼叫就夠準，不需要多花這些錢。
        scan = {"places": [], "products_by_place": {}, "loose_products": []}
        if is_long_form:
            # 說明欄也要掃，否則說明欄列出的店名不在候選清單裡，會被主要分析排除
            scan = self._extract_place_candidates(
                "\n".join(part for part in (ocr_text, caption) if part)
            )
        place_candidates = scan["places"]

        # 準備系統提示詞
        system_prompt = """請對提供的影片文字內容進行以下分析，並以 JSON 格式回傳：

1. ocr_text：一律回傳空字串（後端會自行填入原文，不需要你複述）
2. caption：一律回傳空字串（後端會自行填入原文，不需要你複述）
3. summary：基於文字內容和字幕，生成重點摘要（{summary_limit}字以內）
4. title：生成一個吸引人的標題（20字以內），要能準確反映內容主題，適合作為影片或圖片的標題
5. important_time：從文字中提取任何明確提及的重要時間資訊，例如營業時間、活動日期、有效期限等。如果沒有，則回傳空字串。
6. important_location：提取內容中明確提到、且能在 Google 地圖上搜尋到的「具體地點名稱」。
   - 優先抽取專有名稱：店名、餐廳、咖啡廳、飯店、商場、市場、景點、展館、車站（例如：澀谷橫丁、唐吉訶德、六本木之丘、teamLab）。
   - 不要只回傳國家、都道府縣、城市或行政區這類大範圍地名（例如：日本、東京、澀谷、六本木）。
     只有在整段內容完全沒有提到任何具體場所時，才退而使用大範圍地名。
   - 交通節點（機場、車站、公車站）只是移動過程時一律不要列入。
   - 航空公司、租車行、交通業者、贊助品牌本身不是要去的地點，不要列入。
   - 行政區、商圈名稱（例如：澀谷、原宿、六本木、信義區）本身不要單獨列入；
     若該區域內有提到具體店家或設施，請列出那個具體名稱而不是區域名。
   - 依照內容中出現的順序列出，不要重複，最多 {max_locations} 個，用「/」隔開。
   - 說明欄或時間軸章節裡列出的店名同樣要納入；
     說明欄若以清單列出景點（例如「▶︎」「📍」「1.」開頭，或「分享10個景點」），清單中每一項都必須列入，不可只取前幾個。
   - 超過上限時，優先保留內容主要推薦或實際造訪的景點、店家，其次才是住宿。
   - 若逐字稿中的店名疑似音譯錯字，請以最合理的正確寫法輸出。
   - 如果有提供「候選地點清單」，請以該清單為主要依據挑選，不要自行發明清單外的地點；
     但可以修正清單中明顯的同音錯字。
   - 如果沒有，則回傳空字串。
7. products：影片中實際吃到、喝到或買到的東西（餐點、飲料、伴手禮、商品）。
   - 用影片中的講法，保持簡短，例如「三層肉」「雞皮餃子」「兔兔玩偶」。
   - 只是路過看到、沒有消費的不要列。如果有提供候選商品清單，請以該清單為準。
   - 最多 15 個。沒有就回傳空陣列。
8. todos：影片中提到「事前要做的事」，例如需要預約、換錢、買票、辦網卡、線上登錄。沒有就回傳空陣列。
9. tips：影片中提到的注意事項或行前須知，例如穿著建議、禁止事項、排隊技巧、營業時間陷阱。沒有就回傳空陣列。
10. address：`important_location` 中每個地點在內容裡「明確寫出的地址」（例如說明欄的「📍店名 台北市松山區三民路146號」）。
   - 依照 important_location 的順序，用「/」隔開，數量要與 important_location 一致；某個地點沒有寫出地址就留空（例如「台北市松山區三民路146號 / 」）。
   - 只能照抄內容中出現的地址，不要自行推測或編造。
   - 若 important_location 本身就是完整地址，填入相同內容。
   - 整段內容都沒有寫出任何地址，回傳空字串。
11. region：內容主要所在的城市或地區（例如：金門、東京、台南），用來輔助地圖查詢同名店家；判斷不出來就回傳空字串。

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
    "ocr_text": "",
    "caption": "",
    "summary": "整合摘要，例如：星巴克咖啡店內用餐區，顧客使用筆電工作",
    "title": "吸引人的標題，例如：星巴克咖啡店工作日常",
    "important_time": "例如：週一至週五 09:00-18:00，如果沒有則回傳空字串",
    "important_location": "例如：台北101 / 象山步道，如果沒有則回傳空字串",
    "address": "例如：台北市信義區信義路五段7號 / ，內容中沒寫出地址則回傳空字串",
    "region": "例如：台北",
    "products": ["三層肉", "雞皮餃子"],
    "todos": ["需要事先線上預約"],
    "tips": ["假日人多建議早點去"],
    "original_path": "保留原始連結"
}"""

        # 這段提示詞本身包含 JSON 大括號，不能用 str.format()，
        # 改用明確的字串替換帶入長度上限。
        system_prompt = system_prompt.replace(
            "{summary_limit}", str(summary_limit)
        ).replace("{max_locations}", str(max_locations))

        try:
            # 更徹底的文字清理，移除所有可能導致JSON錯誤的字符
            import re

            def clean_text(text):
                if not text:
                    return ""
                # 只移除控制字元；保留換行與「▶︎」「📍」等符號，
                # 說明欄的景點清單靠這些結構才看得出是一項一項的地點。
                text = re.sub(r"[\x00-\x09\x0b-\x1f\x7f\u200b-\u200f\ufeff]", " ", text)
                text = re.sub(r"[ \t\u3000]+", " ", text)
                text = re.sub(r" *\n *", "\n", text)
                text = re.sub(r"\n{3,}", "\n\n", text)
                return text.strip()

            # 限制長度避免超出token限制。
            # 字幕上限放寬到 28000 字，足以涵蓋約 100 分鐘的中文逐字稿，
            # 長影片才不會只剩開頭幾句就被截掉（gpt-4o 有 128k context）。
            # 由於已改為不讓模型複述 ocr_text / caption，
            # 輸出長度不會因為輸入變長而爆掉 max_tokens。
            clean_ocr_text = clean_text(ocr_text)[:2000]
            clean_caption = clean_text(caption)[:28000]

            scanned_products_fallback = []
            user_message = (
                f"文字內容：{clean_ocr_text}\n\n"
                f"字幕內容：{clean_caption}\n\n"
                f"原始連結：{original_path}"
            )
            if place_candidates:
                candidate_line = " / ".join(place_candidates[:30])
                user_message += f"\n\n候選地點清單（由逐字稿逐段掃描取得）：{candidate_line}"

            scanned_products = []
            for items in scan["products_by_place"].values():
                scanned_products.extend(items)
            scanned_products.extend(scan["loose_products"])
            scanned_products_fallback = list(scanned_products)
            if scanned_products:
                user_message += (
                    "\n\n候選商品清單（由逐字稿逐段掃描取得）："
                    + " / ".join(scanned_products[:40])
                )

            # 呼叫LLM進行處理
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_message,
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
                "region",
                "products",
                "todos",
                "tips",
            ]
            for field in required_fields:
                if field not in result:
                    if field in ["important_location", "address", "products", "todos", "tips"]:
                        result[field] = []
                    else:
                        result[field] = ""

            # ocr_text / caption 一律以原始輸入為準，
            # 避免模型複述時被 max_tokens 截斷或改寫內容。
            # 這兩個欄位會一起被寫入 AstraDB 並參與向量化，
            # 因此仍需截斷：完整逐字稿（長影片可達數萬字）會超出
            # embedding 模型的輸入上限，也可能撐爆單一欄位的長度限制。
            for field in ("products", "todos", "tips"):
                value = result.get(field)
                if isinstance(value, str):
                    value = [v.strip() for v in value.split("/") if v.strip()]
                result[field] = [str(v).strip() for v in (value or []) if str(v).strip()]

            # 掃描到的商品沒被模型收錄時，補回去避免漏掉
            if not result["products"] and scanned_products_fallback:
                result["products"] = scanned_products_fallback[:15]

            result["ocr_text"] = ocr_text[:MAX_STORED_TEXT_CHARS]
            result["caption"] = caption[:MAX_STORED_TEXT_CHARS]

            # 處理 Google Maps 詳細資訊查詢的自動補充邏輯
            # 優先用店名（important_location）查詢，能帶出評分、營業時間等完整細節
            # 若無店名才退而使用 address（純地址，只能抓到座標）
            def split_field(value, keep_empty=False) -> list:
                # 模型偶爾會回傳陣列而不是「/」分隔字串，兩種都要接受
                if isinstance(value, list):
                    value = "/".join(str(v) for v in value)
                parts = [
                    part.strip()
                    for part in str(value or "").replace("｜｜｜", "/").split("/")
                ]
                return parts if keep_empty else [p for p in parts if p]

            locations = split_field(result.get("important_location"))
            text_addresses = split_field(result.get("address"), keep_empty=True)
            if not locations:
                locations = [a for a in text_addresses if a]
                text_addresses = list(locations)

            region = str(result.get("region") or "").strip()

            # 說明欄寫出的地址要跟地點一一對應；數量對不上時只信任單一地點的情況
            if len(text_addresses) != len(locations):
                found = [a for a in text_addresses if a]
                text_addresses = (
                    found[:1] if len(locations) == 1 else []
                ) + [""] * len(locations)
            text_addresses = text_addresses[: len(locations)]

            if locations:
                addresses = []
                all_details = []

                for loc, text_address in zip(locations, text_addresses):
                    # 店名加上說明欄的地址一起查，避免同名分店或撞名查到別處
                    query = loc
                    if text_address and text_address not in loc:
                        query = f"{loc} {text_address}"
                    elif region and region not in loc:
                        # 「時苑」「耐心有限公司」這類名稱太通用，不加地區會查到別的縣市
                        query = f"{loc} {region}"
                    details = self._search_address_with_google_maps(query)
                    if details and details.get("address"):
                        # 找到詳細資訊
                        addresses.append(details["address"])
                        all_details.append(details)
                    else:
                        # 查不到（或沒有 Maps 金鑰）時，優先保留內容中寫出的地址，
                        # 沒有才退回地點名稱
                        fallback = text_address or loc
                        addresses.append(fallback)
                        all_details.append({"address": fallback})

                # 把逐段掃描到的商品掛回各自的地點，
                # 讓前端能在每個景點卡片上顯示「這裡吃了/買了什麼」
                products_by_place = scan["products_by_place"]
                if products_by_place:
                    for loc_name, detail in zip(locations, all_details):
                        matched = products_by_place.get(loc_name)
                        if matched is None:
                            # 模型可能修正過錯字，用包含關係再比對一次
                            for key, items in products_by_place.items():
                                if key in loc_name or loc_name in key:
                                    matched = items
                                    break
                        if matched:
                            detail["products"] = list(matched)

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
