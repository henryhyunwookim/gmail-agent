@echo off
cd /d "%~dp0"
python -m src.main >> logs/agent.log 2>&1
