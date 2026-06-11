@echo off
set "CURRENT_DIR=%~dp0"
echo ***** Current directory: %CURRENT_DIR% *****

set FFMPEG_BINARY=%CURRENT_DIR%lib\ffmpeg\ffmpeg-7.0-essentials_build\ffmpeg.exe
echo ***** FFmpeg file: %FFMPEG_BINARY% *****
set IMAGEMAGICK_BINARY=%CURRENT_DIR%lib\imagemagic\ImageMagick-7.1.1-29-portable-Q16-x64\magick.exe
echo ***** ImageMagick file: %IMAGEMAGICK_BINARY% *****

%CURRENT_DIR%lib\python\python.exe  %CURRENT_DIR%MoneyPrinterTurbo\main.py