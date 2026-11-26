@echo off
setlocal
chcp 65001 >nul
title Painel de Automacoes

cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo Python nao encontrado neste computador.
    pause
    exit /b 1
)

%PY% painel_local.py
if errorlevel 1 pause
