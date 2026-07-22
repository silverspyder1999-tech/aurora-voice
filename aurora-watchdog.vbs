' Launch the Aurora watchdog hidden (no console window), same pattern as
' gpu-watchdog.vbs / ollama-bridge.vbs.
CreateObject("Wscript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\silve\Projects\aurora-voice\aurora-watchdog.ps1""", 0, False
