# gmail_utils.py
from email.mime.text import MIMEText
import base64
from email import message_from_bytes
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os.path
import pickle
import asyncio
from datetime import datetime, timezone
import time

# Gmail API setup
SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']

def authenticate_gmail():
    """
    Authenticate and return Gmail service using OAuth2 credentials.
    
    This function handles the OAuth2 authentication flow for Gmail API access.
    It first checks for existing credentials in 'token.pickle', refreshes them if expired,
    or initiates a new authentication flow if no valid credentials exist.
    
    Returns:
        googleapiclient.discovery.Resource: Authenticated Gmail service object
        
    Note:
        Requires 'credentials.json' file for initial authentication setup.
        Creates/updates 'token.pickle' file to store authentication tokens.
    """
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    return build('gmail', 'v1', credentials=creds)

def send_email(service, user_id, to_email, subject, body):
    """
    Send a simple email using the Gmail API.
    
    Args:
        service: Authenticated Gmail API service object
        user_id: Gmail user ID (usually 'me' for the authenticated user)
        to_email: Recipient email address
        subject: Email subject line
        body: Email body content (plain text)
    
    Returns:
        str: Message ID of the sent email on success, or error message on failure
        
    Note:
        The email is sent as plain text. For HTML emails, modify the MIMEText type.
    """
    message = MIMEText(body)
    message['to'] = to_email
    message['subject'] = subject
    
    encoded_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
    
    try:
        sent_message = service.users().messages().send(userId=user_id, body=encoded_message).execute()
        # return f"Message sent successfully! Message Id: {sent_message['id']}"
        return sent_message['id']
    except HttpError as error:
        return f"An error occurred: {error}"
    
    
def list_emails(service, user_id, max_results=10):
    """
    List recent emails from the user's Gmail inbox.
    
    Args:
        service: Authenticated Gmail API service object
        user_id: Gmail user ID (usually 'me' for the authenticated user)
        max_results: Maximum number of emails to retrieve (default: 10)
    
    Returns:
        str: Formatted string containing email information (sender, subject, ID),
             or error message if an error occurs
        
    Note:
        Returns emails in reverse chronological order (most recent first).
        Each email shows: From, Subject, and Message ID.
    """
    try:
        results = service.users().messages().list(userId=user_id, maxResults=max_results).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return "No messages found."
        
        email_list = []
        for message in messages:
            msg = service.users().messages().get(userId=user_id, id=message['id']).execute()
            headers = msg['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            email_list.append(f"From: {sender} | Subject: {subject} | ID: {message['id']}")
        
        return "\n".join(email_list)
    except HttpError as error:
        return f"An error occurred: {error}"
    
def read_email(service, user_id, email_id):
    """
    Read a specific email by its ID and return its content.
    
    Args:
        service: Authenticated Gmail API service object
        user_id: Gmail user ID (usually 'me' for the authenticated user)
        email_id: Unique identifier of the email to read
    
    Returns:
        str: Formatted string containing email details (sender, subject, body),
             or error message if an error occurs
        
    Note:
        Uses 'raw' format to get the complete email content.
        Extracts sender and subject from email headers.
        Body content is retrieved from the message snippet.
    """
    try:
        message = service.users().messages().get(userId=user_id, id=email_id, format='raw').execute()
        msg_bytes = base64.urlsafe_b64decode(message['raw'])
        msg = message_from_bytes(msg_bytes)
        
        # Get subject and sender directly from the decoded message
        subject = msg['subject'] if msg['subject'] else 'No Subject'
        sender = msg['from'] if msg['from'] else 'Unknown Sender'
        
        # Get email body from snippet
        body = message.get('snippet', 'No content available')
        
        return f"From: {sender}\nSubject: {subject}\n\n{body}"
    except Exception as e:
        return f"Error reading email: {e}"
    
    
async def wait_for_user_response(service, email_id, user_id='me', timeout=300, check_interval=10):
    """
    Async function that waits for a user response email and reads it when it arrives.
    
    Args:
        service: Gmail API service object
        email_id: ID of the original email to match responses to
        user_id: Gmail user ID (default: 'me')
        timeout: Maximum time to wait in seconds (default: 5 minutes)
        check_interval: How often to check for new emails in seconds (default: 10s)
    
    Returns:
        dict: Contains email content or timeout/error information
    """
    
    try:
        # Get the thread ID of the original email
        original_msg = service.users().messages().get(userId=user_id, id=email_id).execute()
        original_thread_id = original_msg.get('threadId', '')
        if not original_thread_id:
            return {
                'success': False,
                'error': 'Could not get thread ID from original email'
            }
        
        # Get initial message list to establish baseline
        initial_results = service.users().messages().list(userId=user_id, maxResults=1).execute()
        initial_messages = initial_results.get('messages', [])
        last_message_id = initial_messages[0]['id'] if initial_messages else None
        
        print(f"Monitoring for responses to email ID: {email_id} (timeout: {timeout}s)")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            await asyncio.sleep(check_interval)
            
            # Check for new messages
            try:
                current_results = service.users().messages().list(userId=user_id, maxResults=5).execute()
                current_messages = current_results.get('messages', [])
                
                if current_messages:
                    # Check if there's a new message (different from last known message)
                    latest_message_id = current_messages[0]['id']
                    
                    if latest_message_id != last_message_id:
                        # We have a new message, let's check if it's in the same thread
                        for message in current_messages:
                            if message['id'] == last_message_id:
                                break  # Stop checking once we reach the last known message
                            
                            # Skip the original email itself
                            if message['id'] == email_id:
                                continue
                            
                            # Get message details
                            msg_details = service.users().messages().get(
                                userId=user_id, 
                                id=message['id']
                            ).execute()
                            
                            thread_id = msg_details.get('threadId', '')
                            
                            # Check if this message is in the same thread as the original email
                            if thread_id == original_thread_id:
                                headers = msg_details['payload']['headers']
                                sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
                                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
                                
                                print(f"Response found from: {sender}")
                                
                                # Read the full email content
                                email_content = read_email(service, user_id, message['id'])
                                
                                return {
                                    'success': True,
                                    'message_id': message['id'],
                                    'thread_id': thread_id,
                                    'original_email_id': email_id,
                                    'sender': sender,
                                    'subject': subject,
                                    'content': email_content,
                                    'received_at': datetime.now(timezone.utc).isoformat()
                                }
                        
                        # Update the last known message ID
                        last_message_id = latest_message_id
            
            except HttpError as error:
                print(f"Error checking for messages: {error}")
                await asyncio.sleep(check_interval)
                continue
        
        # Timeout reached
        return {
            'success': False,
            'error': 'Timeout reached - no matching response received',
            'timeout': timeout
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f"Error in wait_for_user_response: {str(e)}"
        }