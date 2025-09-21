from supabase import Client
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

class DatabaseManager:
    def __init__(self, client: Client) -> None:
        self.client = client

    def store_message(self, user_data: Dict[str, Any], message_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Stores a user and their associated message in the database.
        
        Args:
            user_data (dict): A dictionary with 'email' and 'name' keys.
                Example: {"email": "user@example.com", "name": "John Doe"}
            message_data (dict): A dictionary with keys 'thread_id', 'message_id', 
                                'sender', 'body', 'subject', and 'timestamp'.
                Example: {
                    "thread_id": "18a9f84f0c5d7bae",
                    "message_id": "CAHkZjsD0eXAmpf",
                    "sender": "user",  # Changed from 'from' to 'sender'
                    "body": "This is the email text content.",
                    "subject": "Re: Hello",
                    "timestamp": "2024-01-15T10:32:00Z"
                }
        
        Returns:
            tuple: (success: bool, error_message: str | None)
        """
        try:
            # 1. Prepare and upsert the user record
            # We use the current UTC time for the updated_at field
            current_utc_time = datetime.now(timezone.utc).isoformat()
            user_record = {
                "email": user_data["email"],
                "name": user_data["name"],
                "updated_at": current_utc_time
            }
            
            # Upsert the user. on_conflict='email' tells Supabase what the unique key is.
            user_response = self.client.table("users") \
                .upsert(user_record, on_conflict="email") \
                .execute()

            
            # Check for errors in the user upsert operation
            error = getattr(user_response, 'error', None)
            if error:
                return False, f"Error upserting user: {getattr(error, 'message', 'Unknown error')}"
            
            # print(f"✓ User upserted successfully: {user_data['email']}")

            # 2. Insert the message record
            # The 'user_email' field in the message table is populated from the user_data
            message_record = {
                "thread_id": message_data["thread_id"],
                "message_id": message_data["message_id"],
                "user_email": user_data["email"], # This links the message to the user
                "sender": message_data["sender"], # Changed from 'from' to 'sender'
                "body": message_data["body"],
                "subject": message_data["subject"],
                "timestamp": message_data["timestamp"]
            }

            message_response = self.client.table("messages") \
                .upsert(message_record, on_conflict="thread_id,message_id") \
                .execute()
                
            # Check for errors in the message insert operation
            error = getattr(message_response, 'error', None)
            if error:
                return False, f"Error inserting message: {getattr(error, 'message', 'Unknown error')}"
            
             # print(f"✓ Message inserted successfully into thread '{message_data['thread_id']}'")

            return True, None

        except KeyError as e:
            # This catches missing keys in the input dictionaries
            error_msg = f"Missing required data field: {e}"
            print(error_msg)
            return False, error_msg
        except Exception as e:
            # This catches any other unexpected errors
            error_msg = f"An unexpected error occurred: {e}"
            print(error_msg)
            return False, error_msg

    
        
