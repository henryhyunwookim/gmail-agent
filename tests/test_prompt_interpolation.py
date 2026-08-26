
import sys
import os
from unittest.mock import MagicMock

# Insert src directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import google.generativeai as genai
# Mock genai before importing EmailSummarizer properly
genai.GenerativeModel = MagicMock()
genai.configure = MagicMock()

from src.summarizer import EmailSummarizer

def test_prompt_interpolation():
    # Setup
    summarizer = EmailSummarizer("fake_key")
    
    # Mock the generate_content to capture the prompt
    captured_prompt = []
    def mock_generate_content(prompt):
        captured_prompt.append(prompt)
        mock_response = MagicMock()
        mock_response.text = '{"summary": "Test", "sections": [], "action_required": false, "reason": "Test"}'
        return mock_response
    
    summarizer.model.generate_content = mock_generate_content
    
    # Test data
    email_content = {
        "subject": "FIXED_SUBJECT",
        "sender": "FIXED_SENDER",
        "body": "FIXED_BODY_CONTENT"
    }
    
    # Run summarization (general)
    summarizer.summarize(email_content, include_translation=False)
    
    # Verify prompt contents
    prompt = captured_prompt[0]
    print("Checking General Prompt:")
    assert "FIXED_SUBJECT" in prompt
    assert "FIXED_SENDER" in prompt
    assert "FIXED_BODY_CONTENT" in prompt
    assert "{email_content['subject']}" not in prompt
    print("✓ General prompt correctly interpolated")
    
    # Run summarization (FTChinese)
    captured_prompt.clear()
    summarizer.summarize(email_content, include_translation=True)
    
    prompt_zh = captured_prompt[0]
    print("\nChecking FTChinese Prompt:")
    assert "FIXED_SUBJECT" in prompt_zh
    assert "FIXED_SENDER" in prompt_zh
    assert "FIXED_BODY_CONTENT" in prompt_zh
    assert "{email_content['subject']}" not in prompt_zh
    print("✓ FTChinese prompt correctly interpolated")

if __name__ == "__main__":
    try:
        test_prompt_interpolation()
        print("\nAll interpolation tests passed!")
    except AssertionError as e:
        print(f"\nTest failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
