<#
.SYNOPSIS
    Automated Google Cloud deployment script for Gmail Agent.

.DESCRIPTION
    Deploys the Gmail Agent container to Google Cloud Run, configures IAM service accounts,
    enables required GCP APIs, and sets up Google Cloud Scheduler for scheduled inbox monitoring.
    Automatically resolves configuration defaults from gcloud CLI config and src.config.

.PARAMETER ProjectId
    The Google Cloud Project ID to deploy to. Defaults to active gcloud project.

.PARAMETER Region
    The Google Cloud Region (e.g. 'asia-northeast1'). Defaults to 'asia-northeast1'.

.PARAMETER ServiceName
    The Cloud Run service name. Defaults to 'gmail-agent'.

.PARAMETER JobName
    The Cloud Scheduler job name. Defaults to 'gmail-agent-daily-trigger'.

.PARAMETER Schedule
    The cron schedule expression. Defaults to '0 5,17 * * *' (twice daily).

.PARAMETER Timezone
    The timezone identifier for Cloud Scheduler. Defaults to 'Asia/Seoul'.

.PARAMETER MaxEmails
    Maximum emails to fetch per run. Defaults to 20.

.EXAMPLE
    .\deploy_cloud.ps1

.EXAMPLE
    .\deploy_cloud.ps1 -ProjectId "my-gcp-project" -Region "us-east1"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$Region,

    [Parameter(Mandatory = $false)]
    [string]$ServiceName,

    [Parameter(Mandatory = $false)]
    [string]$JobName,

    [Parameter(Mandatory = $false)]
    [string]$Schedule,

    [Parameter(Mandatory = $false)]
    [string]$Timezone,

    [Parameter(Mandatory = $false)]
    [int]$MaxEmails,

    [Parameter(Mandatory = $false)]
    [string]$TargetLearningLanguage
)

$ErrorActionPreference = "Stop"

# ==============================================================================
# SECTION 1: Cloud-Native Configuration Loading
# ==============================================================================

# Resolve target Project ID directly from arguments or gcloud config
$TARGET_PROJECT = if ($ProjectId) { 
    $ProjectId 
} else { 
    (gcloud config get-value project 2>$null).Trim() 
}

if (-not $TARGET_PROJECT -or $TARGET_PROJECT -eq "(unset)") {
    Write-Error "GCP Project is not configured. Specify -ProjectId or run 'gcloud config set project <ID>'."
    exit 1
}

# Retrieve centralized defaults from src.config
$CONFIG_DEFAULTS = try {
    py -3 -c "import json; from src.config import get_schedule, get_timezone, get_max_emails; print(json.dumps({'schedule': get_schedule(), 'timezone': get_timezone(), 'max_emails': get_max_emails()}))" 2>$null | ConvertFrom-Json
} catch {
    $null
}

$TARGET_REGION = if ($Region) { $Region } else { "asia-northeast1" }
$TARGET_SERVICE = if ($ServiceName) { $ServiceName } else { "gmail-agent" }
$TARGET_JOB = if ($JobName) { $JobName } else { "gmail-agent-daily-trigger" }
$TARGET_SCHEDULE = if ($Schedule) { $Schedule } elseif ($CONFIG_DEFAULTS -and $CONFIG_DEFAULTS.schedule) { $CONFIG_DEFAULTS.schedule } else { "0 5,17 * * *" }
$TARGET_TIMEZONE = if ($Timezone) { $Timezone } elseif ($CONFIG_DEFAULTS -and $CONFIG_DEFAULTS.timezone) { $CONFIG_DEFAULTS.timezone } else { "Asia/Seoul" }
$TARGET_MAX_EMAILS = if ($MaxEmails) { $MaxEmails } elseif ($CONFIG_DEFAULTS -and $CONFIG_DEFAULTS.max_emails) { $CONFIG_DEFAULTS.max_emails } else { 20 }
$TARGET_LANG = if ($TargetLearningLanguage) { $TargetLearningLanguage } elseif ($env:TARGET_LEARNING_LANGUAGE) { $env:TARGET_LEARNING_LANGUAGE } else { "Mandarin Chinese" }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Deploying Gmail Agent to Google Cloud Run" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Project:   $TARGET_PROJECT"
Write-Host " Region:    $TARGET_REGION"
Write-Host " Service:   $TARGET_SERVICE"
Write-Host " Schedule:  $TARGET_SCHEDULE ($TARGET_TIMEZONE)"
Write-Host " Batch:     $TARGET_MAX_EMAILS emails/run"
Write-Host " Language:  $TARGET_LANG"
Write-Host "=========================================================="

# ==============================================================================
# SECTION 2: Prerequisite Validation & API Enablement
# ==============================================================================

