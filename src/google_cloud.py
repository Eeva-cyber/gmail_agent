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

# Global configuration
PROJECT_ID = "gmail-agent-470407"
SUBSCRIPTION_NAME = "gmail-events-sub"
TOPIC_NAME = "gmail-events"

class GmailWorkflowSystem:
    def __init__(self):
        """Initialize Gmail Workflow System with all necessary clients"""
        self.service = authenticate_gmail()
        self.client = create_client(
            os.getenv("DATABASE_URL"), 
            os.getenv("DATABASE_API_KEY")
        )
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(
            PROJECT_ID, SUBSCRIPTION_NAME
        )
        self.streaming_pull_future = None
        
        # Track processed messages to avoid duplicates
        self.processed_messages = set()
        
        # Setup Gmail push notifications
        self._setup_push_notifications()
        
        print("Gmail Workflow System initialized successfully")

    def _setup_push_notifications(self):
        """Setup Gmail push notifications"""
        try:
            setup_gmail_push_notifications(self.service, PROJECT_ID, TOPIC_NAME)
            print(f"Gmail push notifications setup complete")
        except Exception as e:
            print(f"Error setting up push notifications: {e}")

    def send_initial_email(self, user_id: str, recipient: str, subject: str, body: str) -> str:
        """Sends the first email to a user. Stores threadId and workflow state in Supabase. Returns thread_id for tracking."""
        
        # Create email message with proper MIME format
        message = {
            'raw': base64.urlsafe_b64encode(
                f"To: {recipient}\r\n"
                f"Subject: {subject}\r\n"
                f"Content-Type: text/plain; charset=utf-8\r\n"
                f"\r\n{body}".encode('utf-8')
            ).decode()
        }
        
        try:
            # Send email via Gmail API
            sent_message = self.service.users().messages().send(
                userId=user_id, body=message
            ).execute()
            
            thread_id = sent_message['threadId']
            message_id = sent_message['id']
            
            # Save initial workflow state
            self.save_workflow_state(thread_id, step=0, status='sent_initial')
            
            print(f"✅ Initial email sent successfully!")
            print(f"   Thread ID: {thread_id}")
            print(f"   Message ID: {message_id}")
            print(f"   Recipient: {recipient}")
            
            return thread_id
            
        except Exception as e:
            print(f"❌ Error sending initial email: {e}")
            raise
        
    def pubsub_listener(self, event_data: bytes) -> None:
        """Process Pub/Sub message and extract new Gmail messages"""
        
        try:
            # Decode Pub/Sub message
            message_data = event_data.decode('utf-8')
            notification = json.loads(message_data)
            
            email_address = notification.get('emailAddress')
            history_id = notification.get('historyId')
            
            print(f"\n🔔 RAW PUBSUB NOTIFICATION:")
            print(f"   Email: {email_address}")
            print(f"   History ID: {history_id}")
            print(f"   Full notification: {notification}")
            
            if not history_id:
                print("⚠️ No historyId in notification")
                return
                
            print(f"🔔 Processing notification for {email_address}, historyId: {history_id}")
            
            # Get stored history ID or use a default
            stored_history_id = self.get_last_history_id()
            start_history_id = stored_history_id if stored_history_id else str(max(1, int(history_id) - 100))
            
            print(f"📋 HISTORY ID CALCULATION:")
            print(f"   Current historyId: {history_id}")
            print(f"   Stored historyId: {stored_history_id}")
            print(f"   Using startHistoryId: {start_history_id}")
            
            # Fetch new messages using history API
            try:
                history_response = self.service.users().history().list(
                    userId='me',
                    startHistoryId=start_history_id,
                    historyTypes=['messageAdded']
                ).execute()
                
                print(f"📋 HISTORY API RESPONSE:")
                print(f"   Full response keys: {list(history_response.keys())}")
                print(f"   Full response: {history_response}")
                
            except Exception as api_error:
                print(f"⚠️ Gmail API error fetching history: {api_error}")
                return
            
            # Store the current history ID for next time
            self.save_last_history_id(history_id)
            
            if 'history' not in history_response:
                print("ℹ️ No new messages in history")
                print(f"📋 Response only contains: {list(history_response.keys())}")
                
                # Let's also try to get recent messages directly
                print("🔍 Trying alternative approach - fetching recent messages...")
                try:
                    recent_messages = self.service.users().messages().list(
                        userId='me',
                        maxResults=10,
                        q=''  # Get all recent messages
                    ).execute()
                    
                    print(f"📬 RECENT MESSAGES:")
                    if 'messages' in recent_messages:
                        print(f"   Found {len(recent_messages['messages'])} recent messages")
                        
                        # Process the most recent messages
                        for msg in recent_messages['messages'][:5]:  # Check last 5 messages
                            message_id = msg['id']
                            print(f"\n🔍 Checking recent message: {message_id}")
                            
                            try:
                                full_message = self.service.users().messages().get(
                                    userId='me',
                                    id=message_id,
                                    format='full'
                                ).execute()
                                
                                # Check if this message was received recently (last 5 minutes)
                                internal_date = int(full_message.get('internalDate', 0))
                                current_time = int(time.time() * 1000)
                                time_diff = current_time - internal_date
                                
                                print(f"   Internal date: {internal_date}")
                                print(f"   Current time: {current_time}")
                                print(f"   Time diff: {time_diff}ms ({time_diff/1000/60:.1f} minutes)")
                                
                                # If message is less than 5 minutes old, process it
                                if time_diff < 5 * 60 * 1000:  # 5 minutes in milliseconds
                                    print(f"✅ Recent message detected - processing...")
                                    self.process_incoming_message('me', full_message)
                                else:
                                    print(f"⏭️ Message too old, skipping")
                                    
                            except Exception as msg_error:
                                print(f"❌ Error processing recent message {message_id}: {msg_error}")
                    else:
                        print("   No recent messages found")
                        
                except Exception as recent_error:
                    print(f"❌ Error fetching recent messages: {recent_error}")
                
                return
                
            print(f"📬 Found {len(history_response['history'])} history items")
                
            # Process each new message
            messages_processed = 0
            for i, history_item in enumerate(history_response['history']):
                print(f"\n📋 HISTORY ITEM {i}:")
                print(f"   Keys: {list(history_item.keys())}")
                
                if 'messagesAdded' in history_item:
                    print(f"📨 Processing {len(history_item['messagesAdded'])} added messages")
                    for j, message_added in enumerate(history_item['messagesAdded']):
                        message_id = message_added['message']['id']
                        
                        print(f"\n📧 MESSAGE ADDED {j}:")
                        print(f"   Message ID: {message_id}")
                        print(f"   Full message_added: {message_added}")
                        
                        try:
                            # Fetch full message details
                            full_message = self.service.users().messages().get(
                                userId='me',
                                id=message_id,
                                format='full'
                            ).execute()
                            
                            print(f"🔍 FULL MESSAGE DETAILS:")
                            print(f"   Thread ID: {full_message.get('threadId', 'NO_THREAD_ID')}")
                            print(f"   Message ID: {full_message.get('id', 'NO_MESSAGE_ID')}")
                            print(f"   Snippet: {full_message.get('snippet', 'NO_SNIPPET')}")
                            
                            # Process the incoming message
                            self.process_incoming_message('me', full_message)
                            messages_processed += 1
                            
                        except Exception as msg_error:
                            print(f"⚠️ Error processing message {message_id}: {msg_error}")
                            import traceback
                            traceback.print_exc()
                else:
                    print(f"⏭️ History item {i} has no messagesAdded")
                    print(f"   Available keys: {list(history_item.keys())}")
                            
            print(f"\n📬 SUMMARY: Processed {messages_processed} new messages total")
                        
        except Exception as e:
            print(f"❌ Error in pubsub_listener: {e}")
            import traceback
            traceback.print_exc()

    def get_last_history_id(self) -> Optional[str]:
        """Get the last processed history ID from storage"""
        try:
            # For now, return None to always check recent messages
            # You could store this in Supabase if needed
            return None
        except:
            return None
    
    def save_last_history_id(self, history_id: str) -> None:
        """Save the last processed history ID"""
        try:
            # For now, just print it
            # You could store this in Supabase if needed
            print(f"💾 Would save history ID: {history_id}")
        except:
            pass

    def process_incoming_message(self, user_id: str, message: dict) -> None:
        """Matches incoming message by threadId against Supabase workflows"""
        
        try:
            thread_id = message['threadId']
            message_id = message['id']
            
            print(f"\n🔍 PROCESSING INCOMING MESSAGE:")
            print(f"   Thread ID: {thread_id}")
            print(f"   Message ID: {message_id}")
            
            # Check if we've already processed this message
            if message_id in self.processed_messages:
                print(f"⏭️ ALREADY PROCESSED: Message {message_id} already handled")
                return
            
            # Extract message headers
            headers = message['payload'].get('headers', [])
            print(f"   Headers count: {len(headers)}")
            
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            subject_header = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            to_header = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
            
            print(f"📨 MESSAGE DETAILS:")
            print(f"   From: {from_header}")
            print(f"   To: {to_header}")
            print(f"   Subject: {subject_header}")
            print(f"   Thread ID: {thread_id}")
            print(f"   Message ID: {message_id}")
            
            # Get your Gmail address for filtering
            my_email = os.getenv("GMAIL_ADDRESS", "").lower()
            if not my_email:
                print("⚠️ GMAIL_ADDRESS not set in environment variables")
                # Try to get it from the service
                try:
                    profile = self.service.users().getProfile(userId='me').execute()
                    my_email = profile.get('emailAddress', '').lower()
                    print(f"📧 Detected your email: {my_email}")
                except Exception as e:
                    print(f"❌ Could not detect your email address: {e}")
                    return
            
            print(f"🆔 EMAIL FILTERING:")
            print(f"   My email: {my_email}")
            print(f"   From header: {from_header}")
            print(f"   Is from me? {my_email in from_header.lower() if my_email else 'Unknown'}")
            
            # Skip if this message is FROM us (outgoing message)
            if my_email and my_email in from_header.lower():
                print(f"⏭️ SKIPPING: Outgoing message from self: {from_header}")
                # Still mark as processed to avoid re-checking
                self.processed_messages.add(message_id)
                return
                
            # Skip noreply addresses
            if 'noreply' in from_header.lower() or 'no-reply' in from_header.lower():
                print(f"⏭️ SKIPPING: Noreply message: {from_header}")
                self.processed_messages.add(message_id)
                return
            
            # Skip if this message is TO someone else (not to us)
            if my_email and my_email not in to_header.lower():
                print(f"⏭️ SKIPPING: Message not addressed to us: {to_header}")
                self.processed_messages.add(message_id)
                return
            
            print(f"✅ MESSAGE PASSED ALL FILTERS - Looking up workflow...")
            
            # Load workflow state
            workflow_state = self.load_workflow_state(thread_id)
            
            print(f"💾 WORKFLOW LOOKUP:")
            print(f"   Thread ID: {thread_id}")
            print(f"   Workflow found: {workflow_state is not None}")
            
            if not workflow_state:
                print(f"❓ NO WORKFLOW FOUND for thread: {thread_id}")
                # Mark as processed even if no workflow found
                self.processed_messages.add(message_id)
                return
                
            current_step = workflow_state['step']
            status = workflow_state['status']
            
            print(f"📋 WORKFLOW STATE:")
            print(f"   Thread: {thread_id}")
            print(f"   Current Step: {current_step}")
            print(f"   Status: {status}")
            print(f"   Full workflow: {workflow_state}")
            
            # Skip if workflow is already completed
            if current_step >= 4 or status == 'completed':
                print(f"✅ WORKFLOW ALREADY COMPLETED for thread: {thread_id}")
                self.processed_messages.add(message_id)
                return
            
            # Check if we've already processed a message for this workflow step
            # This prevents processing the same reply multiple times
            last_processed_step_key = f"{thread_id}_step_{current_step}"
            if last_processed_step_key in self.processed_messages:
                print(f"⏭️ STEP ALREADY PROCESSED: Step {current_step} for thread {thread_id} already handled")
                return
            
            print(f"🎯 CALLING WORKFLOW MANAGER:")
            print(f"   Thread: {thread_id}")
            print(f"   Current Step: {current_step}")
            print(f"   This appears to be a genuine incoming reply - processing workflow...")
            
            # Mark this message as processed BEFORE calling workflow manager
            self.processed_messages.add(message_id)
            self.processed_messages.add(last_processed_step_key)
            
            # Pass to workflow manager
            self.workflow_manager(thread_id, current_step, message)
            
        except Exception as e:
            print(f"❌ Error processing incoming message: {e}")
            import traceback
            traceback.print_exc()

    def load_workflow_state(self, thread_id: str) -> Optional[Dict]:
        """Fetches workflow state by threadId from Supabase"""
        
        try:
            print(f"🔍 LOADING WORKFLOW STATE for thread: {thread_id}")
            
            result = self.client.table('workflows').select('*').eq('thread_id', thread_id).execute()
            
            print(f"💾 DATABASE QUERY RESULT:")
            print(f"   Query: SELECT * FROM workflows WHERE thread_id = '{thread_id}'")
            print(f"   Results count: {len(result.data) if result.data else 0}")
            print(f"   Results: {result.data}")
            
            if result.data:
                workflow = result.data[0]
                print(f"✅ WORKFLOW FOUND: {workflow}")
                return workflow
            else:
                print(f"❌ NO WORKFLOW FOUND for thread: {thread_id}")
                return None
                
        except Exception as e:
            print(f"❌ Error loading workflow state: {e}")
            import traceback
            traceback.print_exc()
            return None

    def workflow_manager(self, thread_id: str, step: int, incoming_message: dict) -> None:
        """Handles the 3-step workflow logic"""
        
        try:
            print(f"\n⚙️ WORKFLOW MANAGER CALLED:")
            print(f"   Thread ID: {thread_id}")
            print(f"   Current Step: {step}")
            print(f"   Message ID: {incoming_message.get('id', 'NO_ID')}")
            
            # Double-check workflow state to ensure we're still at the expected step
            current_workflow = self.load_workflow_state(thread_id)
            if not current_workflow:
                print(f"❌ WORKFLOW DISAPPEARED: No workflow found for {thread_id}")
                return
                
            if current_workflow['step'] != step:
                print(f"⚠️ STEP MISMATCH: Expected step {step}, but workflow is at step {current_workflow['step']}")
                print(f"   This likely means another process already handled this reply")
                return
            
            # Workflow logic based on current step
            if step == 0:
                # First reply received, send follow-up #1
                print(f"🎯 EXECUTING STEP 0 → 1: Sending first follow-up")
                self.send_reply_email('me', thread_id, "Testing testing - Follow-up #1")
                self.save_workflow_state(thread_id, step=1, status='sent_followup_1')
                print(f"✅ STEP 0 → 1 COMPLETED")
                
            elif step == 1:
                # Second reply received, send follow-up #2
                print(f"🎯 EXECUTING STEP 1 → 2: Sending second follow-up")
                self.send_reply_email('me', thread_id, "Testing testing - Follow-up #2")
                self.save_workflow_state(thread_id, step=2, status='sent_followup_2')
                print(f"✅ STEP 1 → 2 COMPLETED")
                
            elif step == 2:
                # Third reply received, send final follow-up #3
                print(f"🎯 EXECUTING STEP 2 → 3: Sending final follow-up")
                self.send_reply_email('me', thread_id, "Testing testing - Follow-up #3")
                self.save_workflow_state(thread_id, step=3, status='sent_followup_3')
                print(f"✅ STEP 2 → 3 COMPLETED")
                
            elif step == 3:
                # Final reply received, complete workflow
                print(f"🏁 EXECUTING STEP 3 → Complete: Workflow finished!")
                self.save_workflow_state(thread_id, step=4, status='completed')
                print(f"✅ WORKFLOW COMPLETED")
                
            else:
                print(f"⚠️ UNEXPECTED STEP: {step} for thread {thread_id}")
                
        except Exception as e:
            print(f"❌ Error in workflow_manager: {e}")
            import traceback
            traceback.print_exc()

    def send_reply_email(self, user_id: str, thread_id: str, body: str) -> None:
        """Sends reply email in the same thread via Gmail API"""
        
        try:
            print(f"📤 Sending reply in thread {thread_id}")
            
            # Get the original thread to extract recipient info
            thread = self.service.users().threads().get(
                userId=user_id,
                id=thread_id
            ).execute()
            
            # Get the most recent message from someone else (not from us)
            my_email = os.getenv("GMAIL_ADDRESS", "").lower()
            if not my_email:
                profile = self.service.users().getProfile(userId='me').execute()
                my_email = profile.get('emailAddress', '').lower()
            
            latest_external_message = None
            for message in reversed(thread['messages']):  # Start from most recent
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                
                # Find the most recent message NOT from us
                if my_email not in from_header.lower():
                    latest_external_message = message
                    break
            
            if not latest_external_message:
                print("❌ Could not find external message to reply to")
                return
                
            headers = latest_external_message['payload'].get('headers', [])
            
            # Extract sender info (now our reply recipient)
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            subject_header = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            message_id_header = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')
            
            print(f"📋 REPLY DETAILS:")
            print(f"   Replying to: {from_header}")
            print(f"   Original subject: {subject_header}")
            print(f"   Original message ID: {message_id_header}")
            
            # Add "Re:" if not already present
            if not subject_header.startswith('Re:'):
                reply_subject = f"Re: {subject_header}"
            else:
                reply_subject = subject_header
            
            # Create properly formatted reply message
            reply_message = {
                'raw': base64.urlsafe_b64encode(
                    f"To: {from_header}\r\n"
                    f"Subject: {reply_subject}\r\n"
                    f"In-Reply-To: {message_id_header}\r\n"
                    f"References: {message_id_header}\r\n"
                    f"Content-Type: text/plain; charset=utf-8\r\n"
                    f"\r\n{body}".encode('utf-8')
                ).decode(),
                'threadId': thread_id
            }
            
            # Send reply
            sent_message = self.service.users().messages().send(
                userId=user_id, body=reply_message
            ).execute()
            
            print(f"✅ Reply sent successfully!")
            print(f"   Thread ID: {thread_id}")
            print(f"   Message ID: {sent_message['id']}")
            print(f"   To: {from_header}")
            
        except Exception as e:
            print(f"❌ Error sending reply: {e}")
            import traceback
            traceback.print_exc()
            raise

    def save_workflow_state(self, thread_id: str, step: int, status: str) -> None:
        """Writes workflow state to Supabase"""
        
        try:
            workflow_data = {
                'thread_id': thread_id,
                'step': step,
                'status': status,
                'updated_at': datetime.now().isoformat()
            }
            
            # Upsert workflow state using thread_id as primary key
            result = self.client.table('workflows').upsert(
                workflow_data,
                on_conflict='thread_id'
            ).execute()
            
            print(f"💾 Saved workflow state: {thread_id} → step {step} ({status})")
            
        except Exception as e:
            print(f"❌ Error saving workflow state: {e}")
            raise

    def load_workflow_state(self, thread_id: str) -> Optional[Dict]:
        """Fetches workflow state by threadId from Supabase"""
        
        try:
            print(f"🔍 LOADING WORKFLOW STATE for thread: {thread_id}")
            
            result = self.client.table('workflows').select('*').eq('thread_id', thread_id).execute()
            
            print(f"💾 DATABASE QUERY RESULT:")
            print(f"   Query: SELECT * FROM workflows WHERE thread_id = '{thread_id}'")
            print(f"   Results count: {len(result.data) if result.data else 0}")
            print(f"   Results: {result.data}")
            
            if result.data:
                workflow = result.data[0]
                print(f"✅ WORKFLOW FOUND: {workflow}")
                return workflow
            else:
                print(f"❌ NO WORKFLOW FOUND for thread: {thread_id}")
                return None
                
        except Exception as e:
            print(f"❌ Error loading workflow state: {e}")
            import traceback
            traceback.print_exc()
            return None

    def start_listening(self):
        """Start the Pub/Sub listener in a separate thread"""
        
        def callback(message):
            try:
                print(f"\n🔔 Received Pub/Sub notification")
                print(f"   Data: {message.data.decode('utf-8')}")
                
                # Process the message through our workflow
                self.pubsub_listener(message.data)
                
                # Acknowledge the message
                message.ack()
                print(f"✅ Message acknowledged\n")
                
            except Exception as e:
                print(f"❌ Error processing Pub/Sub message: {e}")
                message.nack()
        
        print(f"👂 Starting Pub/Sub listener...")
        print(f"   Subscription: {self.subscription_path}")
        
        # Configure flow control
        flow_control = pubsub_v1.types.FlowControl(max_messages=10)
        
        # Start listening
        self.streaming_pull_future = self.subscriber.subscribe(
            self.subscription_path, 
            callback=callback,
            flow_control=flow_control
        )
        
        print(f"✅ Pub/Sub listener started successfully!")
        return self.streaming_pull_future

    def stop_listening(self):
        """Stop the Pub/Sub listener"""
        if self.streaming_pull_future:
            self.streaming_pull_future.cancel()
            print("🛑 Pub/Sub listener stopped")

    def start_workflow_example(self, recipient: str, subject: str = "", body: str = ""):
        """Start a new email workflow"""
        
        if not subject:
            subject = "Test Workflow Email"
        if not body:
            body = "This is the initial email in our workflow. Please reply to continue the conversation!"
        
        print(f"\n🚀 Starting new workflow...")
        print(f"   To: {recipient}")
        print(f"   Subject: {subject}")
        
        thread_id = self.send_initial_email(
            user_id='me',
            recipient=recipient,
            subject=subject,
            body=body
        )
        
        print(f"✅ Workflow started successfully!")
        print(f"   Thread ID: {thread_id}")
        print(f"   Status: Waiting for reply...")
        
        return thread_id


