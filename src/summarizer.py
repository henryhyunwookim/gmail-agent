import os
import google.generativeai as genai
import json

class EmailSummarizer:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')
    
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

    def summarize(self, email_content):
        """Summarizes the email and determines if action is required."""
        prompt = f"""You are an intelligent email assistant. Analyze the following email and provide a response.

Email Subject: {email_content['subject']}
Email Sender: {email_content['sender']}
Email Body:
{email_content['body'][:2000]}

IMPORTANT: You must respond with ONLY valid JSON in this exact format (no additional text):
{{
    "summary": "A concise 1-2 sentence summary of the email content",
    "action_required": true,
    "reason": "Brief explanation of why action is or isn't required"
}}

Rules:
- summary: Concise overview of the email (1-2 sentences)
- action_required: true if the email requires a response or action from the recipient, false otherwise
- reason: Brief explanation (one sentence)
- Output ONLY the JSON object, nothing else
"""
        
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            
            # Clean up markdown code blocks
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0].strip()
            elif '```' in text:
                text = text.split('```')[1].split('```')[0].strip()
            
            # Try to parse JSON
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract JSON from the text
                import re
                json_match = re.search(r'\{[^{}]*"summary"[^{}]*"action_required"[^{}]*"reason"[^{}]*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))
                else:
                    raise ValueError("Could not extract valid JSON from response")
                    
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error summarizing email: {e}")
            print(f"Raw response: {response.text if 'response' in locals() else 'No response'}")
            return {
                "summary": "Error summarizing email.",
                "action_required": False,
                "reason": "AI processing failed."
            }
