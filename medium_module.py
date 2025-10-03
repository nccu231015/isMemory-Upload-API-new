import os
from typing import Dict
from tavily import TavilyClient


async def scrape_medium_article(url: str) -> Dict:
    """使用 Tavily Extract API 爬取 Medium 文章"""
    try:
        # 從環境變數獲取 API key
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("未設置 TAVILY_API_KEY 環境變數")
        
        # 初始化 Tavily 客戶端
        client = TavilyClient(api_key=api_key)
        
        # 使用 Tavily Extract API
        response = client.extract(
            urls=[url],
            extract_depth="advanced",
            include_images=False,
            format="text"
        )
        
        # 檢查是否有結果
        if not response.get("results"):
            if response.get("failed_results"):
                error_msg = response["failed_results"][0].get("error", "未知錯誤")
                raise Exception(f"提取失敗: {error_msg}")
            raise Exception("未能提取到任何內容")
        
        # 獲取第一個結果
        result = response["results"][0]
        raw_content = result.get("raw_content", "")
        
        # 直接使用 raw_content 作為文章內容（已經是純文字格式）
        return {
            "content": raw_content.strip(),
            "url": url,
        }
        
    except Exception as e:
        raise Exception(f"爬取 Medium 文章失敗: {str(e)}")


async def process_medium_article(url: str) -> Dict:
    """處理 Medium 文章，輸出與其他模組一致的格式
    
    Returns:
        {
            "raw_output": {...},
            "ai_input": {...}
        }
    """
    try:
        data = await scrape_medium_article(url)
        
        # 只獲取文章內容
        content = data.get("content", "").strip()
        
        raw_output = {
            "content": content,
            "url": url,
        }
        
        ai_input = {
            "original_path": url,
            "ocr_text": content,
            "caption": content,
        }
        
        return {
            "raw_output": raw_output,
            "ai_input": ai_input,
        }
        
    except Exception as e:
        return {
            "raw_output": {"content": "", "error": str(e), "url": url},
            "ai_input": {
                "original_path": url,
                "ocr_text": "",
                "caption": f"處理錯誤: {str(e)}",
            },
        }

