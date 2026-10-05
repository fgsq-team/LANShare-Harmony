@echo off
REM ============================================================================
REM  LANShare HarmonyOS 7 (API 26) build script
REM
REM  NOTE: this file is intentionally ASCII-only.
REM        cmd.exe parses .bat/.cmd using the OEM codepage (GBK on Chinese
REM        Windows), while editors usually save UTF-8. Non-ASCII characters in
REM        a .cmd file get mangled and break command parsing. Keep it ASCII.
REM
REM  Usage:
REM    build.cmd                  -> assemble debug HAP
REM    build.cmd clean            -> clean
REM    build.cmd assembleHap --mode module -p product=default
REM
REM  Why this script exists - hvigor needs three things:
REM    1. project path must be pure ASCII. hvigor rejects non-ASCII paths with
REM       00306003 "Invalid project path". That is why this project lives in
REM       E:\lanshare-harmony\ instead of E:\lanshare<chinese>\.
REM    2. DEVECO_SDK_HOME  -> points at the HarmonyOS SDK
REM    3. JAVA_HOME        -> packaging a HAP runs app_packing_tool.jar from
REM                           the SDK, so java must be on PATH. Missing JDK
REM                           shows up as "spawn java ENOENT" (00308018).
REM ============================================================================
setlocal

REM ---------- change these three lines for your machine ----------
set "CL_TOOLS=D:\Downloads\commandline-tools-windows-x64-26.0.0.851\command-line-tools"
set "JAVA_HOME=C:\Users\vivi\.workbuddy\binaries\java\jdk-21.0.2"
set "PROJECT_PATH=E:\lanshare-harmony\LANShareV5"

REM ---------- environment ----------
set "DEVECO_NODE_HOME=%CL_TOOLS%\tool\node"
set "DEVECO_SDK_HOME=%CL_TOOLS%\sdk"
set "PATH=%JAVA_HOME%\bin;%DEVECO_NODE_HOME%;%PATH%"

if not exist "%CL_TOOLS%\bin\hvigorw.bat" (
    echo [ERROR] command-line-tools not found: %CL_TOOLS%
    exit /b 1
)
if not exist "%JAVA_HOME%\bin\java.exe" (
    echo [ERROR] JDK not found: %JAVA_HOME%
    echo         packaging a HAP requires java, please fix JAVA_HOME
    exit /b 1
)
if not exist "%PROJECT_PATH%\build-profile.json5" (
    echo [ERROR] project not found: %PROJECT_PATH%
    exit /b 1
)

cd /d "%PROJECT_PATH%"

REM ---------- run ----------
if "%~1"=="" (
    echo [INFO] no task given, defaulting to assembleHap
    call "%CL_TOOLS%\bin\hvigorw.bat" assembleHap
) else (
    call "%CL_TOOLS%\bin\hvigorw.bat" %*
)

set BUILD_RESULT=%ERRORLEVEL%
echo.
if "%BUILD_RESULT%"=="0" (
    echo [OK] build succeeded. HAP output:
    dir /b /s "%PROJECT_PATH%\entry\build\default\outputs\*.hap" 2>nul
    echo.
    echo [INFO] pushing HAP to phone ...
    call "%~dp0push.cmd"
) else (
    echo [FAIL] build failed, exit code %BUILD_RESULT%
    echo        logs: %PROJECT_PATH%\.hvigor\outputs\build-logs\
)
endlocal & exit /b %BUILD_RESULT%
