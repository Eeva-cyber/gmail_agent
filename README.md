# RAID Club Email Agent

An autonomous AI system that manages email correspondence with new RAID (Responsive AI Development) club members at the University of Melbourne.

## What It Does

- **Initiates conversations** with new members through personalized welcome emails
- **Extracts key information** using LLM analysis of email exchanges
- **Stores structured data** in Postgres/Supabase for member management
- **Processes Gmail events** via Google Pub/Sub push notifications
- **Operates autonomously** without manual intervention

## Key Features

- **Smart Email Generation**: Personalized welcome messages
- **Information Extraction**: Major, motivation, activity preferences
- **Database Integration**: Raw conversations + extracted insights
- **Workflow Tracking**: Conversation thread state and progress

## How It Works

1. **Email Initiation**: AI agent (Rafael) sends personalized welcome emails
2. **Conversation Management**: Handles back-and-forth email threads
3. **Data Extraction**: LLM parses conversations to structured fields
4. **Database Storage**: Application + workflow tracking tables
5. **Event Processing**: Gmail push → Pub/Sub topic → long-running listener

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS club_applications (
  email VARCHAR(255) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  conversation JSONB,
  major VARCHAR(255),
  motivation TEXT,
  desired_activities JSONB
);

CREATE TABLE IF NOT EXISTS workflows (
  id SERIAL PRIMARY KEY,
  thread_id VARCHAR(255) UNIQUE NOT NULL,
  step INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(50) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflows_thread_id ON workflows(thread_id);
```

## Setup

1. Install dependencies: `uv install`

2. Environment variables: copy `.env.example` → `.env`, then `source .env`

3. Google Cloud (Gmail Push + Pub/Sub)

   - Install gcloud SDK: see [Install the Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
   - Authenticate and set project:
     ```bash
     gcloud init
     ```
   - Enable services and set Pub/Sub permissions:

     ```bash
     gcloud services enable gmail.googleapis.com
     gcloud services enable pubsub.googleapis.com

     # Allow Gmail push service account to publish to your topic:
     gcloud pubsub topics add-iam-policy-binding projects/${PROJECT_ID}/topics/${TOPIC_NAME} \
       --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
       --role="roles/pubsub.publisher"
     ```

4. Run
   - Orchestrator: `uv run main.py`
   - Pub/Sub listener (awaits indefinitely): `uv run google-cloud-test.py`

## Files

- `main.py` — Main orchestration
- `google-cloud-test.py` — Pub/Sub listener for Gmail push events
- `chat_manager.py` — LLM chat system
- `LLM_Extraction.py` — Information extraction
- `.env.example` — Environment template

## Current Status

- Generates personalized emails
- Extracts and stores member info
- Handles multiple conversations
- Event-driven via Gmail + Pub/Sub (listener runs indefinitely)
- Response generation, database logging working in `main.py` with infinite event drive architecture on `google-cloud-test.py`
