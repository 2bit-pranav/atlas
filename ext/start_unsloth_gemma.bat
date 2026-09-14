@echo off
title Atlas - Gemma Local Server

echo Starting Gemma llama.cpp server...
echo.

llama-server ^
-m "C:\Users\prana\Desktop\atlas\llm\unsloth\gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf" ^
--mmproj "C:\Users\prana\Desktop\atlas\llm\unsloth\gemma-4-BF16.gguf" ^
--port 8000 ^
-ngl 99 ^
-fa on ^
-b 2048 ^
-ub 512 ^
-c 32768 ^
-t 6 ^
--jinja ^
--reasoning auto ^
--tools all
pause