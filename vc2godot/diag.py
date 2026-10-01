"""Fast, text-only diagnostics (no DFF/TXD decoding, runs in ~1 second).

    vc2godot ipls    "<game>"                     -> which IPL file covers which part of the map
    vc2godot inspect "<game>" X Y [radius]        -> every placement near GTA coords (X, Y)
"""
from __future__ import annotations
import math, os
from pathlib import Path
from .ide import find_ide_files, parse_ide
from .ipl import find_ipl_files, Placement


def _is_lod(name):
    return str(name or '').lower().startswith(('lod', 'islandlod'))


def _parse_ipl_verbose(path):
    """Like parse_ipl but also returns (line_no, text, reason) for every inst line that was rejected."""
    from .ipl import parse_ipl
    good = parse_ipl(path)
    rejected = []
    section = None; n_inst_lines = 0
    for no, raw in enumerate(path.read_text(errors='replace').splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith(';'):
            continue
        low = line.lower()
        if low == 'end':
            section = None; continue
        if low == 'inst':
            section = 'inst'; continue
        if section != 'inst':
            if ',' not in line:
                section = low
            continue
        n_inst_lines += 1
    return good, max(0, n_inst_lines - len(good)), n_inst_lines


def load(game):
    game = Path(game)
    ides = {}
    for p in find_ide_files(game):
        try:
            for k, v in parse_ide(p).items():
                ides[k] = v
        except Exception:
            pass
    files = []
    for p in find_ipl_files(game):
        good, rejected, total = _parse_ipl_verbose(p)
        files.append((p, good, rejected, total))
    return ides, files


def _bbox(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys)))


