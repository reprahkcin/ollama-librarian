param(
  [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot),
  [string]$LibraryDir = "$HOME\Documents\LLM Library",
  [string]$StateDir = "$env:APPDATA\ollama-librarian"
)

$ErrorActionPreference = 'Stop'
$RunDir = Join-Path $StateDir 'run'
$LogDir = Join-Path $StateDir 'logs'
$OllamaPidFile = Join-Path $RunDir 'ollama.pid'
$WebPidFile = Join-Path $RunDir 'web.pid'
$PythonBin = Join-Path $RepoDir '.venv\Scripts\python.exe'
$OcrOnSync = if ($env:OLLAMA_WEB_PDF_OCR_ON_SYNC) { $env:OLLAMA_WEB_PDF_OCR_ON_SYNC } else { '1' }
$OcrLang = if ($env:OLLAMA_WEB_PDF_OCR_LANG) { $env:OLLAMA_WEB_PDF_OCR_LANG } else { 'eng' }
$OcrJobs = if ($env:OLLAMA_WEB_PDF_OCR_JOBS) { $env:OLLAMA_WEB_PDF_OCR_JOBS } else { '1' }
$OcrTimeout = if ($env:OLLAMA_WEB_PDF_OCR_TIMEOUT) { $env:OLLAMA_WEB_PDF_OCR_TIMEOUT } else { '3600' }
$EmbedNumThread = if ($env:OLLAMA_WEB_PDF_EMBED_NUM_THREAD) { $env:OLLAMA_WEB_PDF_EMBED_NUM_THREAD } else { '1' }
$EmbedDelayMs = if ($env:OLLAMA_WEB_PDF_EMBED_DELAY_MS) { $env:OLLAMA_WEB_PDF_EMBED_DELAY_MS } else { '200' }
$DocCooldownSeconds = if ($env:OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS) { $env:OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS } else { '10' }
$DynamicThrottle = if ($env:OLLAMA_WEB_PDF_DYNAMIC_THROTTLE) { $env:OLLAMA_WEB_PDF_DYNAMIC_THROTTLE } else { '1' }
$DynamicTargetEmbedMs = if ($env:OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS) { $env:OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS } else { '1400' }
$DynamicMaxDelayMs = if ($env:OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS) { $env:OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS } else { '2000' }
$DynamicDelayStepMs = if ($env:OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS) { $env:OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS } else { '50' }
$DynamicMinThreads = if ($env:OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS) { $env:OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS } else { '1' }
$DynamicMaxThreads = if ($env:OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS) { $env:OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS } else { '2' }
$GenerateTimeout = if ($env:OLLAMA_WEB_GENERATE_TIMEOUT) { $env:OLLAMA_WEB_GENERATE_TIMEOUT } else { '120' }
$ModelFailureThreshold = if ($env:OLLAMA_WEB_MODEL_FAILURE_THRESHOLD) { $env:OLLAMA_WEB_MODEL_FAILURE_THRESHOLD } else { '1' }
$ModelFailureCooldownSeconds = if ($env:OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS) { $env:OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS } else { '300' }
$SafetyBrakeEnabled = if ($env:OLLAMA_WEB_SAFETY_BRAKE_ENABLED) { $env:OLLAMA_WEB_SAFETY_BRAKE_ENABLED } else { '1' }
$SafetyBrakeCooldownSeconds = if ($env:OLLAMA_WEB_SAFETY_BRAKE_COOLDOWN_SECONDS) { $env:OLLAMA_WEB_SAFETY_BRAKE_COOLDOWN_SECONDS } else { '300' }
$SafetyBrakeCpuPct = if ($env:OLLAMA_WEB_SAFETY_BRAKE_CPU_PCT) { $env:OLLAMA_WEB_SAFETY_BRAKE_CPU_PCT } else { '88' }
$SafetyBrakeGpuUtilPct = if ($env:OLLAMA_WEB_SAFETY_BRAKE_GPU_UTIL_PCT) { $env:OLLAMA_WEB_SAFETY_BRAKE_GPU_UTIL_PCT } else { '88' }
$SafetyBrakeGpuMemPct = if ($env:OLLAMA_WEB_SAFETY_BRAKE_GPU_MEM_PCT) { $env:OLLAMA_WEB_SAFETY_BRAKE_GPU_MEM_PCT } else { '88' }
$SafetyBrakeGpuTempC = if ($env:OLLAMA_WEB_SAFETY_BRAKE_GPU_TEMP_C) { $env:OLLAMA_WEB_SAFETY_BRAKE_GPU_TEMP_C } else { '78' }
$SoftThrottleEnabled = if ($env:OLLAMA_WEB_SOFT_THROTTLE_ENABLED) { $env:OLLAMA_WEB_SOFT_THROTTLE_ENABLED } else { '1' }
$SoftThrottleStartRatioPct = if ($env:OLLAMA_WEB_SOFT_THROTTLE_START_RATIO_PCT) { $env:OLLAMA_WEB_SOFT_THROTTLE_START_RATIO_PCT } else { '28' }
$SoftThrottleMaxDelayMs = if ($env:OLLAMA_WEB_SOFT_THROTTLE_MAX_DELAY_MS) { $env:OLLAMA_WEB_SOFT_THROTTLE_MAX_DELAY_MS } else { '22000' }
$SoftThrottleMinGapMs = if ($env:OLLAMA_WEB_SOFT_THROTTLE_MIN_GAP_MS) { $env:OLLAMA_WEB_SOFT_THROTTLE_MIN_GAP_MS } else { '40000' }
$HeavySerialEnabled = if ($env:OLLAMA_WEB_HEAVY_SERIAL_ENABLED) { $env:OLLAMA_WEB_HEAVY_SERIAL_ENABLED } else { '1' }
$HeavySerialQueueTimeoutSeconds = if ($env:OLLAMA_WEB_HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS) { $env:OLLAMA_WEB_HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS } else { '30' }
$SafeGenerateProfileEnabled = if ($env:OLLAMA_WEB_SAFE_GENERATE_PROFILE_ENABLED) { $env:OLLAMA_WEB_SAFE_GENERATE_PROFILE_ENABLED } else { '1' }
$SafeGenerateNumThread = if ($env:OLLAMA_WEB_SAFE_GENERATE_NUM_THREAD) { $env:OLLAMA_WEB_SAFE_GENERATE_NUM_THREAD } else { '1' }
$SafeGenerateNumBatch = if ($env:OLLAMA_WEB_SAFE_GENERATE_NUM_BATCH) { $env:OLLAMA_WEB_SAFE_GENERATE_NUM_BATCH } else { '10' }
$SafeGenerateNumPredictCap = if ($env:OLLAMA_WEB_SAFE_GENERATE_NUM_PREDICT_CAP) { $env:OLLAMA_WEB_SAFE_GENERATE_NUM_PREDICT_CAP } else { '640' }
$AnswerFallbackModels = if ($env:OLLAMA_WEB_PDF_ANSWER_FALLBACK_MODELS) { $env:OLLAMA_WEB_PDF_ANSWER_FALLBACK_MODELS } else { 'qwen2.5:7b,qwen2.5:3b,llama3.2:3b,llama3.2:1b' }

