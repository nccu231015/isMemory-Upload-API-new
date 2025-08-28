import os
import requests
import json
import subprocess
from typing import Dict, Optional
from openai import OpenAI
from dotenv import load_dotenv
import asyncio

# 載入環境變數
load_dotenv()

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
            file=f,
            response_format="text",  # 純文字格式
            temperature=0.0  # 最穩定的輸出
        )
    
    # 清理臨時檔案
    os.remove(mp3_path)
    
    return resp.strip()  # response_format="text"時返回字符串，不是對象

def download_video(url: str, output_path: str) -> bool:
    """下載影片到指定路徑"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"下載影片失敗: {e}")
        return False

async def process_instagram_reel(url: str, workdir: str = "./shorts_cache") -> Dict:
    """處理Instagram Reels影片"""
    # 驗證URL
    if not url or not url.strip() or not url.startswith(('http://', 'https://')):
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "URL格式無效"
            }
        }
    
    # 確保工作目錄存在
    os.makedirs(workdir, exist_ok=True)
    
    # 準備API請求
    api_url = "https://api.scrapecreators.com/v1/instagram/post"
    api_key = os.getenv("X_API_KEY")
    
    if not api_key:
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "缺少API金鑰"
            }
        }
    
            # 發送API請求
    try:
        print(f"正在請求ScrapeCreators API: {url}")
        response = requests.get(
            api_url,
            params={"url": url},
            headers={"x-api-key": api_key}
        )
        print(f"API回應狀態碼: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        print(f"API回應內容: {json.dumps(data, ensure_ascii=False)[:500]}...")
        
        # 檢查API回應
        if "error" in data:
            print(f"API錯誤: {data['error']}")
            return {
                "raw_output": {"description": "", "caption": ""},
                "ai_input": {
                    "original_path": url,
                    "ocr_text": "",
                    "caption": f"API錯誤: {data.get('error', '未知錯誤')}"
                }
            }
        
        # 提取所需資訊
        caption = ""
        description = ""
        username = ""
        video_url = None
        
        # 檢查API回應格式並提取資訊
        if "data" in data and "xdt_shortcode_media" in data["data"]:
            media_data = data["data"]["xdt_shortcode_media"]
            
            # 嘗試獲取描述/標題
            if "edge_media_to_caption" in media_data and "edges" in media_data["edge_media_to_caption"]:
                edges = media_data["edge_media_to_caption"]["edges"]
                if edges and len(edges) > 0 and "node" in edges[0] and "text" in edges[0]["node"]:
                    caption = edges[0]["node"]["text"]
                    description = caption
            
            # 嘗試獲取用戶名
            if "owner" in media_data and "username" in media_data["owner"]:
                username = media_data["owner"]["username"]
            
            # 嘗試獲取影片URL
            if "video_url" in media_data:
                video_url = media_data["video_url"]
        
        # 如果找不到資訊，嘗試其他格式
        if not caption and "caption" in data:
            caption = data.get("caption", "")
            description = caption
        
        if not username and "username" in data:
            username = data.get("username", "")
        
        # 尋找影片URL (其他可能的格式)
        if not video_url:
            if "media" in data and isinstance(data["media"], list) and len(data["media"]) > 0:
                for media_item in data["media"]:
                    if media_item.get("type") == "video" and "url" in media_item:
                        video_url = media_item["url"]
                        break
            
            # 如果找不到影片URL，嘗試從其他字段獲取
            if not video_url and "videoUrl" in data:
                video_url = data["videoUrl"]
        
        # 如果有影片URL，下載並轉錄
        transcription = ""
        if video_url:
            video_filename = f"{username}_{url.split('/')[-1]}.mp4"
            video_path = os.path.join(workdir, video_filename)
            
            # 下載影片
            if download_video(video_url, video_path):
                # 轉錄影片
                try:
                    transcription = audio_to_text(video_path)
                except Exception as e:
                    print(f"轉錄失敗: {e}")
        
        # 如果有轉錄結果，使用它；否則使用caption
        final_caption = transcription if transcription else caption
        
        # 準備標準化輸出格式
        output = {
            "description": description,
            "caption": final_caption,
            "username": username,
            "video_url": video_url
        }
        
        # 轉換為AI處理需要的格式
        ai_input = {
            "original_path": url,
            "ocr_text": description,
            "caption": final_caption
        }
        
        return {
            "raw_output": output,
            "ai_input": ai_input
        }
        
    except Exception as e:
        print(f"處理Instagram Reel時發生錯誤: {e}")
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": f"處理錯誤: {str(e)}"
            }
        }