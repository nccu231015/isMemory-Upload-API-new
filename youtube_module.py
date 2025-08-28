import os
from yt_dlp import YoutubeDL
import subprocess
from openai import OpenAI
from typing import Dict, Optional

def audio_to_text(video_path: str) -> str:
    """使用Whisper將視頻音頻轉為文字"""
    base = os.path.splitext(video_path)[0]
    mp3_path = base + "_whisper.mp3"
    
    try:
        # 如果mp3檔案不存在才進行轉換
        if not os.path.exists(mp3_path):
            print("🎵 轉換音頻為mp3格式...")
            # 轉換為mp3：單聲道 / 16kHz / 192kbps
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path,
                 "-vn", "-ac", "1", "-ar", "16000",
                 "-b:a", "192k", mp3_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print("🤖 使用Whisper-1進行語音轉文字...")
        # 呼叫Whisper-1
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        with open(mp3_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",  # 純文字格式
                temperature=0.0  # 最穩定的輸出
            )
        
        # 清理臨時檔案
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
        
        return resp.strip()  # response_format="text"時返回字符串，不是對象
        
    except Exception as e:
        print(f"❌ 語音轉文字失敗: {str(e)}")
        # 清理可能存在的臨時檔案
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
        return "語音轉文字處理失敗"

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
    
    # 使用多種下載策略以提高成功率
    download_strategies = [
        # 策略1: 最佳質量
        {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": os.path.join(workdir, "%(title)s [%(id)s].%(ext)s"),
            "restrictfilenames": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hant", "zh-TW", "zh-Hans", "en"],
            "quiet": True,
        },
        # 策略2: 任何可用格式
        {
            "format": "best/worst",
            "outtmpl": os.path.join(workdir, "%(title)s [%(id)s].%(ext)s"),
            "restrictfilenames": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hant", "zh-TW", "zh-Hans", "en"],
            "quiet": True,
        },
        # 策略3: 僅音頻（用於語音轉文字）
        {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(workdir, "%(title)s [%(id)s].%(ext)s"),
            "restrictfilenames": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hant", "zh-TW", "zh-Hans", "en"],
            "quiet": True,
        }
    ]

    # 嘗試多種下載策略
    video_path = None
    info = None
    title = ""
    description = ""
    
    for i, ydl_opts in enumerate(download_strategies):
        try:
            print(f"🔄 嘗試下載策略 {i+1}/3: {ydl_opts['format']}")
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            video_path = ydl.prepare_filename(info)
            title = info.get("title", "").strip()
            description = (info.get("description") or "").strip()
            
            print(f"✅ 策略 {i+1} 成功下載影片: {title}")
            break
            
        except Exception as e:
            print(f"❌ 策略 {i+1} 失敗: {str(e)}")
            if i == len(download_strategies) - 1:  # 最後一個策略也失敗
                print("⚠️  所有下載策略失敗，嘗試僅提取影片資訊...")
                try:
                    with YoutubeDL({"quiet": True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                    title = info.get("title", "").strip()
                    description = (info.get("description") or "").strip()
                    print(f"✅ 成功提取影片資訊: {title}")
                    
                    # 返回僅包含標題和描述的結果
                    return {
                        "raw_output": {
                            "title": title,
                            "description": description,
                            "caption_txt": "無法下載影片，僅使用標題和描述資訊"
                        },
                        "ai_input": {
                            "original_path": url,
                            "ocr_text": f"{title}\n{description}",
                            "caption": "無法下載影片，僅使用標題和描述資訊"
                        }
                    }
                except Exception as e2:
                    print(f"❌ 連資訊提取都失敗: {str(e2)}")
                    return {
                        "raw_output": {"title": "", "description": "", "caption_txt": ""},
                        "ai_input": {
                            "original_path": url,
                            "ocr_text": "",
                            "caption": f"處理失敗: {str(e2)}"
                        }
                    }
            continue
    
    # 處理字幕（只有在成功下載影片時才執行）
    if video_path and os.path.exists(video_path):
        # 嘗試尋找字幕檔案
        import glob
        stem = os.path.splitext(video_path)[0]
        subs = glob.glob(stem + ".*[vs]rt") + glob.glob(stem + "*.vtt")
        
        if subs:
            print(f"✅ 找到字幕檔案: {subs[0]}")
            with open(subs[0], "r", encoding="utf-8") as f:
                caption_txt = f.read().strip()
        else:
            print("⚠️  未找到字幕檔案，使用Whisper進行語音轉文字...")
            caption_txt = audio_to_text(video_path)
    else:
        # 如果沒有成功下載影片，使用備用字幕
        caption_txt = "無法下載影片進行語音轉文字"
    
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