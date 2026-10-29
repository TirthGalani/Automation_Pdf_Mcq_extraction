@echo off
echo ========================================================
echo   Starting MCQ PDF Extraction & Translation Server
echo ========================================================
cd /d %~dp0
python -m uvicorn app.main:app --host localhost --port 8009 --reload --reload-dir app
pause
