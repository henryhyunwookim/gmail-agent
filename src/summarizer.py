import os
import google.generativeai as genai
import json

class EmailSummarizer:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')
    
    def extract_unsubscribe_link(self, email_body):
        """Extracts unsubscribe link from email body if present."""
        import re
        
        # Common unsubscribe link patterns
        patterns = [
            r'https?://[^\s<>"]+?unsubscribe[^\s<>"]*',
            r'https?://[^\s<>"]+?optout[^\s<>"]*',
            r'https?://[^\s<>"]+?opt-out[^\s<>"]*',
            r'https?://[^\s<>"]+?remove[^\s<>"]*',
            r'https?://[^\s<>"]+?preferences[^\s<>"]*',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, email_body, re.IGNORECASE)
            if match:
                link = match.group(0)
                # Clean up trailing punctuation or HTML artifacts
                link = re.sub(r'[,;.)\]]+$', '', link)
                return link
        
        return None
    
    def is_purchase_email(self, email_content):
        """Quickly determines if an email is purchase/transactional related."""
        # Quick keyword check first
        subject_lower = email_content['subject'].lower()
        body_lower = email_content['body'][:500].lower()
        sender_lower = email_content['sender'].lower()
        
        purchase_keywords = [
            'order', 'purchase', 'receipt', 'invoice', 'payment', 'transaction',
            'shipped', 'delivery', 'tracking', 'confirmation', 'your order',
            'thank you for your order', 'order number', 'tracking number',
            'order confirmation', 'purchase confirmation', 'order placed',
            'order received', 'order summary', 'billing', 'charge'
        ]
        
        # Common e-commerce sender domains
        purchase_domains = [
            'amazon', 'rakuten', 'ebay', 'paypal', 'stripe', 'shopify',
            'shop.', 'store.', 'orders@', 'noreply@', 'no-reply@'
        ]
        
        # Check if sender is from a known e-commerce platform
        is_commerce_sender = any(domain in sender_lower for domain in purchase_domains)
        
        # If multiple purchase keywords found, likely a purchase email
        keyword_count = sum(1 for keyword in purchase_keywords if keyword in subject_lower or keyword in body_lower)
        
        # Filter if: (2+ keywords) OR (commerce sender + 1+ keyword)
        return keyword_count >= 2 or (is_commerce_sender and keyword_count >= 1)

    def summarize(self, email_content, include_translation=False):
        """Summarizes the email and determines if action is required."""
        # Extract unsubscribe link
        unsubscribe_link = self.extract_unsubscribe_link(email_content['body'])
        
        translation_instructions = ""
        if include_translation:
            translation_instructions = """
- Since this is a Chinese email for learning purposes, you MUST provide a "learning_segments" list. 
- Break the email body into 3-5 logical segments (paragraphs or groups of related sentences).
- For each segment, provide:
    - "original": The original Chinese text.
    - "pinyin": The pinyin for the segment with tone marks.
    - "vocabulary": A list of key words/phrases in that segment, e.g., [{"word": "...", "pinyin": "...", "english": "..."}].
    - "translation": The English translation of that specific segment.
"""

        prompt = f"""You are an intelligent email assistant. Analyze the following email and provide a structured response.

Email Subject: {email_content['subject']}
Email Sender: {email_content['sender']}
Email Body:
{email_content['body'][:4000]}

IMPORTANT: You must respond with ONLY valid JSON in this exact format (no additional text):
{{
    "summary": "A concise 1-2 sentence overall summary of the email",
    "sections": [
        {{
            "topic": "Topic or theme of this section",
            "insight": "Key insight, information, or takeaway from this section"
        }}
    ],
    "action_required": true,
    "reason": "Brief explanation of why action is or isn't required"{', "learning_segments": [{"original": "...", "pinyin": "...", "vocabulary": [{"word": "...", "pinyin": "...", "english": "..."}], "translation": "..."}]' if include_translation else ''}
}}

Rules:
- summary: Concise overall summary of the email (1-2 sentences)
- sections: Break down the email into logical sections.
- action_required: true if the email requires a response or action from the recipient, false otherwise
- reason: Brief explanation (one sentence){translation_instructions}
- Output ONLY the JSON object, nothing else
"""
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                text = response.text.strip()
                
                # Attempt to extract JSON
                extracted_json = text
                
                # 1. Try finding json code blocks
                if '```json' in text:
                    extracted_json = text.split('```json')[1].split('```')[0].strip()
                elif '```' in text:
                    extracted_json = text.split('```')[1].split('```')[0].strip()
                
                # 2. Try parsing
                try:
                    result = json.loads(extracted_json)
                    result['unsubscribe_link'] = unsubscribe_link
                    return result
                except json.JSONDecodeError:
                    # 3. Fallback: regex search for JSON object
                    import re
                    # Look for { ... } structure, non-greedy
                    json_match = re.search(r'(\{[\s\S]*\})', text)
                    if json_match:
                        try:
                            result = json.loads(json_match.group(1))
                            result['unsubscribe_link'] = unsubscribe_link
                            return result
                        except json.JSONDecodeError:
                            pass # Continue to raise error or retry
                    
                    # If we are here, parsing failed.
                    # If this was the last attempt, raise the error to be caught below
                    if attempt == max_retries - 1:
                        raise ValueError(f"Could not parse JSON from response: {text[:100]}...")
                    else:
                        print(f"JSON parsing failed on attempt {attempt+1}. Retrying...")
                        continue

            except Exception as e:
                import traceback
                import time
                
                print(f"Attempt {attempt+1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    traceback.print_exc()
                    print(f"Error summarizing email after {max_retries} attempts: {e}")
                    
                    # Capture specific error message
                    error_reason = f"AI processing failed: {str(e)}"
                    
                    return {
                        "summary": "Error summarizing email.",
                        "action_required": False,
                        "reason": error_reason,
                        "unsubscribe_link": unsubscribe_link
                    }
