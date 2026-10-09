@echo off
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-essentials_build\bin;%PATH%"
echo Starting Manhwa Video Studio at http://127.0.0.1:8000 ...
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
