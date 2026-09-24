# Gmail Agent

An intelligent email assistant that automatically summarizes your unread Gmail emails using Google's Gemini AI and forwards concise summaries to your inbox.

## Features

- 📰 **Executive-Grade Intelligence Briefings**: Goes beyond superficial one-liners to provide comprehensive context, background significance, and practical takeaways.
- 🌐 **External Content & Media Ingestion**: Automatically detects linked web articles, YouTube videos (extracting audio transcripts), and podcasts, analyzing full source content beyond initial email previews.
- 💡 **Deep-Dive Key Insights**: Breaks down emails and linked sources into rich, analytical thematic sections with specific facts, data points, and strategic implications.
- ⚡ **Actionable Takeaways**: Clearly highlights key next steps, decisions, and recommendations.
- 📚 **FTChinese Deep-Dive & Study Corner**: Comprehensive article briefing coupled with an educational sentence-by-sentence Chinese study section (Original, Pinyin, English, Key Vocabulary).
- 🎯 **Action Detection & Auto-Labeling**: Automatically flags emails requiring action and applies Gmail labels (`ActionRequired` or `ReadLater`).
- 🔗 **Smart Link Architecture**: Preserves hyperlinks and extracts unsubscribe/opt-out links for seamless one-click management.
- ⚙️ **Configurable Limits & Schedule**: Easily adjust batch limits (`MAX_EMAILS`), external link ingestion (`ENABLE_EXTERNAL_FETCH`), body character limits (`MAX_BODY_CHARS`), and cron schedules.
- ☁️ **Cloud Native & Multi-PC Portable**: Runs seamlessly on local Windows/macOS/Linux or serverless on Google Cloud Run.


## Architecture

The system is designed as a fully cloud-native, multi-PC portable application running on **Google Cloud Platform (GCP)**, leveraging **Google Cloud Secret Manager**, **Google Cloud Storage (GCS)**, and **Google Gemini 3.8 Flash** for high-speed, secure, and zero-setup execution across any machine or Cloud Run.

![Gmail Agent Architecture & Workflow Overview](docs/assets/architecture_overview.png)

```mermaid
graph TD
    subgraph Multi-PC Resolution Layer
        GCPAuth[gcloud auth login / ADC] --> SecretMgr[Secret Manager]
        SecretMgr -->|gemini-api-key| Config[src/config.py]
        SecretMgr -->|gmail-agent-token| Auth[src/auth.py]
        SecretMgr -->|gmail-oauth-credentials| Auth
    end

    subgraph Google Cloud Platform
        Scheduler[Cloud Scheduler] -->|Trigger via Configured Cron| CloudRun[Cloud Run Service]
        CloudRun -->|Runs| App[Flask App]
        App -->|Executes| Main[Main Logic]
        Main -->|Operational Logs| GCS[Cloud Storage gs://...-gmail-agent-data]
        Main -->|Structured Logs| CloudLogging[GCP Cloud Logging]
    end

    subgraph Application Logic
        Main -->|Auth & Fetch| GmailClient[Gmail Client]
        Main -->|Analyze| Summarizer[AI Summarizer]
        Summarizer -.->|Summary & Actions| GmailClient
        GmailClient -.->|Email Content| Summarizer
        Summarizer -->|Generate Content| GeminiAPI[Gemini 3.8 Flash]
        GmailClient -->|Send Summaries| GmailAPI[Gmail API]
        GmailClient -->|Apply Labels| GmailAPI
    end

    GmailAPI -->|Delivers Summary| User((User))
```

### Multi-PC Cloud Architecture Strategy

