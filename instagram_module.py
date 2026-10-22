import os
import base64
import requests
import json
import subprocess
from typing import Dict, List, Optional
from openai import OpenAI
from dotenv import load_dotenv
import asyncio
import tempfile
import time
import re
from urllib.parse import urlsplit, urlunsplit

import yt_dlp
from curl_cffi import requests as curl_requests

# 載入環境變數
load_dotenv()

# 輪播貼文最多處理的媒體數量（避免單篇貼文耗費過多時間與費用）
# Instagram 輪播上限為 20 則，因此圖片預設全部處理，可用環境變數調整。
MAX_VIDEOS = int(os.getenv("IG_MAX_VIDEOS", "3"))
MAX_IMAGES = int(os.getenv("IG_MAX_IMAGES", "20"))

# Instagram 網頁版使用的 App ID，呼叫站內 API 時必須帶上
IG_APP_ID = "936619743392459"
# shortcode 使用的 base64 字元表，用來換算成 media id
_SHORTCODE_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def has_audio_stream(video_path: str) -> bool:
    """
    檢查影片是否含有音訊軌

    Instagram 輪播中的影片常常只有畫面沒有聲音（video_url 給的是純視訊軌），
    這種情況下 ffmpeg 抽音訊會直接失敗，必須先判斷再決定要不要轉錄。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except Exception as e:
        # ffprobe 不可用時不阻擋流程，交給後續 ffmpeg 判斷
        print(f"檢查音訊軌失敗（將直接嘗試轉錄）: {e}")
        return True


def audio_to_text(video_path: str) -> str:
    """使用Whisper將視頻音頻轉為文字（無音訊軌時回傳空字串）"""
    if not has_audio_stream(video_path):
        print(f"影片沒有音訊軌，略過轉錄: {video_path}")
        return ""

    base = os.path.splitext(video_path)[0]
    mp3_path = base + "_whisper.mp3"

    # 轉換為mp3
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "192k",
            mp3_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # 保留 ffmpeg 的錯誤訊息，否則只會看到 exit status 難以追查
        raise RuntimeError(
            f"ffmpeg 轉檔失敗 (exit {result.returncode}): {result.stderr.strip()[-500:]}"
        )

    # 呼叫Whisper-1
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    with open(mp3_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",  # 純文字格式
            temperature=0.0,  # 最穩定的輸出
        )

    # 清理臨時檔案
    os.remove(mp3_path)

    return resp.strip()  # response_format="text"時返回字符串，不是對象


def download_video(url: str, output_path: str) -> bool:
    """下載影片到指定路徑"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"下載影片失敗: {e}")
        return False


def normalize_instagram_url(url: str) -> str:
    """
    標準化 Instagram URL

    - 移除 query string 與 fragment（例如分享連結的 ?stkn=、?igsh=、?img_index=），
      這些參數會讓嵌入頁無法解析
    - /reels/ 統一改為 /reel/
    - 補上結尾斜線
    """
    parts = urlsplit(url.strip())
    path = parts.path.replace("/reels/", "/reel/")
    if path and not path.endswith("/"):
        path += "/"
    # 只保留 scheme + netloc + path，丟棄 query 與 fragment
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def extract_shortcode(url: str) -> str:
    """從 Instagram URL 取出 shortcode，作為檔名使用"""
    path = urlsplit(url).path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    for i, seg in enumerate(segments):
        if seg in ("p", "reel", "reels", "tv") and i + 1 < len(segments):
            return segments[i + 1]
    return segments[-1] if segments else "instagram_post"


