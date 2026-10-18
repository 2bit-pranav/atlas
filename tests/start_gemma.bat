@echo off
title Atlas - Gemma Local Server

echo Starting Gemma llama.cpp server...
echo.

set ROOT_DIR=%~dp0..

@REM  llama serve ^
@REM  -m "%ROOT_DIR%\llm\gemma\unsloth_e2b_qat.gguf" ^
@REM  --mmproj "%ROOT_DIR%\llm\gemma\mmproj-F16.gguf" ^
@REM  -ngl 99 ^
@REM  -fa on ^
@REM  -b 2048 ^
@REM  -ub 512 ^
@REM  -c 32768 ^
@REM  -t 6 ^
@REM  --jinja ^
@REM  --reasoning auto ^
@REM  --tools all

llama serve ^
-m "%ROOT_DIR%\llm\gemma\unsloth_e2b_qat.gguf" ^
--mmproj "%ROOT_DIR%\llm\gemma\mmproj-F16.gguf" ^
-ngl 99 ^
-fa on ^
-c 32768 ^
--no-webui ^
--jinja ^
--reasoning auto

pause