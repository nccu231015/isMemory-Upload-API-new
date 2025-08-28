import os
import re
import subprocess
import yt_dlp
from openai import OpenAI
from typing import Dict, Optional

def audio_to_text(video_path: str) -> str:
    """使用Whisper將音頻轉為文字 - 如果是mp4則先提取音頻"""
    try:
        # 檢查輸入檔案是否存在
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"音頻檔案不存在: {video_path}")
        
        file_size = os.path.getsize(video_path)
        print(f"🎵 音頻檔案大小: {file_size / 1024 / 1024:.1f}MB")
        
        if file_size == 0:
            raise Exception("音頻檔案為空")
        
        # 如果是mp4檔案，先用ffmpeg提取純音頻
        audio_file_for_whisper = video_path
        if video_path.endswith('.mp4'):
            print("🔄 檢測到mp4檔案，提取純音頻...")
            base = os.path.splitext(video_path)[0]
            audio_file_for_whisper = base + "_audio.m4a"
            
            try:
                result = subprocess.run([
                    "ffmpeg", "-y", "-i", video_path,
                    "-vn", "-acodec", "copy", 
                    audio_file_for_whisper
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    print(f"⚠️ ffmpeg提取音頻失敗，直接使用原檔案: {result.stderr}")
                    audio_file_for_whisper = video_path
                else:
                    print("✅ 音頻提取成功")
            except Exception as e:
                print(f"⚠️ ffmpeg提取音頻失敗，直接使用原檔案: {e}")
                audio_file_for_whisper = video_path
        
        print("🤖 使用Whisper-1進行語音轉文字...")
        
        # 呼叫Whisper-1
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        with open(audio_file_for_whisper, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",  # 純文字格式
                temperature=0.0  # 最穩定的輸出
            )
        
        # 清理提取的音頻檔案（如果有的話）
        if audio_file_for_whisper != video_path and os.path.exists(audio_file_for_whisper):
            try:
                os.remove(audio_file_for_whisper)
                print("🗑️ 已清理提取的音頻暫存檔")
            except:
                pass
        
        transcription = resp.strip()
        if transcription:
            print(f"✅ 語音轉文字成功，長度: {len(transcription)}字符")
            return transcription
        else:
            print("⚠️ Whisper返回空結果")
            return ""
    
    except Exception as e:
        print(f"❌ 語音轉文字失敗: {e}")
        return ""

def is_valid_youtube_url(url: str) -> bool:
    """檢查是否為有效的YouTube URL"""
    patterns = [
        r"^(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+(&\S*)?$",
        r"^(https?://)?(www\.)?youtube\.com/shorts/[\w-]+(\?\S*)?$",
        r"^(https?://)?(www\.)?youtu\.be/[\w-]+(\?\S*)?$"
    ]
    return any(re.match(pattern, url) for pattern in patterns)

def extract_video_id(url: str) -> str:
    """從YouTube URL中提取影片ID"""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([\w-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_youtube_audio_with_ytdlp(url: str, workdir: str = "shorts_cache") -> tuple[str, Dict]:
    """
    使用yt-dlp下載YouTube音頻
    
    Returns:
        tuple: (audio_file_path, video_info_dict)
    """
    try:
        # 確保工作目錄存在
        os.makedirs(workdir, exist_ok=True)
        
        # 驗證URL
        if not is_valid_youtube_url(url):
            raise ValueError("無效的YouTube URL")
        
        print(f"🎬 正在使用yt-dlp處理YouTube影片: {url}")
        
        # 提取影片ID
        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError("無法提取影片ID")
        
        # yt-dlp配置 - 只下載音頻
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': os.path.join(workdir, f'%(title)s_%(id)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 首先獲取影片資訊
            print("📋 正在獲取影片資訊...")
            info = ydl.extract_info(url, download=False)
            
            title = info.get('title', '未知標題')
            author = info.get('uploader', '未知作者')
            description = info.get('description', '')
            duration = info.get('duration', 0)
            view_count = info.get('view_count', 0)
            
            print(f"📺 影片標題: {title}")
            print(f"👤 作者: {author}")
            print(f"⏱️ 長度: {duration}秒")
            print(f"👁️ 觀看次數: {view_count}")
            
            # 下載音頻
            print("⬇️ 開始下載音頻...")
            ydl.download([url])
            
            # 搜索實際下載的音頻文件
            audio_file_path = None
            for file_path in os.listdir(workdir):
                if video_id in file_path and (file_path.endswith('.m4a') or file_path.endswith('.webm') or file_path.endswith('.mp3') or file_path.endswith('.opus') or file_path.endswith('.mp4')):
                    audio_file_path = os.path.join(workdir, file_path)
                    break
            
            if not audio_file_path or not os.path.exists(audio_file_path):
                raise Exception("音頻下載失敗，找不到下載的文件")
            
            file_size = os.path.getsize(audio_file_path)
            print(f"✅ 音頻下載完成: {audio_file_path} ({file_size / 1024 / 1024:.1f}MB)")
            
            # 組織影片資訊
            video_data = {
                "title": title,
                "author": author,
                "description": description,
                "duration": duration,
                "view_count": view_count,
                "video_id": video_id
            }
            
            return audio_file_path, video_data
        
    except Exception as e:
        error_msg = f"yt-dlp YouTube下載失敗: {str(e)}"
        print(f"❌ {error_msg}")
        return None, {"error": error_msg}

def process_youtube_video(url: str) -> Dict:
    """
    處理YouTube影片：下載、轉錄、分析
    
    Returns:
        Dict: 包含raw_output和ai_input的結果
    """
    try:
        # 下載音頻
        audio_path, video_info = download_youtube_audio_with_ytdlp(url)
        
        if audio_path is None:
            # 下載失敗，返回完整格式的基本資訊
            return {
                "raw_output": {
                    "description": video_info.get("error", "下載失敗"),
                    "caption": "(影片下載失敗)",
                    "title": "未知標題",
                    "author": "未知作者",
                    "view_count": 0,
                    "duration": 0
                },
                "ai_input": {
                    "original_path": url,
                    "ocr_text": "",
                    "caption": "(影片下載失敗)"
                }
            }
        
        # 語音轉文字
        print("🎙️ 開始語音轉文字...")
        caption = audio_to_text(audio_path)
        
        if not caption:
            caption = "(無法轉錄音頻)"
            print("⚠️ 語音轉文字失敗，將使用影片描述")
        
        # 使用影片描述作為OCR文字
        ocr_text = video_info.get("description", "")[:500]  # 限制長度
        
        # 清理下載的音頻檔案
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
                print(f"🗑️ 已清理音頻檔案: {audio_path}")
        except Exception as e:
            print(f"⚠️ 清理檔案失敗: {e}")
        
        # 組合結果
        result = {
            "raw_output": {
                "description": video_info.get("description", ""),
                "caption": caption,
                "title": video_info.get("title", ""),
                "author": video_info.get("author", ""),
                "view_count": video_info.get("view_count", 0),
                "duration": video_info.get("duration", 0)
            },
            "ai_input": {
                "original_path": url,
                "ocr_text": ocr_text,
                "caption": caption
            }
        }
        
        print("✅ YouTube影片處理完成")
        return result
        
    except Exception as e:
        error_msg = f"處理YouTube影片時發生錯誤: {str(e)}"
        print(f"❌ {error_msg}")
        
        return {
            "raw_output": {
                "description": error_msg,
                "caption": "(處理失敗)",
                "title": "未知標題",
                "author": "未知作者",
                "view_count": 0,
                "duration": 0
            },
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "(處理失敗)"
            }
        }

# 測試函數
if __name__ == "__main__":
    test_url = "https://www.youtube.com/shorts/xNSo6xoFsYc"
    result = process_youtube_video(test_url)
    print("測試結果:", result)