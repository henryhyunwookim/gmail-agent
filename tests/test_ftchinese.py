import os
from dotenv import load_dotenv
from src.summarizer import EmailSummarizer
import json

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

def test_ftchinese():
    summarizer = EmailSummarizer(api_key)
    
    mock_email = {
        'subject': "每日FT速读",
        'sender': "newsletter.ftchinese.com",
        'body': """
欢迎订阅FT中文网！成为高级会员可以享受无限制阅读。
今天的新闻是关于全球经济复苏。
中国经济在第三季度表现出强劲的增长势头。
请点击这里了解更多关于我们会员福利的信息。
"""
    }
    
    analysis = summarizer.summarize(mock_email, include_translation=True)
    
    print("\n--- ANALYSIS RESULT ---")
    print(json.dumps(analysis, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    if not api_key:
        print("Set GEMINI_API_KEY to test.")
    else:
        test_ftchinese()
