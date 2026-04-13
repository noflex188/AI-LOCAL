@echo off
cd /d "%~dp0"
title AI Assistant

:: Venv present ?
if not exist "venv\" (
    echo [ERREUR] Lance install.bat d'abord.
    pause
    exit /b 1
)

:: Ollama installe ?
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Ollama n'est pas installe. Lance install.bat d'abord.
    pause
    exit /b 1
)

:: Ollama en cours d'execution ?
ollama list >nul 2>&1
if errorlevel 1 (
    echo  Ollama n'est pas demarre - lancement...
    start "" ollama serve
    timeout /t 3 /nobreak >nul
)

:: Activer le venv
call venv\Scripts\activate.bat

:: Afficher les adresses
echo.
echo  Demarrage du serveur...
echo  Local  : http://localhost:8000
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set LOCAL_IP=%%a
    goto :found_ip
)
:found_ip
set LOCAL_IP=%LOCAL_IP: =%
echo  Reseau : http://%LOCAL_IP%:8000
echo.

start http://localhost:8000
python server.py
