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
    
    
    # Sample response generation
    response = chat_app.process_user_input("please generate the sample response which could happen to user Rasheedmohammed2006@gmail.com")
    print(f"Response: {response}")
    
    # Step 2: Use gmail API to send and receive emails 
    # Send Email
    email_id = send_email(service, 'me', 'rasheedmohammed2006@gmail.com', 'Test Email', response)
    print(f"Email ID: {email_id}")
    
    # Await user response
    print("Awaiting for user response...")
    user_response = await wait_for_user_response(service, email_id, 'me', 300, 10)

    if user_response['success']: 
        response_email = read_email(service, 'me', user_response['message_id'])
        print(f"Response Email: {response_email}")
        
        # Step 3: Append conversation to JSON 
        try: 
            # Load existing data or create new structure
            try:
                with open('src/actual_response.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except:
                # Create initial structure if file doesn't exist
                data = {
                    "email": "rasheedmohammed2006@gmail.com",
                    "name": "Rasheed M",
                    "conversation": []
                }
                
            # Create new conversation entry
            new_conversation_entry = {
                "agent": response,  # The agent's message we sent
                "user": response_email,  # Use the already-read email content
                "timestamp": user_response['received_at']
            }
                
            # Append to conversation array
            data['conversation'].append(new_conversation_entry)
            
            # Save updated data back to file
            with open('src/actual_response.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                print("Successfully appended conversation to actual_response.json")
                
        except Exception as e:
            print(f"Error updating actual_response.json: {e}")
    else:
        print(f"No user response received: {user_response.get('error', 'Unknown error')}")
            
            
    
    # # Step 3 & 4: Extract key member information and store in Supabase
    # supabase: Client = create_client(os.getenv("DATABASE_URL"), os.getenv("DATABASE_API_KEY"))
    
    # try:
    #     supabase.table("club_applications").upsert(extract_member_info_llm(User_1,chat_app )).execute()
    #     supabase.table("club_applications").upsert(extract_member_info_llm(User_2,chat_app)).execute()
        
    # except Exception as e:
    #     print(f"Error inserting data: {e}")



if __name__ == "__main__":
    asyncio.run(main())