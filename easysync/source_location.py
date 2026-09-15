"""Persist the actual import location in Sound notes and reveal that exact file."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

MARKER = re.compile(r"^\[EasySync source v1\] (.+)$", re.MULTILINE)


def locations(notes: str) -> dict[str, str]:
    match = MARKER.search(notes or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def with_location(notes: str, source: Path, language: str) -> str:
    data = locations(notes)
    data[language] = str(source.absolute())
    line = "[EasySync source v1] " + json.dumps(data, ensure_ascii=False)
    if MARKER.search(notes):
        return MARKER.sub(lambda _: line, notes, count=1)
    return notes + ("\n" if notes and not notes.endswith("\n") else "") + line


def remember(bridge, object_path: str, source: Path, language: str) -> bool:
    rows = bridge._call("ak.wwise.core.object.get", {
        "from": {"path": [object_path]}, "options": {"return": ["id", "notes"]},
    }).get("return", [])
    if not rows:
        return False
    row = rows[0]
    bridge._call("ak.wwise.core.object.setNotes", {
        "object": row["id"],
        "value": with_location(row.get("notes", ""), source, language),
    })
    return True


def paths_for_objects(bridge, object_ids: list[str]) -> list[Path]:
    if not object_ids:
        object_ids = [r["id"] for r in bridge.selected_objects()]
    paths: list[Path] = []
    for oid in object_ids:
        rows = bridge._call("ak.wwise.core.object.get", {
            "from": {"id": [oid]},
            "options": {"return": ["id", "type", "notes", "parent"]},
        }).get("return", [])
        if rows and rows[0].get("type") == "AudioFileSource":
            parent = rows[0].get("parent", {}).get("id")
            if parent:
                rows = bridge._call("ak.wwise.core.object.get", {
                    "from": {"id": [parent]}, "options": {"return": ["notes"]},
                }).get("return", [])
        for row in rows:
            paths.extend(Path(p) for p in locations(row.get("notes", "")).values())
    return list(dict.fromkeys(paths))


def reveal(path: Path) -> None:
    # No name search, relocation fallback, or substitution with Wwise Originals.
    if not path.is_absolute():
        raise ValueError(f"저장된 원본 경로가 올바르지 않습니다.\n\n{path}")
    if not path.is_file():
        raise FileNotFoundError(
            f"처음 가져온 위치에서 원본 파일을 찾을 수 없습니다.\n\n{path}\n\n"
            "파일이나 폴더가 이동되었거나 이름이 바뀌었을 수 있습니다.")
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    subprocess.Popen([str(explorer), "/select,", str(path)], shell=False)


def run(object_ids: list[str], url: str | None = None) -> int:
    """Command add-on entry point; no Easy Sync window or IPC port required."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .waapi_bridge import WwiseBridge

    app = QApplication.instance() or QApplication([])
    try:
        with WwiseBridge(url) as bridge:
            paths = paths_for_objects(bridge, object_ids)
        if not paths:
            raise ValueError("선택한 오브젝트에 기록된 원본 경로가 없습니다.\n\n"
                             "이 버전의 Easy Sync로 임포트한 Sound 또는 Audio Source를 선택하세요.")
        failures = []
        for path in paths:
            try:
                reveal(path)
            except (OSError, ValueError) as exc:
                failures.append(str(exc))
        if failures:
            raise ValueError("\n\n".join(failures))
        return 0
    except Exception as exc:
        QMessageBox.information(None, "Easy Sync — 가져온 원본 파일 찾기", str(exc))
        return 1
