@echo off
rem Avvia tk-ftp dalla cartella (nessuna installazione). Siti e impostazioni stanno nella cartella "Dati".
start "" "%~dp0app\python\pythonw.exe" "%~dp0app\run.py" %*
