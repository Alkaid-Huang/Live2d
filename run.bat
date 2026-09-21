@echo off
rem ---------------------------------------------------------------------------
rem One-click launcher. "One-click start" means this script, not a container --
rem the reason is in docs/adr/0002, the manual checks are in docs/smoke-test.md.
rem
rem KEEP THIS FILE ASCII-ONLY. cmd.exe parses .bat with the OEM code page (GBK on
rem Chinese Windows), so UTF-8 Chinese text here becomes mojibake and a multi-byte
rem character can even swallow the line break -- which silently merges the next
rem command into a comment and breaks everything after it. That is exactly how the
rem first version of this file failed. User-facing messages are English for this
rem reason; the Chinese docs explain what they mean.
rem
rem .gitattributes pins *.bat to CRLF, so a checkout cannot break the line endings.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv
if exist ".env" goto run

echo [!] .env not found: starting with defaults.
echo     Copy .env.example to .env and fill in LLM_API_KEY to actually chat.

:run
rem Only needed when the editable install is missing; harmless otherwise.
set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m main
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" goto failed
exit /b 0

:no_venv
echo [x] .venv not found. Create it first:
echo     python -m venv .venv
echo     .venv\Scripts\pip install -e ".[dev,gui]"
pause
exit /b 1

:failed
echo [x] The program exited with code %EXITCODE%
pause
exit /b %EXITCODE%
