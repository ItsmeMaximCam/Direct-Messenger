@echo off
rem ------------------------------------------------------------------
rem  Install.bat - installs Direct Messenger for the current user.
rem
rem  No Python and no administrator rights needed. It copies the app to
rem    %LOCALAPPDATA%\Programs\Direct Messenger
rem  adds Desktop and Start Menu shortcuts, and lists the app under
rem  Settings > Apps so it can be uninstalled like any other program.
rem  Running it again updates an existing install.
rem ------------------------------------------------------------------
setlocal
set "APP_DIR=%LOCALAPPDATA%\Programs\Direct Messenger"
set "UNINSTALL_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DirectMessenger"

echo Installing Direct Messenger...
echo.

rem Windows can open a .bat straight from inside a .zip, but then the app
rem files next to it aren't really there.
if not exist "%~dp0DirectMessenger.exe" set "MISSING=1"
if not exist "%~dp0_internal" set "MISSING=1"
if defined MISSING (
    echo Can't find DirectMessenger.exe and its _internal folder next to this file.
    echo If you opened this from inside a .zip, right-click the .zip,
    echo choose "Extract All...", then run Install.bat from the extracted folder.
    goto :failed
)

rem An app that's running can't be replaced, so close it first.
tasklist /fi "imagename eq DirectMessenger.exe" | find /i "DirectMessenger.exe" >nul && (
    echo Closing the running copy of Direct Messenger...
    taskkill /im DirectMessenger.exe /f >nul 2>&1
    rem Wait about 2 seconds so Windows lets go of the old .exe.
    ping -n 3 127.0.0.1 >nul
)

rem Copy the whole app folder. /MIR also removes files an older version left
rem behind, so the install always matches this folder exactly (minus Install.bat).
rem robocopy's exit codes 0-7 all mean success, 8 and up mean it failed.
robocopy "%~dp0." "%APP_DIR%" /MIR /XF Install.bat /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :failed

rem Desktop and Start Menu shortcuts. PowerShell reads APP_DIR from the
rem environment, and asks Windows where the Desktop really is (it may be in OneDrive).
powershell -NoProfile -Command ^
  "$shell = New-Object -ComObject WScript.Shell;" ^
  "foreach ($folder in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {" ^
  "  $link = $shell.CreateShortcut((Join-Path $folder 'Direct Messenger.lnk'));" ^
  "  $link.TargetPath = Join-Path $env:APP_DIR 'DirectMessenger.exe';" ^
  "  $link.WorkingDirectory = $env:APP_DIR;" ^
  "  $link.Save() }" || goto :failed

rem List it in Settings > Apps (current user only, no admin needed).
reg add "%UNINSTALL_KEY%" /v DisplayName /d "Direct Messenger" /f >nul
reg add "%UNINSTALL_KEY%" /v DisplayIcon /d "%APP_DIR%\DirectMessenger.exe" /f >nul
reg add "%UNINSTALL_KEY%" /v InstallLocation /d "%APP_DIR%" /f >nul
reg add "%UNINSTALL_KEY%" /v UninstallString /d "\"%APP_DIR%\Uninstall.bat\"" /f >nul
reg add "%UNINSTALL_KEY%" /v NoModify /t REG_DWORD /d 1 /f >nul
reg add "%UNINSTALL_KEY%" /v NoRepair /t REG_DWORD /d 1 /f >nul

echo Installed to %APP_DIR%
echo Shortcuts added to your Desktop and Start Menu.
echo.
echo First launch: if Windows Firewall asks, allow "Private networks"
echo so others on your Wi-Fi can connect to you.
echo.
if defined QUIET exit /b 0
echo Starting Direct Messenger...
start "" "%APP_DIR%\DirectMessenger.exe"
pause
exit /b 0

:failed
echo.
echo Installation failed.
if not defined QUIET pause
exit /b 1
