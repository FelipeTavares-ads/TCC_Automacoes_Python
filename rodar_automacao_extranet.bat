@echo off
setlocal
chcp 65001 >nul

title Automacao Extranet - Execucao Direta

cd /d "%~dp0"

set "PYTHON_VENV=%~dp0venv\Scripts\python.exe"
set "SCRIPT_AUTOMACAO=%~dp0teste_playwright.py"
set "ARQUIVO_LOG=%~dp0automacao_manual.log"
if not defined ETAPA_AUTOMACAO set "ETAPA_AUTOMACAO=completa"

if not exist "%PYTHON_VENV%" (
    >> "%ARQUIVO_LOG%" echo [%date% %time%] ERRO: Python do venv nao encontrado: %PYTHON_VENV%
    exit /b 1
)

if not exist "%SCRIPT_AUTOMACAO%" (
    >> "%ARQUIVO_LOG%" echo [%date% %time%] ERRO: teste_playwright.py nao encontrado: %SCRIPT_AUTOMACAO%
    exit /b 1
)

>> "%ARQUIVO_LOG%" echo.
>> "%ARQUIVO_LOG%" echo [%date% %time%] ===== EXECUCAO DIRETA INICIADA =====

"%PYTHON_VENV%" -u "%SCRIPT_AUTOMACAO%" >> "%ARQUIVO_LOG%" 2>&1
set "CODIGO_SAIDA=%ERRORLEVEL%"

if "%CODIGO_SAIDA%"=="0" (
    >> "%ARQUIVO_LOG%" echo [%date% %time%] Execucao direta concluida com sucesso.
) else (
    >> "%ARQUIVO_LOG%" echo [%date% %time%] Execucao direta encerrada com erro. Codigo: %CODIGO_SAIDA%.
)

exit /b %CODIGO_SAIDA%
