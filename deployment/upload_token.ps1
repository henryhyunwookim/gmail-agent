<#
.SYNOPSIS
    Uploads a refreshed or newly authorized token.json to Google Cloud Secret Manager.

.DESCRIPTION
    Reads local token.json and uploads it as a new version of the Gmail token secret
    in Google Cloud Secret Manager. This allows Cloud Run and remote machines to
    access the new credentials immediately without requiring any code redeployment.

.PARAMETER ProjectId
    The Google Cloud Project ID. Defaults to $GCP_PROJECT_ID from .env or active gcloud config.

.PARAMETER SecretName
    The target secret name in Secret Manager. Defaults to 'gmail-agent-token'.

.PARAMETER TokenPath
    The path to the local token JSON file. Defaults to 'token.json'.

.EXAMPLE
    .\upload_token.ps1

.EXAMPLE
    .\upload_token.ps1 -ProjectId "my-gcp-project" -SecretName "gmail-agent-token"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$SecretName = "gmail-agent-token",

    [Parameter(Mandatory = $false)]
    [string]$TokenPath = "token.json"
)

$ErrorActionPreference = "Stop"

# ==============================================================================
# SECTION 1: Environment & Parameter Resolution
# ==============================================================================

# Read .env file if present in workspace root
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
            $envKey = $matches[1].Trim()
            $envVal = $matches[2].Trim()
            Set-Variable -Name $envKey -Value $envVal -Scope Script
        }
    }
}

$TARGET_PROJECT = if ($ProjectId) { 
    $ProjectId 
} elseif ($GCP_PROJECT_ID) { 
    $GCP_PROJECT_ID 
} else { 
    (gcloud config get-value project 2>$null).Trim() 
}

if (-not $TARGET_PROJECT -or $TARGET_PROJECT -eq "(unset)") {
    Write-Error "Could not determine GCP project ID. Provide -ProjectId or run 'gcloud config set project <ID>'."
    exit 1
}

# ==============================================================================
# SECTION 2: Token Validation & Upload
# ==============================================================================

if (-not (Test-Path $TokenPath)) {
    Write-Error "Token file '$TokenPath' not found. Run 'python -m src.auth' first to generate valid credentials."
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Uploading Token to Google Cloud Secret Manager" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Project: $TARGET_PROJECT"
Write-Host " Secret:  $SecretName"
Write-Host " Source:  $TokenPath"
Write-Host "=========================================================="

Write-Host "`nAdding new secret version to '$SecretName'..." -ForegroundColor Yellow
gcloud secrets versions add $SecretName --data-file=$TokenPath --project $TARGET_PROJECT

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[+] Success: Token uploaded to Secret Manager!" -ForegroundColor Green
    Write-Host "    Cloud Run and remote instances will use this updated token automatically on next execution."
} else {
    Write-Error "Failed to upload token. Check that the secret '$SecretName' exists in project '$TARGET_PROJECT'."
    Write-Host "To create the secret for the first time, run:" -ForegroundColor Yellow
    Write-Host "  gcloud secrets create $SecretName --data-file=$TokenPath --project $TARGET_PROJECT" -ForegroundColor Yellow
}
