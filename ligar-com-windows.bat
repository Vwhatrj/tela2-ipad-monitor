@echo off
rem Tela 2: abre o servidor sozinho quando voce entra no Windows.
rem Cria um atalho para o iniciar.bat na pasta Inicializar do seu usuario
rem (nao precisa de administrador). Para desfazer: desligar-com-windows.bat
rem Opcional (usado nos testes): passe outra pasta como primeiro argumento.
setlocal
set "DESTINO=%~1"
set "PASTA=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = $env:DESTINO; if (-not $d) { $d = [Environment]::GetFolderPath('Startup') };" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Tela 2.lnk'));" ^
  "$s.TargetPath = Join-Path $env:PASTA 'iniciar.bat';" ^
  "$s.WorkingDirectory = $env:PASTA;" ^
  "$s.WindowStyle = 7;" ^
  "$s.Description = 'Tela 2 - iPad como segundo monitor';" ^
  "$s.Save();" ^
  "Write-Host ('Pronto: o Tela 2 vai abrir minimizado quando voce entrar no Windows.');" ^
  "Write-Host ('Atalho criado em: ' + $d)"
if errorlevel 1 (
  echo Nao foi possivel criar o atalho.
  exit /b 1
)
if "%~1"=="" pause
