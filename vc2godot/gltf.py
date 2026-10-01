from __future__ import annotations
from pathlib import Path
import os, struct, sys
import json, math
from urllib.parse import quote
from array import array
from functools import lru_cache
from PIL import Image as PILImage

# Statistics collected while cleaning meshes (logged by the importer).
STATS = {'bad_index': 0, 'degenerate': 0, 'spike': 0, 'nan': 0, 'meshes': 0,
         'with_colors': 0, 'computed_normals': 0, 'matrix_alt': 0,
         'uv_ok': 0, 'uv_missing': 0, 'uv_degenerate': 0, 'uv_src': {}}
UNTEXTURED = {}   # texture name (or '<none>') -> meshes exported without an image
DEGEN_UV = {}     # texture name -> meshes whose UVs are all identical
UV_DEBUG = []   # first few raw texcoord shapes, printed by the importer
# Absolute limit for a single triangle edge (GTA units == metres).
MAX_EDGE = float(os.environ.get('VC2GODOT_MAX_EDGE', '6000'))
# Smallest edge length that may ever be considered a "spike".  Vice City has
# huge flat ground/promenade quads (2 triangles, 400-900 m long) that the old
# limit of 400 m silently deleted, leaving holes in the map.
MIN_SPIKE = float(os.environ.get('VC2GODOT_MIN_SPIKE', '2000'))
SPIKE_LOG = []    # (model, texture, edge_m, limit_m) for every triangle dropped as spike
# Missing prelit colours -> slightly dimmed white so unlit meshes are not blinding.
DEFAULT_COLOR = (0.8, 0.8, 0.8, 1.0)


def _triples(values):
    if values is None or not values:
        return []
    if isinstance(values[0], (list, tuple)):
        return [tuple(v[:3]) for v in values]
    if len(values) % 3:
        raise ValueError(f"Expected XYZ flat array, got {len(values)} values")
    return [tuple(values[i:i + 3]) for i in range(0, len(values), 3)]


def _uvs(values):
    if values is None or not values:
        return []
    if isinstance(values[0], (list, tuple)):
        return [tuple(v[:2]) for v in values]
    if len(values) % 2:
        raise ValueError(f"Expected UV flat array, got {len(values)} values")
    return [tuple(values[i:i + 2]) for i in range(0, len(values), 2)]


def _indices(values):
    if values is None or not values:
        return []
    if isinstance(values[0], (list, tuple)):
        return [int(x) for tri in values for x in tri]
    return [int(x) for x in values]


def _flat_matrix(m):
    """Return a flat list of 16 floats or None (accepts flat or 4x4 nested)."""
    if m is None:
        return None
    try:
        if len(m) == 0:
            return None
        if isinstance(m[0], (list, tuple)):
            m = [float(x) for row in m for x in row]
        else:
            m = [float(x) for x in m]
    except Exception:
        return None
    return m if len(m) == 16 else None


def _matrix_kind(m):
    """None = identity/unusable, 'col' = translation in m[3],m[7],m[11]
    (row-major, column vectors), 'row' = translation in m[12..14] (row vectors)."""
    if m is None:
        return None
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    if all(abs(a - b) < 1e-6 for a, b in zip(m, ident)):
        return None
    last_row_ok = abs(m[12]) + abs(m[13]) + abs(m[14]) < 1e-6 and abs(m[15] - 1) < 1e-5
    last_col_ok = abs(m[3]) + abs(m[7]) + abs(m[11]) < 1e-6 and abs(m[15] - 1) < 1e-5
    if last_row_ok:
        return 'col'          # original 0.5.x assumption
    if last_col_ok:
        STATS['matrix_alt'] += 1
        return 'row'
    return 'col'


