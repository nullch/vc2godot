from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class IdeObject:
    object_id: int
    model: str
    texture: str
    draw_distance: float = 0.0
    flags: int = 0


def _clean(line: str) -> str:
    return line.split('#', 1)[0].strip()


def parse_ide(path: Path) -> dict[int, IdeObject]:
    """objs / tobj sections.

    III: id, model, txd, meshcount, dist1..distN, flags
    VC:  same, tobj additionally has timeOn, timeOff after flags.
    """
    result: dict[int, IdeObject] = {}
    section = None
    for raw in path.read_text(errors="replace").splitlines():
        line = _clean(raw)
        if not line or line.startswith(";"):
            continue
        low = line.lower()
        if low == "end":
            section = None; continue
        if ',' not in line:
            section = low if low in ("objs", "tobj") else "other"
            continue
        if section not in ("objs", "tobj"):
            continue
        p = [x.strip() for x in line.split(',')]
        if len(p) < 5:
            continue
        try:
            oid = int(p[0]); model = p[1]; txd = p[2]
            meshes = int(float(p[3]))
            dist = float(p[4]) if meshes >= 1 else 0.0
            flags = int(float(p[4 + meshes]))
        except (ValueError, IndexError):
            # never drop the object just because of a weird flags field
            try:
                oid = int(p[0]); model = p[1]; txd = p[2]; dist = 0.0; flags = 0
            except ValueError:
                continue
        result[oid] = IdeObject(oid, model, txd, dist, flags)
    return result


def find_ide_files(game_root: Path):
    # Linux is case-sensitive while stock/modded VC data commonly uses .IDE.
    roots = [game_root / "data", game_root]
    seen = set()
    for base in roots:
        if not base.exists():
            continue
        for p in sorted((q for q in base.rglob("*") if q.is_file() and q.suffix.lower() == ".ide"), key=lambda q: str(q).casefold()):
            key = str(p.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            yield p
