import os
from yt_dlp import YoutubeDL
import subprocess
from openai import OpenAI
from typing import Dict, Optional

def audio_to_text(video_path: str) -> str:
    """使用Whisper將視頻音頻轉為文字"""
    base = os.path.splitext(video_path)[0]
    mp3_path = base + "_whisper.mp3"
    
    # 轉換為mp3
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path,
         "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "192k", mp3_path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 呼叫Whisper-1
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    with open(mp3_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    
    # 清理臨時檔案
    os.remove(mp3_path)
    
    return resp.text.strip()

def process_youtube_short(url: str, workdir: str = "./shorts_cache") -> Dict:
    """處理YouTube Shorts影片"""
    # 驗證URL
    if not url or not url.strip() or not url.startswith(('http://', 'https://')):
        return {
            "raw_output": {"title": "", "description": "", "caption_txt": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "URL格式無效"
            }
        }
        
    os.makedirs(workdir, exist_ok=True)
    
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(workdir, "%(title)s [%(id)s].%(ext)s"),
        "restrictfilenames": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["zh-Hant", "zh-TW", "zh-Hans", "en"],
        "quiet": True,
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    
    video_path = ydl.prepare_filename(info)
    title = info.get("title", "").strip()
    description = (info.get("description") or "").strip()
    
    # 嘗試尋找字幕檔案
    import glob
    stem = os.path.splitext(video_path)[0]
    subs = glob.glob(stem + ".*[vs]rt") + glob.glob(stem + "*.vtt")
    
    if subs:
        with open(subs[0], "r", encoding="utf-8") as f:
            caption_txt = f.read().strip()
    else:
        caption_txt = audio_to_text(video_path)
    
    # 準備標準化輸出格式
    output = {
        "title": title,
        "description": description,
        "caption_txt": caption_txt
    }
    
    # 轉換為AI處理需要的格式
    ai_input = {
        "original_path": url,
        "ocr_text": f"{title}\n{description}",
        "caption": caption_txt
    }
    
    return {
        "raw_output": output,
        "ai_input": ai_input
    }