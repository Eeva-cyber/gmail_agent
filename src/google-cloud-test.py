from gmail_utils import authenticate_gmail, setup_gmail_push_notifications

service = authenticate_gmail()
setup_gmail_push_notifications(service, "gmail-agent-470407", "gmail-events")