def _node_to_media_item(node: Dict) -> Optional[Dict]:
    """把單一媒體節點（貼文本身或輪播子項）轉成統一格式"""
    if not isinstance(node, dict):
        return None

    typename = node.get("__typename", "")
    is_video = bool(node.get("is_video")) or "Video" in typename

    if is_video:
        video_url = node.get("video_url") or node.get("videoUrl")
        if video_url:
            return {
                "type": "video",
                "url": video_url,
                "alt": node.get("accessibility_caption") or "",
                # 無聲影片會改用封面圖做 OCR／描述
                "thumbnail": node.get("display_url") or node.get("thumbnail_src") or "",
            }
        # 標記為影片但拿不到影片網址時，退回使用縮圖
        image_url = node.get("display_url") or node.get("thumbnail_src")
        if image_url:
            return {
                "type": "image",
                "url": image_url,
                "alt": node.get("accessibility_caption") or "",
            }
        return None

    image_url = node.get("display_url") or node.get("thumbnail_src") or node.get("url")
    if image_url:
        return {
            "type": "image",
            "url": image_url,
            "alt": node.get("accessibility_caption") or "",
        }
    return None


def extract_media_items(data: Dict) -> List[Dict]:
    """
    從 API 回應中取出所有媒體項目（影片與圖片）

    支援：
    - 單一影片 / 單一圖片貼文
    - 輪播貼文（edge_sidecar_to_children，例如第一則是影片、其餘是圖片）
    - 其他扁平格式（carousel_media / media 陣列）
    """
    items: List[Dict] = []

    media_data = None
    if isinstance(data.get("data"), dict):
        media_data = data["data"].get("xdt_shortcode_media")
    if not media_data and isinstance(data.get("xdt_shortcode_media"), dict):
        media_data = data["xdt_shortcode_media"]

    if isinstance(media_data, dict):
        # 輪播貼文：媒體都放在子節點裡，貼文本身不會有 video_url
        sidecar = media_data.get("edge_sidecar_to_children")
        edges = sidecar.get("edges", []) if isinstance(sidecar, dict) else []
        if edges:
            for edge in edges:
                node = edge.get("node") if isinstance(edge, dict) else None
                item = _node_to_media_item(node or {})
                if item:
                    items.append(item)
        else:
            item = _node_to_media_item(media_data)
            if item:
                items.append(item)

    # 其他可能的回應格式
    if not items:
        for key in ("carousel_media", "media"):
            value = data.get(key)
            if isinstance(value, list):
                for entry in value:
                    if not isinstance(entry, dict):
                        continue
                    entry_type = entry.get("type") or entry.get("media_type")
                    url_value = entry.get("url") or entry.get("video_url")
                    if entry_type == "video" and url_value:
                        items.append({"type": "video", "url": url_value, "alt": ""})
                    elif url_value or entry.get("display_url"):
                        items.append(
                            {
                                "type": "image",
                                "url": url_value or entry.get("display_url"),
                                "alt": "",
                            }
                        )
                if items:
                    break

    if not items and data.get("videoUrl"):
        items.append({"type": "video", "url": data["videoUrl"], "alt": ""})

    return items


def analyze_image_bytes(image_bytes: bytes) -> Dict:
    """用 GPT-4o 對圖片做 OCR 與描述"""
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """請分析這張圖片並以 JSON 格式回傳：

1. OCR 文字辨識：提取圖片中所有可見的文字內容，保持原始換行。
2. 圖片描述：用繁體中文簡潔描述圖片的主要物件與場景。

請嚴格按照以下 JSON 格式回傳：
{
    "ocr_text": "圖片中的文字，沒有則回傳空字串",
    "caption": "圖片的繁體中文描述"
}""",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=1500,
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    result = json.loads(completion.choices[0].message.content)
    return {
        "ocr_text": (result.get("ocr_text") or "").strip(),
        "caption": (result.get("caption") or "").strip(),
    }


def analyze_image_url(image_url: str, index: int) -> Dict:
    """下載輪播中的圖片並用 GPT-4o 做 OCR 與描述"""
    try:
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        analysis = analyze_image_bytes(response.content)
        return {"index": index, "url": image_url, **analysis}
    except Exception as e:
        print(f"分析第 {index} 張圖片失敗: {e}")
        return {"index": index, "url": image_url, "ocr_text": "", "caption": ""}


