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

#Initialise Gmail API
service = authenticate_gmail() 


def read_files_content():
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
    

async def main(): 
    """
    Main function that orchestrates the entire workflow:
    1. Reads reference files and sets up the AI chat application
    2. #TODO Use gmail API send and receive emails
    3. #TODO Return JSON of the conversation
    4. Uses sample responses to extract key member information
    5. Stores data in Supabase database
    """
    
    # Step 1: Read reference files to enhance the AI's context
    context = read_files_content()
    
    # NOTE: ENABLE THIS WHEN READING FROM REFERENCE FILES
    enhanced_system_message = f"{system_message}\n\nBelow is the context from our reference files. Please use this information to inform your responses:{context}"

    chat_app = ChatApplication(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=os.getenv("OPENAI_MODEL", ""),
        endpoint=os.getenv("OPENAI_ENDPOINT", ""),
        system_message=system_message
    )

    user_emails = ['rasheedmohammed2006@gmail.com']


    # Sample response generation
    response: str = chat_app.process_user_input(f"please generate the sample response which could happen to user {user_emails[0]}") or ""
    print(f"Response: {response}")
    
    # TODO: Use gmail API to send custom email and receive custom email responses via pub/sub
    workflow = GmailWorkflow()
    listener_future = workflow.start_listening()
    
    
    workflow.send_initial_email(
            recipient=user_emails[0],
            subject="Welcome to RAID! 👋", 
            body=response
        )
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        workflow.stop_listening(listener_future)
        print("Workflow stopped")
    # TODO: Handle incoming email responses            
        
    
    # # Step 3 & 4: Extract key member information and store in Supabase
    supabase: Client = create_client(os.getenv("DATABASE_URL", ""), os.getenv("DATABASE_API_KEY", ""))

    try:
        supabase.table("club_applications").upsert(extract_member_info_llm(User_1,chat_app )).execute()
        supabase.table("club_applications").upsert(extract_member_info_llm(User_2,chat_app)).execute()
        
    except Exception as e:
        print(f"Error inserting data: {e}")



if __name__ == "__main__":
    asyncio.run(main())








