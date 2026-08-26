import time
from unittest.mock import MagicMock
import sys
import os

# Insert src directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.summarizer import EmailSummarizer

class MockGenerativeModel:
    def __init__(self, model_name):
        self.call_count = 0
    
    def generate_content(self, prompt):
        self.call_count += 1
        if self.call_count < 2:
            raise Exception("429 Resource exhausted: Quota exceeded")
        
        mock_response = MagicMock()
        mock_response.text = '{"summary": "Test", "sections": [], "action_required": false, "reason": "Test"}'
        return mock_response

# Mock google.generativeai.GenerativeModel globally before instantiating
import google.generativeai as genai
genai.GenerativeModel = MockGenerativeModel
genai.configure = MagicMock()


def test_summarizer_rate_limit():
    # Monkey patch time.sleep so we don't actually wait 60 seconds
    original_sleep = time.sleep
    sleeps = []
    def mock_sleep(seconds):
        sleeps.append(seconds)
    time.sleep = mock_sleep

    try:
        summarizer = EmailSummarizer("fake_key")
        content = {
            "subject": "Test",
            "sender": "test@example.com",
            "body": "Test body"
        }
        res = summarizer.summarize(content, include_translation=False)
        print("Summary result:", res["summary"])
        print("Sleeps triggered:", sleeps)
    finally:
        time.sleep = original_sleep

def test_extract_unsubscribe_link_multilingual():
    summarizer = EmailSummarizer("fake_key")
    
    # Test 1: Plain text English (fallback)
    plain_text_en = "Please click here to unsubscribe: https://example.com/unsubscribe/123."
    assert summarizer.extract_unsubscribe_link(plain_text_en) == "https://example.com/unsubscribe/123"
    
    # Test 2: HTML with Spanish anchor text
    html_es = '<html><body>Para <a href="https://example.com/baja">darse de baja</a>, haz clic aquí.</body></html>'
    assert summarizer.extract_unsubscribe_link(html_es) == "https://example.com/baja"
    
    # Test 3: HTML with Chinese anchor text
    html_zh = '<html><body>如果您不想收到此类邮件，请点击这里<a href="https://example.com/tuiding">退订</a></body></html>'
    assert summarizer.extract_unsubscribe_link(html_zh) == "https://example.com/tuiding"
    
    # Test 4: HTML with English URL keyword but no anchor text keyword
    html_url = '<html><body>Click the link: <a href="https://example.com/optout?user=123">here</a></body></html>'
    assert summarizer.extract_unsubscribe_link(html_url) == "https://example.com/optout?user=123"

if __name__ == "__main__":
    test_summarizer_rate_limit()
    test_extract_unsubscribe_link_multilingual()
    print("All tests passed!")
