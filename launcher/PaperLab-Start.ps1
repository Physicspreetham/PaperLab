# Starts PaperLab (API on 8001 + web app on 5173) in the background and opens it.
# Safe to run repeatedly: servers that are already up are left alone.
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
if (-not (Wait-Url $url 90)) {
    Fail "The PaperLab web app did not start.`nSee: $logDir\web.err.log"
}
Start-Process $url
