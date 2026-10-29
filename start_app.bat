@echo off
echo ================================================================
echo   MCQ PDF Extraction and Translation System (Gemini API)
echo ================================================================
echo.
echo Installing / Updating Python requirements...
python -m pip install -r backend/requirements.txt
echo.
echo Starting FastAPI Server and Web Dashboard on http://localhost:8009
echo.
start "" http://localhost:8009
cd backend
python -m uvicorn app.main:app --host localhost --port 8009 --reload --reload-dir app
pause
