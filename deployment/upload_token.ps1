# Upload Token to Secret Manager
# Run this after: python src/auth.py
# This updates the token in Cloud Run WITHOUT redeploying.

# Read .env file if present
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Variable -Name $name -Value $value -Scope Script
        }
    }
}

$PROJECT_ID = if ($GCP_PROJECT_ID) { $GCP_PROJECT_ID } else { (gcloud config get-value project 2>$null).Trim() }
$SECRET_NAME = if ($SECRET_NAME) { $SECRET_NAME } else { "gmail-agent-token" }

if (-not (Test-Path "token.json")) {
    Write-Error "token.json not found. Run 'python src/auth.py' first to generate it."
    exit 1
}

Write-Host "Uploading token.json to Secret Manager..." -ForegroundColor Cyan
gcloud secrets versions add $SECRET_NAME --data-file=token.json --project $PROJECT_ID

if ($LASTEXITCODE -eq 0) {
    Write-Host "Done! Cloud Run will use the new token on the next run." -ForegroundColor Green
} else {
    Write-Error "Failed to upload token. Check that the secret '$SECRET_NAME' exists."
    Write-Host "To create it for the first time, run:"
    Write-Host "  gcloud secrets create $SECRET_NAME --data-file=token.json --project $PROJECT_ID"
}