| Layer | Target Cloud Service | Purpose & Storage Format | Multi-PC Resolution Strategy |
| :--- | :--- | :--- | :--- |
| **API Keys & Secrets** (`GEMINI_API_KEY`) | **Google Cloud Secret Manager** | Secure string (`secrets/gemini-api-key`) | Dual-mode: Python SDK with fallback to authenticated `gcloud secrets versions access` CLI |
| **OAuth Tokens** (`token.json`) | **Google Cloud Secret Manager** | Serialized JSON token (`secrets/gmail-agent-token`) | Auto-resolved when local file is missing; in-memory refresh with OS temp cache fallback |
| **OAuth Client IDs** (`credentials.json`) | **Google Cloud Secret Manager** | Raw client secrets JSON (`secrets/gmail-oauth-credentials`) | Auto-downloaded in-memory on demand if interactive web browser login is triggered |
| **Persistent State** (`state.json`) | **Google Cloud Storage (GCS)** | `gs://<bucket>/gmail-agent/state.json` | Single source of truth; local runs write fallbacks only to OS temp dir (`tempfile.gettempdir()`) |
| **Operational & Audit Logs** (`run_log.json`) | **Google Cloud Storage & Cloud Logging** | `gs://<bucket>/gmail-agent/run_log.json` + `stdout` | Decoupled from state; streamed to Cloud Logging on Cloud Run and GCS |

### System Components

*   **Cloud Secret Manager**: Canonical vault storing `gemini-api-key`, `gmail-agent-token`, and `gmail-oauth-credentials`. Allows zero-setup execution on any computer.
*   **Cloud Storage (GCS)**: Stores decoupled execution logs (`run_log.json`) and agent state without polluting local git workspaces.
*   **Cloud Scheduler**: The configurable "alarm clock" that triggers the system according to your custom cron schedule.
*   **Cloud Run**: The serverless container compute environment hosting the agent container.
*   **Gmail Client**: The internal Python module that handles authentication, fetches unread emails, and constructs forwarded summaries.
*   **AI Summarizer**: The intelligence layer that analyzes emails with Gemini 3.8 Flash.

### Logic Flow

The application follows a linear execution pipeline, optimized for batch processing:

1.  **Trigger & Auth**: The Cloud Scheduler triggers the container (or triggered manually/locally). The app authenticates with Gmail using OAuth 2.0.
2.  **Fetch**: Retrieves unread emails from the inbox according to the configured batch limit (default: 20 emails, customizable via `MAX_EMAILS` or CLI).
3.  **Smart Filtering**:
    *   **Self-Sent**: Ignores emails sent by the user to avoid loops.
    *   **Redundancy Check**: Skips threads that have already been summarized by the agent (checks for "Fwd:" from user).
    *   **Transactional**: Detects and skips purchase receipts, shipping notifications, and invoices (e.g., from Amazon, PayPal) to focus on communication.
4.  **AI Analysis**:
    *   The **EmailSummarizer** sends the email body to **Gemini 3.8 Flash**.
    *   Gemini generates a structured JSON response containing:
        *   Concise summary.
        *   Key insights/facts.
        *   Action required status (True/False) & reason.
5.  **Action & Notification**:
    *   **Forward**: The agent forwards the original email to the user, prepending the AI summary and insights.
    *   **Unsubscribe Link**: If detected, the agent extracts the `unsubscribe`, `opt-out`, or `preferences` link and appends it to the summary for quick management.
    *   **Chinese Study Corner**: If the email is from `newsletter.ftchinese.com`, a special study section is appended with original text, pinyin, English, and vocabulary. The general summary and insights are excluded to save API resources and avoid duplicate content.
    *   **Label**: Applies `ActionRequired` or `ReadLater` labels to the original message for easy sorting.
6.  **Reporting**: A final execution log is sent to the user, detailing processing stats and any errors.

## Example Output

Here's how an incoming email looks when processed by the agent:

**Original Email:**
> **From:** Sarah Jones (via Project Alpha Updates) <<sarah.jones@example.com>><br>
> **Subject:** Project Alpha Update & Q4 Planning<br>
> **Body:** Hi everyone, quick update on Project Alpha. The backend API is finally complete and all tests are passing! However, we're hitting some snags with the frontend integration—specifically around the new auth flow. We likely need another 2 days to iron that out. Also, we really need to lock down the Q4 roadmap. Can we meet next Tuesday at 2 PM to go over the proposed features? Let me know if that works.<br>
>
> [You are receiving this because you are subscribed to Project Alpha Updates. Unsubscribe]

