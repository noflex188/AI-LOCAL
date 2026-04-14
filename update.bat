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
if errorlevel 1 goto :installer_git
goto :git_ok

:installer_git
echo  Git non trouve - installation automatique...
winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
if not errorlevel 1 goto :git_installe
echo  winget indisponible - telechargement direct...
set GIT_URL=https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe
set GIT_INST=%TEMP%\GitInstaller.exe
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%GIT_URL%' -OutFile '%GIT_INST%'"
if errorlevel 1 goto :erreur_git
"%GIT_INST%" /VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS="icons,ext\reg\shellhere,assoc,assoc_sh"
:git_installe
echo  Git installe. Ferme cette fenetre, reouvre-la et relance update.bat
pause
exit /b 0

:erreur_git
echo  [ERREUR] Impossible d'installer Git automatiquement.
echo  Installe-le manuellement : https://git-scm.com/download/win
pause
exit /b 1

:git_ok

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
