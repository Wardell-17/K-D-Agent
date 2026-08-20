@echo off
rem K-D Agent dashboard launcher (double-click)
cd /d D:\agent-project\dashboard
"C:\Python314\python.exe" -m streamlit run "D:\agent-project\dashboard\app.py" --server.headless true
pause