def main():
    """Main execution function"""
    
    print("🔧 Initializing Gmail Workflow System...")
    
    # Initialize the workflow system
    workflow_system = GmailWorkflowSystem()
    
    # Start the Pub/Sub listener
    listener_future = workflow_system.start_listening()
    
    # Example: Start a workflow
    recipient_email = input("\n📧 Enter recipient email to start workflow (or press Enter to skip): ").strip()
    
    if recipient_email:
        workflow_system.start_workflow_example(recipient_email)
    else:
        print("⏭️ Skipping workflow start. System is ready to process incoming messages.")
    
    print("\n" + "="*60)
    print("🎉 Gmail Workflow System is now running!")
    print("📬 Send emails and replies will be processed automatically")
    print("🛑 Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Gmail Workflow System...")
        workflow_system.stop_listening()
        print("✅ Shutdown complete")


if __name__ == "__main__":
    main()


# Database Schema for Supabase
"""
-- Create the workflows table
CREATE TABLE IF NOT EXISTS workflows (
    id BIGSERIAL PRIMARY KEY,
    thread_id VARCHAR(255) UNIQUE NOT NULL,
    step INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_workflows_thread_id ON workflows(thread_id);
CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
CREATE INDEX IF NOT EXISTS idx_workflows_step ON workflows(step);

-- Create a function to automatically update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for auto-updating updated_at
CREATE TRIGGER update_workflows_updated_at 
    BEFORE UPDATE ON workflows 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
"""


# Required Environment Variables (.env file)
"""
DATABASE_URL=your-supabase-database-url
DATABASE_API_KEY=your-supabase-anon-key
GMAIL_ADDRESS=your-gmail-address@gmail.com
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/service-account-key.json
"""