def _matrix_transform_point(m, v, kind='col'):
    x, y, z = map(float, v[:3])
    if kind == 'row':
        return (x * m[0] + y * m[4] + z * m[8] + m[12],
                x * m[1] + y * m[5] + z * m[9] + m[13],
                x * m[2] + y * m[6] + z * m[10] + m[14])
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def _matrix_transform_normal(m, v, kind='col'):
    x, y, z = map(float, v[:3])
    if kind == 'row':
        q = (x * m[0] + y * m[4] + z * m[8], x * m[1] + y * m[5] + z * m[9], x * m[2] + y * m[6] + z * m[10])
    else:
        q = (m[0] * x + m[1] * y + m[2] * z, m[4] * x + m[5] * y + m[6] * z, m[8] * x + m[9] * y + m[10] * z)
    l = (q[0]*q[0] + q[1]*q[1] + q[2]*q[2]) ** 0.5
    return (q[0]/l, q[1]/l, q[2]/l) if l else (0.0, 0.0, 1.0)


def _clean_triangles(pos, inds, label='', tex=''):
    """Drop triangles that reference missing vertices, are degenerate, contain
    NaN or are absurdly long "spikes" (a single displaced vertex stretches
    triangles across half of the map)."""
    n = len(pos); tris = []
    for i in range(0, len(inds) - 2, 3):
        a, b, c = inds[i], inds[i + 1], inds[i + 2]
        if a < 0 or b < 0 or c < 0 or a >= n or b >= n or c >= n:
            STATS['bad_index'] += 1; continue
        if a == b or b == c or a == c:
            STATS['degenerate'] += 1; continue
        pa, pb, pc = pos[a], pos[b], pos[c]
        e = 0.0
        for p, q in ((pa, pb), (pb, pc), (pc, pa)):
            d = ((p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2) ** 0.5
            e = max(e, d)
        if e != e or e == float('inf'):
            STATS['nan'] += 1; continue
        tris.append((a, b, c, e))
    if not tris:
        return []
    es = sorted(t[3] for t in tris)
    p95 = es[int(0.95 * (len(es) - 1))]
    limit = min(MAX_EDGE, max(MIN_SPIKE, p95 * 8.0))
    out = []
    for a, b, c, e in tris:
        if e > limit:
            STATS['spike'] += 1
            if len(SPIKE_LOG) < 200:
                SPIKE_LOG.append((label, tex, round(e, 1), round(limit, 1)))
            continue
        out.extend((a, b, c))
    return out


def _smooth_normals(pos, inds):
    acc = [[0.0, 0.0, 0.0] for _ in pos]
    for i in range(0, len(inds) - 2, 3):
        a, b, c = inds[i], inds[i + 1], inds[i + 2]
        pa, pb, pc = pos[a], pos[b], pos[c]
        ux, uy, uz = pb[0]-pa[0], pb[1]-pa[1], pb[2]-pa[2]
        vx, vy, vz = pc[0]-pa[0], pc[1]-pa[1], pc[2]-pa[2]
        nx, ny, nz = uy*vz - uz*vy, uz*vx - ux*vz, ux*vy - uy*vx
        for k in (a, b, c):
            acc[k][0] += nx; acc[k][1] += ny; acc[k][2] += nz
    out = []
    for x, y, z in acc:
        l = (x*x + y*y + z*z) ** 0.5
        out.append((x/l, y/l, z/l) if l > 1e-12 else (0.0, 0.0, 1.0))
    return out


def _vertex_colors(m, n):
    """Prelit RenderWare vertex colours -> list of RGBA floats (0..1) or None."""
    if not getattr(m, 'has_colors', True):
        return None
    c = getattr(m, 'colors', None)
    if c is None or len(c) == 0:
        return None
    try:
        if isinstance(c[0], (list, tuple)):
            rows = [tuple(float(x) for x in v[:4]) for v in c]
        else:
            k = 4 if len(c) == 4 * n else 3 if len(c) == 3 * n else 0
            if not k:
                return None
            rows = [tuple(float(x) for x in c[i:i + k]) for i in range(0, len(c), k)]
    except Exception:
        return None
    if len(rows) != n or any(len(r) < 3 for r in rows):
        return None
    mx = max(max(r[:3]) for r in rows)
    if mx < 0.02:                       # all black = "no prelit data"
        return None
    sc = 1.0 / 255.0 if mx > 1.001 else 1.0
    return [(min(1.0, r[0]*sc), min(1.0, r[1]*sc), min(1.0, r[2]*sc), 1.0) for r in rows]


def _plain(values):
    """numpy / array.array / memoryview / tuple -> plain python list (or None)."""
    if values is None:
        return None
    if hasattr(values, 'tolist'):
        try:
            values = values.tolist()
        except Exception:
            pass
    try:
        return list(values)
    except Exception:
        return None


def _describe(v, depth=0):
    if depth > 3:
        return '...'
    if isinstance(v, (list, tuple)) or hasattr(v, 'tolist'):
        pl = _plain(v) or []
        return f"{type(v).__name__}[{len(pl)}]" + ("(" + _describe(pl[0], depth + 1) + ")" if pl else "")
    return type(v).__name__


def _try_uv_layouts(tc, n):
    """Return list of n (u, v) from any known texcoord layout, else None."""
    tc = _plain(tc)
    if not tc:
        return None
    first = tc[0]
    fl = _plain(first) if not isinstance(first, (int, float)) else None
    # A) per-vertex pairs: [(u, v), ...]
    if fl is not None and len(fl) in (2, 3) and len(tc) >= n and not (isinstance(fl[0], (list, tuple))):
        if len(tc) == n:
            return [(float(_plain(r)[0]), float(_plain(r)[1])) for r in tc]
    # B) per-set containers: [[(u,v)...], [(u,v)...]] or [[u,v,u,v...], ...]
    if fl is not None and len(fl) >= n:
        if isinstance(fl[0], (list, tuple)) or hasattr(fl[0], 'tolist'):
            return [(float(_plain(r)[0]), float(_plain(r)[1])) for r in fl[:n]]
        if len(fl) >= 2 * n:
            return [(float(fl[2 * i]), float(fl[2 * i + 1])) for i in range(n)]
    # C) flat float array (possibly several sets concatenated; take the first set)
    if fl is None and len(tc) >= 2 * n:
        return [(float(tc[2 * i]), float(tc[2 * i + 1])) for i in range(n)]
    return None


def _uv_is_degenerate(uv):
    us = [u for u, _ in uv]; vs = [v for _, v in uv]
    return bool(uv) and max(us) - min(us) < 1e-6 and max(vs) - min(vs) < 1e-6


def _extract_uvs(m, n):
    src = 'none'
    uv = None
    tc = getattr(m, 'texcoords', None)
    if len(UV_DEBUG) < 6:
        UV_DEBUG.append('texcoords=%s vertex_count=%s uv_set_count=%s n_pos=%d' % (
            _describe(tc) if tc is not None else None, getattr(m, 'vertex_count', '?'),
            getattr(m, 'uv_set_count', '?'), n))
    try:
        uv = _try_uv_layouts(tc, n)
        if uv:
            src = 'texcoords'
    except Exception:
        uv = None
    if not uv:
        raw = getattr(m, 'texcoords_as_bytes', None)
        try:
            if raw and len(raw) >= n * 8:
                vals = struct.unpack('<%df' % (n * 2), bytes(raw)[:n * 8])
                uv = [(vals[2 * i], vals[2 * i + 1]) for i in range(n)]
                src = 'bytes'
        except Exception:
            uv = None
    if uv:
        bad = any((u != u) or (v != v) or abs(u) > 1e6 or abs(v) > 1e6 for u, v in uv)
        if bad:
            uv = None
    if not uv:
        STATS['uv_missing'] += 1
        STATS['uv_src']['none'] = STATS['uv_src'].get('none', 0) + 1
        return [(0.0, 0.0)] * n, False
    us = [u for u, _ in uv]; vs = [v for _, v in uv]
    if max(us) - min(us) < 1e-6 and max(vs) - min(vs) < 1e-6:
        STATS['uv_degenerate'] += 1
    else:
        STATS['uv_ok'] += 1
    STATS['uv_src'][src] = STATS['uv_src'].get(src, 0) + 1
    return uv, True


_COLOR_HINTS = (
    (('sand', 'beach', 'shore'), (0.86, 0.78, 0.60)),
    (('grass', 'gras', 'lawn', 'park', 'field'), (0.30, 0.45, 0.20)),
    (('dirt', 'soil', 'mud', 'earth'), (0.42, 0.33, 0.22)),
    (('road', 'asph', 'tarmac', 'street'), (0.25, 0.25, 0.27)),
    (('pave', 'side', 'conc', 'cement', 'step', 'kerb', 'curb', 'stone', 'brick'), (0.62, 0.60, 0.56)),
    (('roof',), (0.55, 0.32, 0.25)),
    (('water', 'sea', 'ocean'), (0.10, 0.45, 0.55)),
    (('glass', 'win'), (0.35, 0.50, 0.60)),
    (('black',), (0.05, 0.05, 0.05)),
    (('white',), (0.92, 0.92, 0.92)),
    (('leaf', 'palm', 'tree', 'plant', 'fern', 'ivy', 'bush', 'hedge'), (0.20, 0.42, 0.18)),
    (('bark', 'wood', 'fence'), (0.40, 0.28, 0.18)),
    (('metal', 'alum', 'steel', 'rust'), (0.50, 0.52, 0.55)),
)


def _guess_color(name):
    """Placeholder colour for a texture that could not be found (by name hint)."""
    n = (name or '').lower()
    for keys, col in _COLOR_HINTS:
        if any(k in n for k in keys):
            return col + (1.0,)
    return None


def _norm_tex_name(value):
    if not isinstance(value, str):
        return ""
    value = value.strip().replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    if value.lower().endswith((".png", ".dds", ".txd")):
        value = Path(value).stem
    return value.casefold()


def _texture_name(mesh):
    for attr in ("texture_name", "material_name", "texture", "name"):
        value = getattr(mesh, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for attr in ("material", "materials"):
        value = getattr(mesh, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)) and value:
            item = value[0]
            for sub in ("texture_name", "name", "texture"):
                v = getattr(item, sub, None)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return ""


def _finite3(v):
    return math.isfinite(v[0]) and math.isfinite(v[1]) and math.isfinite(v[2])


def sanitize_record(rec):
    """Drop triangles that touch non-finite vertices, remove unreferenced
    vertices, replace NaN normals/uv/colours.  Returns the record or None.
    A single NaN/Inf in a GLB makes Godot's importer produce garbage or fail,
    and a failed chunk GLB is silently replaced by the LOD GLB in the streamer."""
    P = rec['positions']; N = rec['normals']; U = rec['uv']; C = rec['colors']
    n = len(P)
    ok = [_finite3(v) and abs(v[0]) < 1e6 and abs(v[1]) < 1e6 and abs(v[2]) < 1e6 for v in P]
    used = {}
    idx = []
    ind = rec['indices']
    for i in range(0, len(ind) - 2, 3):
        a, b, c = ind[i], ind[i + 1], ind[i + 2]
        if not (0 <= a < n and 0 <= b < n and 0 <= c < n):
            continue
        if not (ok[a] and ok[b] and ok[c]):
            continue
        for k in (a, b, c):
            if k not in used:
                used[k] = len(used)
        idx.extend((used[a], used[b], used[c]))
    if not idx:
        return None
    order = sorted(used, key=used.get)
    out = dict(rec)
    out['positions'] = [P[k] for k in order]
    nn = []
    for k in order:
        v = N[k] if k < len(N) else (0.0, 1.0, 0.0)
        nn.append(tuple(x if math.isfinite(x) else 0.0 for x in v[:3]) if _finite3(v) else (0.0, 1.0, 0.0))
    out['normals'] = nn
    uu = []
    for k in order:
        v = U[k] if k < len(U) else (0.0, 0.0)
        uu.append((float(v[0]) if math.isfinite(v[0]) and abs(v[0]) < 1e6 else 0.0,
                   float(v[1]) if math.isfinite(v[1]) and abs(v[1]) < 1e6 else 0.0))
    out['uv'] = uu
    cc = []
    for k in order:
        v = C[k] if C and k < len(C) else DEFAULT_COLOR
        cc.append(tuple(x if math.isfinite(x) else 1.0 for x in v[:4]))
    out['colors'] = cc
    out['indices'] = idx
    return out


def mesh_records(meshes, texture_map=None, label=''):
    """Convert rwfury GenericMesh objects to lightweight Python records.

    No GLB is written here: the importer merges many GTA objects into one GLB
    per world chunk. Besides positions/uv this now keeps prelit vertex colours
    (this is what gives Vice City its look), computes normals when the DFF has
    none, and removes broken triangles.
    """
    texture_map = {_norm_tex_name(k): Path(v) for k, v in (texture_map or {}).items()}
    records = []
    for mi, m in enumerate(meshes):
        pos = _triples(getattr(m, "positions", None))
        if not pos:
            continue
        mx = _flat_matrix(getattr(m, "transform", None))
        kind = _matrix_kind(mx)
        if kind:
            pos = [_matrix_transform_point(mx, v, kind) for v in pos]
        inds = _indices(getattr(m, "indices", None))
        if not inds:
            continue
        inds = _clean_triangles(pos, inds, label, _texture_name(m))
        if not inds:
            continue
        raw_normals = getattr(m, "normals", None)
        nor = _triples(raw_normals) if raw_normals is not None and len(raw_normals) else []
        if len(nor) != len(pos) or all(abs(n[0]) + abs(n[1]) + abs(n[2]) < 1e-9 for n in nor[:8]):
            nor = _smooth_normals(pos, inds)
            STATS['computed_normals'] += 1
        elif kind:
            nor = [_matrix_transform_normal(mx, v, kind) for v in nor]
        uv, _uv_ok = _extract_uvs(m, len(pos))
        cols = _vertex_colors(m, len(pos))
        STATS['meshes'] += 1
        if cols:
            STATS['with_colors'] += 1
        else:
            cols = [DEFAULT_COLOR] * len(pos)
        tex_name = _texture_name(m)
        path = texture_map.get(_norm_tex_name(tex_name)) if tex_name else None
        if tex_name and path is None:
            UNTEXTURED[tex_name] = UNTEXTURED.get(tex_name, 0) + 1
        elif not tex_name:
            UNTEXTURED['<none>'] = UNTEXTURED.get('<none>', 0) + 1
        fb = _guess_color(tex_name) if path is None else None
        if fb and not any(abs(c - d) > 1e-3 for c, d in zip(cols[0], DEFAULT_COLOR)):
            # no prelit data + no texture: tint by name instead of neutral grey
            cols = [fb] * len(pos)
        if path is not None and _uv_is_degenerate(uv):
            DEGEN_UV[tex_name] = DEGEN_UV.get(tex_name, 0) + 1
        rec = sanitize_record({"positions": pos, "normals": nor, "uv": uv, "colors": cols, "indices": inds,
                        "texture": path, "texture_name": tex_name, "mesh_name": f"mesh_{mi}",
                        "diffuse_color": getattr(m, "diffuse_color", None)})
        if rec is not None:
            records.append(rec)
    return records


@lru_cache(maxsize=None)
def _alpha_of(path):
    """(has_any_transparent_pixel)"""
    if not path:
        return False
    try:
        with PILImage.open(path) as im:
            if 'A' in im.getbands():
                return im.getchannel('A').getextrema()[0] < 255
    except Exception:
        pass
    return False


def _material_color(col):
    """RenderWare material colour -> RGBA floats, or None if white/unusable."""
    if not isinstance(col, (list, tuple)) or len(col) < 3:
        return None
    try:
        vals = [float(x) for x in col[:4]]
    except Exception:
        return None
    if max(vals[:3]) > 1.0:
        vals = [x / 255.0 for x in vals]
    vals = vals[:3] + [1.0]
    if min(vals[:3]) > 0.98:
        return None
    return vals


def export_records(records, out: Path):
    """Write ONE GLB for a whole chunk.

    Records that share texture + material colour are merged into one primitive.
    Materials are KHR_materials_unlit: Vice City is lit by baked (prelit)
    vertex colours, so vertex colour x texture is exactly the original look.
    Everything is double sided because DFF triangle winding is not reliable.
    """
    out = Path(out)
    single_sided = os.environ.get('VC2GODOT_SINGLE_SIDED') == '1'
    groups = {}
    clean = []
    for r in records:
        r2 = sanitize_record(r)      # placed records can get NaN from bad quaternions/scales
        if r2 is not None:
            clean.append(r2)
    records = clean
    for r in records:
        tex = r.get('texture')
        col = _material_color(r.get('diffuse_color'))
        key = (str(tex).lower() if tex else '', tuple(round(c, 3) for c in col) if col else None)
        groups.setdefault(key, []).append(r)

    blob = bytearray(); views = []; accessors = []
    images = []; textures = []; materials = []; meshes = []; nodes = []
    img_index = {}

    def add_view(data, target):
        blob.extend(b'\0' * ((4 - len(blob) % 4) % 4))
        off = len(blob); blob.extend(data)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        return len(views) - 1

    def add_acc(view, comp, typ, count, mn=None, mx=None):
        a = {"bufferView": view, "componentType": comp, "count": count, "type": typ}
        if mn is not None: a["min"] = mn
        if mx is not None: a["max"] = mx
        accessors.append(a); return len(accessors) - 1

    def tex_index(path):
        key = str(path).lower()
        if key in img_index:
            return img_index[key]
        try:
            rel = os.path.relpath(Path(path).resolve(), out.parent.resolve()).replace('\\', '/')
        except Exception:
            rel = str(path)
        images.append({"uri": quote(rel, safe="/._-"), "name": Path(path).stem})
        textures.append({"sampler": 0, "source": len(images) - 1, "name": Path(path).stem})
        img_index[key] = len(textures) - 1
        return img_index[key]

    for (texkey, col), recs in groups.items():
        pos = array('f'); nor = array('f'); uvs = array('f'); cls = array('f'); idx = array('I')
        base = 0
        for r in recs:
            P = r['positions']; N = r['normals']; U = r['uv']
            C = r.get('colors') or [DEFAULT_COLOR] * len(P)
            for v in P: pos.extend(v)
            for v in N: nor.extend(v)
            for v in U: uvs.extend((v[0], v[1]))     # glTF V-down == RenderWare V-down -> no flip
            for v in C: cls.extend(v)
            idx.extend([i + base for i in r['indices']])
            base += len(P)
        if not len(idx):
            continue
        if sys.byteorder != 'little':
            pos.byteswap(); nor.byteswap(); uvs.byteswap(); cls.byteswap(); idx.byteswap()
        if not all(math.isfinite(x) for x in pos):
            raise ValueError('non-finite POSITION in %s' % out)
        xs = pos[0::3]; ys = pos[1::3]; zs = pos[2::3]
        pmin = [min(xs), min(ys), min(zs)]; pmax = [max(xs), max(ys), max(zs)]
        pa = add_acc(add_view(pos.tobytes(), 34962), 5126, "VEC3", base, pmin, pmax)
        na = add_acc(add_view(nor.tobytes(), 34962), 5126, "VEC3", base)
        ua = add_acc(add_view(uvs.tobytes(), 34962), 5126, "VEC2", base)
        ca = add_acc(add_view(cls.tobytes(), 34962), 5126, "VEC4", base)
        ia = add_acc(add_view(idx.tobytes(), 34963), 5125, "SCALAR", len(idx))

        pbr = {"baseColorFactor": list(col) if col else [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0, "roughnessFactor": 1.0}
        mat = {"name": recs[0].get('texture_name') or 'default', "pbrMetallicRoughness": pbr,
               "doubleSided": not single_sided,
               "extensions": {"KHR_materials_unlit": {}}}
        tpath = recs[0].get('texture')
        if tpath and not Path(str(tpath)).is_file():
            tpath = None
        if tpath:
            pbr["baseColorTexture"] = {"index": tex_index(tpath)}
            if _alpha_of(str(tpath)):
                mat["alphaMode"] = "MASK"; mat["alphaCutoff"] = 0.5
        materials.append(mat)
        meshes.append({"name": mat["name"], "primitives": [{
            "attributes": {"POSITION": pa, "NORMAL": na, "TEXCOORD_0": ua, "COLOR_0": ca},
            "indices": ia, "material": len(materials) - 1}]})
        nodes.append({"mesh": len(meshes) - 1, "name": mat["name"]})

    doc = {"asset": {"version": "2.0", "generator": "VC2Godot 0.6"},
           "extensionsUsed": ["KHR_materials_unlit"],
           "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "materials": materials,
           "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors}
    if textures:
        doc["images"] = images; doc["textures"] = textures
        doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    js = json.dumps(doc, separators=(',', ':'), allow_nan=False).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    binb = bytes(blob) + b'\0' * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binb)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack('<II', len(binb), 0x004E4942)); f.write(binb)
    return out


def validate_glb(path, project_root=None):
    """Independent strict re-read of an exported GLB.  Returns (problems, stats).
    Mirrors what Godot's glTF importer requires, so a chunk that fails here is
    a chunk that would silently turn into LOD in the game."""
    problems = []; stats = {'bytes': 0, 'verts': 0, 'tris': 0, 'prims': 0, 'images': 0}
    path = Path(path)
    try:
        b = path.read_bytes()
        stats['bytes'] = len(b)
        magic, ver, total = struct.unpack_from('<III', b, 0)
        if magic != 0x46546C67 or ver != 2 or total != len(b):
            problems.append('bad GLB header/length')
            return problems, stats
        jl, jt = struct.unpack_from('<II', b, 12)
        def _bad(c):
            raise ValueError('non-finite JSON constant ' + c)
        doc = json.loads(b[20:20 + jl].decode('utf-8'), parse_constant=_bad)
        bl, bt = struct.unpack_from('<II', b, 20 + jl)
        blen = doc['buffers'][0]['byteLength']
        if blen > bl:
            problems.append('buffer longer than BIN chunk')
        acc = doc['accessors']; views = doc['bufferViews']
        sizes = {5126: 4, 5125: 4, 5123: 2}; comps = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
        for i, a in enumerate(acc):
            v = views[a['bufferView']]
            need = a['count'] * comps[a['type']] * sizes[a['componentType']]
            if a.get('byteOffset', 0) + need > v['byteLength'] or v['byteOffset'] + v['byteLength'] > blen:
                problems.append('accessor %d out of range' % i)
            for key in ('min', 'max'):
                if key in a and not all(math.isfinite(x) for x in a[key]):
                    problems.append('accessor %d %s not finite' % (i, key))
        base = 20 + jl + 8
        for mi, m in enumerate(doc['meshes']):
            for pr in m['primitives']:
                stats['prims'] += 1
                cnt = acc[pr['attributes']['POSITION']]['count']
                for name, ai in pr['attributes'].items():
                    if acc[ai]['count'] != cnt:
                        problems.append('mesh %d attribute %s count mismatch' % (mi, name))
                ia = acc[pr['indices']]
                if ia['count'] % 3:
                    problems.append('mesh %d index count not multiple of 3' % mi)
                v = views[ia['bufferView']]
                off = base + v['byteOffset'] + ia.get('byteOffset', 0)
                idx = array('I'); idx.frombytes(b[off:off + ia['count'] * 4])
                if idx and max(idx) >= cnt:
                    problems.append('mesh %d index >= vertex count' % mi)
                fa = acc[pr['attributes']['POSITION']]; fv = views[fa['bufferView']]
                fo = base + fv['byteOffset'] + fa.get('byteOffset', 0)
                fl = array('f'); fl.frombytes(b[fo:fo + cnt * 12])
                if not all(math.isfinite(x) for x in fl):
                    problems.append('mesh %d has non-finite positions' % mi)
                stats['verts'] += cnt; stats['tris'] += ia['count'] // 3
        root = path.parent
        for im in doc.get('images', []):
            from urllib.parse import unquote
            q = (root / unquote(im['uri'])).resolve()
            stats['images'] += 1
            if not q.is_file():
                problems.append('missing image ' + im['uri'])
        if stats['verts'] == 0:
            problems.append('GLB has no geometry')
    except Exception as e:
        problems.append('%s: %s' % (type(e).__name__, e))
    return problems, stats
