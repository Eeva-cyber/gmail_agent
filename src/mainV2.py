from chat_manager import ChatApplication
import dotenv
import os 
from supabase import create_client, Client
from sample_response import User_1, User_2
from LLM_Extraction import extract_member_info_llm
import pathlib
from gmail_utils import *
import asyncio
import json
import time
from datetime import datetime
from google_cloud import GmailWorkflow


# System message that defines Rafael's persona and behavior as RAID's AI agent
system_message = """
You are Rafael, RAID's latest agent for the University of Melbourne's RAID (Responsive AI Development) club. Your task is to manage the email correspondence with a new member. Your primary goal is to initiate and maintain a conversation to build rapport, leading to a personalized invitation to club events.
Persona & Style: Write in a friendly, smart-casual, and conversational tone, mirroring the style of the "Stella_messages.txt" conversation. The email must be easy to read and designed for a back-and-forth exchange.
Content and Structure:
Initial Email: Draft a welcome email to a new member. Start with a warm greeting, introduce yourself as RAID's latest agent, and ask them about their interests and major. Do not provide any event details in this initial email; the goal is to encourage a reply.
Subsequent Emails: Once a conversation is generated and you have a good understanding of the user's interests, you will then provide information on upcoming events. The invitation to these events must be personalized based on the interests and major you have learned. The aim is to make the invitation feel tailored and highly relevant to the individual member.
Constraints: Do not ask for any more information than what is specified above. The entire response should be under 250 words and ready to be used as a final output.

"""
root_dir = pathlib.Path(__file__).parent.parent
dotenv.load_dotenv(root_dir / ".env")

