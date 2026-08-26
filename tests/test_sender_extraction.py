import json
from unittest.mock import MagicMock
import time

def test_sender_parsing():
    senders = [
        "John Doe <john@example.com>",
        "<news@newsletter.ftchinese.com>",
        "news@newsletter.ftchinese.com>",
        "news@newsletter.ftchinese.com"
    ]
    
    for sender_email in senders:
        original = sender_email
        if '<' in sender_email:
            sender_email = sender_email.split('<')[1].split('>')[0]
        sender_email = sender_email.strip('<> ')
        
        is_ftchinese = sender_email.lower().endswith("newsletter.ftchinese.com")
        print(f"Original: {original} | Parsed: {sender_email} | FTChinese: {is_ftchinese}")

test_sender_parsing()
