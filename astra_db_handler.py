import os
import uuid
from datetime import datetime
from typing import Dict
from astrapy import DataAPIClient
from langchain_openai import OpenAIEmbeddings

class AstraDBHandler:
    def __init__(self, 
                 api_endpoint=None, 
                 token=None,
                 collection_name=None):
        
        # 獲取環境變數或使用傳入的參數
        self.api_endpoint = api_endpoint or os.getenv("ASTRA_DB_API_ENDPOINT")
        # 同時支援兩種命名，並優先使用 ASTRA_DB_TOKEN（你指定的名稱）
        self.token = token or os.getenv("ASTRA_DB_TOKEN") or os.getenv("ASTRA_DB_APPLICATION_TOKEN")
        self.collection_name = collection_name or os.getenv("ASTRA_DB_COLLECTION_NAME", "image_vectors")
        
        # 初始化OpenAI嵌入模型
        self.embeddings = OpenAIEmbeddings(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            model="text-embedding-3-small",
            dimensions=1536
        )
        
        # 初始化AstraDB客戶端
        self.client = None
        self.database = None
        self.collection = None
        
    def initialize_connection(self):
        """初始化與AstraDB的連接"""
        try:
            # 連線前的必要參數檢查
            if not self.api_endpoint:
                print("初始化AstraDB連接失敗: 缺少 ASTRA_DB_API_ENDPOINT")
                return False
            if not self.token:
                print("初始化AstraDB連接失敗: 缺少 ASTRA_DB_APPLICATION_TOKEN 或 ASTRA_DB_TOKEN")
                return False
            print("正在初始化AstraDB連接...")
            
            # 創建客戶端
            self.client = DataAPIClient(self.token)
            self.database = self.client.get_database(self.api_endpoint)
            
            # 檢查集合是否存在
            collections = self.database.list_collections()
            collection_names = [col.name for col in collections]
            
            # 如果集合不存在，則創建
            if self.collection_name not in collection_names:
                print(f"創建新集合: {self.collection_name}")
                self.collection = self.database.create_collection(
                    name=self.collection_name,
                    definition={
                        'vector': {
                            'dimension': 1536,
                            'metric': 'cosine'
                        }
                    }
                )
            else:
                print(f"使用現有集合: {self.collection_name}")
                self.collection = self.database.get_collection(self.collection_name)
                
            print("AstraDB連接初始化完成")
            return True
            
        except Exception as e:
            print(f"初始化AstraDB連接失敗: {str(e)}")
            return False
        
    def store_video_data(self, analysis_result: Dict, source_type: str) -> Dict:
        """將視頻、圖片或文章分析結果存儲到AstraDB

        source_type:
            - image: 圖片
            - youtube/tiktok/instagram: 短影音
            - threads/article: 文章類（threads）
        """
        if not self.collection:
            success = self.initialize_connection()
            if not success:
                return {"success": False, "error": "無法連接到AstraDB"}
        
        try:
            # 準備向量化文本
            ocr_text = analysis_result.get("ocr_text", "")
            caption = analysis_result.get("caption", "")
            summary = analysis_result.get("summary", "")
            title = analysis_result.get("title", "")
            
            combined_text = f"標題：{title}\n摘要：{summary}\n"
            
            if ocr_text.strip():
                combined_text += f"文字內容：{ocr_text}\n"
            
            if caption.strip():
                if source_type == "image":
                    combined_text += f"圖片描述：{caption}"
                else:
                    combined_text += f"字幕內容：{caption}"
            
            # 生成向量
            print("正在生成向量...")
            embedding = self.embeddings.embed_query(combined_text)
            
            # 準備文檔
            document_id = str(uuid.uuid4())
            
            # 根據類型準備不同的metadata結構
            if source_type == "image":
                # 圖片專用欄位結構
                filename = analysis_result.get("filename", f"image_{document_id[:8]}.jpg")
                document = {
                    "_id": document_id,
                    "$vector": embedding,
                    "text": combined_text,
                    "metadata": {
                        "document_id": document_id,
                        "filename": filename,
                        "title": title,
                        "ocr_text": ocr_text,
                        "caption": caption,
                        "summary": summary,
                        "important_time": analysis_result.get("important_time", ""),
                        "important_location": analysis_result.get("important_location", ""),
                        "original_path": analysis_result.get("original_path", ""),
                        "upload_time": datetime.now().isoformat(),
                        "content_type": "image",
                    }
                }
            elif source_type in ["youtube", "tiktok", "instagram"]:
                # 影片專用欄位結構
                document = {
                    "_id": document_id,
                    "$vector": embedding,
                    "text": combined_text,
                    "metadata": {
                        "document_id": document_id,
                        "title": title,
                        "ocr_text": ocr_text,
                        "caption": caption,
                        "summary": summary,
                        "important_time": analysis_result.get("important_time", ""),
                        "important_location": analysis_result.get("important_location", ""),
                        "original_path": analysis_result.get("original_path", ""),
                        "source_type": source_type,  # "youtube", "tiktok", "instagram"
                        "upload_time": datetime.now().isoformat(),
                        "content_type": "short_video",
                    }
                }
            else:
                # 文章（threads）欄位結構
                document = {
                    "_id": document_id,
                    "$vector": embedding,
                    "text": combined_text,
                    "metadata": {
                        "document_id": document_id,
                        "title": title,
                        "ocr_text": ocr_text,
                        "caption": caption,
                        "summary": summary,
                        "important_time": analysis_result.get("important_time", ""),
                        "important_location": analysis_result.get("important_location", ""),
                        "original_path": analysis_result.get("original_path", ""),
                        "source_type": source_type,  # threads/article
                        "upload_time": datetime.now().isoformat(),
                        "content_type": "article",
                    }
                }
            
            # 存儲到AstraDB
            print("正在存儲到AstraDB...")
            result = self.collection.insert_one(document)
            
            print(f"視頻數據存儲完成，文檔ID: {document_id}")
            
            # 返回結果
            return {
                "success": True,
                "document_id": document_id,
                "storage_result": {
                    "database_document": document,
                    "inserted_id": document_id
                }
            }
            
        except Exception as e:
            print(f"存儲視頻數據時發生錯誤: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def search_similar_videos(self, query: str, limit: int = 5) -> Dict:
        """根據文本查詢相似視頻"""
        if not self.collection:
            success = self.initialize_connection()
            if not success:
                return {"success": False, "error": "無法連接到AstraDB"}
        
        try:
            # 生成查詢向量
            query_embedding = self.embeddings.embed_query(query)
            
            # 執行向量搜索
            results = self.collection.vector_find(
                vector=query_embedding,
                limit=limit,
                fields=["metadata"]
            )
            
            # 處理結果 - 根據content_type返回不同的欄位
            formatted_results = []
            for doc in results:
                metadata = doc.get("metadata", {})
                content_type = metadata.get("content_type", "short_video")
                
                result_item = {
                    "document_id": metadata.get("document_id"),
                    "title": metadata.get("title"),
                    "summary": metadata.get("summary"),
                    "important_time": metadata.get("important_time"),
                    "important_location": metadata.get("important_location"),
                    "original_path": metadata.get("original_path"),
                    "upload_time": metadata.get("upload_time"),
                    "content_type": content_type
                }
                
                # 根據內容類型添加特定欄位
                if content_type == "image":
                    result_item["filename"] = metadata.get("filename")
                else:
                    result_item["source_type"] = metadata.get("source_type")
                
                formatted_results.append(result_item)
            
            return {
                "success": True,
                "results": formatted_results,
                "count": len(formatted_results)
            }
            
        except Exception as e:
            print(f"搜索視頻時發生錯誤: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def delete_record(self, document_id: str) -> Dict:
        """刪除指定ID的記錄"""
        if not self.collection:
            success = self.initialize_connection()
            if not success:
                return {"success": False, "error": "無法連接到AstraDB"}
        
        try:
            # 執行刪除操作
            print(f"正在刪除文檔 ID: {document_id}...")
            result = self.collection.delete_one({"_id": document_id})
            
            # 檢查刪除結果
            if result.deleted_count > 0:
                print(f"文檔已成功刪除: {document_id}")
                return {
                    "success": True,
                    "message": f"文檔已成功刪除: {document_id}"
                }
            else:
                print(f"未找到文檔: {document_id}")
                return {
                    "success": False,
                    "error": f"未找到文檔: {document_id}"
                }
                
        except Exception as e:
            print(f"刪除文檔時發生錯誤: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }