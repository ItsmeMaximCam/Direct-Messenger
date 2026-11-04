@echo off
rem ------------------------------------------------------------------
rem  Uninstall.bat - removes Direct Messenger installed by Install.bat.
rem  Also runs from Settings > Apps > Direct Messenger > Uninstall.
rem ------------------------------------------------------------------
setlocal
set "APP_DIR=%LOCALAPPDATA%\Programs\Direct Messenger"
set "UNINSTALL_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DirectMessenger"

if not defined QUIET (
    choice /m "Remove Direct Messenger from this computer"
    if errorlevel 2 exit /b 0
)

rem Close the app if it's running, and give Windows a moment to let go of the .exe.
taskkill /im DirectMessenger.exe /f >nul 2>&1 && ping -n 3 127.0.0.1 >nul

powershell -NoProfile -Command ^
  "foreach ($folder in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {" ^
  "  Remove-Item (Join-Path $folder 'Direct Messenger.lnk') -ErrorAction SilentlyContinue }"
reg delete "%UNINSTALL_KEY%" /f >nul 2>&1

echo Direct Messenger has been removed.
echo (Your saved name and colour in %APPDATA%\DirectMessenger were kept.)
if not defined QUIET pause

rem Delete the app folder last. This script may be inside that folder, and
rem cmd reads scripts line by line, so "(goto)" ends the script first and the
rem rest of this line still runs. If a file is still in use, wait and try once more.
(goto) 2>nul & rmdir /s /q "%APP_DIR%" 2>nul & if exist "%APP_DIR%" (ping -n 3 127.0.0.1 >nul & rmdir /s /q "%APP_DIR%")
