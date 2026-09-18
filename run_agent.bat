@echo off
REM ==============================================================================
REM Gmail Agent - Windows Execution & Scheduled Task Launcher
REM ==============================================================================
REM Purpose:
REM   Executes the Gmail Agent main module and appends structured execution logs
REM   to 'logs/agent.log'. Designed to be invoked manually or automatically via
REM   Windows Task Scheduler.
REM
REM Behavior:
REM   1. Changes working directory to this script's directory (%~dp0).
REM   2. Ensures the local 'logs' directory exists.
REM   3. Runs 'python -m src.main' redirecting stdout and stderr.
REM ==============================================================================

cd /d "%~dp0"

REM Ensure logging directory exists
if not exist "logs" (
    mkdir "logs"
)

REM Execute the agent and capture combined stdout/stderr
python -m src.main >> logs\agent.log 2>&1
