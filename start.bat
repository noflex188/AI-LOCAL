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

:: Libérer le port 8000 si déjà occupé par une instance précédente
echo Vérification du port 8000...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Lancer le serveur web
echo Démarrage du serveur...
echo Interface disponible sur : http://localhost:8000
echo.
python server.py
