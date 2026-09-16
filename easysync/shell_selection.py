"""Read Explorer's selection manifest without command-line length limits."""
from pathlib import Path
import tempfile


def consume(filename: str) -> list[str]:
    path = Path(filename).resolve()
    directory = (Path(tempfile.gettempdir()) / 'EasySync-Selections').resolve()
    if path.parent != directory or path.suffix != '.paths':
        raise ValueError('잘못된 탐색기 파일 목록 위치입니다.')
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('탐색기 파일 목록이 너무 큽니다.')
    files = path.read_text(encoding='utf-8').splitlines()
    if not files or any(not Path(p).is_absolute() for p in files):
        raise ValueError('잘못된 탐색기 파일 목록입니다.')
    path.unlink()
    return files