def extract_video_frame(video_path: str) -> Optional[bytes]:
    """從影片取出一張畫面（無聲影片改用畫面做 OCR／描述）"""
    frame_path = os.path.splitext(video_path)[0] + "_frame.jpg"
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "1",
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                frame_path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not os.path.exists(frame_path):
            print(f"取出影片畫面失敗: {result.stderr.strip()[-300:]}")
            return None
        with open(frame_path, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"取出影片畫面失敗: {e}")
        return None
    finally:
        if os.path.exists(frame_path):
            try:
                os.remove(frame_path)
            except OSError:
                pass


def transcribe_video_url(
    video_url: str, index: int, workdir: str, shortcode: str, thumbnail: str = ""
) -> Dict:
    """
    下載輪播中的影片並轉錄

    Instagram 輪播裡的影片常常沒有音訊軌（例如只是一段展示畫面），
    這時改用影片畫面或封面圖做 OCR／描述，避免這則媒體完全沒有內容。
    """
    video_path = os.path.join(workdir, f"{shortcode}_{index}.mp4")
    transcription = ""
    cover: Dict = {"ocr_text": "", "caption": ""}
    try:
        if download_video(video_url, video_path):
            transcription = audio_to_text(video_path)
            if not transcription:
                # 沒有語音內容時，退回分析畫面
                frame = extract_video_frame(video_path)
                try:
                    if frame:
                        cover = analyze_image_bytes(frame)
                    elif thumbnail:
                        response = requests.get(thumbnail, timeout=30)
                        response.raise_for_status()
                        cover = analyze_image_bytes(response.content)
                except Exception as e:
                    print(f"分析第 {index} 則影片畫面失敗: {e}")
    except Exception as e:
        print(f"轉錄第 {index} 則影片失敗: {e}")
    finally:
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except OSError:
                pass
    return {
        "index": index,
        "url": video_url,
        "transcription": transcription,
        "cover_ocr_text": cover.get("ocr_text", ""),
        "cover_caption": cover.get("caption", ""),
    }


def _get_with_retry(url: str, attempts: int = 3, session=None, **kwargs):
    """GET 請求，遇到限流（429）、伺服器錯誤或網路問題時以指數退避重試"""
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            if session is not None:
                response = session.get(url, timeout=30, **kwargs)
            else:
                response = curl_requests.get(
                    url, impersonate="chrome", timeout=30, **kwargs
                )
            if response.status_code != 429 and response.status_code < 500:
                return response
            last_error = RuntimeError(f"HTTP {response.status_code}")
        except Exception as e:
            last_error = e
        if attempt < attempts - 1:
            wait = 2**attempt
            print(f"請求 Instagram 失敗（{last_error}），{wait} 秒後重試")
            time.sleep(wait)
    raise RuntimeError(f"請求 Instagram 失敗: {last_error}")


def shortcode_to_media_id(shortcode: str) -> str:
    """把貼文 shortcode 換算成 Instagram 內部的 media id"""
    # 私人貼文的 shortcode 會比較長，只有前 11 碼對應 media id
    media_id = 0
    for char in shortcode[:11]:
        media_id = media_id * 64 + _SHORTCODE_ALPHABET.index(char)
    return str(media_id)


def _instagram_session_ids() -> List[str]:
    """
    已登入帳號的 sessionid（選填），用於抓取嵌入頁拿不到的貼文

    IG_SESSIONID 可用逗號分隔多組帳號，某組被限流或失效時自動換下一組。
    """
    raw = os.getenv("IG_SESSIONID") or ""
    return [value.strip() for value in raw.split(",") if value.strip()]


