import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.summarizer import EmailSummarizer

def test_ftchinese_summary():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        return

    summarizer = EmailSummarizer(api_key)
    
    mock_email = {
        'subject': 'FT中文网每日精选',
        'sender': 'FT News <newsletter.ftchinese.com>',
        'body': '你好，这是今天的FT中文网每日精选。我们诚邀您阅读以下文章。'
    }
    
    print("Testing FTChinese email summarization...")
    analysis = summarizer.summarize(mock_email, include_translation=True)
    
    print("\n--- ANALYSIS RESULT ---")
    print(f"Summary: {analysis.get('summary')}")
    print(f"Pinyin: {analysis.get('pinyin')}")
    print(f"English: {analysis.get('english_translation')}")
    
    if analysis.get('pinyin') and analysis.get('english_translation'):
        print("\nSUCCESS: Pinyin and English translation generated.")
    else:
        print("\nFAILURE: Missing pinyin or English translation.")

if __name__ == "__main__":
    test_ftchinese_summary()