**Agent's Executive Intelligence Briefing:**
> ================================================================================<br>
> 📰 **EXECUTIVE INTELLIGENCE BRIEFING**<br>
> ================================================================================<br>
> 📌 **Subject:** Project Alpha Update & Q4 Planning<br>
> 👤 **Sender:** Sarah Jones (via Project Alpha Updates) <<sarah.jones@example.com>><br>
> <br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> 💡 **EXECUTIVE SUMMARY & CONTEXT**<br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> Sarah Jones reports that the backend API for Project Alpha has achieved full test coverage and reached production completion. However, client-side rollout is experiencing a brief 48-hour delay stemming from OAuth token refresh edge-cases in the new authentication flow. In parallel, team leadership is finalizing the Q4 engineering roadmap to prioritize incoming feature requests.<br>
> <br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> 🔍 **DEEP-DIVE KEY INSIGHTS**<br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> • [Backend Architecture]: Core REST endpoints are fully deployed with automated CI test suites passing.<br>
> • [Frontend Auth Bottleneck]: Integration roadblock isolated to state synchronization in the revised OAuth flow; estimated resolution within 2 working days.<br>
> • [Q4 Milestone Scheduling]: Team planning session proposed for Tuesday at 2:00 PM to lock down quarterly feature delivery commitments.<br>
> <br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> 🌐 **EXTERNAL SOURCE INSIGHTS (Full Article / Video / Audio)**<br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> Video demo demonstrates the new multi-tenant auth architecture and interactive dashboard prototype.<br>
> <br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> ⚡ **ACTIONABLE TAKEAWAYS**<br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> • Confirm availability for the Q4 planning meeting on Tuesday at 2:00 PM.<br>
> • Review frontend auth branch PR before Wednesday's scheduled merge window.<br>
> <br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> 🎯 **ACTION STATUS**<br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> **Action Required**: YES ⚠️<br>
> **Reason**: Needs calendar confirmation for the proposed planning meeting time.<br>
> <br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> 🔗 **REFERENCED SOURCES & LINKS**<br>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
> • [YOUTUBE] Project Alpha Walkthrough: https://youtube.com/watch?v=...<br>
> • [UNSUBSCRIBE] https://example.com/unsubscribe<br>
> ================================================================================

## 🎨 Personalization Showcase

This agent is highly customizable. While it includes built-in support for **Chinese language learning**, the same logic can be applied to any specialized newsletter, technical digest, or specific communication style.

### ✨ Example: Custom Study Materials
The agent can be configured to extract content from specific newsletters and transform them into personalized study or reference materials (e.g., custom study guides, flashcards, or NotebookLM-generated audio overviews and presentations).

---

## Prerequisites

- Python 3.11+
- Google Cloud account (for deployment)
- Gmail account
- Google Cloud Project with billing enabled

1.  **Google Cloud Project**: You need a Google Cloud Project.
2.  **Gmail API Enabled**: Enable the Gmail API for your project.
3.  **OAuth Consent Screen**:
    -   Go to [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent).
    -   Set "User Type" to **External**.
    -   Fill in required fields (App name, support email).
    -   **IMPORTANT**: Under "Publishing status", click **"Publish App"** to set it to "In production". This prevents the authentication token from expiring every 7 days.