def _fetch_post_from_embed(shortcode: str) -> Optional[Dict]:
    """
    從 Instagram 公開嵌入頁（/p/{shortcode}/embed/captioned/）取出貼文資料

    嵌入頁不需登入，頁面內的 contextJSON 含有與 GraphQL 相同的 shortcode_media
    （影片網址、輪播子項、文案、作者），直接包成 xdt_shortcode_media 格式回傳。
    貼文關閉嵌入或需要登入才能看時，contextJSON 會是 null，回傳 None。
    """
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    response = _get_with_retry(embed_url)
    print(f"嵌入頁回應狀態碼: {response.status_code}")
    response.raise_for_status()

    match = re.search(r'"contextJSON":("(?:[^"\\]|\\.)*")', response.text)
    if not match:
        return None
    context = json.loads(json.loads(match.group(1)))
    media = (context.get("gql_data") or {}).get("shortcode_media")
    if not isinstance(media, dict):
        return None
    return {"data": {"xdt_shortcode_media": media}}


def _v1_item_to_node(item: Dict) -> Dict:
    """把站內 API（/api/v1/media/.../info/）的媒體項目轉成 shortcode_media 節點格式"""
    candidates = (item.get("image_versions2") or {}).get("candidates") or []
    display_url = candidates[0].get("url", "") if candidates else ""
    videos = item.get("video_versions") or []
    node = {
        "is_video": bool(videos),
        "display_url": display_url,
        "accessibility_caption": item.get("accessibility_caption") or "",
    }
    if videos:
        best = max(
            videos, key=lambda v: (v.get("width") or 0) * (v.get("height") or 0)
        )
        node["video_url"] = best.get("url")
    return node


def _fetch_post_from_api(shortcode: str, session_id: str) -> Optional[Dict]:
    """
    以已登入的 sessionid 呼叫 Instagram 站內 API 取得貼文資料

    嵌入頁拿不到的貼文（關閉嵌入、年齡限制、需登入）可以從這裡取得，
    回傳格式同樣包成 xdt_shortcode_media，後續流程不需要區分來源。
    """
    media_id = shortcode_to_media_id(shortcode)
    # Instagram 會先 302 導回同一網址以補發 csrftoken、mid 等 cookies，
    # 必須用同一個 session 保存 cookies 並跟隨導向，否則永遠拿不到資料
    session = curl_requests.Session(impersonate="chrome")
    session.cookies.set("sessionid", session_id, domain=".instagram.com")
    response = _get_with_retry(
        f"https://www.instagram.com/api/v1/media/{media_id}/info/",
        session=session,
        headers={
            "X-IG-App-ID": IG_APP_ID,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/p/{shortcode}/",
        },
    )
    print(f"站內 API 回應狀態碼: {response.status_code}")

    # 導向 /challenge/ 代表帳號被要求驗證；導向 /accounts/login/ 代表 sessionid 失效
    final_url = str(response.url)
    if "challenge" in final_url or "checkpoint" in final_url:
        raise RuntimeError("帳號被 Instagram 要求安全驗證，請在 App 上確認登入後再試")
    if "/accounts/login" in final_url or response.status_code in (401, 403):
        raise RuntimeError("sessionid 已失效或被登出，請更新 IG_SESSIONID")
    if response.status_code == 400 and "not found" in response.text.lower():
        # 帳號正常，但貼文已刪除或對此帳號不可見
        print("站內 API：貼文不存在或無法存取")
        return None
    response.raise_for_status()

    items = response.json().get("items") or []
    if not items:
        return None
    item = items[0]

    carousel = item.get("carousel_media") or []
    if carousel:
        media = {
            "edge_sidecar_to_children": {
                "edges": [{"node": _v1_item_to_node(child)} for child in carousel]
            }
        }
    else:
        media = _v1_item_to_node(item)

    caption = item.get("caption") or {}
    media["edge_media_to_caption"] = {
        "edges": [{"node": {"text": caption.get("text") or ""}}]
    }
    media["owner"] = {"username": (item.get("user") or {}).get("username") or ""}
    return {"data": {"xdt_shortcode_media": media}}


def _ytdlp_entry_to_node(entry: Dict) -> Dict:
    """把 yt-dlp 的單一影片資訊轉成 shortcode_media 節點格式"""
    return {
        "is_video": True,
        "video_url": entry.get("url"),
        "display_url": entry.get("thumbnail") or "",
    }


