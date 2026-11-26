@echo off
setlocal
chcp 65001 >nul

title Limpeza de Cache - Automacao Extranet

cd /d "%~dp0"

echo ==========================================
echo LIMPEZA DE CACHE DOS PERFIS DO CHROME
echo ==========================================
echo.
echo Isto remove apenas cache/arquivos temporarios.
echo Login, cookies e sessao salva NAO sao apagados.
echo.

for /d %%P in (perfil_chrome_*) do call :limpar_perfil "%%P"

echo ==========================================
echo LIMPEZA CONCLUIDA.
echo ==========================================
echo.

pause
exit /b 0


:limpar_perfil
set "PERFIL=%~1"

echo --- Perfil: %PERFIL% ---

call :remover "%PERFIL%\Default\Cache"
call :remover "%PERFIL%\Default\Code Cache"
call :remover "%PERFIL%\Default\GPUCache"
call :remover "%PERFIL%\Default\DawnWebGPUCache"
call :remover "%PERFIL%\Default\DawnGraphiteCache"
call :remover "%PERFIL%\Default\GrShaderCache"
call :remover "%PERFIL%\Default\ShaderCache"
call :remover "%PERFIL%\Default\GPUPersistentCache"
call :remover "%PERFIL%\optimization_guide_model_store"
call :remover "%PERFIL%\WasmTtsEngine"
call :remover "%PERFIL%\OnDeviceHeadSuggestModel"
call :remover "%PERFIL%\Safe Browsing"
call :remover "%PERFIL%\hyphen-data"
call :remover "%PERFIL%\ZxcvbnData"
call :remover "%PERFIL%\PKIMetadata"
call :remover "%PERFIL%\OptimizationHints"
call :remover "%PERFIL%\CertificateRevocation"
call :remover "%PERFIL%\ActorSafetyLists"
call :remover "%PERFIL%\Crowd Deny"
call :remover "%PERFIL%\Subresource Filter"
call :remover "%PERFIL%\component_crx_cache"
call :remover "%PERFIL%\GrShaderCache"
call :remover "%PERFIL%\ShaderCache"

echo.
exit /b 0


:remover
if exist "%~1" (
    echo   Removendo %~1
    rd /s /q "%~1" 2>nul
)
exit /b 0
