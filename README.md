# Gmail Agent

An intelligent email assistant that automatically summarizes your unread Gmail emails using Google's Gemini AI and forwards concise summaries to your inbox.

## Features

- 🤖 **AI-Powered Summarization**: Uses Gemini 2.0 Flash to create concise email summaries
- 🎯 **Action Detection**: Automatically identifies emails requiring your attention
- 🧵 **Thread Continuity**: Summaries appear in the original email thread
- 🔍 **Smart Filtering**:
  - Skips self-sent emails
  - Filters out purchase/transactional emails (Amazon, PayPal, etc.)
  - Prevents duplicate summaries
- ☁️ **Cloud Deployment**: Runs on Google Cloud Run (Free Tier eligible)
- ⏰ **Scheduled Execution**: Automatically processes emails daily at 2:00 AM

## Prerequisites

- Python 3.11+
- Google Cloud account (for deployment)
- Gmail account
- Google Cloud Project with billing enabled

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/henryhyunwookim/gmail-agent.git
cd gmail-agent
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download `credentials.json` and place it in the project root

### 4. Set Up Gemini API

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create an API key
3. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

4. Edit `.env` and add your API key and GCP configuration:

```env
GEMINI_API_KEY=your_actual_api_key

# GCP Configuration (needed for cloud deployment)
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
SERVICE_NAME=gmail-agent
JOB_NAME=gmail-agent-daily-trigger
SCHEDULE=0 2 * * *
TIMEZONE=Asia/Seoul
```

### 5. Authenticate Gmail

Run the agent locally once to authenticate:

```bash
python src/main.py
```

This will open a browser window for Gmail authentication and create `token.json`.

## Local Usage

Run the agent manually:

```bash
python src/main.py
```

This will:
- Check for unread emails
- Summarize them using Gemini AI
- Forward summaries to your email
- Display statistics

## Cloud Deployment (Google Cloud Run)

### Prerequisites

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed
- Google Cloud Project with billing enabled

### Deploy

1. Ensure your `.env` file has the correct `GCP_PROJECT_ID` set

2. Run the deployment script:

```powershell
.\deploy_cloud.ps1
```

The script will:
- Build and deploy the container to Cloud Run
- Create a Cloud Scheduler job to run daily at 2:00 AM
- Set up all necessary permissions

### Verify Deployment

Check the logs:

```powershell
gcloud run services logs read gmail-agent --region=us-central1 --limit=50
```

Or manually trigger:

```powershell
gcloud scheduler jobs run gmail-agent-daily-trigger --location=us-central1
```

## Configuration

### Email Processing Limit

Edit `src/main.py`:

```python
messages = client.list_unread_messages(max_results=50)  # Change this number
```

### Schedule

Edit `deploy_cloud.ps1`:

```powershell
$SCHEDULE = "0 2 * * *"  # Cron format: daily at 2:00 AM
$TIMEZONE = "Asia/Seoul"  # Your timezone
```

### Purchase Keywords

Edit `src/summarizer.py` to customize purchase detection:

```python
purchase_keywords = [
    'order', 'purchase', 'receipt', 'invoice', 'payment',
    # Add more keywords
]
```

## Project Structure

```
gmail-agent/
├── src/
│   ├── app.py              # Flask web server for Cloud Run
│   ├── main.py             # Main application logic
│   ├── auth.py             # Gmail authentication
│   ├── gmail_client.py     # Gmail API client
│   └── summarizer.py       # AI summarization logic
├── Dockerfile              # Container configuration
├── deploy_cloud.ps1        # Cloud deployment script
├── requirements.txt        # Python dependencies
├── credentials.json        # Gmail OAuth credentials (not in repo)
├── token.json             # Gmail auth token (not in repo)
└── .env                   # Environment variables (not in repo)
```

## Cost Estimate

Running once per day on Google Cloud Run:

- **Cloud Run**: $0.00/month (within free tier)
- **Cloud Scheduler**: $0.00/month (3 jobs free)
- **Gemini API**: $0.00/month (generous free tier)

**Total**: Free! 🎉

## Security Notes

⚠️ **Never commit these files to Git:**
- `credentials.json`
- `token.json`
- `.env`

These files contain sensitive authentication data.

## Troubleshooting

### "ModuleNotFoundError"
- Ensure `PYTHONPATH=/app` is set in `Dockerfile`
- All imports use absolute paths (`from src.module import ...`)

### "could not locate runnable browser"
- Ensure `token.json` is included in `Dockerfile`
- Run locally first to generate `token.json`

### Billing Error
- Enable billing in Google Cloud Console
- Link billing account to your project

## License

This project is licensed under a Non-Commercial License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Powered by [Google Gemini AI](https://ai.google.dev/)
- Uses [Gmail API](https://developers.google.com/gmail/api)
