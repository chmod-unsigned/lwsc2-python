@echo off
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
