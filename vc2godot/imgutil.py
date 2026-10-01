from __future__ import annotations
from pathlib import Path
from rwfury import Img


class MultiImg:
    """Case-insensitive reader across all world IMG archives we discover."""
    def __init__(self, archives, paths=None):
        self.archives = archives
        self.paths = list(paths or [])
        self.entries = [e for img in archives for e in getattr(img, 'entries', [])]
        self._index = {}
        for img in archives:
            for e in getattr(img, 'entries', []):
                name = getattr(e, 'name', '')
                self._index.setdefault(str(name).replace('\\', '/').casefold(), img)

    def read(self, name):
        key = str(name).replace('\\', '/').casefold()
        img = self._index.get(key)
        if img is not None:
            try:
                return img.read(name)
            except Exception:
                pass
        for img in self.archives:
            try:
                return img.read(name)
            except Exception:
                pass
        raise KeyError(name)


def _candidate_paths(root: Path):
    """Discover IMG v1 archives (IMG + matching DIR) case-insensitively."""
    seen = set()
    roots = [root / 'models', root / 'data' / 'maps']
    for base in roots:
        if not base.exists():
            continue
        for p in base.rglob('*'):
            if not p.is_file() or p.suffix.lower() != '.img':
                continue
            # IMG v1 requires the companion .dir beside it. Some installs use
            # uppercase/lowercase names, so compare directory entries casefolded.
            sibling_names = {q.name.casefold(): q for q in p.parent.iterdir() if q.is_file()}
            d = sibling_names.get((p.stem + '.dir').casefold())
            # Do not accidentally open animation/cutscene archives without a DIR.
            if d is None:
                continue
            key = str(p.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            yield p


def locate_imgs(game_root: Path):
    paths = list(_candidate_paths(game_root))
    # Prefer the canonical world archive first; this makes duplicate filenames
    # resolve the same way the stock VC install does.
    preferred = ['gta3.img', 'gta_int.img', 'txd.img']
    paths.sort(key=lambda p: (preferred.index(p.name.casefold()) if p.name.casefold() in preferred else 99,
                              str(p).casefold()))
    return paths


def open_img(game_root: Path):
    paths = locate_imgs(game_root)
    if not paths:
        raise FileNotFoundError(f'Cannot find GTA VC IMG v1 archives below {game_root}')
    archives = []
    opened = []
    for p in paths:
        try:
            archives.append(Img.from_file(p))
            opened.append(p)
        except Exception as e:
            # A broken unrelated IMG should not block the world archive.
            print(f'WARNING: IMG open failed {p}: {e}')
    if not archives:
        raise FileNotFoundError(f'No usable IMG archives found below {game_root}')
    return MultiImg(archives, opened)
