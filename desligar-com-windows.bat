@echo off
rem Tela 2: deixa de abrir sozinho com o Windows (apaga o atalho da pasta Inicializar).
rem Opcional (usado nos testes): passe outra pasta como primeiro argumento.
setlocal
set "DESTINO=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = $env:DESTINO; if (-not $d) { $d = [Environment]::GetFolderPath('Startup') };" ^
  "$a = Join-Path $d 'Tela 2.lnk';" ^
  "if (Test-Path -LiteralPath $a) { Remove-Item -LiteralPath $a; Write-Host 'Pronto: o Tela 2 nao abre mais sozinho.' }" ^
  "else { Write-Host 'O Tela 2 ja nao estava configurado para abrir com o Windows.' }"
if "%~1"=="" pause
