# RAID Club Email Agent

An autonomous AI system that manages email correspondence with new RAID (Responsive AI Development) club members at the University of Melbourne.

## What It Does

- **Initiates conversations** with new members through personalized welcome emails
- **Extracts key information** using LLM analysis of email exchanges
- **Stores structured data** in Supabase database for member management
- **Operates autonomously** without manual intervention

## Key Features

- **Smart Email Generation**: Creates personalized welcome messages based on member profiles
- **Information Extraction**: Uses AI to identify member's major, motivation, and activity preferences
- **Database Integration**: Automatically stores both raw conversations and extracted insights
- **Context-Aware**: Leverages reference files for consistent club messaging

## How It Works

1. **Email Initiation**: AI agent (Rafael) sends personalized welcome emails to new members
2. **Conversation Management**: Maintains back-and-forth email exchanges to build rapport
3. **Data Extraction**: LLM analyzes conversations to extract structured member information
4. **Database Storage**: Stores data in `club_applications` table with fields for major, motivation, and activities

## Database Schema

```sql
CREATE TABLE club_applications (
  email VARCHAR(255) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  conversation JSONB,
  major VARCHAR(255),
  motivation TEXT,
  desired_activities JSONB
);
```

## Setup

1. Install dependencies: `uv install`
2. Copy `.env.example` to `.env` and configure your environment variables:
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL`
   - `OPENAI_ENDPOINT`
   - `DATABASE_URL`
   - `DATABASE_API_KEY`
3. Run: `uv run main.py`

## Files

- `main.py` - Main orchestration and database operations
- `chat_manager.py` - AI chat system and LLM management
- `LLM_Extraction.py` - Information extraction from conversations
- `sample_response.py` - Sample conversation data for testing
- `.env.example` - Template for environment variable configuration

## Current Status

Fully functional autonomous system that can:

- Generate personalized emails
- Extract member information
- Store data in database
- Handle multiple conversations simultaneously
