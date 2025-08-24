import os
import dotenv
import openai
import requests
from supabase import create_client, Client


dotenv.load_dotenv()

# Configure the client for OpenRouter API (which provides access to DeepSeek models)
client = openai.OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),  # Use your OpenRouter API key
    base_url="https://openrouter.ai/api/v1"  # OpenRouter's API endpoint
)

# Create a chat completion
response = client.chat.completions.create(
    model="deepseek/deepseek-chat-v3.1",
    messages=[
        {"role": "system", "content": "You are Rafael, RAID's latest agent for the University of Melbourne's RAID (Responsive AI Development) club. Your task is to manage email correspondence with new members to build rapport and provide personalized event invitations.\n\nPersona & Style: Write in a friendly, smart-casual, and conversational tone. Keep emails easy to read and designed for back-and-forth exchange.\n\nStrategy:\n1. Initial Email: Welcome new members warmly, introduce yourself as RAID's agent, and ask about their interests and major. Focus on building conversation, not providing event details yet.\n\n2. Follow-up: Once you understand their interests and major, provide personalized event information that feels tailored and highly relevant to them.\n\nConstraints: Keep responses under 250 words. Don't ask for unnecessary information beyond interests and major. Focus on building genuine rapport before moving to event invitations."},
        {"role": "user", "content": "please generate the sample response which could happen"}
    ],
    temperature=0.7,
    max_tokens=250
)

supabase: Client = create_client(os.getenv("DATABASE_URL"), os.getenv("DATABASE_API_KEY"))

# Example JSON returned from LLM
llm_output = {
    "name": "Alice Smith",
    "email": "alice@example.com",
    "motivation": "I want to contribute to community projects."
}



def main():
    print("Hello from gmail-agent!")
    
    # Print the response
    print("Response content:")
    print(response.choices[0].message.content)
    
    supabase.table("club_applications").insert(llm_output).execute()


if __name__ == "__main__":
    main()
