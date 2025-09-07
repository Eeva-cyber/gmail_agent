from gmail_utils import authenticate_gmail, setup_gmail_push_notifications
from google.cloud import pubsub_v1

service = authenticate_gmail()
setup_gmail_push_notifications(service, "gmail-agent-470407", "gmail-events")


# Listen for messages on your Pub/Sub subscription
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path("gmail-agent-470407", 'gmail-events-sub')

# Event handler when new gmail sends a notification
def callback(message):
    print(f"Received message: {message.data}")
    message.ack()

# Callback function whenever a new message is received
streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
streaming_pull_future.result()