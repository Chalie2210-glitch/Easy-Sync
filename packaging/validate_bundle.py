"""Reject an incomplete or development-runtime-dependent Windows shell bundle."""
from pathlib import Path
import re

import pefile

root = Path(__file__).resolve().parents[1]
bundle = root / "dist" / "EasySync"
internal = bundle / "_internal"
name = (internal / "easysync-shell-host.txt").read_text(encoding="ascii").strip()
if not re.fullmatch(r"EasySyncShell-[0-9a-f]{16}\.dll", name):
    raise RuntimeError("Invalid shell module manifest")
for path in (bundle / "EasySync.exe", internal / name):
    with pefile.PE(str(path)) as binary:
        if binary.FILE_HEADER.Machine != 0x8664:
            raise RuntimeError(f"Expected native x64 binary: {path.name}")
        if path.name == name:
            dependencies = {entry.dll.decode("ascii").lower()
                            for entry in binary.DIRECTORY_ENTRY_IMPORT}
            # /MT must keep VC runtime and Python out of the Explorer module.
            system_dlls = {"kernel32.dll", "advapi32.dll", "ole32.dll", "shell32.dll", "user32.dll"}
            if dependencies - system_dlls:
                raise RuntimeError(f"Shell module has external dependencies: {dependencies - system_dlls}")
            exports = {entry.name for entry in binary.DIRECTORY_ENTRY_EXPORT.symbols}
            if not {b"DllGetClassObject", b"DllCanUnloadNow"} <= exports:
                raise RuntimeError("Missing COM exports")
if not (internal / "python312.dll").is_file():
    raise RuntimeError("Bundled Python runtime is missing")
print("Validated x64 bundle and self-contained Explorer module")
