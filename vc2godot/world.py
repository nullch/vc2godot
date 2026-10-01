from __future__ import annotations
from pathlib import Path
import copy, json, math, os, struct
from .coords import vc_vec3
from .gltf import mesh_records, export_records, validate_glb, sanitize_record, STATS as MESH_STATS, UV_DEBUG, UNTEXTURED, DEGEN_UV, SPIKE_LOG


def _quat_matrix(x, y, z, w):
    n = x*x + y*y + z*z + w*w
    if n < 1e-12:
        return ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    s = 2.0 / n
    xx, yy, zz = x*x*s, y*y*s, z*z*s
    xy, xz, yz = x*y*s, x*z*s, y*z*s
    wx, wy, wz = w*x*s, w*y*s, w*z*s
    return ((1-yy-zz, xy-wz, xz+wy), (xy+wz, 1-xx-zz, yz-wx), (xz-wy, yz+wx, 1-xx-yy))


def placement_matrix(p):
    # Keep the quaternion convention from the working 0.5.0 importer.
    return _quat_matrix(-p.qx, -p.qy, -p.qz, p.qw)


def _transform_record(rec, p):
    r = placement_matrix(p)
    sx, sy, sz = p.sx or 1.0, p.sy or 1.0, p.sz or 1.0
    pos = []
    for v in rec['positions']:
        x, y, z = v[0]*sx, v[1]*sy, v[2]*sz
        gx = r[0][0]*x + r[0][1]*y + r[0][2]*z + p.x
        gy = r[1][0]*x + r[1][1]*y + r[1][2]*z + p.y
        gz = r[2][0]*x + r[2][1]*y + r[2][2]*z + p.z
        pos.append((gx, gz, -gy))
    nor = []
    for v in rec['normals']:
        x, y, z = v[0]/sx, v[1]/sy, v[2]/sz
        gx = r[0][0]*x + r[0][1]*y + r[0][2]*z
        gy = r[1][0]*x + r[1][1]*y + r[1][2]*z
        gz = r[2][0]*x + r[2][1]*y + r[2][2]*z
        l = (gx*gx + gy*gy + gz*gz) ** 0.5 or 1.0
        nor.append((gx/l, gz/l, -gy/l))
    out = dict(rec)
    out['positions'] = pos
    out['normals'] = nor
    if sx * sy * sz < 0:
        ind = list(rec['indices'])
        for i in range(0, len(ind) - 2, 3):
            ind[i+1], ind[i+2] = ind[i+2], ind[i+1]
        out['indices'] = ind
    return out


def _box_triangles(bmin, bmax):
    x0, y0, z0 = bmin; x1, y1, z1 = bmax
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    tri = [0,1,2,0,2,3,4,6,5,4,7,6,0,4,5,0,5,1,1,5,6,1,6,2,2,6,7,2,7,3,4,0,3,4,3,7]
    return [v[i] for i in tri]


def _sphere_triangles(center, radius, segments=12, rings=6):
    cx, cy, cz = center; verts = []
    for r in range(rings + 1):
        phi = math.pi * r / rings; sp = math.sin(phi); cp = math.cos(phi)
        for s in range(segments):
            th = 2 * math.pi * s / segments
            verts.append((cx + radius*sp*math.cos(th), cy + radius*cp, cz + radius*sp*math.sin(th)))
    tri = []
    for r in range(rings):
        for s in range(segments):
            a = r*segments+s; b = r*segments+(s+1)%segments; c = (r+1)*segments+(s+1)%segments; d = (r+1)*segments+s
            tri.extend((verts[a], verts[b], verts[c], verts[a], verts[c], verts[d]))
    return tri


def _face_indices(face):
    for names in (('a','b','c'), ('i1','i2','i3'), ('v1','v2','v3')):
        if all(hasattr(face, n) for n in names):
            return tuple(int(getattr(face, n)) for n in names)
    vals = getattr(face, 'indices', None)
    if isinstance(vals, (tuple, list)) and len(vals) >= 3:
        return int(vals[0]), int(vals[1]), int(vals[2])
    return None