def _hd_grid(files, ides):
    grid = {}
    for p, good, *_ in files:
        for pl in good:
            o = ides.get(pl.object_id)
            name = o.model if o else pl.model
            if pl.interior != 0 or _is_lod(name) or _is_lod(pl.model):
                continue
            grid.setdefault((int(pl.x // 64), int(pl.y // 64)), []).append((pl.x, pl.y))
    return grid


def _nearest_hd(grid, x, y, r=64.0):
    best = 1e18
    cx, cy = int(x // 64), int(y // 64)
    for gx in range(cx - 1, cx + 2):
        for gy in range(cy - 1, cy + 2):
            for hx, hy in grid.get((gx, gy), ()):
                d = math.hypot(hx - x, hy - y)
                if d < best:
                    best = d
    return best


def ipl_report(game):
    ides, files = load(game)
    grid = _hd_grid(files, ides)
    out = []
    out.append('IDE objects: %d   IPL files: %d' % (len(ides), len(files)))
    out.append('')
    out.append('%-34s %6s %6s %6s %6s %6s %6s  %s' % ('IPL file', 'lines', 'parsed', 'reject', 'HD', 'LOD', 'inter', 'HD bbox (GTA x0,y0,x1,y1)  |  LOD-with-no-HD-within-64m'))
    tot = dict(lines=0, parsed=0, rej=0, hd=0, lod=0, inter=0)
    for p, good, rej, total in files:
        hd = [pl for pl in good if pl.interior == 0 and not (_is_lod(pl.model) or _is_lod((ides.get(pl.object_id).model if ides.get(pl.object_id) else '')))]
        lod = [pl for pl in good if pl.interior == 0 and (_is_lod(pl.model) or _is_lod((ides.get(pl.object_id).model if ides.get(pl.object_id) else '')))]
        inter = [pl for pl in good if pl.interior != 0]
        lod_only = [pl for pl in lod if _nearest_hd(grid, pl.x, pl.y) > 64.0]
        out.append('%-34s %6d %6d %6d %6d %6d %6d  %s | %d' % (p.name[:34], total, len(good), rej, len(hd), len(lod), len(inter), _bbox([(q.x, q.y) for q in hd]), len(lod_only)))
        tot['lines'] += total; tot['parsed'] += len(good); tot['rej'] += rej; tot['hd'] += len(hd); tot['lod'] += len(lod); tot['inter'] += len(inter)
    out.append('')
    out.append('TOTAL lines=%(lines)d parsed=%(parsed)d rejected=%(rej)d HD=%(hd)d LOD=%(lod)d interior=%(inter)d' % tot)
    unresolved = sum(1 for _, good, *_ in files for pl in good if pl.object_id not in ides)
    out.append('placements whose id is not in any IDE: %d' % unresolved)
    return '\n'.join(out)


def inspect_area(game, x, y, radius=120.0):
    ides, files = load(game)
    grid = _hd_grid(files, ides)
    rows = []
    for p, good, *_ in files:
        for pl in good:
            if math.hypot(pl.x - x, pl.y - y) > radius:
                continue
            o = ides.get(pl.object_id)
            name = o.model if o else pl.model
            kind = 'INTERIOR' if pl.interior != 0 else ('LOD' if (_is_lod(name) or _is_lod(pl.model)) else 'HD')
            extra = ''
            if kind == 'LOD':
                d = _nearest_hd(grid, pl.x, pl.y)
                extra = 'nearestHD=%dm%s' % (min(d, 9999), '  <-- LOD WITHOUT HD' if d > 64 else '')
            rows.append((kind, p.name, pl.object_id, name, (o.texture if o else '?'), round(pl.x), round(pl.y), round(pl.z), pl.interior, extra))
    rows.sort(key=lambda r: (r[0], r[3].lower()))
    out = ['area GTA x=%.0f y=%.0f r=%.0f : %d placements (HD=%d LOD=%d INTERIOR=%d)' % (
        x, y, radius, len(rows), sum(r[0] == 'HD' for r in rows), sum(r[0] == 'LOD' for r in rows), sum(r[0] == 'INTERIOR' for r in rows)), '']
    out.append('%-8s %-22s %6s %-26s %-20s %6s %6s %5s %3s  %s' % ('kind', 'ipl', 'id', 'model', 'txd', 'x', 'y', 'z', 'int', ''))
    for r in rows:
        out.append('%-8s %-22s %6d %-26s %-20s %6d %6d %5d %3d  %s' % (r[0], r[1][:22], r[2], r[3][:26], r[4][:20], r[5], r[6], r[7], r[8], r[9]))
    return '\n'.join(out)


# ----------------------------------------------------------------------------------------------
# Geometry based diagnostics (need rwfury, read real DFFs, no textures, 30-90 s)
#   vc2godot where "<game>" X Y [radius]   -> which real models lie under one GTA point
#   vc2godot holes "<game>"                -> finds places where props (palms, benches...) stand on NOTHING
# ----------------------------------------------------------------------------------------------
def _point_in_tri(px, pz, a, b, c):
    """Barycentric test in the XZ plane.  Returns interpolated y or None."""
    d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
    if abs(d) < 1e-9:
        return None
    l1 = ((b[2] - c[2]) * (px - c[0]) + (c[0] - b[0]) * (pz - c[2])) / d
    l2 = ((c[2] - a[2]) * (px - c[0]) + (a[0] - c[0]) * (pz - c[2])) / d
    l3 = 1.0 - l1 - l2
    if l1 < -1e-6 or l2 < -1e-6 or l3 < -1e-6:
        return None
    return l1 * a[1] + l2 * b[1] + l3 * c[1]


class _Scene:
    pass


def _load_scene(game):
    import logging, tempfile
    from .imgutil import open_img
    from .converter import Converter
    from .world import _model_bbox, find_exterior_areas
    game = Path(game)
    sc = _Scene()
    sc.ides, files = load(game)
    sc.placements = [pl for _, good, *_ in files for pl in good]
    log = logging.getLogger('vc2godot.where'); log.setLevel(logging.ERROR)
    conv = Converter.__new__(Converter)          # no COL indexing, no texture decoding: geometry only
    conv.img = open_img(game); conv.game_root = game; conv.out = Path(tempfile.mkdtemp(prefix='vc2diag_')); conv.log = log
    conv.txd_cache = {}; conv.mesh_cache = {}; conv.collision_cache = {}; conv.external_files = {}
    conv.external_collision_models = {}; conv.missing_tex = {}; conv.failures = {}
    conv.debug_dumped = True; conv._tex_owner = None
    conv._index_external_files()
    conv.txd = lambda name: {}
    sc.conv = conv
    sc.ext_areas, _ = find_exterior_areas(sc.placements, sc.ides)
    sc.cache = {}
    sc.unresolved = 0
    models = {}
    for pl in sc.placements:
        o = sc.ides.get(pl.object_id)
        if o is None:
            sc.unresolved += 1
            continue
        models.setdefault(o.model.casefold(), o)
    print('reading %d DFF models ...' % len(models), flush=True)
    sc.models = models
    sc.bad = {}
    for key, o in models.items():
        if _model_bbox(conv, o, sc.cache) is None:
            sc.bad[key] = conv.failures.get(key, 'no drawable mesh')
    return sc


def _kind_of(sc, pl, o):
    from .world import is_lod
    kind = 'LOD' if (is_lod(o.model) or is_lod(pl.model)) else 'HD'
    if pl.interior != 0:
        kind = 'INT-shown' if ((pl.source, pl.interior) in sc.ext_areas and kind == 'HD') else 'INTERIOR(hidden)'
    return kind


def _placed_records(sc, o, pl):
    import copy
    from .gltf import mesh_records
    from .world import _transform_record
    data = sc.conv.meshes(o.model, o.texture)
    if not data:
        return []
    meshes, _ = data
    return [_transform_record(copy.deepcopy(r), pl) for r in mesh_records(meshes, None, o.model)]


def _candidate_rows(sc, X, Z, radius):
    from .world import _footprint
    rows = []
    for pl in sc.placements:
        o = sc.ides.get(pl.object_id)
        if o is None:
            continue
        box = sc.cache.get((o.model.casefold(), o.texture.casefold()))
        if not box:
            continue
        fp = _footprint(box, pl)
        if not (fp[0] - radius <= X <= fp[2] + radius and fp[1] - radius <= Z <= fp[3] + radius):
            continue
        heights = []; tri_total = 0
        for placed in _placed_records(sc, o, pl):
            P = placed['positions']; I = placed['indices']
            tri_total += len(I) // 3
            for i in range(0, len(I) - 2, 3):
                h = _point_in_tri(X, Z, P[I[i]], P[I[i + 1]], P[I[i + 2]])
                if h is not None:
                    heights.append(h)
        rows.append((0 if heights else 1, _kind_of(sc, pl, o), os.path.basename(pl.source), o.model, o.texture,
                     round(pl.x), round(pl.y), round(pl.z), round(fp[2] - fp[0]), round(fp[3] - fp[1]), tri_total,
                     (round(min(heights), 1), round(max(heights), 1)) if heights else None))
    rows.sort(key=lambda r: (r[0], r[1], r[3].lower()))
    out = ['%-7s %-16s %-17s %-26s %-18s %6s %6s %5s %6s %6s %7s  %s' % ('covers', 'kind', 'ipl', 'model', 'txd', 'x', 'y', 'z', 'w_m', 'd_m', 'tris', 'z at point')]
    for r in rows:
        out.append('%-7s %-16s %-17s %-26s %-18s %6d %6d %5d %6d %6d %7d  %s' % (
            'COVERS' if r[0] == 0 else '-', r[1], r[2][:17], r[3][:26], r[4][:18], r[5], r[6], r[7], r[8], r[9], r[10], r[11] or ''))
    return out


def _bad_models_lines(sc, x, y):
    users = {}
    for pl in sc.placements:
        o = sc.ides.get(pl.object_id)
        if o and o.model.casefold() in sc.bad:
            users.setdefault(o.model.casefold(), []).append(pl)
    out = ['MODELS THAT PRODUCE NO GEOMETRY AT ALL (missing DFF / parse error / empty): %d' % len(sc.bad), '']
    for k, why in sorted(sc.bad.items()):
        pts = users.get(k, [])
        if pts:
            near = min(math.hypot(p.x - x, p.y - y) for p in pts)
            out.append('%-28s %-34s n=%-4d nearest placement: %d m  (%s)' % (sc.models[k].model[:28], why[:34], len(pts), near, os.path.basename(pts[0].source)))
    return out


def where_is(game, x, y, radius=60.0):
    import time
    t0 = time.time()
    sc = _load_scene(game)
    X, Z = float(x), -float(y)
    out = ['where GTA x=%.0f y=%.0f (Godot x=%.0f z=%.0f), margin %.0f m, %.0f s' % (x, y, X, Z, radius, time.time() - t0),
           'placements whose id is not in any IDE: %d' % sc.unresolved, '',
           'COVERS = a real triangle of this placed model lies exactly above/below the point (height range = GTA z of the surface there).', '']
    out += _candidate_rows(sc, X, Z, radius) + [''] + _bad_models_lines(sc, x, y)
    return '\n'.join(out)


_CELL = 8.0


def holes_report(game, png_path='holes_map.png'):
    """Rasterise every up-facing triangle of every VISIBLE (HD, exterior) placement, then look for props that
    stand on nothing.  Where palms/benches/lamps float over empty space the ground piece is missing."""
    import time
    from .world import _footprint
    t0 = time.time()
    sc = _load_scene(game)
    grid = {}          # (cx, cz) -> [heights]
    props = []         # (pl, o, cx, cz)
    n_ground = 0
    for pl in sc.placements:
        o = sc.ides.get(pl.object_id)
        if o is None:
            continue
        if _kind_of(sc, pl, o) not in ('HD', 'INT-shown'):
            continue
        box = sc.cache.get((o.model.casefold(), o.texture.casefold()))
        if not box:
            continue
        fp = _footprint(box, pl)
        w = fp[2] - fp[0]; d = fp[3] - fp[1]
        if max(w, d) < 30.0:
            props.append((pl, o))
            continue
        for placed in _placed_records(sc, o, pl):
            P = placed['positions']; I = placed['indices']
            for i in range(0, len(I) - 2, 3):
                a, b, c = P[I[i]], P[I[i + 1]], P[I[i + 2]]
                ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                ln = (nx * nx + ny * ny + nz * nz) ** 0.5
                if ln < 1e-9 or abs(ny) / ln < 0.6:
                    continue                                  # walls are not ground
                x0 = min(a[0], b[0], c[0]); x1 = max(a[0], b[0], c[0])
                z0 = min(a[2], b[2], c[2]); z1 = max(a[2], b[2], c[2])
                if (x1 - x0) > 1500 or (z1 - z0) > 1500:
                    continue
                for cx in range(int(x0 // _CELL), int(x1 // _CELL) + 1):
                    for cz in range(int(z0 // _CELL), int(z1 // _CELL) + 1):
                        h = _point_in_tri((cx + 0.5) * _CELL, (cz + 0.5) * _CELL, a, b, c)
                        if h is not None:
                            grid.setdefault((cx, cz), []).append(h)
                            n_ground += 1
    floating = []
    for pl, o in props:
        cx, cz = int(math.floor(pl.x / _CELL)), int(math.floor(-pl.y / _CELL))
        ok = False
        for gx in (cx - 1, cx, cx + 1):
            for gz in (cz - 1, cz, cz + 1):
                for h in grid.get((gx, gz), ()):
                    if pl.z - 10.0 <= h <= pl.z + 3.0:
                        ok = True; break
                if ok: break
            if ok: break
        if not ok and pl.z > -5.0:
            floating.append((pl, o))
    clusters = {}
    for pl, o in floating:
        clusters.setdefault((int(pl.x // 96), int(pl.y // 96)), []).append((pl, o))
    out = ['holes: %d ground cells rasterised (%.0f m cells), %d props checked, %d props stand on NOTHING, %.0f s' % (
        len(grid), _CELL, len(props), len(floating), time.time() - t0), '',
        'Each cluster = a 96x96 m square where props (palms, lamps, benches, bushes) have no ground triangle below them.',
        'A real hole shows up as a big cluster.  Coordinates are GTA x,y.', '']
    top = sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:25]
    for (gx, gy), items in top:
        xs = [p.x for p, _ in items]; ys = [p.y for p, _ in items]
        names = {}
        for _, o in items:
            names[o.model] = names.get(o.model, 0) + 1
        out.append('cluster x %5d..%5d  y %5d..%5d  props=%-3d  e.g. %s' % (
            min(xs), max(xs), min(ys), max(ys), len(items),
            ', '.join('%s x%d' % kv for kv in sorted(names.items(), key=lambda kv: -kv[1])[:5])))
    # what could be the missing ground: candidates under the centre of the 3 biggest clusters
    for (gx, gy), items in top[:3]:
        cxm = sum(p.x for p, _ in items) / len(items); cym = sum(p.y for p, _ in items) / len(items)
        out += ['', '=== models under cluster centre GTA x=%.0f y=%.0f (margin 40 m) ===' % (cxm, cym)]
        out += _candidate_rows(sc, cxm, -cym, 40.0)
    out += [''] + _bad_models_lines(sc, 0, 0)
    try:
        from PIL import Image, ImageDraw
        xs = [k[0] for k in grid]; zs = [k[1] for k in grid]
        if xs:
            x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
            W = min(x1 - x0 + 1, 3000); H = min(z1 - z0 + 1, 3000)
            im = Image.new('RGB', (W, H), (0, 0, 0))
            px = im.load()
            for (cx, cz), hs in grid.items():
                ix, iz = cx - x0, cz - z0
                if 0 <= ix < W and 0 <= iz < H:
                    hmax = max(hs)
                    px[ix, iz] = (40, 90, 200) if hmax < 1.0 else ((60, 160, 60) if hmax < 12 else (200, 200, 200))
            dr = ImageDraw.Draw(im)
            for pl, o in floating:
                ix = int(pl.x // _CELL) - x0; iz = int(-pl.y // _CELL) - z0
                dr.rectangle((ix - 1, iz - 1, ix + 1, iz + 1), fill=(255, 0, 0))
            im.save(png_path)
            out.append('')
            out.append('map saved: %s  (1 px = %d m, north up; x0=%d y_top=%d; blue=below 1 m, green=ground, grey=high, RED=props standing on nothing)' % (
                png_path, _CELL, x0 * _CELL, -z0 * _CELL))
    except Exception as e:
        out.append('map not saved: %s' % e)
    return '\n'.join(out)
