@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

echo ========================================
echo  Arc Slicer - PyInstaller Build
echo ========================================
echo.

if not exist "%ROOT%ffmpeg.exe" (
    echo [ERROR] ffmpeg.exe not found.
    echo        Download from https://ffmpeg.org/download.html
    echo        and place ffmpeg.exe in this folder before building.
    echo.
    exit /b 1
)

if not exist "%PYTHON%" (
    echo [ERROR] Repository Python not found: %PYTHON%
    echo        Create the repository .venv before building.
    exit /b 1
)

echo Checking dependencies...
"%PYTHON%" -c "import PyQt6, PyInstaller" > nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyQt6 and PyInstaller must be installed in the repository .venv.
    echo        This build entry does not install or upgrade dependencies.
    exit /b 1
)

echo.
echo Running PyInstaller with the repository .venv...
pushd "%ROOT%"
"%PYTHON%" -m PyInstaller "%ROOT%build.spec" --clean --noconfirm
set "BUILD_EXIT=%ERRORLEVEL%"
popd

if not "%BUILD_EXIT%"=="0" (
    echo.
    echo [FAILED] Build failed. See output above.
    exit /b %BUILD_EXIT%
)

echo.
echo ========================================
echo  Done! Output: dist\ArcSlicer.exe
echo ========================================
echo.
exit /b 0
