@echo off
rem Abre Analisis de Acciones con doble clic.
rem La primera vez crea el entorno virtual e instala las dependencias.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto run

echo Primera ejecucion: instalando el programa. Puede tardar unos minutos...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo No se encontro Python. Instalelo desde https://www.python.org/downloads/
    echo y marque la casilla "Add python.exe to PATH".
    pause
    exit /b 1
)
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto failed

:run
start "" ".venv\Scripts\pythonw.exe" -m analisis_acciones
exit /b 0

:failed
echo.
echo La instalacion fallo. Revise los mensajes de arriba.
if exist ".venv" rmdir /s /q ".venv"
pause
exit /b 1
