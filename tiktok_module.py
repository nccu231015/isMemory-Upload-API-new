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
                response_format="text",
                temperature=0.0
            )
        
        os.remove(m4a)  # 清理暫存檔
        return txt.strip()
        
    except Exception as e:
        print(f"轉錄失敗: {e}")
        return ""

async def process_tiktok_video(url: str, save_dir: str = "./shorts_cache") -> Dict:
    """處理TikTok影片，提取說明和字幕"""
    print(f"TikTok模組接收到的URL: '{url}'")
    
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
    
    # 檢查是否是TikTok視頻URL
    if '/video/' not in url and '@' not in url:
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": "請提供有效的TikTok影片連結"
            }
        }
    
    os.makedirs(save_dir, exist_ok=True)
    
    try:
        # 建立TikTok會話
        ms_token = os.getenv("MS_TOKEN")
        
        # 創建API實例，先嘗試帶token的方式
        api = None
        session_created = False
        
        try:
            print("正在初始化TikTok API...")
            if ms_token:
                print("使用MS_TOKEN創建API實例")
                api = TikTokApi()
                await api.create_sessions(ms_tokens=[ms_token], num_sessions=1, sleep_after=3)
                session_created = True
                print("TikTok API會話創建成功（使用MS_TOKEN）")
            else:
                print("沒有MS_TOKEN，嘗試無token方式")
                api = TikTokApi()
                await api.create_sessions(num_sessions=1, sleep_after=3)
                session_created = True
                print("TikTok API會話創建成功（無token）")
        except Exception as session_error:
            print(f"標準方式創建會話失敗: {session_error}")
            
            # 在部署環境中，會話創建經常失敗，直接返回錯誤資訊
            print("⚠️  TikTok會話創建失敗，這在部署環境中很常見")
            print("   可能原因：1) 網路限制 2) TikTok反爬蟲 3) 環境配置問題")
            
            return {
                "raw_output": {"description": "", "caption": ""},
                "ai_input": {
                    "original_path": url,
                    "ocr_text": "",
                    "caption": f"TikTok會話創建失敗: {str(session_error)}"
                }
            }
        
        # 獲取影片資訊
        print(f"正在調用TikTokApi.video()，URL: '{url}'")
        video = api.video(url=url)
        print(f"TikTokApi.video()成功，正在獲取影片資訊...")
        video_data = await video.info()
        print(f"成功獲取影片資訊")
        
        # 提取基本資訊
        description = video_data.get('desc', '') or ""
        username = video_data.get('author', {}).get('uniqueId', 'unknown')
        
        # 檢查是否有字幕
        caption = video_data.get('voice_to_text', '') or ""
        
        # 如果沒有字幕，嘗試下載並轉錄（只有在有會話時才嘗試）
        if not caption:
            if session_created:
                try:
                    print("影片沒有字幕，正在嘗試下載並使用Whisper轉錄...")
                    video_id = getattr(video, 'id', 'unknown')
                    video_path = os.path.join(save_dir, f"{username}_{video_id}.mp4")
                    
                    if not os.path.exists(video_path):
                        print("正在下載影片...")
                        
                        # 嘗試下載影片
                        video_bytes = None
                        for method in ['no_wm=True', 'no_wm=False', 'default']:
                            try:
                                print(f"嘗試下載方法: {method}")
                                if method == 'no_wm=True':
                                    video_bytes = await video.bytes(no_wm=True)
                                elif method == 'no_wm=False':
                                    video_bytes = await video.bytes(no_wm=False)
                                else:
                                    video_bytes = await video.bytes()
                                
                                if video_bytes and len(video_bytes) > 0:
                                    print(f"下載成功，方法: {method}")
                                    break
                            except Exception as e:
                                print(f"方法 {method} 失敗: {e}")
                                continue
                        
                        if video_bytes and len(video_bytes) > 0:
                            with open(video_path, "wb") as f:
                                f.write(video_bytes)
                            print(f"影片已下載至: {video_path}")
                        else:
                            print("所有下載方法都失敗，跳過轉錄")
                            caption = "(無法下載影片進行轉錄)"
                    
                    # 如果有影片檔案，進行轉錄
                    if os.path.exists(video_path) and caption != "(無法下載影片進行轉錄)":
                        print("使用Whisper-1轉錄中...")
                        caption = whisper_transcribe(video_path)
                        if not caption:
                            caption = "(轉錄失敗)"
                            
                except Exception as download_error:
                    print(f"下載轉錄過程中發生錯誤: {download_error}")
                    caption = f"處理錯誤: {str(download_error)}"
            else:
                print("沒有有效會話，跳過影片下載，僅使用描述資訊")
                caption = "(無會話，無法下載影片)"
        
        # 準備輸出格式
        output = {
            "description": description,
            "caption": caption
        }
        
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
        traceback.print_exc()
        
        return {
            "raw_output": {"description": "", "caption": ""},
            "ai_input": {
                "original_path": url, 
                "ocr_text": "", 
                "caption": f"處理錯誤: {str(e)}"
            }
        }
    
    finally:
        # 清理API資源
        try:
            if 'api' in locals() and hasattr(api, 'close'):
                await api.close()
        except:
            pass