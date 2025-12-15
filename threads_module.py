import re
from typing import Dict

from playwright.async_api import async_playwright


async def scrape_thread(url: str) -> Dict:
    """以 Playwright 爬取 Threads 貼文，從 og:description 提取內容"""
    # 從 URL 中提取 username 和 code
    username_match = re.search(r'@([^/]+)/', url)
    code_match = re.search(r'/post/([^/?]+)', url)
    target_username = username_match.group(1) if username_match else None
    target_code = code_match.group(1) if code_match else None
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        await page.goto(url)
        await page.wait_for_load_state('domcontentloaded')
        
        # 🎯 從 og:description 提取內容
        try:
            og_desc = await page.get_attribute('meta[property="og:description"]', 'content')
            og_title = await page.get_attribute('meta[property="og:title"]', 'content')
            og_image = await page.get_attribute('meta[property="og:image"]', 'content')
            
            if og_desc:
                print(f"✅ 從 og:description 提取到內容: {og_desc[:100]}...")
                
                # 提取圖片
                images = []
                if og_image:
                    images.append(og_image)
                
                await context.close()
                await browser.close()
                
                return {
                    "thread": {
                        "text": og_desc,
                        "username": target_username or "unknown",
                        "code": target_code or "",
                        "url": url,
                        "images": images,
                        "videos": [],
                    },
                    "replies": [],
                }
            else:
                await context.close()
                await browser.close()
                raise ValueError("無法找到 og:description")
                
        except Exception as error:
            await context.close()
            await browser.close()
            raise ValueError(f"提取 og:description 失敗: {error}")


async def process_threads_article(url: str) -> Dict:
    """處理 Threads 文章，輸出與其他模組一致的格式

    Returns:
        {
            "raw_output": {...},
            "ai_input": {...}
        }
    """
    try:
        data = await scrape_thread(url)
        main = data.get("thread", {})

        # Threads 沒有明確的標題，將全文文字作為 ocr_text 與 caption 輸入 AI
        text = (main.get("text") or "").strip()
        username = main.get("username") or ""
        images = main.get("images") or []
        videos = main.get("videos") or []

        raw_output = {
            "text": text,
            "username": username,
            "images": images,
            "videos": videos,
            "url": url,
        }

        ai_input = {
            "original_path": url,
            "ocr_text": text,
            "caption": text,
        }

        return {
            "raw_output": raw_output,
            "ai_input": ai_input,
        }

    except Exception as e:
        return {
            "raw_output": {"text": "", "error": str(e)},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": f"處理錯誤: {str(e)}",
            },
        }


