@echo off
title Atlas - Gemma Local Server

echo Starting Gemma llama.cpp server...
echo.

llama serve ^
-m "C:\Users\prana\Desktop\atlas\llm\google\gemma-4-E2B_q4_0-it.gguf" ^
--mmproj "C:\Users\prana\Desktop\atlas\llm\google\gemma-4-E2B-it-mmproj.gguf" ^
--port 8000 ^
-c 64000 ^
--jinja ^
--reasoning auto
pause