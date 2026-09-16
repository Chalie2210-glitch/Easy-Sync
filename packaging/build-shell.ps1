$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Install Visual Studio C++ desktop build tools.' }
$devShell = Join-Path $vs 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
Import-Module $devShell
Enter-VsDevShell -VsInstallPath $vs -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64'
$output = Join-Path $root 'build\shell'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$source = Join-Path $PSScriptRoot 'shell\EasySyncShell.cpp'
$hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.Substring(0, 16).ToLowerInvariant()
$name = "EasySyncShell-$hash.dll"
Push-Location -LiteralPath $output
try {
    # An unchanged module may already be loaded by Explorer.
    if (-not (Test-Path -LiteralPath $name)) {
        & cl.exe /nologo /std:c++17 /EHsc /MT /LD /O2 /W4 /DUNICODE /D_UNICODE $source "/Fe:$name" /link /EXPORT:DllGetClassObject,PRIVATE /EXPORT:DllCanUnloadNow,PRIVATE ole32.lib shell32.lib advapi32.lib user32.lib uuid.lib
        if ($LASTEXITCODE -ne 0) { throw 'Shell command build failed.' }
    }
    Set-Content -LiteralPath 'easysync-shell-host.txt' -Value $name -Encoding ascii
} finally { Pop-Location }
