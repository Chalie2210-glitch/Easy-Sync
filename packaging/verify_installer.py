"""Install/upgrade/uninstall test on a machine with no installed Easy Sync.

An older installer version is built with the same application payload to verify
Inno Setup's upgrade identity and settings retention. Integration tasks are off.
"""
import json
import os
import subprocess
import sys
import tempfile
import winreg
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from easysync.version import VERSION

installer = root / 'dist' / 'release' / f'Easy-Sync-Setup-{VERSION}-x64.exe'
uninstall_key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D59879B2-AD07-4DA2-89C3-C29B67228C56}_is1'
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key):
        raise RuntimeError('Use a clean machine: Easy Sync is already installed.')
except FileNotFoundError:
    pass

compiler = next(p for p in (
    Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe',
    Path(os.environ['ProgramFiles(x86)']) / 'Inno Setup 6/ISCC.exe',
) if p.exists())
baseline_dir = root / 'build' / 'baseline'
subprocess.run([str(compiler), '/Qp', '/DAppVersion=0.0.0', f'/O{baseline_dir}',
                str(root / 'packaging' / 'installer.iss')], check=True, timeout=180)
baseline = baseline_dir / 'Easy-Sync-Setup-0.0.0-x64.exe'
with tempfile.TemporaryDirectory(prefix='EasySync-Installer-Test-') as tmp:
    folder = Path(tmp)
    install_dir = folder / 'Program With Spaces'
    env = dict(os.environ, APPDATA=str(folder / 'Roaming'),
               LOCALAPPDATA=str(folder / 'Local'), QT_QPA_PLATFORM='offscreen')
    settings = folder / 'Roaming' / 'EasySync' / 'settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text('{"pins":["keep-me"],"defaults_version":1}', encoding='utf-8')
    before = settings.read_bytes()
    def install(package):
        subprocess.run([str(package), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                        '/NOICONS', '/TASKS=', f'/DIR={install_dir}',
                        f'/LOG={folder / "install.log"}'], env=env, check=True, timeout=180)
    try:
        install(baseline)
        exe = install_dir / 'EasySync.exe'
        assert exe.exists()
        report = folder / 'smoke.json'
        result = subprocess.run([str(exe), '--smoke-test', str(report)], env=env, timeout=40)
        assert result.returncode == 0, report.read_text(encoding='utf-8') if report.exists() else result
        assert json.loads(report.read_text()) == {'version': VERSION, 'visible': True}
        assert (install_dir / 'ThirdPartyLicenses' / 'versions.json').exists()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key) as key:
            assert winreg.QueryValueEx(key, 'DisplayVersion')[0] == '0.0.0'
        install(installer)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key) as key:
            assert winreg.QueryValueEx(key, 'DisplayVersion')[0] == VERSION
        assert settings.read_bytes() == before
        subprocess.run([str(exe), '--smoke-test', str(report)], env=env, check=True, timeout=40)
        print('PASS: install, frozen GUI, installer version upgrade, settings retention, license files')
    finally:
        uninstaller = install_dir / 'unins000.exe'
        if uninstaller.exists():
            subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                           env=env, check=True, timeout=120)
    assert not (install_dir / 'EasySync.exe').exists()
    assert settings.read_bytes() == before
    print('PASS: uninstall removes application and preserves user settings')
