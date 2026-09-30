@echo off

:: Demande d'élévation de privilèges (Administrateur)
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' goto UACPrompt
goto gotAdmin

:UACPrompt
    echo Demande des privileges administrateur (requis pour interagir avec le jeu)...
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    set params= %*
    echo UAC.ShellExecute "cmd.exe", "/c ""%~s0"" %params%", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    pushd "%CD%"
    CD /D "%~dp0"

set VENV=.venv
set PYTHON=%VENV%\Scripts\python.exe
set PIP=%VENV%\Scripts\pip.exe
set PY=lwsc
if "%1"=="clean" (
    echo Nettoyage de l'environnement virtuel...
    if exist %VENV% rmdir /S /Q %VENV%
    goto end
)

if not exist %VENV% (
    echo Création de l'environnement virtuel...
    python -m venv %VENV%
)

echo Mise à jour de pip...
%PYTHON% -m pip install --upgrade pip > nul

echo Installation des dépendances...
%PIP% install -r requirements.txt > nul

if "%1"=="install" (
    echo Installation terminée !
    goto end
)

echo Lancement de LWSC...
%PYTHON% src\%PY%.py

:end
