import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from bs4 import BeautifulSoup

class GmailClient:
    def __init__(self, creds):
        self.service = build('gmail', 'v1', credentials=creds)

    def list_unread_messages(self, max_results=10):
        """Lists unread messages."""
        try:
            results = self.service.users().messages().list(
                userId='me', q='is:unread', maxResults=max_results).execute()
            messages = results.get('messages', [])
            return messages
        except HttpError as error:
            print(f'An error occurred: {error}')
            return []
    
    def thread_has_summary(self, thread_id, user_email):
        """Check if a thread already has a forwarded summary from the agent."""
        try:
            thread = self.service.users().threads().get(userId='me', id=thread_id).execute()
            messages = thread.get('messages', [])
            
            # Check if any message in the thread is a forward from the user with "Fwd:" subject
            for msg in messages:
                # Skip messages in trash
                label_ids = msg.get('labelIds', [])
                if 'TRASH' in label_ids:
                    continue
                
                headers = msg.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
                
                # Check if it's a forward from user (our summary)
                if 'Fwd:' in subject and user_email.lower() in sender.lower():
                    return True
            return False
        except HttpError as error:
            print(f'Error checking thread: {error}')
            return False

    def get_message_content(self, msg_id):
        """Gets the content of a message."""
        try:
            message = self.service.users().messages().get(userId='me', id=msg_id).execute()
            payload = message.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            
            parts = payload.get('parts', [])
            body = ""
            
            if not parts:
                # Simple message
                data = payload.get('body', {}).get('data')
                if data:
                    body = base64.urlsafe_b64decode(data).decode()
            else:
                # Multipart message
                for part in parts:
                    if part.get('mimeType') == 'text/plain':
                        data = part.get('body', {}).get('data')
                        if data:
                            body += base64.urlsafe_b64decode(data).decode()
                    elif part.get('mimeType') == 'text/html':
                        # Prefer plain text, but if only HTML exists, we might want to parse it
                        # For now, let's just append it if we don't have body yet, or ignore
                        pass
            
            # If body is HTML, strip tags (simple approach)
            if body and '<html' in body.lower():
                soup = BeautifulSoup(body, 'html.parser')
                body = soup.get_text()

            return {
                'id': msg_id,
                'subject': subject,
                'sender': sender,
                'body': body
            }
        except HttpError as error:
            print(f'An error occurred: {error}')
            return None

    def send_reply(self, to, subject, body):
        """Sends a reply email."""
        try:
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            body = {'raw': raw}
            
            message = self.service.users().messages().send(userId='me', body=body).execute()
            print(f'Message Id: {message["id"]}')
            return message
        except HttpError as error:
            print(f'An error occurred: {error}')
            return None
    
    
    def forward_message(self, original_msg_id, to, summary_text):
        """Forwards a message with summary prepended and original email embedded, preserving thread."""
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.message import MIMEMessage
            from email import message_from_bytes
            
            # Get the original message in raw format and metadata
            original = self.service.users().messages().get(userId='me', id=original_msg_id, format='raw').execute()
            original_raw = base64.urlsafe_b64decode(original['raw'])
            
            # Parse the original email
            original_email = message_from_bytes(original_raw)
            
            # Create the forwarding message
            msg = MIMEMultipart()
            msg['To'] = to
            msg['Subject'] = 'Fwd: ' + (original_email.get('Subject', 'No Subject'))
            
            # Add threading headers to keep it in the same thread
            if original_email.get('Message-ID'):
                msg['In-Reply-To'] = original_email.get('Message-ID')
                msg['References'] = original_email.get('References', '') + ' ' + original_email.get('Message-ID')
            
            # Add summary as the first part (plain text)
            summary_part = MIMEText(summary_text, 'plain')
            msg.attach(summary_part)
            
            # Attach the original email as message/rfc822
            # This makes Gmail display it as a proper embedded email
            original_msg_part = MIMEMessage(original_email)
            msg.attach(original_msg_part)
            
            # Send the message with threadId to keep in same conversation
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            body = {
                'raw': raw,
                'threadId': original['threadId']  # Keep in same thread
            }
            
            message = self.service.users().messages().send(userId='me', body=body).execute()
            print(f'Forwarded Message Id: {message["id"]} (Thread: {message.get("threadId", "N/A")})')
            return message
        except HttpError as error:
            print(f'An error occurred: {error}')

            return None
            
    def mark_as_read(self, msg_id):
        """Marks a message as read."""
        try:
            self.service.users().messages().modify(
                userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
        except HttpError as error:
            print(f'An error occurred: {error}')
    
    def get_or_create_label(self, label_name):
        """Gets or creates a Gmail label by name."""
        try:
            # List all labels
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            # Check if label exists
            for label in labels:
                if label['name'] == label_name:
                    return label['id']
            
            # Create label if it doesn't exist
            label_object = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            created_label = self.service.users().labels().create(userId='me', body=label_object).execute()
            print(f'Created new label: {label_name}')
            return created_label['id']
        except HttpError as error:
            print(f'An error occurred getting/creating label: {error}')
            return None
    
    def add_label(self, msg_id, label_name):
        """Adds a label to a message."""
        try:
            label_id = self.get_or_create_label(label_name)
            if label_id:
                self.service.users().messages().modify(
                    userId='me', id=msg_id, body={'addLabelIds': [label_id]}).execute()
                print(f'Applied label: {label_name}')
        except HttpError as error:
            print(f'An error occurred adding label: {error}')
    
    def send_execution_log(self, to, stats, errors=None, execution_time="Unknown"):
        """Sends an execution summary email with statistics and errors."""
        try:
            from datetime import datetime
            
            # Format the execution summary
            status = "✅ SUCCESS" if not errors else "❌ FAILED"
            
            error_section = ""
            if errors:
                error_section = f"\n\n🚨 ERRORS:\n{errors}\n"
            
            body = f"""
Gmail Agent Execution Log
========================

Status: {status}
Execution Time: {execution_time}

📊 STATISTICS:
--------------
Total unread emails: {stats.get('total', 0)}
Filtered (self-sent): {stats.get('self_sent', 0)}
Filtered (purchase): {stats.get('purchase', 0)}
Filtered (already summarized): {stats.get('already_summarized', 0)}
Processed & forwarded: {stats.get('processed', 0)}
{error_section}
========================

This is an automated execution log from your Gmail Agent running on Google Cloud Run.
"""
            
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = f"Gmail Agent Log - {status} - {execution_time}"
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            body_data = {'raw': raw}
            
            result = self.service.users().messages().send(userId='me', body=body_data).execute()
            print(f'Execution log sent. Message Id: {result["id"]}')
            return result
        except HttpError as error:
            print(f'An error occurred sending execution log: {error}')
            return None

