$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    $basePython = (Get-Command python -ErrorAction Stop).Source
    & $basePython -m venv (Join-Path $repoRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed' }
}
& $venvPython -m pip install -e $repoRoot
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed' }
$localBin = Join-Path $env:USERPROFILE '.local/bin'
New-Item -ItemType Directory -Path $localBin -Force | Out-Null
$wrapper = '@echo off' + "`r`n" + '"' + $venvPython + '" -X utf8 -m doudian_auto.cli %*' + "`r`nexit /b %errorlevel%`r`n"
[IO.File]::WriteAllText((Join-Path $localBin 'doudian-auto.cmd'),$wrapper,[Text.UTF8Encoding]::new($false))
$userPath = [Environment]::GetEnvironmentVariable('Path','User')
if (@($userPath -split ';') -notcontains $localBin -and @($userPath -split ';') -notcontains $localBin.Replace('\','/')) {
    [Environment]::SetEnvironmentVariable('Path',($userPath.TrimEnd(';')+';'+$localBin),'User')
}
if (@($env:Path -split ';') -notcontains $localBin -and @($env:Path -split ';') -notcontains $localBin.Replace('\','/')) {
    $env:Path += ';' + $localBin
}
$desktop = [Environment]::GetFolderPath('Desktop')
$linkName = ([char]0x6296).ToString()+[char]0x5e97+[char]0x672c+[char]0x5730+[char]0x4e0a+[char]0x4f20+'.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop $linkName))
$shortcut.TargetPath = Join-Path $repoRoot '.venv/Scripts/pythonw.exe'
$shortcut.Arguments = '-X utf8 -m doudian_auto.cli gui'
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = 'Douyin Shop local product uploader'
$shortcut.Save()
Write-Output ('Installed command: '+(Join-Path $localBin 'doudian-auto.cmd'))
Write-Output ('Desktop shortcut: '+(Join-Path $desktop $linkName))
