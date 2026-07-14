# Upload Token to Secret Manager
# Run this after: python src/auth.py
# This updates the token in Cloud Run WITHOUT redeploying.

$PROJECT_ID = "gen-lang-client-0480639565"
$SECRET_NAME = "gmail-agent-token"

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
