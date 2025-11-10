@echo off
setlocal

REM Streamlit launch script
REM Requirements: streamlit, pandas, openpyxl
REM Ensure .venv exists (python -m venv .venv) before running.

cd /d "%~dp0"
set "VENV_DIR=%~dp0.venv"

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Missing .venv virtual environment. Run python -m venv .venv first.
    exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"

echo Starting Streamlit...
python -m streamlit run app.py

endlocal
