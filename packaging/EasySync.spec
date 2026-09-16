# Build from a clean source tree. Never collect personal assets or logs.
from pathlib import Path

root = Path(SPECPATH).parent
shell_dir = root / 'build' / 'shell'
shell_name = (shell_dir / 'easysync-shell-host.txt').read_text(encoding='ascii').strip()
a = Analysis(
    [str(root / 'run_easysync.pyw')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'LICENSE'), '.'),
           (str(shell_dir / shell_name), '.'),
           (str(shell_dir / 'easysync-shell-host.txt'), '.'),
           (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
           (str(root / 'build' / 'ThirdPartyLicenses'), 'ThirdPartyLicenses')],
    hiddenimports=['waapi'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter', 'pytest'],
    noarchive=False, optimize=1,
)
# Qt's broad hooks include unused plugins (including GPL-only Virtual Keyboard).
# This Widgets app needs only the following LGPL modules and plugins.
qt_modules = {'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll', 'Qt6Svg.dll'}
qt_plugins = {'qwindows.dll', 'qoffscreen.dll', 'qminimal.dll',
              'qmodernwindowsstyle.dll', 'qgif.dll', 'qico.dll', 'qjpeg.dll',
              'qsvg.dll', 'qsvgicon.dll', 'qnetworklistmanager.dll',
              'qcertonlybackend.dll', 'qopensslbackend.dll', 'qschannelbackend.dll'}
def needed_binary(entry):
    dest = entry[0].replace('\\', '/')
    name = dest.rsplit('/', 1)[-1]
    if name.lower() in {'icuuc.dll', 'icuin.dll'} or name.lower().startswith('api-ms-win-'):
        return False  # Windows system components, never third-party PATH substitutes.
    if '/plugins/' in dest and dest.startswith('PySide6/'):
        return name in qt_plugins
    if name.startswith('Qt6') and name.endswith('.dll'):
        return name in qt_modules
    return name != 'opengl32sw.dll'
a.binaries = [entry for entry in a.binaries if needed_binary(entry)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='EasySync',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='EasySync')
