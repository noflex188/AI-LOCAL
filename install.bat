@echo off
cd /d "%~dp0"
title AI Assistant - Installation

echo.
echo  =============================================
echo   Installation de l'AI Assistant
echo  =============================================
echo.


:: ══════════════════════════════════════════════
:: 1. Python
:: ══════════════════════════════════════════════
echo [1/4] Verification de Python...
python --version >nul 2>&1
if errorlevel 1 goto :installer_python
echo  OK - Python detecte
goto :python_ok

:installer_python
echo  Python non trouve - installation automatique...
winget install --id Python.Python.3.11 -e --silent --accept-package-agreements --accept-source-agreements
if not errorlevel 1 goto :python_installe
echo  winget indisponible - telechargement direct...
set PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
set PY_INST=%TEMP%\python_installer.exe
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INST%'"
if errorlevel 1 goto :erreur_python
"%PY_INST%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

:python_installe
echo  Python installe. Ferme cette fenetre, reouvre-la et relance install.bat
pause
exit /b 0

:erreur_python
echo  [ERREUR] Impossible d'installer Python automatiquement.
echo  Installe-le manuellement : https://www.python.org/downloads/
pause
exit /b 1

:python_ok


:: ══════════════════════════════════════════════
:: 2. Ollama
:: ══════════════════════════════════════════════
echo.
echo [2/4] Verification d'Ollama...
ollama --version >nul 2>&1
if errorlevel 1 goto :installer_ollama
echo  OK - Ollama detecte
goto :ollama_ok

:installer_ollama
echo  Ollama non trouve - installation automatique...
winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
if not errorlevel 1 goto :ollama_installe
echo  winget indisponible - telechargement direct...
set OL_URL=https://ollama.com/download/OllamaSetup.exe
set OL_INST=%TEMP%\OllamaSetup.exe
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%OL_URL%' -OutFile '%OL_INST%'"
if errorlevel 1 goto :erreur_ollama
"%OL_INST%" /silent

:ollama_installe
echo  Ollama installe. Ferme cette fenetre, reouvre-la et relance install.bat
pause
exit /b 0

:erreur_ollama
echo  [ERREUR] Impossible d'installer Ollama automatiquement.
echo  Installe-le manuellement : https://ollama.com/download
pause
exit /b 1

:ollama_ok


:: ══════════════════════════════════════════════
:: 3. Packages Python
:: ══════════════════════════════════════════════
echo.
echo [3/4] Installation des packages Python...
if not exist "venv\" (
    python -m venv venv
    if errorlevel 1 goto :erreur_venv
)
call venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 goto :erreur_pip
echo  OK
goto :packages_ok

:erreur_venv
echo  [ERREUR] Impossible de creer le venv.
pause
exit /b 1

:erreur_pip
echo  [ERREUR] Echec de l'installation des packages.
pause
exit /b 1

:packages_ok


:: ══════════════════════════════════════════════
:: 4. Modeles Ollama
:: ══════════════════════════════════════════════
echo.
echo [4/4] Telechargement du modele IA...
echo.
echo   1) gemma4:26b   Qualite maximale   ~17 GB  (necessite 16+ GB RAM)
echo   2) gemma4:e4b   Leger et rapide     ~3 GB  (necessite 4+ GB RAM)
echo.
set /p MODEL_CHOICE=Ton choix [1 ou 2] :

if "%MODEL_CHOICE%"=="1" goto :pull_26b
if "%MODEL_CHOICE%"=="2" goto :pull_e4b
echo  Choix invalide. Relance install.bat.
pause
exit /b 1

:pull_26b
echo  Telechargement de gemma4:26b...
ollama pull gemma4:26b
goto :pull_nomic

:pull_e4b
echo  Telechargement de gemma4:e4b...
ollama pull gemma4:e4b
goto :pull_nomic

:pull_nomic
echo.
echo  Telechargement du modele d'indexation (RAG)...
ollama pull nomic-embed-text


:: ══════════════════════════════════════════════
:: Fin
:: ══════════════════════════════════════════════
echo.
echo  =============================================
echo   Installation terminee !
echo   Lance start_web.bat pour demarrer.
echo  =============================================
echo.
pause
