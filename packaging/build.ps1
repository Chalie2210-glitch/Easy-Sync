param([string]$Python = 'python', [string]$Iscc = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not $Iscc) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw 'Install Inno Setup 6 or pass -Iscc with the ISCC.exe path.' }
$Python = (Get-Command $Python -ErrorAction Stop).Source
# Prevent unrelated tools on PATH (e.g. Poppler's ICU) from replacing Windows DLLs.
$env:PATH = "$(Split-Path -Parent $Python);$env:SystemRoot\System32;$env:SystemRoot"
$version = & $Python -c 'from easysync.version import VERSION; print(VERSION)'
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid version' }
& $Python packaging/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
& $Python -m PyInstaller --noconfirm --clean packaging/EasySync.spec
if ($LASTEXITCODE -ne 0) { throw 'Application build failed' }
& $Iscc "/DAppVersion=$version" packaging/installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
$asset = Get-Item -LiteralPath "dist\release\Easy-Sync-Setup-$version-x64.exe"
$checksum = (Get-FileHash -LiteralPath $asset.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
"$checksum  $($asset.Name)" | Set-Content -LiteralPath 'dist\release\SHA256SUMS.txt' -Encoding ascii
Write-Output "Built $($asset.Name) SHA256=$checksum"
