"""Collect redistribution notices from the exact build environment."""
import importlib.metadata as metadata
import json
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "build" / "ThirdPartyLicenses"
out.mkdir(parents=True, exist_ok=True)
versions = {}
for dist in metadata.distributions():
    name = dist.metadata['Name']
    versions[name] = dist.version
    for file in dist.files or []:
        if not any(word in str(file).lower() for word in ("license", "copying", "copyright", "notice")):
            continue
        src = Path(dist.locate_file(file))
        if src.is_file() and src.suffix.lower() not in ('.py', '.pyc', '.pyd', '.dll', '.exe'):
            safe_parts = [p for p in file.parts if p not in ('.', '..')]
            target = out / name / Path(*safe_parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
(out / "versions.json").write_text(json.dumps(versions, indent=2, sort_keys=True), encoding='utf-8')
python_license = Path(sys.base_prefix) / "LICENSE.txt"
shutil.copyfile(python_license, out / 'Python-LICENSE.txt')
shutil.copyfile(root / 'THIRD_PARTY_NOTICES.md', out / 'README.md')
shutil.copytree(root / 'packaging' / 'licenses', out / 'Upstream', dirs_exist_ok=True)
print(f'Collected notices for {len(versions)} packages')
