# Gmail Agent - Cloud Deployment Script

# Load configuration from .env file
if (-not (Test-Path ".env")) {
    Write-Error ".env file not found. Please create it with required variables."
    Write-Host "Required variables in .env:"
    Write-Host "  GCP_PROJECT_ID=your-project-id"
    exit 1
}

# Read .env file and set variables
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        Set-Variable -Name $name -Value $value -Scope Script
    }
}

# Configuration (can be overridden in .env)
if (-not $GCP_PROJECT_ID) {
    Write-Error "GCP_PROJECT_ID not set in .env file"
    exit 1
}

# Retrieve centralized defaults from src.config if not explicitly provided in .env
$CONFIG_DEFAULTS = try {
    py -3 -c "import json; from src.config import get_schedule, get_timezone, get_max_emails; print(json.dumps({'schedule': get_schedule(), 'timezone': get_timezone(), 'max_emails': get_max_emails()}))" 2>$null | ConvertFrom-Json
} catch {
    $null
}

$PROJECT_ID = $GCP_PROJECT_ID
$REGION = if ($GCP_REGION) { $GCP_REGION } else { "us-central1" }
$SERVICE_NAME = if ($SERVICE_NAME) { $SERVICE_NAME } else { "gmail-agent" }
$JOB_NAME = if ($JOB_NAME) { $JOB_NAME } else { "gmail-agent-daily-trigger" }
$SCHEDULE = if ($SCHEDULE) { $SCHEDULE } elseif ($CONFIG_DEFAULTS -and $CONFIG_DEFAULTS.schedule) { $CONFIG_DEFAULTS.schedule } else { "0 5,17 * * *" }
$TIMEZONE = if ($TIMEZONE) { $TIMEZONE } elseif ($CONFIG_DEFAULTS -and $CONFIG_DEFAULTS.timezone) { $CONFIG_DEFAULTS.timezone } else { "Asia/Seoul" }
$MAX_EMAILS = if ($MAX_EMAILS) { $MAX_EMAILS } elseif ($CONFIG_DEFAULTS -and $CONFIG_DEFAULTS.max_emails) { $CONFIG_DEFAULTS.max_emails } else { 20 }

Write-Host "Deploying Gmail Agent to Google Cloud..." -ForegroundColor Green

# 1. Check if gcloud is installed
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "Google Cloud SDK (gcloud) is not installed. Please install it first."
    exit 1
}

# 2. Set Project
Write-Host "Setting project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID

# 3. Enable required services
Write-Host "Enabling required APIs (Cloud Run, Cloud Build, Artifact Registry, Cloud Scheduler)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com

# 4. Deploy to Cloud Run
Write-Host "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME `
    --source . `
    --region $REGION `
    --set-env-vars "MAX_EMAILS=$MAX_EMAILS,SCHEDULE=$SCHEDULE,TIMEZONE=$TIMEZONE" `
    --no-allow-unauthenticated `
    --quiet

# Get the Service URL
$SERVICE_URL = gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)'
Write-Host "Service deployed at: $SERVICE_URL" -ForegroundColor Cyan

# 5. Create Service Account for Scheduler
$SA_NAME = "gmail-agent-scheduler-sa"
$SA_EMAIL = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "Setting up Service Account for Scheduler..."
# Check if SA exists
if (-not (gcloud iam service-accounts list --filter="email:$SA_EMAIL" --format="value(email)")) {
    gcloud iam service-accounts create $SA_NAME --display-name "Gmail Agent Scheduler"
}

# Grant permission to invoke Cloud Run
gcloud run services add-iam-policy-binding $SERVICE_NAME `
    --region $REGION `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/run.invoker"

# 6. Create/Update Cloud Scheduler Job
Write-Host "Configuring Cloud Scheduler..."
if (gcloud scheduler jobs list --location=$REGION --filter="name:projects/$PROJECT_ID/locations/$REGION/jobs/$JOB_NAME" --format="value(name)") {
    Write-Host "Updating existing job..."
    gcloud scheduler jobs update http $JOB_NAME `
        --location=$REGION `
        --schedule=$SCHEDULE `
        --time-zone=$TIMEZONE `
        --uri=$SERVICE_URL `
        --http-method=POST `
        --oidc-service-account-email=$SA_EMAIL
}
else {
    Write-Host "Creating new job..."
    gcloud scheduler jobs create http $JOB_NAME `
        --location=$REGION `
        --schedule=$SCHEDULE `
        --time-zone=$TIMEZONE `
        --uri=$SERVICE_URL `
        --http-method=POST `
        --oidc-service-account-email=$SA_EMAIL
}

Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host "Your agent schedule is configured to: '$SCHEDULE' ($TIMEZONE)."
