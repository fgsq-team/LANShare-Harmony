@echo off
REM ============================================================================
REM  LANShare HarmonyOS (API 26) build script
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
REM       00306003 "Invalid project path". That is why this project must not
REM       live under a directory whose name contains non-ASCII characters.
REM    2. DEVECO_SDK_HOME  -> points at the HarmonyOS SDK
REM    3. JAVA_HOME        -> packaging a HAP runs app_packing_tool.jar from
REM                           the SDK, so java must be on PATH. Missing JDK
REM                           shows up as "spawn java ENOENT" (00308018).
REM ============================================================================
setlocal

REM ---------- change these two lines for your machine ----------
REM CL_TOOLS  : the "commandline-tools" folder of your HarmonyOS SDK.
REM JAVA_HOME : any JDK 17/21 works; DevEco Studio's bundled jbr is fine.
REM Both are read from the environment first, so a clean fork needs no edit;
REM set them permanently, or just hardcode the two lines below.
set "CL_TOOLS=%DEVECO_CLI_TOOLS%"
set "JAVA_HOME=%DEVECO_JDK_HOME%"

REM Project root defaults to the folder this script lives in.
set "PROJECT_PATH=%~dp0"
if "%PROJECT_PATH:~-1%"=="\" set "PROJECT_PATH=%PROJECT_PATH:~0,-1%"

REM ---------- environment ----------
set "DEVECO_NODE_HOME=%CL_TOOLS%\tool\node"
set "DEVECO_SDK_HOME=%CL_TOOLS%\sdk"
set "PATH=%JAVA_HOME%\bin;%DEVECO_NODE_HOME%;%PATH%"

if "%CL_TOOLS%"=="" (
    echo [ERROR] CL_TOOLS is not set.
    echo         set the DEVECO_CLI_TOOLS environment variable to your
    echo         commandline-tools folder, or hardcode it in this script.
    exit /b 1
)
if not exist "%CL_TOOLS%\bin\hvigorw.bat" (
    echo [ERROR] command-line-tools not found: %CL_TOOLS%
    exit /b 1
)
if "%JAVA_HOME%"=="" (
    echo [ERROR] JAVA_HOME is not set.
    echo         set the DEVECO_JDK_HOME environment variable to your JDK,
    echo         or hardcode it in this script.
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
) else (
    echo [FAIL] build failed, exit code %BUILD_RESULT%
    echo        logs: %PROJECT_PATH%\.hvigor\outputs\build-logs\
)
endlocal & exit /b %BUILD_RESULT%
