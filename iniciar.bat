@echo off
title Tela 2
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado.
  echo Instale em python.org e marque a opcao "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Conferindo bibliotecas...
python -m pip install --quiet --disable-pip-version-check mss pillow

python servidor.py %*
pause
