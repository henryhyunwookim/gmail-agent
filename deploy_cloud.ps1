# Gmail Agent - Cloud Deployment Script

# Configuration
$PROJECT_ID = "serp-425005"  # Replace with your actual Project ID
$REGION = "us-central1"
$SERVICE_NAME = "gmail-agent"
$JOB_NAME = "gmail-agent-daily-trigger"
$SCHEDULE = "0 2 * * *"  # Run at 2:00 AM every day
$TIMEZONE = "Asia/Seoul" # Set to your timezone

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
Write-Host "Your agent will run daily at 2:00 AM ($TIMEZONE)."
