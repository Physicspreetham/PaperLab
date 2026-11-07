# Creates a "PaperLab" icon on the Desktop that starts the app with one double-click.
$launcher = $PSScriptRoot
$desktop  = [Environment]::GetFolderPath('Desktop')
$ws       = New-Object -ComObject WScript.Shell
$lnk      = $ws.CreateShortcut((Join-Path $desktop 'PaperLab.lnk'))
$lnk.TargetPath       = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$lnk.Arguments        = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $launcher 'PaperLab-Start.ps1') + '"'
$lnk.WorkingDirectory = Split-Path -Parent $launcher
$lnk.IconLocation     = (Join-Path $launcher 'paperlab.ico') + ',0'
$lnk.Description      = 'Start PaperLab and open it in your browser'
$lnk.WindowStyle      = 7   # minimised: no console flash
$lnk.Save()
Write-Output ('Created ' + (Join-Path $desktop 'PaperLab.lnk'))
