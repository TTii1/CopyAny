@echo off
rem CopyAny Windows 一键构建: 生成 dist\CopyAny.exe (单文件) 与 dist\CopyAny\ (目录版)
setlocal
cd /d "%~dp0\.."

if not exist .venv (
    python -m venv .venv || (echo [错误] 未找到 Python, 请先安装 Python 3.11+ && exit /b 1)
)
call .venv\Scripts\activate.bat

pip install -q -r requirements.txt pyinstaller pillow || exit /b 1

python build\make_icon.py || exit /b 1

echo == 运行自检 ==
python run.py --selftest || (echo [错误] 自检未通过, 取消打包 && exit /b 1)

echo == 打包单文件版 ==
pyinstaller --noconfirm --clean --windowed --onefile --name CopyAny --icon build\icon.ico --workpath build\work-onefile run.py || exit /b 1

echo == 打包目录版(启动更快) ==
pyinstaller --noconfirm --clean --windowed --onedir --name CopyAny --icon build\icon.ico --workpath build\work-onedir run.py || exit /b 1

rmdir /s /q build\work-onefile build\work-onedir 2>nul & del /q CopyAny.spec 2>nul

echo.
echo 构建完成:
echo   单文件: dist\CopyAny.exe
echo   目录版: dist\CopyAny\CopyAny.exe
endlocal
