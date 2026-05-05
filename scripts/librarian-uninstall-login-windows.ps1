$TaskName = 'OllamaLibrarianStartup'
schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
Write-Host "Removed startup task (if present): $TaskName"
