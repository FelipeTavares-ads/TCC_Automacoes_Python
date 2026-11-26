@echo off
setlocal
chcp 65001 >nul
title Hub de Automacoes

cd /d "%~dp0programa"

echo ============================================================
echo  HUB DE AUTOMACOES
echo ============================================================
echo.

if not exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    if not exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
        echo O Google Chrome nao foi encontrado neste computador.
        echo Instale o Chrome e de dois cliques em INICIAR.bat de novo.
        echo.
        pause
        exit /b 1
    )
)

if exist "venv\Scripts\python.exe" goto :executar

echo Primeira vez neste computador: preparando o ambiente.
echo Isso leva alguns minutos e so acontece uma vez.
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo Python nao encontrado. Instalando o Python...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo.
    echo Python instalado. FECHE esta janela e de dois cliques em INICIAR.bat de novo.
    echo.
    pause
    exit /b 0
)

%PY% -m venv venv
if errorlevel 1 goto :erro

"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -r requirements_hub.txt
if errorlevel 1 goto :erro

:executar
"venv\Scripts\python.exe" -u executar_hub.py
echo.
pause
exit /b 0

:erro
echo.
echo Nao foi possivel preparar o ambiente. Tire um print desta tela e envie
echo para quem mantem o hub.
echo.
pause
exit /b 1