def _fetch_post_from_ytdlp(url: str, session_id: str = "") -> Optional[Dict]:
    """
    嵌入頁拿不到資料時，改用 yt-dlp 取得影片資訊

    yt-dlp 只會回傳影片（輪播中的圖片會被略過），因此僅作為備援。
    """
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "best[vcodec!=none][acodec!=none]/best",
    }
    cookie_path = None
    if session_id:
        # yt-dlp 需要 Netscape 格式的 cookies 檔案
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False
        ) as cookie_file:
            cookie_file.write("# Netscape HTTP Cookie File\n")
            cookie_file.write(
                f".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\t{session_id}\n"
            )
            cookie_path = cookie_file.name
        options["cookiefile"] = cookie_path
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    finally:
        if cookie_path and os.path.exists(cookie_path):
            os.remove(cookie_path)
    if not info:
        return None

    entries = [e for e in (info.get("entries") or []) if e and e.get("url")]
    if entries:
        media = {
            "edge_sidecar_to_children": {
                "edges": [{"node": _ytdlp_entry_to_node(e)} for e in entries]
            }
        }
        first = entries[0]
    elif info.get("url"):
        media = _ytdlp_entry_to_node(info)
        first = info
    else:
        return None

    media["edge_media_to_caption"] = {
        "edges": [
            {"node": {"text": first.get("description") or info.get("description") or ""}}
        ]
    }
    media["owner"] = {
        "username": first.get("channel") or info.get("channel") or first.get("uploader_id") or ""
    }
    return {"data": {"xdt_shortcode_media": media}}


def _video_nodes_missing_url(data: Dict) -> List[Dict]:
    """找出標記為影片、卻沒有影片網址的節點（嵌入頁常見，只給封面圖）"""
    media_data = (data.get("data") or {}).get("xdt_shortcode_media")
    if not isinstance(media_data, dict):
        return []
    sidecar = media_data.get("edge_sidecar_to_children")
    edges = sidecar.get("edges", []) if isinstance(sidecar, dict) else []
    nodes = [e.get("node") for e in edges if isinstance(e, dict)] if edges else [media_data]
    return [
        node
        for node in nodes
        if isinstance(node, dict)
        and (node.get("is_video") or "Video" in node.get("__typename", ""))
        and not (node.get("video_url") or node.get("videoUrl"))
    ]


def _fill_missing_video_urls(data: Dict, source: Dict) -> int:
    """用其他來源（yt-dlp）的影片網址依序補回缺網址的影片節點，回傳補上的數量"""
    video_urls = [i["url"] for i in extract_media_items(source) if i["type"] == "video"]
    filled = 0
    for node, video_url in zip(_video_nodes_missing_url(data), video_urls):
        node["video_url"] = video_url
        filled += 1
    return filled


