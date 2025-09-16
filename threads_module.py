import json
from typing import Dict, List, Optional

from parsel import Selector
from nested_lookup import nested_lookup
import jmespath
from playwright.async_api import async_playwright


def _parse_thread(data: Dict) -> Dict:
    """從 Threads 內嵌 JSON 中解析出主要欄位"""
    result = jmespath.search(
        """{
        text: post.caption.text,
        published_on: post.taken_at,
        id: post.id,
        pk: post.pk,
        code: post.code,
        username: post.user.username,
        user_pic: post.user.profile_pic_url,
        user_verified: post.user.is_verified,
        user_pk: post.user.pk,
        user_id: post.user.id,
        has_audio: post.has_audio,
        reply_count: view_replies_cta_string,
        like_count: post.like_count,
        images: post.carousel_media[].image_versions2.candidates[1].url,
        image_count: post.carousel_media_count,
        videos: post.video_versions[].url
    }""",
        data,
    )

    if not result:
        return {}

    # 規整化資料
    result["videos"] = list(set(result.get("videos") or []))
    if result.get("reply_count") and type(result["reply_count"]) != int:
        try:
            result["reply_count"] = int(str(result["reply_count"]).split(" ")[0])
        except Exception:
            result["reply_count"] = 0

    username = result.get("username") or "unknown"
    code = result.get("code") or ""
    result["url"] = f"https://www.threads.net/@{username}/post/{code}" if code else ""

    return result


async def scrape_thread(url: str) -> Dict:
    """以 Playwright 爬取 Threads 貼文與回覆，並回傳精簡後的 JSON"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        await page.goto(url)
        await page.wait_for_selector("[data-pressable-container=true]")

        selector = Selector(await page.content())
        hidden_datasets = selector.css('script[type="application/json"][data-sjs]::text').getall()

        for hidden_dataset in hidden_datasets:
            if '"ScheduledServerJS"' not in hidden_dataset:
                continue
            if "thread_items" not in hidden_dataset:
                continue
            data = json.loads(hidden_dataset)
            thread_items_list = nested_lookup("thread_items", data)
            if not thread_items_list:
                continue

            threads: List[Dict] = [_parse_thread(t) for thread in thread_items_list for t in thread]
            threads = [t for t in threads if t]
            if not threads:
                continue

            await context.close()
            await browser.close()

            return {
                "thread": threads[0],
                "replies": threads[1:],
            }

        await context.close()
        await browser.close()
        raise ValueError("could not find thread data in page")


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