class IntegratedWorkflow:
    def __init__(self):
        """Initialize the integrated workflow system"""
        self.workflow = GmailWorkflow()
        self.chat_app = None
        self.supabase = create_client(os.getenv("DATABASE_URL", ""), os.getenv("DATABASE_API_KEY", ""))
        self.active_threads = {}  # Track active conversation threads
        
    def setup_chat_application(self):
        """Setup the chat application with enhanced context"""
        context = self.read_files_content()
        enhanced_system_message = f"{system_message}\n\nBelow is the context from our reference files. Please use this information to inform your responses:{context}"
        
        self.chat_app = ChatApplication(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", ""),
            endpoint=os.getenv("OPENAI_ENDPOINT", ""),
            system_message=enhanced_system_message
        )

    def read_files_content(self):
        """Read the content of the text files and return as a string"""
        files_content = ""
        files_to_read = ["Stella_messages.txt", "RAID_info.txt"]
        
        for file_name in files_to_read:
            try:
                file_path = os.path.join("src", file_name)
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as file:
                        files_content += f"\n\n--- Content from {file_name} ---\n{file.read()}"
                else:
                    print(f"Warning: {file_name} not found in src directory")
            except Exception as e:
                print(f"Error reading {file_name}: {e}")
        
        return files_content

    def generate_response(self, user_email: str, step: int, incoming_message: dict = None):
        """Generate appropriate response based on workflow step"""
        if step == 0:
            # Initial welcome email
            prompt = f"Generate the initial welcome email for new member {user_email}"
        elif step == 1:
            # First follow-up
            prompt = f"Generate a follow-up email asking about their background and interests for {user_email}"
        elif step == 2:
            # Second follow-up with more engagement
            prompt = f"Generate a more engaging follow-up email for {user_email}, building on previous conversation"
        else:
            # Final personalized invitation
            prompt = f"Generate a personalized event invitation for {user_email} based on their interests"
        
        response = self.chat_app.process_user_input(prompt) 
        return response or ""

    def enhanced_workflow_manager(self, thread_id: str, step: int, incoming_message: dict = None):
        """Enhanced workflow manager that generates AI responses"""
        try:
            # Get user email from thread
            user_email = self.active_threads.get(thread_id, {}).get('email', '')
            
            if step < 3:  # Steps 0, 1, 2 send AI-generated responses
                ai_response = self.generate_response(user_email, step, incoming_message)
                
                # Use the workflow manager with generated content
                self.workflow.workflow_manager(
                    thread_id=thread_id,
                    step=step,
                    incoming_message=incoming_message or {},
                    message_body=ai_response,
                    message_subject=""  # Let it use default subject handling
                )
                
                print(f"AI response sent for step {step} - Thread: {thread_id}")
                
            else:  # Step 3 - workflow completion
                self.workflow.workflow_manager(thread_id, step, incoming_message or {})
                
        except Exception as e:
            print(f"Error in enhanced_workflow_manager: {e}")

    def start_conversation_flow(self, user_emails: list):
        """Start the conversation flow for multiple users"""
        for email in user_emails:
            try:
                # Generate initial AI response
                initial_response = self.generate_response(email, 0)
                
                # Send initial email
                thread_id = self.workflow.send_initial_email(
                    recipient=email,
                    subject="Welcome to RAID! 👋",
                    body=initial_response
                )
                
                # Track the thread
                self.active_threads[thread_id] = {
                    'email': email,
                    'step': 0,
                    'started_at': datetime.now()
                }
                
                print(f"Started conversation with {email} - Thread: {thread_id}")
                
            except Exception as e:
                print(f"Error starting conversation with {email}: {e}")

    def setup_enhanced_pubsub_listener(self):
        """Setup enhanced Pub/Sub listener that uses AI responses"""
        # Override the workflow's process_incoming_message to use our enhanced manager
        original_process_incoming = self.workflow.process_incoming_message
        
        def enhanced_process_incoming_message(message: dict):
            try:
                thread_id = message['threadId']
                
                # Call original processing logic for filtering and validation
                # But replace the workflow_manager call
                
                # Extract headers for validation (copied from original)
                headers = message['payload'].get('headers', [])
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                to_header = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
                
                my_email = os.getenv("GMAIL_ADDRESS", "")
                if not my_email:
                    profile = self.workflow.service.users().getProfile(userId='me').execute()
                    my_email = profile.get('emailAddress', '')
                
                # Skip validation (same as original)
                if my_email.lower() in from_header.lower():
                    return
                if my_email.lower() not in to_header.lower():
                    return
                if 'noreply' in from_header.lower():
                    return
                
                # Load workflow state
                workflow_state = self.workflow.load_workflow_state(thread_id)
                if not workflow_state:
                    return
                    
                current_step = workflow_state['step']
                if current_step >= 4:
                    return
                
                print(f"Processing reply with AI - Thread: {thread_id}, Step: {current_step}")
                
                # Use our enhanced workflow manager instead
                self.enhanced_workflow_manager(thread_id, current_step, message)
                
            except Exception as e:
                print(f"Error in enhanced message processing: {e}")
        
        # Replace the method
        self.workflow.process_incoming_message = enhanced_process_incoming_message

    async def run_workflow(self):
        """Main workflow execution"""
        try:
            # Setup components
            print("Setting up chat application...")
            self.setup_chat_application()
            
            print("Setting up enhanced Pub/Sub listener...")
            self.setup_enhanced_pubsub_listener()
            
            # Start Gmail listener
            print("Starting Gmail listener...")
            listener_future = self.workflow.start_listening()
            
            # Define target users
            user_emails = ['rasheedmohammed2006@gmail.com']
            
            # Start conversations
            print("Starting conversation flows...")
            self.start_conversation_flow(user_emails)
            
            # Keep the workflow running
            print("Workflow running. Press Ctrl+C to stop.")
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("Stopping workflow...")
                self.workflow.stop_listening(listener_future)
                
            # Process sample data (keep existing functionality)
            print("Processing sample data...")
            try:
                self.supabase.table("club_applications").upsert(extract_member_info_llm(User_1, self.chat_app)).execute()
                self.supabase.table("club_applications").upsert(extract_member_info_llm(User_2, self.chat_app)).execute()
                print("Sample data processed successfully")
            except Exception as e:
                print(f"Error processing sample data: {e}")
                
        except Exception as e:
            print(f"Error in workflow execution: {e}")

async def main():
    """
    Main function that orchestrates the entire integrated workflow:
    1. Sets up AI chat application with context
    2. Initializes Gmail workflow with Pub/Sub listening
    3. Sends AI-generated initial emails
    4. Waits for responses and continues conversation loop (up to 3 exchanges)
    5. Processes sample data for database storage
    """
    
    workflow = IntegratedWorkflow()
    await workflow.run_workflow()

if __name__ == "__main__":
    asyncio.run(main())