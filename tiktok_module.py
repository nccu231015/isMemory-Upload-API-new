import os
import asyncio
from TikTokApi import TikTokApi
import ffmpeg
from openai import OpenAI
from typing import Dict, Optional

def whisper_transcribe(mp4_path: str) -> str:
    """使用Whisper-1將影片音頻轉為文字"""
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # 提取音頻
        m4a = mp4_path.replace(".mp4", "_32k.m4a")
        (
            ffmpeg
            .input(mp4_path)
            .output(m4a, ac=1, ar=16000, audio_bitrate="32k", vn=None)
            .overwrite_output()
            .run(quiet=True)
        )
        
        with open(m4a, "rb") as f:
            txt = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",  # 純文字格式
                temperature=0.0  # 最穩定的輸出
            )  # response_format="text"時直接返回字符串
        
        os.remove(m4a)  # 清理暫存檔
        return txt.strip()
        
    except Exception as e:
        print(f"轉錄失敗: {e}")
        return ""

async def process_tiktok_video(url: str, save_dir: str = "./shorts_cache") -> Dict:
    """處理TikTok影片，提取說明和字幕"""
    # 記錄接收到的URL
    print(f"TikTok模組接收到的URL: '{url}' (長度: {len(url) if url else 'None'})")
    
    # 驗證URL
    if not url or not url.strip() or not url.startswith(('http://', 'https://')):
        print(f"URL驗證失敗: url='{url}', 是否為空: {not url}, 是否為空白: {not url.strip() if url else 'N/A'}")
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "URL格式無效"
            }
        }
    
    # 檢查是否是TikTok視頻URL
    if '/video/' not in url and '@' not in url:
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "請提供有效的TikTok影片連結（需包含 /video/ 或 @ 標識）"
            }
        }
    
    os.makedirs(save_dir, exist_ok=True)
    
    try:
        # 建立TikTok會話
        ms_token = os.getenv("MS_TOKEN")
        
        async with TikTokApi() as api:
            if ms_token:
                await api.create_sessions(ms_tokens=[ms_token], num_sessions=1, sleep_after=3)
            else:
                await api.create_sessions(num_sessions=1, sleep_after=3)
            
            # 獲取影片資訊
            print(f"正在調用TikTokApi.video()，URL: '{url}'")
            video = api.video(url=url)
            print(f"TikTokApi.video()成功，正在獲取影片資訊...")
            video_data = await video.info()
            print(f"成功獲取影片資訊，video.id: {getattr(video, 'id', 'Unknown')}")
            
            # 提取基本資訊
            description = video_data.get('desc', '') or ""
            username = video_data['author']['uniqueId']
            
            # 檢查是否有字幕
            caption = video_data.get('voice_to_text', '')
            
            # 如果沒有字幕且需要轉錄（完全按照原始main.py邏輯）
            if not caption:
                try:
                    # 下載影片
                    print(f"影片沒有字幕，正在下載以使用 Whisper 轉錄...")
                    video_path = os.path.join(save_dir, f"{username}_{video.id}.mp4")
                    
                    if not os.path.exists(video_path):
                        print(f"正在下載影片...")
                        
                        # 先檢查video對象的下載信息
                        print("檢查影片下載資訊...")
                        
                        # 嘗試不同的下載方法
                        try:
                            print("嘗試方法1: 使用no_wm=True...")
                            video_bytes = await video.bytes(no_wm=True)
                        except Exception as e1:
                            print(f"方法1失敗: {e1}")
                            try:
                                print("嘗試方法2: 使用no_wm=False...")
                                video_bytes = await video.bytes(no_wm=False)
                            except Exception as e2:
                                print(f"方法2失敗: {e2}")
                                try:
                                    print("嘗試方法3: 直接調用bytes()...")
                                    video_bytes = await video.bytes()
                                except Exception as e3:
                                    print(f"方法3失敗: {e3}")
                                    print("所有下載方法都失敗，可能是TikTok反爬蟲限制")
                                    video_bytes = None
                                    caption = ""  # 若爬不到，就留空
                        
                        if video_bytes and len(video_bytes) > 0:
                            with open(video_path, "wb") as f:
                                f.write(video_bytes)
                            print(f"影片已下載至: {video_path}")
                        else:
                            print("未能獲取有效的影片數據，跳過轉錄")
                            caption = "(無法下載影片進行轉錄)"
                            continue_transcription = False
                    else:
                        continue_transcription = True
                    
                    # 使用 Whisper 轉錄（只有在成功下載或文件已存在時）
                    if 'continue_transcription' not in locals() or continue_transcription:
                        print("使用 Whisper-1 轉錄中...")
                        caption = whisper_transcribe(video_path)
                        
                except Exception as download_error:
                    print(f"下載過程中發生錯誤: {download_error}")
                    print(f"錯誤類型: {type(download_error).__name__}")
                    print("將繼續處理，但沒有轉錄內容")
                    caption = ""  # 若爬不到，就留空
            
            # 準備標準化輸出格式
            output = {
                "description": description,
                "caption": caption
            }
            
            # 轉換為AI處理需要的格式
            ai_input = {
                "original_path": url,
                "ocr_text": description,
                "caption": caption
            }
            
            return {
                "raw_output": output,
                "ai_input": ai_input
            }
    
    except Exception as e:
        import traceback
        print(f"處理TikTok影片時發生錯誤: {e}")
        print(f"錯誤類型: {type(e).__name__}")
        print(f"完整錯誤追蹤:")
        traceback.print_exc()
        print(f"當時處理的URL: '{url}'")
        
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {"original_path": url, "ocr_text": "", "caption": f"處理錯誤: {str(e)}"}
        }