def _transform_point(v, p):
    r = placement_matrix(p)
    sx, sy, sz = p.sx or 1.0, p.sy or 1.0, p.sz or 1.0
    x, y, z = v[0] * sx, v[1] * sy, v[2] * sz
    gx = r[0][0]*x + r[0][1]*y + r[0][2]*z + p.x
    gy = r[1][0]*x + r[1][1]*y + r[1][2]*z + p.y
    gz = r[2][0]*x + r[2][1]*y + r[2][2]*z + p.z
    return (gx, gz, -gy)


def collision_triangles(model, p):
    if model is None:
        return []
    tris = []
    verts = getattr(model, 'vertices', []) or []
    for f in getattr(model, 'faces', []) or []:
        ids = _face_indices(f)
        if ids and all(0 <= i < len(verts) for i in ids):
            tris.extend((verts[ids[0]], verts[ids[1]], verts[ids[2]]))
    for b in getattr(model, 'boxes', []) or []:
        try:
            tris.extend(_box_triangles(b.min, b.max))
        except AttributeError:
            pass
    for s in getattr(model, 'spheres', []) or []:
        try:
            tris.extend(_sphere_triangles(s.center, s.radius))
        except AttributeError:
            pass
    return [_transform_point(v, p) for v in tris]


def _write_collision_bin(path, faces):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sI', b'VCOL', len(faces)))
        for x, y, z in faces:
            f.write(struct.pack('<3f', x, y, z))


_LOD_PREFIXES = ('lod', 'islandlod')


def is_lod(name):
    """Vice City LOD models: LODxxx (city blocks) and IslandLODxxx (huge low-res
    ground/sea-floor terrain of the whole island, textured from IslandLODmainland)."""
    return str(name or '').lower().startswith(_LOD_PREFIXES)


# --- 0.6.10: base terrain (sea floor / ground under the detailed world) -------------------------
# IslandLOD* is the ONLY ground under the bay/beach water in Vice City.  Since 0.6.4 it is drawn
# only in the far LOD ring, so near the camera the sea had no floor at all (sky colour showed
# through, only alpha-cut decals such as grass patches were left floating).  The detailed chunk
# now also carries a lowered copy of it, so it lies UNDER every real road/pavement/sand piece.
_BASE_DROP = float(os.environ.get('VC2GODOT_BASE_DROP', '4.0'))      # metres the copy is lowered
_BASE_MAX_Z = float(os.environ.get('VC2GODOT_BASE_MAX_Z', '8.0'))    # keep triangles whose lowest point is <= this (GTA z)
_BASE_MODE = os.environ.get('VC2GODOT_BASE', 'off').lower()          # on | off  (off since 0.6.11: IslandLOD is a coarse sheet at/above water level, not a sea floor)


def is_base_terrain(name):
    return str(name or '').lower().startswith('islandlod')


def make_base_record(rec, drop=None, max_z=None):
    """Placed record (Godot axes, y up) -> copy lowered by `drop` m that keeps only the sea/shore
    triangles (lowest vertex <= max_z).  Returns None when nothing is left."""
    drop = _BASE_DROP if drop is None else drop
    max_z = _BASE_MAX_Z if max_z is None else max_z
    P = rec['positions']; ind = rec['indices']
    keep = []
    for i in range(0, len(ind) - 2, 3):
        a, b, c = ind[i], ind[i + 1], ind[i + 2]
        if min(P[a][1], P[b][1], P[c][1]) <= max_z:
            keep.extend((a, b, c))
    if not keep:
        return None
    out = dict(rec)
    out['positions'] = [(x, y - drop, z) for x, y, z in P]
    out['indices'] = keep
    return sanitize_record(out)


def _model_kind(p, obj, lod_ids):
    # Do NOT use draw distance as a proxy for LOD. Ordinary VC buildings often
    # have draw distances >300m; treating those as LOD deletes large parts of the city.
    if is_lod(obj.model) or is_lod(p.model):
        return 'lod'
    return 'high'



_TWIN_DIST = float(os.environ.get('VC2GODOT_TWIN_DIST', '1.5'))


