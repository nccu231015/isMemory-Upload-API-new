"""
Vercel部署入口點
"""
import sys
import os

# 添加根目錄到Python路徑，以便導入模組
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel會自動調用這個app實例
# 不需要額外的handler函數
