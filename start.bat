@echo off

:: Verifier que le venv existe
if not exist "venv\" (
    echo.
    echo [ERREUR] Le venv n'existe pas.
    echo          Lance install.bat d'abord !
    echo.
    pause
    exit /b 1
)

:: Verifier que les packages sont installes
call venv\Scripts\activate.bat
python -c "import ollama" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERREUR] Les packages ne sont pas installes dans le venv.
    echo          Lance install.bat d'abord !
    echo.
    pause
    exit /b 1
)

:: Lancer l'assistant
python main.py
