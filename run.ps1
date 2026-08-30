# Запуск бота локально. ПКМ → «Выполнить с помощью PowerShell»
# или в терминале:  ./run.ps1
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m bot.main
