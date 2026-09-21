@echo off
rem 一键启动。双击即可。docs/product.md 里说的"一键启动"就是这个脚本，不是容器，
rem 理由见 docs/adr/0002。
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [x] 没找到 .venv。请先按 README 建虚拟环境：
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -e ".[dev,gui]"
    pause
    exit /b 1
)

if not exist ".env" (
    echo [!] 没找到 .env，将按默认值启动。
    echo     要真正对话，请先复制 .env.example 为 .env 并填入 LLM_API_KEY。
)

rem 装过 editable 包就不需要这句，但没装过时也能跑起来。
set "PYTHONPATH=%CD%\src"

".venv\Scripts\python.exe" -m main
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo [x] 程序退出，代码 %EXITCODE%
    pause
)
exit /b %EXITCODE%
