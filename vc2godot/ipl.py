from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Placement:
    object_id: int
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float
    interior: int = 0
    lod: int = -1
    sx: float = 1.0
    sy: float = 1.0
    sz: float = 1.0
    source: str = ""
    model: str = ""


def _clean(line):
    return line.split('#', 1)[0].strip()


def parse_ipl(path: Path) -> list[Placement]:
    """Parse the text ``inst`` section of a GTA III / Vice City IPL.

    VC:   id, model, interior, x, y, z, sx, sy, sz, qx, qy, qz, qw   (13 fields)
    III:  id, model,           x, y, z, sx, sy, sz, qx, qy, qz, qw   (12 fields)
    SA:   id, model, interior, x, y, z, qx, qy, qz, qw, lod          (11 fields)
    """
    out = []; section = None
    for raw in path.read_text(errors="replace").splitlines():
        line = _clean(raw)
        if not line or line.startswith(';'):
            continue
        low = line.lower()
        if low == "end":
            section = None; continue
        if low == "inst":
            section = "inst"; continue
        if section != "inst":
            # any other section header (zone, cull, pick, path, occl ...)
            if ',' not in line:
                section = low
            continue
        p = [x.strip() for x in line.split(',')]
        try:
            oid = int(p[0]); model = p[1]
            if len(p) >= 13:            # Vice City
                interior = int(p[2]); x, y, z = map(float, p[3:6])
                sx, sy, sz = map(float, p[6:9]); qx, qy, qz, qw = map(float, p[9:13])
                lod = -1
            elif len(p) == 12:          # GTA III
                interior = 0; x, y, z = map(float, p[2:5])
                sx, sy, sz = map(float, p[5:8]); qx, qy, qz, qw = map(float, p[8:12])
                lod = -1
            elif len(p) >= 11:          # San Andreas
                interior = int(p[2]); x, y, z = map(float, p[3:6])
                qx, qy, qz, qw = map(float, p[6:10]); sx = sy = sz = 1.0
                lod = int(p[10])
            else:
                continue
        except (ValueError, IndexError):
            continue
        out.append(Placement(oid, x, y, z, qx, qy, qz, qw, interior, lod, sx, sy, sz, str(path), model))
    return out


def find_ipl_files(game_root: Path):
    """Find every text IPL, independent of extension casing, without duplicates."""
    roots = [game_root / "data" / "maps", game_root / "data"]
    seen = set()
    for base in roots:
        if not base.exists():
            continue
        files = (q for q in base.rglob("*") if q.is_file() and q.suffix.lower() == ".ipl")
        for p in sorted(files, key=lambda q: str(q).casefold()):
            key = str(p.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            yield p
