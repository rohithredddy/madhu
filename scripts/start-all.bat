@echo off
rem Start all three parts of the application on Windows (docs/02 section 4).
rem Each opens in its own window; close a window to stop that part.
rem   Python engine  http://localhost:8000
rem   Java backend   http://localhost:8080
rem   React UI       http://localhost:5173   <- open this one
setlocal
set ROOT=%~dp0..

if not exist "%ROOT%\analyzer\.venv\Scripts\python.exe" (
  echo No analyzer\.venv found. Create it first: see analyzer\README.md
  exit /b 1
)

start "PARE engine :8000" /D "%ROOT%\analyzer" "%ROOT%\analyzer\.venv\Scripts\python.exe" -m uvicorn service.app:app --host 127.0.0.1 --port 8000
rem Started from backend\, so the default data dir ..\data is the project's data folder.
start "Java backend :8080" /D "%ROOT%\backend" cmd /c mvnw.cmd -q spring-boot:run
start "React UI :5173" /D "%ROOT%\frontend" cmd /c npm run dev -- --strictPort

echo Open http://localhost:5173 once the backend window shows "Started XaiRcaApplication".
endlocal
