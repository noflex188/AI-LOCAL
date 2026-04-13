@echo off
cd /d "%~dp0"
title AI Assistant - Mise a jour

echo.
echo  =============================================
echo   Mise a jour de l'AI Assistant
echo  =============================================
echo.

:: Verifier que git est disponible
git --version >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Git n'est pas installe ou pas dans le PATH.
    echo  Installe Git : https://git-scm.com/download/win
    pause
    exit /b 1
)

:: Verifier qu'on est bien dans un depot git
git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Ce dossier n'est pas un depot Git.
    echo  L'update automatique necessite que le projet ait ete clone avec git clone.
    pause
    exit /b 1
)

echo  Telechargement des mises a jour...
git pull
if errorlevel 1 (
    echo.
    echo  [ERREUR] Echec de la mise a jour.
    echo  Si tu as modifie des fichiers du projet, git peut refuser de merger.
    echo  Lance : git stash  puis relance update.bat
    pause
    exit /b 1
)

echo.
echo  Mise a jour des packages Python...
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
    echo  OK
) else (
    echo  Venv introuvable - lance install.bat d'abord.
)

echo.
echo  =============================================
echo   Mise a jour terminee !
echo   Relance start_web.bat pour demarrer.
echo  =============================================
echo.
pause
