# Starts PaperLab (API on 8001 + web app on 5173) in the background and opens it.
# Keeps running servers and refreshes an older PaperLab API when needed.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

$root     = Split-Path -Parent $PSScriptRoot
$python   = Join-Path $root '.venv\Scripts\python.exe'
$frontend = Join-Path $root 'frontend'
$logDir   = Join-Path $root 'launcher\logs'
$apiPort  = 8001
$webPort  = 5173
$url      = "http://127.0.0.1:$webPort/"

function Fail($msg) {
    [System.Windows.Forms.MessageBox]::Show($msg, 'PaperLab', 'OK', 'Error') | Out-Null
    exit 1
}

function Test-Port($port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $port); return $true } catch { return $false } finally { $c.Close() }
}

function Wait-Url($u, $seconds) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
        try { if ((Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { return $true } } catch {}
        Start-Sleep -Milliseconds 700
    }
    return $false
}

if (-not (Test-Path $python))                          { Fail "Python environment not found:`n$python`n`nRun the setup steps in README.md first." }
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) { Fail "Frontend packages are missing.`n`nRun 'npm install' in:`n$frontend" }
New-Item -ItemType Directory -Force $logDir | Out-Null

if (Test-Port $apiPort) {
    $schema = Invoke-RestMethod "http://127.0.0.1:$apiPort/openapi.json" -TimeoutSec 5
    if ($schema.info.title -ne 'PaperLab API' -or -not $schema.paths.'/api/ejee/questions/search'.post) {
        Fail 'Port 8001 is occupied by a different service.'
    }
    if (-not $schema.components.schemas.SearchBody.properties.node_ids -or
        -not $schema.components.schemas.ReviewCropBody.properties.confirm_edges -or
        -not $schema.paths.'/api/ejee/collections/{paper_id}/questions/{number}/figures' -or
        -not $schema.paths.'/api/ejee/library/papers/order' -or
        -not $schema.paths.'/api/ejee/library/papers/{paper_id}/order') {
        $jobsRoot = $env:PAPERLAB_EJEE_JOBS_ROOT
        if (-not $jobsRoot) { $jobsRoot = Join-Path $root 'importer_EJEE\runs\web' }
        $activeImport = Get-ChildItem -LiteralPath $jobsRoot -Filter state.json -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } |
            Where-Object { $_.status -in 'running', 'queued' } | Select-Object -First 1
        if ($activeImport) { Fail 'An EJEE import is active. Wait for it to finish before reopening PaperLab.' }

        $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $apiPort -State Listen |
            Select-Object -First 1
        $apiProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        # The Windows venv launcher may hand the socket to the base Python.
        # Identify the listener by its command and the PaperLab OpenAPI above.
        if (-not $apiProcess -or $apiProcess.Name -notmatch '^python(?:[\d.]*)\.exe$' -or
            $apiProcess.CommandLine -notmatch '(?:^|\s)"?uvicorn"?\s+"?backend\.main:app"?(?:\s|$)') {
            Fail 'The API port is occupied by a process this launcher could not identify as PaperLab.'
        }
        Stop-Process -Id $listener.OwningProcess
        $deadline = (Get-Date).AddSeconds(10)
        while ((Test-Port $apiPort) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
        if (Test-Port $apiPort) { Fail 'The old PaperLab API did not stop.' }
    }
}

if (-not (Test-Port $apiPort)) {
    Start-Process -FilePath $python -WorkingDirectory $root -WindowStyle Hidden `
        -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--port', $apiPort `
        -RedirectStandardOutput (Join-Path $logDir 'api.out.log') `
        -RedirectStandardError  (Join-Path $logDir 'api.err.log')
}
if (-not (Test-Port $webPort)) {
    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npm) { Fail 'Node.js (npm) was not found. Install Node 18+ from nodejs.org.' }
    Start-Process -FilePath $npm -WorkingDirectory $frontend -WindowStyle Hidden `
        -ArgumentList 'run', 'dev', '--', '--port', $webPort, '--host', '127.0.0.1' `
        -RedirectStandardOutput (Join-Path $logDir 'web.out.log') `
        -RedirectStandardError  (Join-Path $logDir 'web.err.log')
}

if (-not (Wait-Url "http://127.0.0.1:$apiPort/api/papers" 60)) {
    Fail "The PaperLab API did not start.`nSee: $logDir\api.err.log"
}
$schema = Invoke-RestMethod "http://127.0.0.1:$apiPort/openapi.json" -TimeoutSec 5
if (-not $schema.components.schemas.SearchBody.properties.node_ids) {
    Fail 'The running PaperLab API does not support EJEE multiple subtopic selection.'
}
if (-not $schema.components.schemas.ReviewCropBody.properties.confirm_edges) {
    Fail 'The running PaperLab API does not support EJEE crop confirmation.'
}
if (-not (Wait-Url $url 90)) {
    Fail "The PaperLab web app did not start.`nSee: $logDir\web.err.log"
}
Start-Process $url
