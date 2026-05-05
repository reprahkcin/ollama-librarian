function Test-Http($Url) {
  try {
    $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
    return $true
  } catch {
    return $false
  }
}

if (Test-Http 'http://127.0.0.1:11434/api/tags') {
  Write-Host 'Ollama: running'
} else {
  Write-Host 'Ollama: stopped'
}

if (Test-Http 'http://127.0.0.1:8088/api/pdf/status') {
  Write-Host 'Web UI: running (http://127.0.0.1:8088)'
} else {
  Write-Host 'Web UI: stopped'
}