def find_exterior_areas(placements, ides):
    """Detect outdoor IPL area groups that are stored with a non-zero ``interior`` id.

    Vice City uses the ``interior`` field as an area/visibility id, and some outdoor
    blocks are stored exactly like interiors.  The reliable marker is a LOD twin at
    (almost) the same transform.  Importantly, that LOD twin is *not guaranteed to
    have interior=0*: Ocean Beach uses pairs such as ``oceanrda05_*`` /
    ``LODanrda05_*`` with the same non-zero area id.  The old importer only looked
    for LOD twins with interior=0, so those outdoor ground strips were dropped and
    the corresponding district appeared as a hole.

    In auto mode a group is shown when at least one non-LOD placement has a nearby
    LOD placement from the same IPL source, regardless of the LOD placement's own
    interior value.  ``VC2GODOT_INTERIORS=none`` restores the old filtering, and
    ``all`` shows every non-zero interior group.
    """
    mode = os.environ.get('VC2GODOT_INTERIORS', 'auto').lower()
    if mode == 'none':
        return set(), []
    groups = {}
    # Index every LOD placement, not only interior=0.  Some genuine outdoor
    # ground/road LODs in Ocean Beach keep the same non-zero area id as their HD pair.
    lods = {}
    for p in placements:
        o = ides.get(p.object_id)
        name = o.model if o else p.model
        if is_lod(name) or is_lod(p.model):
            lods.setdefault((p.source, int(p.x // 8), int(p.y // 8)), []).append(p)
        elif p.interior != 0:
            groups.setdefault((p.source, p.interior), []).append((p, name))
    keep = set(); report = []
    for key, items in groups.items():
        twins = 0
        for p, name in items:
            found = False
            cx, cy = int(p.x // 8), int(p.y // 8)
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for l in lods.get((p.source, gx, gy), ()):
                        # A true twin normally keeps the same area id; old stock data also
                        # uses interior=0 for the LOD half, so accept that form too.
                        same_area = (l.interior == 0 or l.interior == p.interior)
                        if same_area and math.hypot(l.x - p.x, l.y - p.y) <= _TWIN_DIST and abs(l.z - p.z) <= 5.0:
                            found = True; break
                    if found: break
                if found: break
            twins += int(found)
        take = mode == 'all' or twins > 0
        if take:
            keep.add(key)
        report.append({'ipl': os.path.basename(key[0]), 'area': key[1], 'objects': len(items), 'lod_twins': twins,
                       'shown_in_world': bool(take), 'sample': sorted({n for _, n in items})[:6]})
    return keep, sorted(report, key=lambda r: (r['ipl'].lower(), r['area']))


_CELL = 8.0
EMPTY_MODELS = set()   # models for which rwfury/cleanup produced zero drawable meshes


def _model_bbox(converter, o, cache):
    """Model-space bounding box (VC axes) of a model, or None."""
    key = (o.model.casefold(), o.texture.casefold())
    if key in cache:
        return cache[key]
    box = None
    data = converter.meshes(o.model, o.texture)
    if data:
        meshes, texmap = data
        xs = []; ys = []; zs = []
        for rec in mesh_records(meshes, texmap):
            for v in rec['positions']:
                xs.append(v[0]); ys.append(v[1]); zs.append(v[2])
        if xs:
            box = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
    cache[key] = box
    return box


def _footprint(box, p):
    """Axis aligned XZ footprint (Godot axes) of a placed model bbox."""
    r = placement_matrix(p)
    sx, sy, sz = p.sx or 1.0, p.sy or 1.0, p.sz or 1.0
    gxs = []; gzs = []
    for x in (box[0], box[3]):
        for y in (box[1], box[4]):
            for z in (box[2], box[5]):
                x2, y2, z2 = x*sx, y*sy, z*sz
                gx = r[0][0]*x2 + r[0][1]*y2 + r[0][2]*z2 + p.x
                gy = r[1][0]*x2 + r[1][1]*y2 + r[1][2]*z2 + p.y
                gxs.append(gx); gzs.append(-gy)
    return min(gxs), min(gzs), max(gxs), max(gzs)


def _cells(fp):
    return (int(math.floor(fp[0] / _CELL)), int(math.floor(fp[1] / _CELL)),
            int(math.floor(fp[2] / _CELL)), int(math.floor(fp[3] / _CELL)))


def find_lod_only(entries, converter, log):
    """Vice City draws a LODxxx model only while its detailed counterpart is
    not loaded - but LOD models that have NO detailed counterpart are drawn at
    every distance, they are the only representation of that piece of the map
    (bridges, ground strips, ...).  The importer used to drop all of them from
    the near view, which leaves holes in some districts.

    entries: [(placement, ide_object, kind)].  Returns the set of ids (id(p))
    of LOD placements whose footprint is (almost) not covered by any detailed
    placement.  Those must be shown together with the detailed models.
    """
    if os.environ.get('VC2GODOT_LOD_FILL', '1') == '0':
        return set(), []
    cache = {}
    covered = set()
    lods = []
    for p, o, kind in entries:
        box = _model_bbox(converter, o, cache)
        if not box:
            continue
        fp = _footprint(box, p)
        if kind == 'high':
            x0, z0, x1, z1 = _cells(fp)
            if (x1 - x0 + 1) * (z1 - z0 + 1) > 40000:
                continue
            for ix in range(x0, x1 + 1):
                for iz in range(z0, z1 + 1):
                    covered.add((ix, iz))
        else:
            lods.append((p, o, fp))
    orphans = set(); report = []
    for p, o, fp in lods:
        x0, z0, x1, z1 = _cells(fp)
        nx, nz = x1 - x0 + 1, z1 - z0 + 1
        total = nx * nz
        if total > 40000:
            continue          # continent sized terrain LOD: always treated as paired
        step_x = max(1, nx // 20); step_z = max(1, nz // 20)
        seen = hit = 0
        for ix in range(x0, x1 + 1, step_x):
            for iz in range(z0, z1 + 1, step_z):
                seen += 1
                if (ix, iz) in covered:
                    hit += 1
        frac = hit / seen if seen else 1.0
        if frac < 0.10:
            orphans.add(id(p))
            report.append({'model': o.model, 'x': round(p.x, 1), 'y': round(p.y, 1), 'z': round(p.z, 1),
                           'footprint_m': [round((x1 - x0 + 1) * _CELL), round((z1 - z0 + 1) * _CELL)],
                           'hd_overlap': round(frac, 2)})
    return orphans, report


def _write_problems(out, entries, converter, ides):
    """data/problems.txt: every model that is placed in the world but produced NOTHING in the export
    (DFF missing in the IMG, DFF parse error, no drawable mesh) with the coordinates of its placements,
    plus every model that lost triangles as 'spikes'.  Send this file if a piece of the map is missing."""
    fails = getattr(converter, 'failures', {})
    by_model = {}
    for p, o, kind in entries:
        key = o.model.casefold()
        reason = fails.get(key) or ('no drawable mesh' if o.model in EMPTY_MODELS else None)
        if reason:
            by_model.setdefault((o.model, o.texture, reason), []).append((p.x, p.y, p.z, os.path.basename(p.source)))
    lines = ['MODELS PLACED IN THE WORLD BUT MISSING FROM THE EXPORT (model, txd, reason, placements, bbox of origins GTA x0,y0,x1,y1, sample):', '']
    for (model, txd, reason), pts in sorted(by_model.items(), key=lambda kv: (-len(kv[1]), kv[0][0].lower())):
        xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
        lines.append('%-28s %-18s %-40s n=%-4d bbox=(%d,%d,%d,%d) e.g. %s @ (%d,%d,%d)' % (
            model[:28], txd[:18], reason[:40], len(pts), min(xs), min(ys), max(xs), max(ys), pts[0][3], pts[0][0], pts[0][1], pts[0][2]))
    if not by_model:
        lines.append('(none)')
    lines += ['', 'TRIANGLES DROPPED AS SPIKES (model, texture, edge m, limit m):', '']
    lines += [str(x) for x in SPIKE_LOG[:200]] or ['(none)']
    (out / 'data/problems.txt').write_text('\n'.join(lines), encoding='utf-8')


def build_chunks(out, placements, ides, converter, chunk_size, log, export_collision=True):
    stats = {'lod': 0, 'interior': 0, 'no_ide': 0, 'no_dff': 0, 'collision_models': 0}
    lod_ids = {p.lod for p in placements if p.lod >= 0}
    entries = []
    ext_areas, area_report = find_exterior_areas(placements, ides)
    stats['interior_shown'] = 0
    for p in placements:
        o = ides.get(p.object_id)
        if not o:
            stats['no_ide'] += 1
            continue
        if p.interior != 0:
            kind0 = _model_kind(p, o, lod_ids)
            if (p.source, p.interior) in ext_areas and kind0 == 'high':
                stats['interior_shown'] += 1          # outdoor piece stored under an area id (Print Works yard, ...)
            else:
                stats['interior'] += 1
                continue
        entries.append((p, o, _model_kind(p, o, lod_ids)))
    log.info('INTERIOR AREAS (ipl, area, objects, lod_twins, shown): %s',
             [(r['ipl'], r['area'], r['objects'], r['lod_twins'], r['shown_in_world']) for r in area_report])

    orphans, orphan_report = find_lod_only(entries, converter, log)
    stats['lod_only_shown'] = len(orphans)
    chunks = {}
    for p, o, kind in entries:
        if kind == 'lod':
            stats['lod'] += 1
            if id(p) in orphans:
                kind = 'high'     # no detailed counterpart -> it IS the near model
        x, _, z = vc_vec3((p.x, p.y, p.z))
        chunks.setdefault((math.floor(x / chunk_size), math.floor(z / chunk_size)), {'high': [], 'lod': [], 'base': []})[kind].append(p)
        if kind == 'lod' and _BASE_MODE != 'off' and (is_base_terrain(o.model) or is_base_terrain(p.model)):
            chunks[(math.floor(x / chunk_size), math.floor(z / chunk_size))]['base'].append(p)

    log.info('placements skipped: %s', stats)
    chunk_dir = out / 'world/chunks'; collision_dir = out / 'world/collision'
    chunk_dir.mkdir(parents=True, exist_ok=True)
    if export_collision:
        collision_dir.mkdir(parents=True, exist_ok=True)

    result = {}
    glb_problems = {}; glb_stats = {}
    minx = minz = 10**9; maxx = maxz = -10**9
    totals = {'high': 0, 'lod': 0, 'collision_faces': 0}

    for n, ((cx, cz), sets) in enumerate(sorted(chunks.items()), 1):
        high_records, lod_records, collision_faces = [], [], []
        for kind in ('high', 'lod', 'base'):
            items = sets[kind]
            if not items:
                continue
            records = lod_records if kind == 'lod' else high_records
            unique = {}
            for p in items:
                o = ides.get(p.object_id)
                if o:
                    unique.setdefault((o.model.casefold(), o.texture.casefold()), o)
            for o in unique.values():
                data = converter.meshes(o.model, o.texture)
                if not data:
                    stats['no_dff'] += 1
                    continue
                meshes, texmap = data
                base = mesh_records(meshes, texmap, o.model)
                if not base:
                    stats['empty_models'] = stats.get('empty_models', 0) + 1
                    EMPTY_MODELS.add(o.model)
                for p in items:
                    po = ides.get(p.object_id)
                    if not po or po.model.casefold() != o.model.casefold() or po.texture.casefold() != o.texture.casefold():
                        continue
                    for rec in base:
                        placed = _transform_record(copy.deepcopy(rec), p)
                        if kind == 'base':
                            placed = make_base_record(placed)
                            if placed is None:
                                continue
                            stats['base_meshes'] = stats.get('base_meshes', 0) + 1
                        records.append(placed)
                    if kind == 'high' and export_collision:
                        cm = converter.collision(o.model)
                        if cm is not None:
                            stats['collision_models'] += 1
                            collision_faces.extend(collision_triangles(cm, p))

        paths = {}
        if high_records:
            gp = chunk_dir / f'chunk_{cx}_{cz}.glb'; export_records(high_records, gp); paths['high'] = gp.relative_to(out).as_posix()
            pr, st = validate_glb(gp); glb_stats[gp.name] = st
            if pr:
                glb_problems[gp.name] = pr; log.error('GLB INVALID %s: %s', gp.name, pr[:5])
        if lod_records:
            gp = chunk_dir / f'chunk_{cx}_{cz}_lod.glb'; export_records(lod_records, gp); paths['lod'] = gp.relative_to(out).as_posix()
            pr, st = validate_glb(gp); glb_stats[gp.name] = st
            if pr:
                glb_problems[gp.name] = pr; log.error('GLB INVALID %s: %s', gp.name, pr[:5])
        if export_collision and collision_faces:
            cp = collision_dir / f'chunk_{cx}_{cz}.bin'; _write_collision_bin(cp, collision_faces); paths['collision'] = cp.relative_to(out).as_posix()

        if paths:
            result[f'{cx},{cz}'] = {
                'objects': len(sets['high']) + len(sets['lod']),
                'high_objects': len(sets['high']), 'lod_objects': len(sets['lod']),
                'high_meshes': len(high_records), 'lod_meshes': len(lod_records),
                'collision_faces': len(collision_faces), 'paths': paths,
            }
            minx, minz = min(minx, cx), min(minz, cz); maxx, maxz = max(maxx, cx), max(maxz, cz)
        totals['high'] += len(high_records); totals['lod'] += len(lod_records); totals['collision_faces'] += len(collision_faces)
        log.info('CHUNK [%d/%d] %d,%d highObj=%d lodObj=%d highMeshes=%d lodMeshes=%d collisionTris=%d', n, len(chunks), cx, cz, len(sets['high']), len(sets['lod']), len(high_records), len(lod_records), len(collision_faces)//3)

    center = {'x': ((minx + maxx + 1) * chunk_size / 2 if result else 0.0), 'z': ((minz + maxz + 1) * chunk_size / 2 if result else 0.0)}
    meta = {'chunk_size': chunk_size, 'center': center, 'chunk_count': len(result), 'high_meshes': totals['high'], 'lod_meshes': totals['lod'], 'collision_triangles': totals['collision_faces']//3, 'stats': stats}
    (out/'data').mkdir(parents=True, exist_ok=True)
    (out/'data/chunks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (out/'data/world_meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    converter.report()
    log.info('placement stats after export: %s', stats)
    log.info('BASE TERRAIN (IslandLOD copy lowered %.1f m, triangles with lowest z <= %.1f) meshes added to detailed chunks: %d  [mode=%s]', _BASE_DROP, _BASE_MAX_Z, stats.get('base_meshes', 0), _BASE_MODE)
    log.info('LOD-ONLY pieces added to near view: %d (first 40): %s', len(orphan_report), orphan_report[:40])
    _write_problems(out, entries, converter, ides)
    if SPIKE_LOG:
        log.warning('SPIKE triangles dropped: %d (model, texture, edge m, limit m): %s', MESH_STATS.get('spike', 0), SPIKE_LOG[:40])
    if EMPTY_MODELS:
        log.warning('%d models produced NO drawable mesh (they will be invisible): %s', len(EMPTY_MODELS), sorted(EMPTY_MODELS)[:80])
    (out/'data/diagnostics.json').write_text(json.dumps({'stats': stats, 'lod_only_shown': orphan_report,
        'glb_problems': glb_problems, 'glb_stats': glb_stats, 'interior_areas': area_report,
        'spikes_dropped': SPIKE_LOG[:200], 'empty_models': sorted(EMPTY_MODELS), 'mesh_cleanup': dict(MESH_STATS)}, indent=2), encoding='utf-8')
    log.info('GLB VALIDATION: %d files checked, %d with problems %s', len(glb_stats), len(glb_problems), sorted(glb_problems)[:20])
    big = sorted(glb_stats.items(), key=lambda kv: -kv[1]['bytes'])[:8]
    log.info('BIGGEST GLBs (name, MB, verts, images): %s', [(k, round(v['bytes']/1e6, 1), v['verts'], v['images']) for k, v in big])
    log.info('MESH CLEANUP: %s', dict(MESH_STATS))
    top = sorted(UNTEXTURED.items(), key=lambda kv: -kv[1])[:40]
    log.info('UNTEXTURED meshes (texture name -> count): %s', top)
    top = sorted(DEGEN_UV.items(), key=lambda kv: -kv[1])[:40]
    log.info('DEGENERATE-UV textures (name -> count): %s', top)
    for d in UV_DEBUG:
        log.info('UV DEBUG: %s', d)
    return result, center