New-Item -ItemType Directory -Path $LibraryDir -Force | Out-Null
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

if (!(Test-Path $PythonBin)) {
  Write-Error "Missing Python venv at $PythonBin. Run Setup Guides/WINDOWS-SETUP.md first."
}

function Test-Http($Url) {
  try {
    $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
    return $true
  } catch {
    return $false
  }
}

if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
  Write-Host 'Starting Ollama...'
  $env:OLLAMA_HOST = '127.0.0.1:11434'
  $ollamaProc = Start-Process -FilePath 'ollama' -ArgumentList @('serve') -WindowStyle Hidden -PassThru
  $ollamaProc.Id | Out-File -FilePath $OllamaPidFile -Encoding ascii -Force
}

for ($i=0; $i -lt 30; $i++) {
  if (Test-Http 'http://127.0.0.1:11434/api/tags') { break }
  Start-Sleep -Seconds 1
}
if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
  Write-Error 'Ollama did not become ready.'
}

if (-not (Test-Http 'http://127.0.0.1:8088/api/pdf/status')) {
  Write-Host 'Starting web app...'
  Write-Host "Safety mode: timeout=$GenerateTimeout s, threshold=$ModelFailureThreshold, cooldown=$ModelFailureCooldownSeconds s"
  $webScript = Join-Path $RepoDir 'scripts\ollama-web-chat.py'
  $env:OLLAMA_WEB_HOST = '127.0.0.1'
  $env:OLLAMA_WEB_PORT = '8088'
  $env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
  $env:OLLAMA_WEB_PDF_SOURCE = $LibraryDir
  $env:OLLAMA_WEB_PDF_INDEX_DB = Join-Path $StateDir 'pdf-rag.sqlite'
  $env:OLLAMA_WEB_HISTORY_PATH = Join-Path $StateDir 'ollama-web-chat-history.json'
  $env:OLLAMA_WEB_STASH_PATH = Join-Path $StateDir 'ollama-response-stash.json'
  $env:OLLAMA_WEB_PDF_OCR_ON_SYNC = $OcrOnSync
  $env:OLLAMA_WEB_PDF_OCR_LANG = $OcrLang
  $env:OLLAMA_WEB_PDF_OCR_JOBS = $OcrJobs
  $env:OLLAMA_WEB_PDF_OCR_TIMEOUT = $OcrTimeout
  $env:OLLAMA_WEB_PDF_EMBED_NUM_THREAD = $EmbedNumThread
  $env:OLLAMA_WEB_PDF_EMBED_DELAY_MS = $EmbedDelayMs
  $env:OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS = $DocCooldownSeconds
  $env:OLLAMA_WEB_PDF_DYNAMIC_THROTTLE = $DynamicThrottle
  $env:OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS = $DynamicTargetEmbedMs
  $env:OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS = $DynamicMaxDelayMs
  $env:OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS = $DynamicDelayStepMs
  $env:OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS = $DynamicMinThreads
  $env:OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS = $DynamicMaxThreads
  $env:OLLAMA_WEB_GENERATE_TIMEOUT = $GenerateTimeout
  $env:OLLAMA_WEB_MODEL_FAILURE_THRESHOLD = $ModelFailureThreshold
  $env:OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS = $ModelFailureCooldownSeconds
  $env:OLLAMA_WEB_SAFETY_BRAKE_ENABLED = $SafetyBrakeEnabled
  $env:OLLAMA_WEB_SAFETY_BRAKE_COOLDOWN_SECONDS = $SafetyBrakeCooldownSeconds
  $env:OLLAMA_WEB_SAFETY_BRAKE_CPU_PCT = $SafetyBrakeCpuPct
  $env:OLLAMA_WEB_SAFETY_BRAKE_GPU_UTIL_PCT = $SafetyBrakeGpuUtilPct
  $env:OLLAMA_WEB_SAFETY_BRAKE_GPU_MEM_PCT = $SafetyBrakeGpuMemPct
  $env:OLLAMA_WEB_SAFETY_BRAKE_GPU_TEMP_C = $SafetyBrakeGpuTempC
  $env:OLLAMA_WEB_SOFT_THROTTLE_ENABLED = $SoftThrottleEnabled
  $env:OLLAMA_WEB_SOFT_THROTTLE_START_RATIO_PCT = $SoftThrottleStartRatioPct
  $env:OLLAMA_WEB_SOFT_THROTTLE_MAX_DELAY_MS = $SoftThrottleMaxDelayMs
  $env:OLLAMA_WEB_SOFT_THROTTLE_MIN_GAP_MS = $SoftThrottleMinGapMs
  $env:OLLAMA_WEB_HEAVY_SERIAL_ENABLED = $HeavySerialEnabled
  $env:OLLAMA_WEB_HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS = $HeavySerialQueueTimeoutSeconds
  $env:OLLAMA_WEB_SAFE_GENERATE_PROFILE_ENABLED = $SafeGenerateProfileEnabled
  $env:OLLAMA_WEB_SAFE_GENERATE_NUM_THREAD = $SafeGenerateNumThread
  $env:OLLAMA_WEB_SAFE_GENERATE_NUM_BATCH = $SafeGenerateNumBatch
  $env:OLLAMA_WEB_SAFE_GENERATE_NUM_PREDICT_CAP = $SafeGenerateNumPredictCap
  $env:OLLAMA_WEB_PDF_ANSWER_FALLBACK_MODELS = $AnswerFallbackModels

  $webProc = Start-Process -FilePath $PythonBin -ArgumentList @($webScript) -WindowStyle Hidden -PassThru
  $webProc.Id | Out-File -FilePath $WebPidFile -Encoding ascii -Force
}

for ($i=0; $i -lt 30; $i++) {
  if (Test-Http 'http://127.0.0.1:8088/api/pdf/status') { break }
  Start-Sleep -Seconds 1
}

if (Test-Http 'http://127.0.0.1:8088/api/pdf/status') {
  Write-Host 'Librarian is running at http://127.0.0.1:8088'
} else {
  Write-Error 'Web app did not become ready.'
}
