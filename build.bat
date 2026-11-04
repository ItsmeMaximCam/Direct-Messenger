@echo off
rem ------------------------------------------------------------------
rem  build.bat - FOR DEVELOPERS: turns the Python code into an app.
rem
rem  You only need this after changing the code. It needs Python on the
rem  computer that runs it. Everyone else just uses the finished
rem  "release" folder (see README) and never needs Python.
rem
rem  Output:
rem    release\Direct Messenger\     DirectMessenger.exe, its _internal folder,
rem                                  and Install/Uninstall
rem    release\DirectMessenger.zip   the same folder, zipped for sharing
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

rem Build files live on this PC only, NOT in the project folder: the project
rem may be synced by OneDrive, and a Python environment made on one PC doesn't
rem work on another. (Not in AppData either: Microsoft Store Python secretly
rem redirects AppData writes, which breaks the environment.)
set "WORK=%USERPROFILE%\.cache\DirectMessenger-build"
set "VENV=%WORK%\build-env"
set "OUT=%~dp0release\Direct Messenger"

rem --- 1. Find Python (the "py" launcher first, then "python") ---
set "PYTHON="
py -3 -c "import sys" >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
    python -c "import sys" >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
    echo Python was not found on this computer.
    echo.
    echo You don't need Python to USE Direct Messenger: just run
    echo   release\Direct Messenger\Install.bat
    echo.
    echo To BUILD it, install Python 3 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then run this again.
    goto :error
)

rem --- 2. Make (or repair) the build environment ---
rem If it was made by a different/removed Python, it won't start: rebuild it.
if exist "%VENV%\Scripts\python.exe" (
    "%VENV%\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo Build environment is broken, recreating it...
        rmdir /s /q "%VENV%"
    )
)
if not exist "%VENV%\Scripts\python.exe" (
    echo Creating build environment in %VENV% ...
    %PYTHON% -m venv "%VENV%" || goto :error
)

echo Installing requirements...
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error

rem --- 3. Build the app ---
rem One-folder build: DirectMessenger.exe plus an _internal folder with Python
rem and the libraries. It opens instantly, because a single-file .exe has to
rem unpack everything to a temp folder on every launch.
rem The --exclude-module lines leave out Pillow parts we never use
rem (AVIF and WebP images, font drawing, colour profiles), about 5 MB.
echo Building DirectMessenger.exe (this takes a minute)...
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --log-level WARN ^
    --name DirectMessenger --icon "%~dp0app.ico" ^
    --add-data "%~dp0user.png;." --add-data "%~dp0heart.png;." --add-data "%~dp0app.ico;." ^
    --exclude-module PIL._avif --exclude-module PIL._webp ^
    --exclude-module PIL._imagingft --exclude-module PIL._imagingcms ^
    --distpath "%WORK%\dist" --workpath "%WORK%\pyinstaller" --specpath "%WORK%" ^
    "%~dp0main.py" || goto :error

rem --- 4. Replace the old release folder with the new build ---
if exist "%OUT%" rmdir /s /q "%OUT%"
if exist "%OUT%" (
    echo Couldn't replace %OUT%
    echo Close Direct Messenger if it's running from that folder, then try again.
    goto :error
)
rem robocopy's exit codes 0-7 all mean success, 8 and up mean it failed
robocopy "%WORK%\dist\DirectMessenger" "%OUT%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :error

rem --- 5. Add the install scripts and zip it all up ---
copy /y "%~dp0installer\Install.bat" "%OUT%\" >nul || goto :error
copy /y "%~dp0installer\Uninstall.bat" "%OUT%\" >nul || goto :error
rem OneDrive or antivirus often scans a brand-new .exe for a few seconds and
rem locks it meanwhile, so retry the zip a few times before giving up.
set "ZIP=%~dp0release\DirectMessenger.zip"
powershell -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "for ($try = 1; $try -le 10; $try++) {" ^
  "  try { Compress-Archive -Path $env:OUT -DestinationPath $env:ZIP -Force; exit 0 }" ^
  "  catch { $problem = $_; Start-Sleep -Seconds 2 } }" ^
  "Write-Host \"Could not create the zip: $problem\"; exit 1" || goto :error

echo.
echo Done!
echo   App folder: release\Direct Messenger\
echo   For sharing: release\DirectMessenger.zip
echo On any Windows PC, open the folder and double-click Install.bat.
if not defined NO_PAUSE pause
exit /b 0

:error
echo.
echo Build failed. Check the messages above.
if not defined NO_PAUSE pause
exit /b 1
