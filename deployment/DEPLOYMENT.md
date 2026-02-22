# Gmail Agent - Production Deployment Guide

## Overview
This guide covers multiple approaches to deploy your Gmail agent for real-time inbox monitoring.

## Option 1: Windows Task Scheduler (Recommended for Windows)

### Setup Steps

1. **Create a batch file** to run the agent:

Create `run_agent.bat` in your project directory:
```batch
@echo off
cd /d "%~dp0"
python -m src.main >> logs/agent.log 2>&1
```

> **Note**: `%~dp0` automatically uses the directory where the batch file is located.

2. **Create logs directory**:
```bash
mkdir logs
```

3. **Open Task Scheduler**:
   - Press `Win + R`, type `taskschd.msc`, press Enter

4. **Create a new task**:
   - Click "Create Task" (not "Create Basic Task")
   - **General tab**:
     - Name: "Gmail Agent"
     - Description: "Automated email summarization agent"
     - Run whether user is logged on or not
     - Run with highest privileges
   
   - **Triggers tab**:
     - Click "New"
     - Begin the task: "On a schedule"
     - Settings: "Daily"
     - Repeat task every: **5 minutes** (or your preferred interval)
     - For a duration of: "Indefinitely"
     - Enabled: ✓
   
   - **Actions tab**:
     - Click "New"
     - Action: "Start a program"
     - Program/script: `C:\path\to\gmail-agent\run_agent.bat`
     - Start in: `C:\path\to\gmail-agent`
     
     > **Note**: Replace `C:\path\to\gmail-agent` with your actual project path.
   
   - **Conditions tab**:
     - Uncheck "Start the task only if the computer is on AC power"
   
   - **Settings tab**:
     - Allow task to be run on demand: ✓
     - If the task is already running: "Do not start a new instance"

5. **Test the task**:
   - Right-click the task → "Run"
   - Check `logs/agent.log` for output

### Pros & Cons
✅ Simple setup on Windows  
✅ Runs in background  
✅ No additional costs  
❌ Requires computer to be on  
❌ 5-minute minimum interval (not truly real-time)

---

## Option 2: Cloud Deployment (Google Cloud Run + Cloud Scheduler)

### Why Cloud?
- Runs 24/7 without your computer
- True scheduled execution
- Scalable and reliable

### Setup Steps

1. **Prerequisites**:
   - Install [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
   - Run `gcloud auth login`
   - Run `gcloud config set project YOUR_PROJECT_ID`

2. **Deploy using the script**:
   
   Open PowerShell and run:
   ```powershell
   # Edit the script first to set your PROJECT_ID
   notepad deploy_cloud.ps1
   
   # Run the script
   .\deploy_cloud.ps1
   ```

   This script will automatically:
   - Enable required Google Cloud APIs
   - Build and deploy the container to Cloud Run
   - Create a Service Account for the scheduler
   - Configure Cloud Scheduler to run daily at 2:00 AM

### Pros & Cons
✅ Runs 24/7  
✅ No local computer needed  
✅ Reliable and scalable  
✅ **Free Tier Friendly**: 1 run/day is $0.00/month  
❌ Requires Google Cloud account

---

## Option 3: Continuous Monitoring with Gmail Push Notifications

For true real-time monitoring, use Gmail's Push Notifications API.

### Setup Steps

1. **Create a monitoring script** (`src/monitor.py`):
```python
import time
from main import main

def monitor_loop():
    """Run the agent continuously with a delay between checks."""
    print("Starting Gmail Agent monitor...")
    
    while True:
        try:
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Checking inbox...")
            main()
            
            # Wait 5 minutes before next check
            time.sleep(300)  # 300 seconds = 5 minutes
            
        except KeyboardInterrupt:
            print("\nStopping monitor...")
            break
        except Exception as e:
            print(f"Error: {e}")
            print("Retrying in 1 minute...")
            time.sleep(60)

if __name__ == "__main__":
    monitor_loop()
```

2. **Run as a background service**:

**Windows (using NSSM)**:
```bash
# Download NSSM: https://nssm.cc/download
nssm install GmailAgent "python" "C:\path\to\gmail-agent\src\monitor.py"
nssm start GmailAgent
```

**Linux/Mac (using systemd)**:
Create `/etc/systemd/system/gmail-agent.service`:
```ini
[Unit]
Description=Gmail Agent
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/gmail-agent
ExecStart=/usr/bin/python3 /path/to/gmail-agent/src/monitor.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable gmail-agent
sudo systemctl start gmail-agent
```

### Pros & Cons
✅ Continuous monitoring  
✅ Faster response (5-minute intervals)  
✅ Full control  
❌ Requires computer/server to be always on  
❌ Uses more resources

---

## Recommended Approach

**For most users**: Start with **Option 1 (Task Scheduler)** for simplicity.

**For 24/7 monitoring**: Use **Option 2 (Cloud Run)** for reliability.

**For development/testing**: Use **Option 3 (Continuous Loop)** to experiment.

---

## Monitoring & Logs

### View logs
```bash
# Windows Task Scheduler logs
type logs\agent.log

# Monitor in real-time
Get-Content logs\agent.log -Wait -Tail 20
```

### Log rotation
Add to `run_agent.bat`:
```batch
@echo off
cd /d "%~dp0"

REM Rotate logs if > 10MB
for %%A in (logs\agent.log) do if %%~zA gtr 10485760 (
    move logs\agent.log logs\agent_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log
)

python -m src.main >> logs/agent.log 2>&1
```

---

## Security Considerations

1. **Protect credentials**:
   - Never commit `credentials.json` or `.env` to git
   - Use environment variables in production
   - Rotate API keys regularly

2. **Token security**:
   - `token.json` contains access tokens
   - Keep it secure and private

3. **Cloud deployment**:
   - Use Secret Manager for credentials
   - Enable VPC for network isolation

---

## Troubleshooting

### Agent not running
- Check Task Scheduler history
- Review `logs/agent.log`
- Verify Python path is correct

### Authentication errors
- Token may have expired
- Re-run authentication flow
- Check OAuth consent screen settings

### Missing emails
- Verify max_results is sufficient
- Check filtering logic
- Review statistics output
