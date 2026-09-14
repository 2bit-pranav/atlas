@echo off
title Atlas - Gemma Local Server

echo Starting Gemma llama.cpp server...
echo.

llama-server ^
-m "C:\Users\prana\Desktop\atlas\llm\google\gemma-4-E2B_q4_0-it.gguf" ^
--mmproj "C:\Users\prana\Desktop\atlas\llm\google\gemma-4-E2B-it-mmproj.gguf" ^
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