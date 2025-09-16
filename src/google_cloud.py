import base64
import json
import os
import time
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv
from google.cloud import pubsub_v1
from supabase import create_client, Client
from gmail_utils import authenticate_gmail, setup_gmail_push_notifications

# Load environment variables
load_dotenv()

# Configuration
PROJECT_ID = os.getenv("PROJECT_ID", "")
SUBSCRIPTION_NAME = os.getenv("SUBSCRIPTION_NAME", "")
TOPIC_NAME = os.getenv("TOPIC_NAME", "")

class GmailWorkflow:
    def __init__(self):
        """Initialize Gmail Workflow with essential clients"""
        self.service = authenticate_gmail()
        self.client = create_client(
            os.getenv("DATABASE_URL",""), 
            os.getenv("DATABASE_API_KEY","")
        )
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_NAME)
        self.processed_messages = set()
        
        # Setup Gmail push notifications
        setup_gmail_push_notifications(self.service, PROJECT_ID, TOPIC_NAME)
        print("Gmail workflow initialized")

    def send_initial_email(self, recipient: str, subject: str, body: str) -> str:
        """Send first email and create workflow record"""
        # Use HTML content type and wrap body in HTML template for better formatting
        html_body = f"""
<html>
  <body style=\"font-family: Arial, sans-serif; font-size: 15px; color: #222;\">
    {body}
  </body>
</html>
"""
        message = {
            'raw': base64.urlsafe_b64encode(
                f"To: {recipient}\r\n"
                f"Subject: {subject}\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n" #text/plain to text/html
                f"\r\n{html_body}".encode('utf-8')
            ).decode()
        }
        
        try:
            sent_message = self.service.users().messages().send(
                userId='me', body=message
            ).execute()
            
            thread_id = sent_message['threadId']
            self.save_workflow_state(thread_id, step=0, status='sent_initial')
            
            print(f"Initial email sent - Thread: {thread_id}")
            return thread_id
            
        except Exception as e:
            print(f"Error sending initial email: {e}")
            raise

    def pubsub_listener(self, event_data: bytes) -> None:
        """Enhanced Pub/Sub listener with improved error handling (no timeouts)"""
        try:
            notification = json.loads(event_data.decode('utf-8'))
            history_id = notification.get('historyId')
            
            if not history_id:
                return
            
            # Fetch messages using history API
            try:
                history_response = self.service.users().history().list(
                    userId='me',
                    startHistoryId=str(max(1, int(history_id) - 100)),
                    historyTypes=['messageAdded']
                ).execute()
            except Exception:
                # Fallback to recent messages if history fails
                try:
                    recent_messages = self.service.users().messages().list(
                        userId='me',
                        maxResults=5
                    ).execute()
                    
                    if 'messages' in recent_messages:
                        for msg in recent_messages['messages']:
                            try:
                                full_message = self.service.users().messages().get(
                                    userId='me',
                                    id=msg['id'],
                                    format='full'
                                ).execute()
                                
                                # Only process recent messages (last 5 minutes)
                                internal_date = int(full_message.get('internalDate', 0))
                                if (time.time() * 1000 - internal_date) < 5 * 60 * 1000:
                                    self.process_incoming_message(full_message)
                            except Exception as msg_error:
                                # Skip individual messages that can't be fetched
                                if "not found" in str(msg_error).lower():
                                    print(f"Message {msg['id']} not found, skipping...")
                                else:
                                    print(f"Error fetching message {msg['id']}: {msg_error}")
                                continue
                except Exception as fallback_error:
                    print(f"Fallback message fetch failed: {fallback_error}")
                return
            
            # Process history response
            if 'history' not in history_response:
                return
                
            for history_item in history_response['history']:
                if 'messagesAdded' in history_item:
                    for message_added in history_item['messagesAdded']:
                        message_id = message_added['message']['id']
                        
                        try:
                            full_message = self.service.users().messages().get(
                                userId='me',
                                id=message_id,
                                format='full'
                            ).execute()
                            
                            self.process_incoming_message(full_message)
                        except Exception as fetch_error:
                            # Handle individual message fetch errors gracefully
                            if "not found" in str(fetch_error).lower():
                                print(f"Message {message_id} not found, skipping...")
                            else:
                                print(f"Error fetching message {message_id}: {fetch_error}")
                            continue
                        
        except Exception as e:
            # Handle timeout errors silently (these are expected)
            if "timed out" in str(e).lower():
                # This is normal - Pub/Sub read timeouts are expected, just continue
                pass
            else:
                print(f"Error in pubsub_listener: {e}")

    def setup_enhanced_integration(self, chat_app=None, active_threads=None):
        """Setup integration with AI chat application and thread tracking"""
        if chat_app:
            self.chat_app = chat_app
        if active_threads is not None:
            self.active_threads = active_threads
            
        # Override process_incoming_message for AI integration
        original_process_incoming = self.process_incoming_message
        
        def enhanced_process_incoming_message(message: dict):
            try:
                thread_id = message['threadId']
                message_id = message['id']
                
                # Skip if already processed
                if message_id in self.processed_messages:
                    return
                self.processed_messages.add(message_id)
                
                # Extract headers for validation
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                to_header = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
                subject_header = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
                
                # Extract email body for debugging
                email_body = self.extract_email_body(message)
                
                my_email = os.getenv("GMAIL_ADDRESS", "")
                if not my_email:
                    profile = self.service.users().getProfile(userId='me').execute()
                    my_email = profile.get('emailAddress', '')
                
                # Skip validation (same as original)
                if my_email.lower() in from_header.lower():
                    return
                if my_email.lower() not in to_header.lower():
                    return
                if 'noreply' in from_header.lower():
                    return
                
                # Load workflow state
                workflow_state = self.load_workflow_state(thread_id)
                if not workflow_state:
                    return
                    
                current_step = workflow_state['step']
                if current_step >= 4:
                    return
                
                # Generate AI response if chat app is available
                if hasattr(self, 'chat_app') and self.chat_app and hasattr(self, 'active_threads'):
                    user_email = self.active_threads.get(thread_id, {}).get('email', '')
                    if user_email:
                        try:
                            # Enhanced prompt with email content
                            base_prompts = {
                                0: f"The user {user_email} has replied to our initial welcome email. Their response was: '{email_body[:500]}...' Generate a follow-up email asking about their background and interests, acknowledging their previous response.",
                                1: f"The user {user_email} has replied again. Their latest response was: '{email_body[:500]}...' Generate a more engaging follow-up email building on this conversation.",
                                2: f"The user {user_email} replied with: '{email_body[:500]}...' Based on their interests shown in this conversation, generate a personalized event invitation.",
                                3: f"Generate a final follow-up for {user_email} based on their response: '{email_body[:500]}...'"
                            }
                            
                            prompt = base_prompts.get(current_step, f"Generate a follow-up for {user_email}")
                            
                            ai_response = self.chat_app.process_user_input(prompt)
                            
                            self.workflow_manager(thread_id, current_step, message, message_body=ai_response)
                            return
                        except Exception as e:
                            # Fall back to default workflow
                            pass
                
                # Use default workflow manager
                self.workflow_manager(thread_id, current_step, message)
                
            except Exception as e:
                print(f"Error in enhanced message processing: {e}")
        
        # Replace the method
        self.process_incoming_message = enhanced_process_incoming_message

    def extract_email_body(self, message: dict) -> str:
        """Extract email body from Gmail message for debugging and AI context"""
        try:
            payload = message.get('payload', {})
            
            # Handle multipart messages
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        body_data = part.get('body', {}).get('data', '')
                        if body_data:
                            return base64.urlsafe_b64decode(body_data).decode('utf-8')
            
            # Handle single part messages
            elif payload.get('mimeType') == 'text/plain':
                body_data = payload.get('body', {}).get('data', '')
                if body_data:
                    return base64.urlsafe_b64decode(body_data).decode('utf-8')
            
            # Fallback to snippet
            return message.get('snippet', '')
            
        except Exception as e:
            return message.get('snippet', '')

    def process_incoming_message(self, message: dict) -> None:
        """Check if message is a reply to our workflow and process it"""
        try:
            thread_id = message['threadId']
            message_id = message['id']
            
            # Skip if already processed
            if message_id in self.processed_messages:
                return
            self.processed_messages.add(message_id)
            
            # Extract headers
            headers = message['payload'].get('headers', [])
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            to_header = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
            
            # Get our email address
            my_email = os.getenv("GMAIL_ADDRESS", "")
            if not my_email:
                profile = self.service.users().getProfile(userId='me').execute()
                my_email = profile.get('emailAddress', '')
            
            # Skip messages from us or to others
            if my_email.lower() in from_header.lower():
                return
            if my_email.lower() not in to_header.lower():
                return
            if 'noreply' in from_header.lower():
                return
            
            # Load workflow state
            workflow_state = self.load_workflow_state(thread_id)
            if not workflow_state:
                return
                
            current_step = workflow_state['step']
            
            # Skip if workflow completed
            if current_step >= 4:
                return
            
            self.workflow_manager(thread_id, current_step, message)
            
        except Exception as e:
            print(f"Error processing message: {e}")

    def workflow_manager(self, thread_id: str, step: int, incoming_message: dict = {}, message_body: str = "", message_subject: str = "") -> None:
        """Enhanced workflow manager that supports AI-generated responses"""
        try:
            # Get user email from thread (for AI integration)
            user_email = getattr(self, 'active_threads', {}).get(thread_id, {}).get('email', '')
            
            if step < 3:  # Steps 0, 1, 2 send responses
                # If message_body is provided (AI-generated), use it; otherwise fallback to default
                if message_body:
                    body = message_body
                else:
                    body = f"Testing testing - Follow-up #{step + 1}"
                
                subject = message_subject
                
                self.send_reply_email(thread_id, body, message_body=body, message_subject=subject)
                self.save_workflow_state(thread_id, step=step+1, status=f'sent_followup_{step+1}')
                
            elif step == 3:
                self.save_workflow_state(thread_id, step=4, status='completed')
                
        except Exception as e:
            print(f"Error in workflow_manager: {e}")

    def send_reply_email(self, thread_id: str, body: str, message_body: str = "", message_subject: str = "") -> None:
        """Send reply in existing thread using HTML formatting and paragraph breaks like initial email"""
        try:
            # Get thread messages
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id
            ).execute()

            # Find most recent external message to reply to
            my_email = os.getenv("GMAIL_ADDRESS", "")
            if not my_email:
                profile = self.service.users().getProfile(userId='me').execute()
                my_email = profile.get('emailAddress', '')

            latest_external_message = None
            for message in reversed(thread['messages']):
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                if my_email.lower() not in from_header.lower():
                    latest_external_message = message
                    break

            if not latest_external_message:
                return

            headers = latest_external_message['payload'].get('headers', [])
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            subject_header = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            message_id_header = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')

            # Prepare reply subject - use custom subject if provided, otherwise default behavior
            if message_subject:
                reply_subject = message_subject
            else:
                reply_subject = f"Re: {subject_header}" if not subject_header.startswith('Re:') else subject_header

            # Use custom body if provided, otherwise use the passed body parameter
            email_body = message_body or body

            # --- Format reply body with HTML paragraph breaks (like initial email) ---
            paragraphs = [p.strip() for p in email_body.strip().split('\n\n') if p.strip()]
            if not paragraphs:
                paragraphs = [email_body.strip()]
            body_paragraphs = [f"<p>{p}</p>" for p in paragraphs]
            formatted_html_body = '\n'.join(body_paragraphs)

            html_body = f"""
<html>
  <body style=\"font-family: Arial, sans-serif; font-size: 15px; color: #222;\">
    {formatted_html_body}
  </body>
</html>
"""

            # Create reply message with HTML content type
            reply_message = {
                'raw': base64.urlsafe_b64encode(
                    f"To: {from_header}\r\n"
                    f"Subject: {reply_subject}\r\n"
                    f"In-Reply-To: {message_id_header}\r\n"
                    f"References: {message_id_header}\r\n"
                    f"Content-Type: text/html; charset=utf-8\r\n" #text/plain to text/html
                    f"\r\n{html_body}".encode('utf-8')
                ).decode(),
                'threadId': thread_id
            }

            # Send reply
            self.service.users().messages().send(
                userId='me', body=reply_message
            ).execute()

            print(f"Reply sent - Thread: {thread_id}")

        except Exception as e:
            print(f"Error sending reply: {e}")

    def save_workflow_state(self, thread_id: str, step: int, status: str) -> None:
        """Save workflow state to Supabase"""
        try:
            workflow_data = {
                'thread_id': thread_id,
                'step': step,
                'status': status,
                'updated_at': datetime.now().isoformat()
            }
            
            self.client.table('workflows').upsert(
                workflow_data,
                on_conflict='thread_id'
            ).execute()
            
        except Exception as e:
            print(f"Error saving workflow state: {e}")

    def load_workflow_state(self, thread_id: str) -> Optional[Dict]:
        """Load workflow state from Supabase"""
        try:
            result = self.client.table('workflows').select('*').eq('thread_id', thread_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"Error loading workflow state: {e}")
            return None

    def start_listening(self):
        """Start Pub/Sub listener with indefinite waiting capability"""
        def callback(message):
            try:
                self.pubsub_listener(message.data)
                message.ack()
            except Exception as e:
                # Handle timeout errors silently, others with logging
                if "timed out" in str(e).lower():
                    # Silent handling of timeout - this is normal
                    pass
                else:
                    print(f"Error processing Pub/Sub message: {e}")
                # Always acknowledge to prevent redelivery
                message.ack()
        
        # Configure flow control without timeout constraints
        flow_control = pubsub_v1.types.FlowControl(max_messages=10)
        future = self.subscriber.subscribe(
            self.subscription_path, 
            callback=callback,
            flow_control=flow_control
        )
        
        print("Pub/Sub listener started")
        return future

    def stop_listening(self, future):
        """Stop Pub/Sub listener"""
        if future:
            future.cancel()

def main():
    """Run the standalone workflow system (for testing)"""
    workflow = GmailWorkflow()
    
    # Start listener
    listener_future = workflow.start_listening()
    
    # Optional: Send initial email
    recipient = input("Enter recipient email (or press Enter to skip): ").strip()
    if recipient:
        workflow.send_initial_email(
            recipient=recipient,
            subject="Test Workflow Email", 
            body="This is the initial email. Please reply to continue."
        )
    
    print("Gmail workflow running. Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        workflow.stop_listening(listener_future)
        print("Workflow stopped")

if __name__ == "__main__":
    main()