# 1. Check if gcloud CLI is available
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "Google Cloud SDK ('gcloud') is not found on PATH. Please install and configure it first."
    exit 1
}

# 2. Set active gcloud project
Write-Host "`n[1/5] Setting active project to $TARGET_PROJECT..." -ForegroundColor Yellow
gcloud config set project $TARGET_PROJECT

# 3. Enable required Google Cloud APIs
Write-Host "`n[2/5] Enabling required Google Cloud APIs..." -ForegroundColor Yellow
gcloud services enable `
    run.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com `
    cloudscheduler.googleapis.com `
    secretmanager.googleapis.com `
    storage.googleapis.com

# Ensure target Cloud Storage bucket exists in regional location
$BUCKET_NAME = "$TARGET_PROJECT-gmail-agent-data"
Write-Host "Ensuring Cloud Storage bucket gs://$BUCKET_NAME exists in $TARGET_REGION..." -ForegroundColor Cyan
$bucketCheck = gcloud storage buckets describe "gs://$BUCKET_NAME" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating Cloud Storage bucket gs://$BUCKET_NAME in $TARGET_REGION..."
    gcloud storage buckets create "gs://$BUCKET_NAME" --location=$TARGET_REGION
} else {
    Write-Host "Cloud Storage bucket gs://$BUCKET_NAME already exists."
}

# ==============================================================================
# SECTION 3: Cloud Run Deployment
# ==============================================================================

Write-Host "`n[3/5] Deploying container image to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $TARGET_SERVICE `
    --source . `
    --region $TARGET_REGION `
    --update-env-vars "GCP_PROJECT_ID=$TARGET_PROJECT,MAX_EMAILS=$TARGET_MAX_EMAILS,TARGET_LEARNING_LANGUAGE=$TARGET_LANG" `
    --no-allow-unauthenticated `
    --quiet

# Retrieve the deployed HTTPS URL
$SERVICE_URL = (gcloud run services describe $TARGET_SERVICE --region $TARGET_REGION --format 'value(status.url)').Trim()
Write-Host "Service deployed successfully at: $SERVICE_URL" -ForegroundColor Green

# ==============================================================================
# SECTION 4: IAM Service Account for Cloud Scheduler
# ==============================================================================

$SA_NAME = "gmail-agent-scheduler-sa"
$SA_EMAIL = "$SA_NAME@$TARGET_PROJECT.iam.gserviceaccount.com"

Write-Host "`n[4/5] Configuring Service Account for Cloud Scheduler..." -ForegroundColor Yellow
$saExists = gcloud iam service-accounts list --filter="email:$SA_EMAIL" --format="value(email)"
if (-not $saExists) {
    Write-Host "Creating service account '$SA_NAME'..."
    gcloud iam service-accounts create $SA_NAME --display-name "Gmail Agent Scheduler"
}

# Bind Cloud Run Invoker role to the scheduler service account
Write-Host "Granting 'roles/run.invoker' permission to $SA_EMAIL..."
gcloud run services add-iam-policy-binding $TARGET_SERVICE `
    --region $TARGET_REGION `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/run.invoker"

# ==============================================================================
# SECTION 5: Cloud Scheduler Job Configuration
# ==============================================================================

Write-Host "`n[5/5] Configuring Cloud Scheduler Trigger..." -ForegroundColor Yellow
$jobExists = gcloud scheduler jobs list --location=$TARGET_REGION --filter="name:projects/$TARGET_PROJECT/locations/$TARGET_REGION/jobs/$TARGET_JOB" --format="value(name)"

if ($jobExists) {
    Write-Host "Updating existing Cloud Scheduler job '$TARGET_JOB'..."
    gcloud scheduler jobs update http $TARGET_JOB `
        --location=$TARGET_REGION `
        --schedule=$TARGET_SCHEDULE `
        --time-zone=$TARGET_TIMEZONE `
        --uri=$SERVICE_URL `
        --http-method=POST `
        --oidc-service-account-email=$SA_EMAIL
} else {
    Write-Host "Creating new Cloud Scheduler job '$TARGET_JOB'..."
    gcloud scheduler jobs create http $TARGET_JOB `
        --location=$TARGET_REGION `
        --schedule=$TARGET_SCHEDULE `
        --time-zone=$TARGET_TIMEZONE `
        --uri=$SERVICE_URL `
        --http-method=POST `
        --oidc-service-account-email=$SA_EMAIL
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Deployment Complete!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Service URL: $SERVICE_URL"
Write-Host "Schedule:    $TARGET_SCHEDULE ($TARGET_TIMEZONE)"
Write-Host "Next Step:   Synchronize OAuth credentials via: python deployment/sync_secrets.py"