def fetch_instagram_post(url: str, shortcode: str) -> Dict:
    """
    自行抓取 Instagram 貼文資料（不依賴第三方爬蟲服務）

    1. 公開嵌入頁：不需登入，支援 Reels、單圖、輪播（影片＋圖片）
    2. 站內 API：有設定 IG_SESSIONID 時依序嘗試每組帳號，可取得需登入或關閉嵌入的貼文
    3. yt-dlp 備援：前兩者都拿不到時仍可取得影片
    全部失敗時拋出例外，避免把錯誤訊息當成貼文內容送給 AI。

    嵌入頁有時只給影片封面、不給影片網址（Reels 常見），
    此時保留嵌入頁的文案與輪播結構，繼續往下用 API / yt-dlp 補影片網址，
    否則影片語音完全不會被轉錄，只剩一張封面圖可分析。
    """
    session_ids = _instagram_session_ids()
    errors = []
    partial = None

    try:
        data = _fetch_post_from_embed(shortcode)
        if data and extract_media_items(data):
            missing = _video_nodes_missing_url(data)
            if not missing:
                print("已從嵌入頁取得貼文資料")
                return data
            print(f"嵌入頁缺少 {len(missing)} 則影片網址，改用其他來源補齊")
            partial = data
            errors.append("嵌入頁缺少影片網址")
        else:
            errors.append("嵌入頁沒有貼文資料（可能已關閉嵌入或需要登入）")
    except Exception as e:
        errors.append(f"嵌入頁抓取失敗: {e}")

    if not session_ids:
        errors.append("未設定 IG_SESSIONID，略過登入抓取")
    for index, session_id in enumerate(session_ids, start=1):
        try:
            data = _fetch_post_from_api(shortcode, session_id)
            if data and extract_media_items(data):
                print(f"已從站內 API 取得貼文資料（帳號 #{index}）")
                return data
            errors.append(f"站內 API 沒有貼文資料（帳號 #{index}）")
            break  # 帳號正常但貼文本身拿不到，換帳號也沒用
        except Exception as e:
            print(f"站內 API 帳號 #{index} 失敗: {e}")
            errors.append(f"站內 API 抓取失敗（帳號 #{index}）: {e}")

    # 先以未登入狀態嘗試，避免失效的 sessionid 連公開影片都拿不到
    for session_id in [""] + session_ids[:1]:
        label = "登入" if session_id else "未登入"
        try:
            data = _fetch_post_from_ytdlp(url, session_id)
            if data and extract_media_items(data):
                if partial and _fill_missing_video_urls(partial, data):
                    # yt-dlp 會略過輪播中的圖片，因此以嵌入頁資料為主、只補影片網址
                    print(f"已用 yt-dlp 補上嵌入頁缺少的影片網址（{label}）")
                    return partial
                print(f"已從 yt-dlp 取得貼文資料（{label}）")
                return data
            errors.append(f"yt-dlp 沒有取得媒體（{label}）")
        except Exception as e:
            errors.append(f"yt-dlp 抓取失敗（{label}）: {e}")

    if partial:
        # 補不到影片網址時，至少還有文案與封面圖可以分析
        print("⚠️ 無法取得影片網址，只能分析封面圖與文案：" + "；".join(errors))
        return partial

    raise RuntimeError(
        "無法取得 Instagram 貼文（貼文可能為私人、已刪除或需要登入）："
        + "；".join(errors)
    )


