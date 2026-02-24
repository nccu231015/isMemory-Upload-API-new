import os
import requests
import subprocess
from typing import Dict
from openai import OpenAI
from urllib.parse import urlsplit, urlunsplit

DOUYIN_WTF_BASE = "https://douyin.wtf"


def normalize_tiktok_url(input_url: str) -> str:
    """標準化 TikTok URL：移除 query 與 fragment"""
    try:
        parts = urlsplit(input_url)
        normalized = urlunsplit(
            (parts.scheme or "https", parts.netloc, parts.path, "", "")
        )
        if normalized.endswith("/"):
            normalized = normalized[:-1]
        return normalized
    except Exception:
        return input_url


def fetch_video_data(url: str) -> dict:
    """
    使用 douyin.wtf Hybrid API 取得 TikTok 影片資料。

    API: GET /api/hybrid/video_data?url={url}
    文件: https://douyin.wtf/docs
    """
    endpoint = f"{DOUYIN_WTF_BASE}/api/hybrid/video_data"
    response = requests.get(endpoint, params={"url": url}, timeout=30)
    response.raise_for_status()
    return response.json()


def download_video(video_url: str, output_path: str) -> bool:
    """下載影片到指定路徑"""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(video_url, headers=headers, stream=True, timeout=60)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"下載影片失敗: {e}")
        return False


def whisper_transcribe(mp4_path: str) -> str:
    """使用 OpenAI Whisper-1 將影片音頻轉為文字"""
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # 將 mp4 轉為 m4a 音頻（降採樣以節省費用）
        m4a_path = mp4_path.replace(".mp4", "_whisper.m4a")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                mp4_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                m4a_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        with open(m4a_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
                temperature=0.0,
            )

        # 清理暫存音頻
        if os.path.exists(m4a_path):
            os.remove(m4a_path)

        return result.strip()

    except Exception as e:
        print(f"Whisper 轉錄失敗: {e}")
        return ""


async def process_tiktok_video(url: str, save_dir: str = "./shorts_cache") -> Dict:
    """
    處理 TikTok 影片：
    1. 透過 douyin.wtf Hybrid API 取得影片資料
    2. 下載影片
    3. 使用 Whisper 轉錄音頻
    """
    print(f"TikTok 模組接收到的 URL: '{url}'")

    # 驗證 URL
    if not url or not url.strip() or not url.startswith(("http://", "https://")):
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "URL 格式無效",
            },
        }

    # 標準化 URL
    cleaned_url = normalize_tiktok_url(url)
    if cleaned_url != url:
        print(f"標準化後的 URL: '{cleaned_url}'")

    os.makedirs(save_dir, exist_ok=True)

    # Step 1: 呼叫 douyin.wtf Hybrid API 取得影片資料
    try:
        print(f"正在呼叫 douyin.wtf API: {cleaned_url}")
        data = fetch_video_data(cleaned_url)
        print(f"API 回應 code: {data.get('code')}")
    except Exception as e:
        print(f"douyin.wtf API 請求失敗: {e}")
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": cleaned_url,
                "ocr_text": "",
                "caption": f"API 請求失敗: {str(e)}",
            },
        }

    # 確認 API 回應成功
    if data.get("code") != 200:
        msg = data.get("data") or "未知錯誤"
        print(f"API 回傳錯誤: {msg}")
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": cleaned_url,
                "ocr_text": "",
                "caption": f"API 錯誤: {msg}",
            },
        }

    # Step 2: 解析影片資料
    video_info = data.get("data", {})

    # 取得影片描述與作者
    description = video_info.get("desc", "") or ""
    author = (video_info.get("author") or {}).get("unique_id", "") or (
        video_info.get("author") or {}
    ).get("nickname", "unknown")
    aweme_id = video_info.get("aweme_id", "") or video_info.get("id", "unknown")

    print(f"影片描述: {description[:100]}")
    print(f"作者: {author}")

    # 優先使用 TikTok 原生語音字幕
    voice_to_text = video_info.get("voice_to_text", "") or ""
    if voice_to_text:
        print(f"✅ 取得 TikTok 原生字幕 (voice_to_text): {voice_to_text[:50]}...")
        return {
            "raw_output": {
                "description": description,
                "caption": voice_to_text,
                "author": author,
                "aweme_id": aweme_id,
            },
            "ai_input": {
                "original_path": cleaned_url,
                "ocr_text": description,  # TikTok 文案（短文 + hashtag），屬於重點資訊
                "caption": voice_to_text,
            },
        }

    print("⚠️ 無 TikTok 原生字幕，改為下載影片並使用 Whisper 轉錄...")

    # 取得無水印影片 URL
    # douyin.wtf 回傳的結構：video.play_addr.url_list 或 video.download_addr.url_list
    video_url = None
    try:
        video_data = video_info.get("video", {}) or {}

        # 優先嘗試 play_addr（通常是無水印）
        play_addr = video_data.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        if url_list:
            video_url = url_list[0]

        # 備選：download_addr
        if not video_url:
            download_addr = video_data.get("download_addr") or {}
            url_list = download_addr.get("url_list") or []
            if url_list:
                video_url = url_list[0]

        # 再備選：bit_rate 列表中的第一個
        if not video_url:
            bit_rate_list = video_data.get("bit_rate") or []
            if bit_rate_list:
                first_bitrate = bit_rate_list[0]
                url_list = (first_bitrate.get("play_addr") or {}).get("url_list") or []
                if url_list:
                    video_url = url_list[0]
    except Exception as e:
        print(f"解析影片 URL 時發生錯誤: {e}")

    print(f"影片下載 URL: {video_url[:80] if video_url else '未找到'}...")

    # Step 3: 下載影片並進行 Whisper 轉錄
    caption = ""
    if video_url:
        video_filename = f"{author}_{aweme_id}.mp4"
        video_path = os.path.join(save_dir, video_filename)

        print("正在下載影片...")
        if download_video(video_url, video_path):
            print(f"影片已下載至: {video_path}")
            print("使用 Whisper-1 轉錄中...")
            caption = whisper_transcribe(video_path)

            # 清理影片檔案
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
                    print(f"已清理影片檔案: {video_path}")
            except Exception as e:
                print(f"清理影片失敗: {e}")

            if not caption:
                caption = "(轉錄失敗)"
        else:
            caption = "(影片下載失敗)"
    else:
        caption = "(無法取得影片下載連結)"

    # 組合結果
    raw_output = {
        "description": description,
        "caption": caption,
        "author": author,
        "aweme_id": aweme_id,
    }

    ai_input = {
        "original_path": cleaned_url,
        "ocr_text": description,  # TikTok 文案（短文 + hashtag），屬於重點資訊
        "caption": caption,
    }

    return {
        "raw_output": raw_output,
        "ai_input": ai_input,
    }
