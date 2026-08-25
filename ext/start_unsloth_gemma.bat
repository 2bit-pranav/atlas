@echo off
title Atlas - Gemma Local Server

echo Starting Gemma llama.cpp server...
echo.

llama-server ^
-m "C:\Users\prana\Desktop\atlas\llm\unsloth\gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf" ^
--mmproj "C:\Users\prana\Desktop\atlas\llm\unsloth\gemma-4-BF16.gguf" ^
--port 8000 ^
-c 64000 ^
--jinja ^
--reasoning auto
pause