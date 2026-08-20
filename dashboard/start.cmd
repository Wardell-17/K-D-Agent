@echo off
rem K-D Agent 指挥中心 · 一键启动（双击即可，不受 PowerShell 执行策略限制）
"C:\Python314\python.exe" -m streamlit run "D:\agent-project\dashboard\app.py" --server.headless true
pause
