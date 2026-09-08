import os
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import yt_dlp

# 音訊處理與轉錄流程與 YouTube 共用：
# 轉成單聲道低位元率、超長時切段、並行送 Whisper。
from youtube_module import audio_to_text, _find_downloaded_media

# TikTok 需要 TLS 指紋偽裝才能通過網頁請求（由 curl_cffi 提供）。
# 沒有安裝時 yt-dlp 會回報 "Unexpected response from webpage request"。
_IMPERSONATE_AVAILABLE = None


def _impersonation_available() -> bool:
    global _IMPERSONATE_AVAILABLE
    if _IMPERSONATE_AVAILABLE is None:
        try:
            import curl_cffi  # noqa: F401

            _IMPERSONATE_AVAILABLE = True
        except Exception:
            _IMPERSONATE_AVAILABLE = False
    return _IMPERSONATE_AVAILABLE


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


def _build_ydl_opts(workdir: str) -> Dict:
    opts: Dict = {
        # TikTok 多數格式是含視訊的 mp4，抓不到純音訊時退回完整影片，
        # 後續轉檔會自行去掉視訊軌。
        "format": "bestaudio/best",
        "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "overwrites": True,
    }

    proxy = os.getenv("YTDLP_PROXY")
    if proxy:
        opts["proxy"] = proxy

    cookies = os.getenv("TIKTOK_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        opts["cookiefile"] = cookies

    return opts


def _extract_native_subtitles(info: Dict) -> str:
    """若 TikTok 本身就有字幕軌，優先使用（免去 Whisper 的時間與費用）"""
    tracks = info.get("subtitles") or {}
    if not tracks:
        return ""
    # 優先中文，其次英文，最後任意一種
    for preferred in ("zh-Hant", "zh-TW", "zh-Hans", "zh", "eng", "en"):
        for lang in tracks:
            if lang.lower().startswith(preferred.lower()):
                return lang
    return next(iter(tracks), "")


def download_tiktok_audio(url: str, workdir: str) -> Tuple[Optional[str], Dict]:
    """使用 yt-dlp 下載 TikTok 影片音訊

    Returns:
        tuple: (audio_path, info_dict)；失敗時 (None, {"error": ...})
    """
    try:
        if not _impersonation_available():
            print(
                "⚠️ 未安裝 curl_cffi，TikTok 的網頁請求可能被拒絕"
                "（requirements.txt 應包含 curl_cffi）"
            )

        opts = _build_ydl_opts(workdir)
        with yt_dlp.YoutubeDL(opts) as ydl:
            print(f"🎬 正在使用 yt-dlp 處理 TikTok 影片: {url}")
            info = ydl.extract_info(url, download=False)

            if info.get("_type") == "playlist":
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    raise Exception("連結沒有可下載的影片")
                info = entries[0]

            print(f"👤 作者: {info.get('uploader')}")
            print(f"⏱️ 長度: {info.get('duration')}秒")

            print("⬇️ 開始下載影片音訊...")
            ydl.download([url])

        audio_path = _find_downloaded_media(workdir)
        if not audio_path or os.path.getsize(audio_path) == 0:
            raise Exception("下載失敗，找不到可用的媒體檔案")

        print(f"✅ 下載完成: {os.path.basename(audio_path)} "
              f"({os.path.getsize(audio_path) / 1024 / 1024:.1f}MB)")
        return audio_path, info

    except Exception as exc:
        message = f"TikTok 下載失敗: {exc}"
        print(f"❌ {message}")
        return None, {"error": message}


async def process_tiktok_video(url: str, save_dir: str = "./shorts_cache") -> Dict:
    """
    處理 TikTok 影片（不依賴任何第三方 API）：
    1. 用 yt-dlp 直接向 TikTok 取得影片資料與媒體
    2. 用 Whisper 轉錄音訊（長影片會自動切段並行處理）
    """
    print(f"TikTok 模組接收到的 URL: '{url}'")

    if not url or not url.strip() or not url.startswith(("http://", "https://")):
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "URL 格式無效",
            },
        }

    cleaned_url = normalize_tiktok_url(url)
    if cleaned_url != url:
        print(f"標準化後的 URL: '{cleaned_url}'")

    os.makedirs(save_dir, exist_ok=True)
    session_dir = tempfile.mkdtemp(prefix="tiktok_", dir=save_dir)

    try:
        audio_path, info = download_tiktok_audio(cleaned_url, session_dir)

        if audio_path is None:
            error_text = info.get("error", "下載失敗")
            return {
                "raw_output": {
                    "description": "",
                    "caption": "(影片下載失敗)",
                    "author": "",
                    "aweme_id": "",
                    "error": error_text,
                },
                "ai_input": {
                    "original_path": cleaned_url,
                    "ocr_text": "",
                    "caption": f"(影片下載失敗) {error_text}",
                },
            }

        # TikTok 文案（短文 + hashtag），資訊密度高，作為 ocr_text
        description = info.get("description") or info.get("title") or ""
        author = info.get("uploader") or info.get("uploader_id") or "unknown"
        aweme_id = info.get("id") or "unknown"

        print(f"影片描述: {description[:100]}")

        print("🎙️ 開始語音轉文字...")
        # 文案當作 Whisper 提示詞，改善店名／地名的轉寫正確率
        caption = audio_to_text(audio_path, context=description[:400])
        if not caption:
            caption = "(轉錄失敗)"
            print("⚠️ 語音轉文字失敗")

        return {
            "raw_output": {
                "description": description,
                "caption": caption,
                "author": author,
                "aweme_id": aweme_id,
                "duration": info.get("duration", 0),
            },
            "ai_input": {
                "original_path": cleaned_url,
                "ocr_text": description,
                "caption": caption,
            },
        }

    except Exception as exc:
        message = f"處理 TikTok 影片時發生錯誤: {exc}"
        print(f"❌ {message}")
        return {
            "raw_output": {
                "description": "",
                "caption": "(處理失敗)",
                "author": "",
                "aweme_id": "",
                "error": message,
            },
            "ai_input": {
                "original_path": cleaned_url,
                "ocr_text": "",
                "caption": "(處理失敗)",
            },
        }
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)
        print("🗑️ 已清理暫存檔案")


if __name__ == "__main__":
    import asyncio
    import sys

    target = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.tiktok.com/@bugatti/video/7339393672959757570"
    )
    print(asyncio.run(process_tiktok_video(target)))