4.  **Credentials**:
    -   Go to [Credentials](https://console.cloud.google.com/apis/credentials).
    -   Click "Create Credentials" > "OAuth client ID".
    -   Application type: **Desktop app**.
    -   Name: "Gmail Agent Desktop".
    -   Click "Create" and download the JSON file.
    -   Rename it to `credentials.json` and place it in the project root.

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
3. **IMPORTANT**: Enable the **Gmail API** and **Generative Language API** for your project in the [API Library](https://console.cloud.google.com/apis/library).
4. Create OAuth 2.0 credentials (Desktop app)
5. Download `credentials.json` and place it in the project root

### 4. Set Up Gemini API Key in Secret Manager

Store your Gemini API key in **Google Cloud Secret Manager** so it is automatically resolved on any machine or Cloud Run without local files:

```bash
# Store Gemini API key in Secret Manager
gcloud secrets create gemini-api-key --data-file=- << 'EOF'
your_gemini_api_key_here
EOF
```

*(Alternatively, run `python sync_secrets.py` to synchronize any existing local keys/tokens directly into Secret Manager).*

### 5. Authenticate Gmail

Run the authentication tool locally once to authorize your account and verify API connectivity:

```bash
python -m src.auth
```

This will open a browser window for Google OAuth 2.0 authentication, save the credentials, and automatically synchronize the token to Google Cloud Secret Manager (`gmail-agent-token`) for zero-setup execution across all your machines and Cloud Run.

## Local Usage

Run the agent manually:

```bash
python -m src.main
```

Or specify a custom email batch limit via CLI flag:

```bash
python -m src.main --max-emails 20
```

Or run in simulation / dry-run mode:

```bash
python -m src.main --dry-run --max-emails 5
```

Or run continuously on a recurring interval (e.g. every 30 minutes):

```bash
python -m src.main --interval 30
```

This will:
- Check for unread emails (up to batch limit, default: 20)
- Ingest external primary articles, YouTube video transcripts, or podcasts
- Summarize them using Gemini AI with rich executive intelligence briefings
- Forward summaries to your email within the original thread
- Apply Gmail labels (`ActionRequired` or `ReadLater`)
- Record execution telemetry to Google Cloud Storage

## Cloud Deployment (Google Cloud Run)

### Prerequisites

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated (`gcloud auth login`)
- Google Cloud Project configured (`gcloud config set project YOUR_PROJECT_ID`)

### Deploy

Run the deployment script:

```powershell
# Standard deployment (uses active gcloud project and defaults):
.\deployment\deploy_cloud.ps1

# Or with explicit parameters:
.\deployment\deploy_cloud.ps1 -ProjectId "gen-lang-client-0480639565" -Region "asia-northeast1" -Schedule "0 5,17 * * *"
```

The script will:
- Build and deploy the container to Cloud Run
- Create a Cloud Scheduler job to run according to your configured schedule (defaults to 5:00 AM and 5:00 PM)
- Configure service account IAM permissions (`roles/run.invoker`)

### Verify Deployment

Check the logs:

```powershell
gcloud run services logs read gmail-agent --region=asia-northeast1 --limit=10
```

Or manually trigger:

```powershell
gcloud scheduler jobs run gmail-agent-daily-trigger --location=asia-northeast1
```

## Configuration

This system enforces a **strict zero-local-`.env` cloud-native architecture**. All credentials, tokens, and sensitive information are resolved dynamically at runtime from **Google Cloud Secret Manager** and Google Cloud Storage. No `.env` files are needed or stored on local machines.

All operational behaviors can be configured dynamically via command-line arguments, Cloud Run parameters, or deployment script flags:

### Email Processing Limit (Batch Size)

Configure the maximum number of unread emails fetched and summarized per execution cycle:

- **Via Command-Line Argument** (local executions):
  Pass `-n` or `--max-emails` directly to the script:
  ```bash
  python -m src.main --max-emails 25
  ```

- **Via Deployment Parameter** (Google Cloud Run):
  Pass `-MaxEmails` when executing the deployment script:
  ```powershell
  .\deployment\deploy_cloud.ps1 -MaxEmails 25
  ```
  Or update the live Cloud Run service directly:
  ```bash
  gcloud run services update gmail-agent --region=asia-northeast1 --set-env-vars="MAX_EMAILS=25"
  ```

- **Via HTTP Trigger** (Cloud Run endpoint / Cloud Scheduler):
  Pass `max_emails` as a URL query parameter or JSON body:
  ```bash
  curl -X POST "https://<SERVICE_URL>/?max_emails=20"
  ```

### External Content & Media Ingestion Controls

The agent can crawl substantive primary sources linked within email messages (e.g. Substack, Medium, news publications, YouTube video transcripts, and podcast notes) to enrich Gemini's synthesis:

- **Default Parameters** (auto-configured in code & Cloud Run):
  - Ingestion Enabled: `ENABLE_EXTERNAL_FETCH=true`
  - Max External Links per Email: `MAX_EXTERNAL_LINKS=2`
  - Network Timeout: `FETCH_TIMEOUT_SECONDS=8`
  - Max Body Character Limit: `MAX_BODY_CHARS=40000`

- **Customizing on Cloud Run**:
  Update runtime variables in the cloud at any time:
  ```bash
  gcloud run services update gmail-agent --region=asia-northeast1 --set-env-vars="MAX_EXTERNAL_LINKS=3,FETCH_TIMEOUT_SECONDS=10"
  ```

- **Built-in Resilience & Anti-Barrier Guards**:
  - **Login Walls & Paywalls**: Detects and rejects pages requiring user credentials, subscription barriers, or security challenges (`401 Unauthorized`, `403 Forbidden`, Cloudflare bot checks, login redirects) without interrupting email processing.
  - **Intelligent Link Discarding**: Automatically ignores tracking links (`utm_*`, `gclid`), unsubscribe/preference slugs, binary assets, and social media URLs.
  - **Fail-Safe Fallbacks**: If external scraping fails or encounters an access wall, the agent gracefully falls back to synthesizing the original email body without error.

### Schedule & Frequency (When and How Often to Run)

The execution timing and frequency can be tailored to your preference:

#### 1. Cloud Deployment (Cloud Scheduler)
Configure `Schedule` and `Timezone` directly when running `.\deployment\deploy_cloud.ps1`:

```powershell
.\deployment\deploy_cloud.ps1 -Schedule "0 5,17 * * *" -Timezone "Asia/Seoul"
```

Common schedule patterns:
| Frequency | Cron Expression (`Schedule`) | Description |
| :--- | :--- | :--- |
| **Twice daily (Default)** | `0 5,17 * * *` | Runs at 5:00 AM and 5:00 PM every day |
| **Once daily** | `0 8 * * *` | Runs every morning at 8:00 AM |
| **Hourly** | `0 * * * *` | Runs at the beginning of every hour |
| **Every 30 minutes** | `*/30 * * * *` | Runs every 30 minutes |
| **Weekdays only** | `0 9 * * 1-5` | Runs Monday through Friday at 9:00 AM |

> **Updating Schedule in Cloud**: You can update Cloud Scheduler directly without redeploying code:
> ```bash
> gcloud scheduler jobs update http gmail-agent-daily-trigger --location=asia-northeast1 --schedule="0 8 * * *" --time-zone="Asia/Seoul"
> ```

#### 2. Local Deployment (Windows Task Scheduler)
If you run the agent on your Windows computer using Task Scheduler:
1. Open Task Scheduler (`taskschd.msc`).
2. Select your `Gmail Agent` task and click **Properties** > **Triggers** tab.
3. Edit the trigger to set your preferred interval (e.g., daily at specific hours, or repeat every 15/30/60 minutes).

### Purchase Keywords

Edit `src/summarizer.py` to customize purchase detection:

```python
purchase_keywords = [
    'order', 'purchase', 'receipt', 'invoice', 'payment',
    # Add more keywords
]
```

## Multi-PC Zero-Setup Execution

In this cloud-native architecture, any newly cloned machine with `gcloud` access can execute immediately with **zero local credential files** or `.env` required.

```powershell
# 1. Authenticate with Google Cloud
gcloud auth login
gcloud config set project gen-lang-client-0480639565

# 2. Run immediately in Dry-Run mode (zero files created on disk)
python -m src.main --dry-run --max-emails 2

# 3. Normal execution
python -m src.main --max-emails 20
```

### Initial Credential Synchronization (One-Time Setup)

If you generate or obtain new local credentials and need to seed Secret Manager:

```powershell
# Sync token.json, credentials.json, and GEMINI_API_KEY to Secret Manager in one shot
python sync_secrets.py
```

## Project Structure

```
gmail-agent/
├── .dockerignore           # Container build ignore rules
├── .gitignore              # Comprehensive Git hygiene & secret protections
├── Dockerfile              # Container image definition for Google Cloud Run
├── LICENSE                 # Project license
├── README.md               # Production architecture & onboarding guide
├── requirements.txt        # Python dependencies (includes cloud secret & storage SDKs)
├── run_agent.bat           # Windows executable & Task Scheduler launcher
├── sync_secrets.py         # Convenience CLI entry point for secret synchronization
├── deployment/
│   ├── DEPLOYMENT.md       # Multi-platform deployment guide
│   ├── deploy_cloud.ps1    # Automated Cloud Run & Cloud Scheduler deployment script
│   ├── sync_secrets.py     # Tool to sync local credentials to Secret Manager
│   └── upload_token.ps1    # Token upload utility
├── docs/
│   └── assets/             # Architecture overview diagrams & documentation assets
└── src/
    ├── __init__.py         # Package marker & exported module declarations
    ├── app.py              # Flask HTTP webhook entry point for Cloud Run
    ├── auth.py             # Dual-mode multi-PC Gmail OAuth 2.0 resolver
    ├── config.py           # Centralized configuration & Secret Manager resolution
    ├── content_fetcher.py  # Multi-modal web, YouTube, podcast content scraper & login guards
    ├── gmail_client.py     # Gmail API client & RFC 822 MIME message builder
    ├── main.py             # End-to-end batch processing pipeline & CLI runner
    ├── storage.py          # Google Cloud Storage state & decoupled run logging
    └── summarizer.py       # AI executive summarization engine (Gemini 3.8 Flash)
```

## Cost Estimate

Running twice per day on Google Cloud Run:

- **Cloud Run (Compute)**: $0.00/month (within free tier — ~60 runs/month vs. 2M free requests limit).
- **Cloud Scheduler**: $0.00/month (1 job configured vs. 3 free jobs allowance per billing account).
- **Gemini API**: $0.00/month (Google AI Studio free tier for Gemini Flash models).
- **Auxiliary Services (Storage & Egress)**: ~$0.05 – $0.10/month (~0.3 JPY / day):
  - *Artifact Registry*: Stores the Docker container image (0.5 GB/month is free; excess image storage is billed at ~$0.10/GB/month).
  - *Network Egress*: Minor cross-region data transfer fees when calling Gmail and Gemini APIs.
  - *Secret Manager* (if used): 6 active secret versions are free per month.

**Total**: **Essentially free** (~$0.05 – $0.10/month or ~10 JPY/month).

> **Tip**: For a completely $0.00 setup without any cloud infrastructure or storage fees, run the agent locally via Windows Task Scheduler (see [Option 1 in DEPLOYMENT.md](deployment/DEPLOYMENT.md)).

## Security Notes

The system is designed with a **cloud-native, zero-local-credentials** architecture. All sensitive API keys, OAuth client secrets, and access tokens are managed exclusively through **Google Cloud Secret Manager**.

`.gitignore` is strictly configured to guarantee that no ephemeral credentials (`credentials.json`, `token.json`, `.env`) are ever tracked or committed to Git.

## Troubleshooting

### "ModuleNotFoundError"
- Ensure `PYTHONPATH=/app` is set in `Dockerfile`
- All imports use absolute paths (`from src.module import ...`)

### "could not locate runnable browser" (Headless / Cloud Run Auth Error)
- Do not run interactive OAuth on headless Cloud Run.
- Authenticate locally first: `python -m src.auth`
- Synchronize token to Secret Manager: `python sync_secrets.py` (or `.\deployment\upload_token.ps1`). Cloud Run resolves the token directly from Secret Manager at runtime without rebuilding containers.

### "Error 403: access_denied" (OAuth Blocked)
- Ensure your email is added to the **Test Users** list in the [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) settings.
- If the app is in "Testing" mode, only approved users can log in.

### "Gmail API has not been used... or it is disabled"
- Click the link provided in the error message to enable the Gmail API for your project in the Google Cloud Console.

### Billing Error
- Enable billing in Google Cloud Console
- Link billing account to your project

## License

This project is licensed under a Non-Commercial License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Powered by [Google Gemini AI](https://ai.google.dev/)
- Uses [Gmail API](https://developers.google.com/gmail/api)
