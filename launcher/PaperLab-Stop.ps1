# Stops the background PaperLab servers started by PaperLab-Start.ps1.
param([switch]$Quiet)
$root = Split-Path -Parent $PSScriptRoot
$rootEsc = [regex]::Escape($root)

# API: the venv python running uvicorn (and its launcher parent).
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'uvicorn backend\.main' -and $_.CommandLine -notmatch 'PaperLab-Stop' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# Web app: node/npm processes started from this project's frontend folder.
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match '^(node|npm)' -and $_.CommandLine -match $rootEsc -and $_.CommandLine -match 'vite|npm' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (-not $Quiet) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('PaperLab servers stopped.', 'PaperLab', 'OK', 'Information') | Out-Null
}
