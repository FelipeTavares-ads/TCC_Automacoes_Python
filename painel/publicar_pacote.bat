@echo off
rem Copia este painel e o teste_playwright.py para o pacote do OneDrive
rem (automacao\instalador_painel), de onde o instalar.bat leva para o
rem computador de outra pessoa. Rode de novo sempre que quiser mandar uma
rem versao nova do painel. Nao leva logs, fechamento nem logins.
setlocal
chcp 65001 >nul
set "PACOTE=%OneDriveCommercial%\dashboards\Teste Python\automacao\instalador_painel"
if not exist "%OneDriveCommercial%\dashboards\Teste Python\automacao\caminhos.py" (
    echo Nao achei a pasta da automacao no OneDrive.
    pause
    exit /b 1
)
robocopy "%~dp0." "%PACOTE%\painel" /E /XD logs __pycache__ /XF fechamento.json publicar_pacote.bat *.pyc /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
copy /y "%~dp0..\teste_playwright.py" "%PACOTE%\teste_playwright.py" >nul
echo.
echo Pacote atualizado em:
echo   %PACOTE%
echo Quem usa o painel em outro computador: rodar o instalar.bat de novo.
timeout /t 8 >nul
