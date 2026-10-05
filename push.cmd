@echo off
REM ============================================================================
REM  push.cmd - push the built HAP to ALL connected phones over hdc
REM
REM  NOTE: ASCII-only on purpose. cmd.exe parses .bat/.cmd with the OEM codepage
REM        (GBK on Chinese Windows); non-ASCII bytes here get mangled.
REM
REM  Usage:
REM    push.cmd                     -> push newest HAP to default Download dir
REM    push.cmd <name.hap>          -> save on phone under a different name
REM    push.cmd "" <dest-dir>       -> push to a different directory on phone
REM
REM  It is called automatically at the end of a successful build.cmd run.
REM  Exit code 0 also means "no device connected" (push skipped, build is fine).
REM
REM  Multi-device: hdc may report several targets (e.g. USB + WiFi TCP for the
REM  SAME phone). We loop over every listed target and push to each with -t so
REM  we never silently pick the wrong channel. A failed push to one target does
REM  not abort the others.
REM ============================================================================
setlocal EnableDelayedExpansion

REM ---------- change these for your machine ----------
set "HDC=C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe"
set "PROJECT_PATH=E:\lanshare-harmony\LANShareV5"

REM ---------- destination ----------
REM /storage/media/100/local/files/Docs/Download is the user-visible "Downloads"
REM folder in Files app. Do NOT use MSYS-style paths here: this script runs under
REM cmd.exe, which does no path translation.
set "HAP_DIR=%PROJECT_PATH%\entry\build\default\outputs\default"
set "DEST_DIR=/storage/media/100/local/files/Docs/Download"

REM ---------- derive version from AppScope/app.json5 ----------
REM Put the app version into the HAP file name so every build is easy to tell
REM apart on the phone (e.g. LANShare-5.0.1.hap). Parsed with findstr only,
REM so no JSON tool / jq dependency is needed.
set "APP_JSON=%PROJECT_PATH%\AppScope\app.json5"
set "VER="
for /f "usebackq tokens=2 delims=:" %%V in (`findstr /c:"versionName" "%APP_JSON%" 2^>nul`) do set "VER=%%V"
REM NOTE: must use !VER! (delayed expansion) inside the block. With %VER% cmd
REM expands the whole parenthesised block at parse time, so the three chained
REM replacements would all act on the ORIGINAL value and leave the spaces/quotes in.
if defined VER (
    set "VER=!VER: =!"
    set "VER=!VER:"=!"
    set "VER=!VER:,=!"
)
if not defined VER set "VER=0"
set "DEST_NAME=LANShare-%VER%.hap"

if not "%~1"=="" set "DEST_NAME=%~1"
if not "%~2"=="" set "DEST_DIR=%~2"

if not exist "%HDC%" (
    echo [ERROR] hdc not found: %HDC%
    exit /b 1
)

REM ---------- locate newest HAP ----------
set "HAP="
for %%F in ("%HAP_DIR%\*.hap") do set "HAP=%%~fF"
if not defined HAP (
    echo [ERROR] no HAP found in "%HAP_DIR%"
    echo         run build.cmd first
    exit /b 1
)

REM ---------- device check ----------
set "TARGETS="
for /f "usebackq tokens=*" %%D in (`"%HDC%" list targets 2^>nul`) do (
    if not "%%D"=="" if /i not "%%D"=="[Empty]" (
        set "TARGETS=!TARGETS! "%%D""
    )
)
if not defined TARGETS (
    echo [WARN] no device connected to hdc, skipping push.
    exit /b 0
)

REM ---------- push to every target ----------
for %%T in (%TARGETS%) do (
    set "T=%%~T"
    echo [INFO] device: !T!
    "%HDC%" -t !T! file send "%HAP%" "%DEST_DIR%/%DEST_NAME%"
    set "RC=!ERRORLEVEL!"
    if not "!RC!"=="0" (
        echo [FAIL] push to !T! failed, exit code !RC!
    ) else (
        echo [OK] pushed to !T!
    )
)

REM ---------- verify size (local) ----------
for %%S in ("%HAP%") do set "LOCAL_SIZE=%%~zS"
echo [OK] local HAP size %LOCAL_SIZE% bytes

endlocal & exit /b 0