async def process_instagram_reel(url: str, workdir: str = "./shorts_cache") -> Dict:
    """處理 Instagram Reels 影片與貼文（支援影片＋圖片混合的輪播貼文）"""
    # 驗證URL
    if not url or not url.strip() or not url.startswith(("http://", "https://")):
        raise ValueError(f"Instagram URL 格式無效: {url}")

    # 確保工作目錄存在
    os.makedirs(workdir, exist_ok=True)

    # 標準化 Instagram URL：移除 ?stkn= 等分享參數，並把 /reels/ 改為 /reel/
    normalized_url = normalize_instagram_url(url)
    shortcode = extract_shortcode(normalized_url)
    print(f"正在抓取 Instagram 貼文: {normalized_url}")

    # 抓取失敗直接拋出例外，交由 API 回傳錯誤，不把錯誤訊息當成內容做摘要
    data = fetch_instagram_post(normalized_url, shortcode)

    try:
        # 提取所需資訊
        caption = ""
        description = ""
        username = ""

        media_data = None
        if isinstance(data.get("data"), dict):
            media_data = data["data"].get("xdt_shortcode_media")
        if not media_data and isinstance(data.get("xdt_shortcode_media"), dict):
            media_data = data["xdt_shortcode_media"]

        if isinstance(media_data, dict):
            # 嘗試獲取描述/標題
            edge_caption = media_data.get("edge_media_to_caption")
            if isinstance(edge_caption, dict):
                edges = edge_caption.get("edges", [])
                if edges and isinstance(edges[0], dict):
                    caption = edges[0].get("node", {}).get("text", "") or ""
                    description = caption

            # 嘗試獲取用戶名
            owner = media_data.get("owner")
            if isinstance(owner, dict):
                username = owner.get("username", "") or ""

        # 如果找不到資訊，嘗試其他格式
        if not caption and "caption" in data:
            caption = data.get("caption", "") or ""
            description = caption

        if not username and "username" in data:
            username = data.get("username", "") or ""

        # 取出所有媒體（輪播貼文可能第一則是影片、其餘是圖片）
        media_items = extract_media_items(data)
        all_videos = [item for item in media_items if item["type"] == "video"]
        all_images = [item for item in media_items if item["type"] == "image"]
        videos = all_videos[:MAX_VIDEOS]
        images = all_images[:MAX_IMAGES]
        print(
            f"偵測到媒體：影片 {len(all_videos)} 則、圖片 {len(all_images)} 張"
            f"（實際處理 影片 {len(videos)} 則、圖片 {len(images)} 張）"
        )

        # 並行處理：影片轉錄 + 圖片 OCR/描述
        tasks = [
            asyncio.to_thread(
                transcribe_video_url,
                item["url"],
                index,
                workdir,
                shortcode,
                item.get("thumbnail", ""),
            )
            for index, item in enumerate(videos, start=1)
        ] + [
            asyncio.to_thread(analyze_image_url, item["url"], index)
            for index, item in enumerate(images, start=1)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        video_results = []
        image_results = []
        for result in results:
            if isinstance(result, Exception):
                print(f"媒體處理失敗: {result}")
            elif "transcription" in result:
                video_results.append(result)
            else:
                image_results.append(result)
        video_results.sort(key=lambda item: item["index"])
        image_results.sort(key=lambda item: item["index"])

        # 組合所有媒體的文字內容
        sections: List[str] = []
        for item in video_results:
            single = len(video_results) == 1
            if item["transcription"]:
                label = (
                    "【影片語音轉錄】"
                    if single
                    else f"【影片 {item['index']} 語音轉錄】"
                )
                sections.append(f"{label}\n{item['transcription']}")
            else:
                # 無聲影片：改用影片畫面的 OCR／描述
                lines = []
                if item.get("cover_caption"):
                    lines.append(f"畫面描述：{item['cover_caption']}")
                if item.get("cover_ocr_text"):
                    lines.append(f"畫面文字：{item['cover_ocr_text']}")
                if lines:
                    label = (
                        "【影片畫面】" if single else f"【影片 {item['index']} 畫面】"
                    )
                    sections.append(f"{label}\n" + "\n".join(lines))

        for item in image_results:
            # index 從 1 開始，用來對回原始的 images 清單（避免中途失敗造成錯位）
            source = (
                images[item["index"] - 1] if 0 < item["index"] <= len(images) else {}
            )
            lines = []
            if item["caption"]:
                lines.append(f"圖片描述：{item['caption']}")
            if item["ocr_text"]:
                lines.append(f"圖片文字：{item['ocr_text']}")
            if not lines and source.get("alt"):
                lines.append(f"圖片描述：{source['alt']}")
            if lines:
                sections.append(f"【圖片 {item['index']}】\n" + "\n".join(lines))

        media_text = "\n\n".join(sections)

        # 影片轉錄（相容既有輸出欄位）
        transcription = "\n\n".join(
            item["transcription"] for item in video_results if item["transcription"]
        )

        # 有解析出媒體內容就使用；否則退回貼文文案
        final_caption = media_text if media_text else caption

        # 準備標準化輸出格式
        output = {
            "description": description,
            "caption": final_caption,
            "username": username,
            "video_url": videos[0]["url"] if videos else None,
            "media_items": media_items,
            "video_count": len(all_videos),
            "image_count": len(all_images),
            "processed_video_count": len(videos),
            "processed_image_count": len(images),
            "transcription": transcription,
            "video_analyses": video_results,
            "image_analyses": image_results,
        }

        # 轉換為AI處理需要的格式
        ai_input = {
            "original_path": url,
            "ocr_text": description,
            "caption": final_caption,
        }

        return {"raw_output": output, "ai_input": ai_input}

    except Exception as e:
        print(f"處理Instagram貼文時發生錯誤: {e}")
        raise
