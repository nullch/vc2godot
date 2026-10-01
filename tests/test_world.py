import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import json, struct, logging
from pathlib import Path
from PIL import Image
from vc2godot.ipl import Placement
from vc2godot.ide import IdeObject
from vc2godot.gltf import mesh_records, export_records
from vc2godot.world import _transform_record, build_chunks, is_lod


class M:  # fake rwfury GenericMesh: a 2x1 wall in the XZ plane facing -Y (GTA space)
    positions = [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)]
    normals = [(0, -1, 0)] * 4
    texcoords = [(0, 0), (1, 0), (1, 1), (0, 1)]
    indices = [0, 1, 2, 0, 2, 3]
    texture_name = 'wall'
    diffuse_color = (255, 255, 255, 255)
    transform = None


def test_ipl_rotation_is_conjugated():
    # IPL quaternion for a 90deg turn is stored inverted; +90 stored as (0,0,-s,c)
    s = 0.70710678
    p = Placement(1, 0, 0, 0, 0, 0, -s, s, model='x')
    rec = _transform_record(mesh_records([M()])[0], p)
    # +90 deg about Z (GTA): (2,0,0) -> (0,2,0) -> Godot (0,0,-2)
    x, y, z = rec['positions'][1]
    assert abs(x) < 1e-5 and abs(z + 2) < 1e-5 and abs(y) < 1e-5


def test_lod_detection():
    assert is_lod('LODbuild1') and not is_lod('hotel1')


def test_glb_roundtrip(tmp_path):
    tex = tmp_path / 'assets/textures/generic'; tex.mkdir(parents=True)
    Image.new('RGBA', (4, 4), (255, 0, 0, 255)).save(tex / 'wall.png')
    rec = mesh_records([M()], {'wall': tex / 'wall.png'})
    recs = [_transform_record(rec[0], Placement(1, 10 * i, 0, 0, 0, 0, 0, 1, model='x')) for i in range(50)]
    glb = tmp_path / 'world/chunks/c.glb'
    export_records(recs, glb)
    b = glb.read_bytes()
    magic, ver, total = struct.unpack_from('<III', b, 0)
    assert magic == 0x46546C67 and ver == 2 and total == len(b)
    jl, jt = struct.unpack_from('<II', b, 12)
    doc = json.loads(b[20:20 + jl])
    assert len(doc['meshes']) == 1                       # 50 wall instances merged into 1 primitive
    assert doc['accessors'][0]['count'] == 200
    assert doc['images'][0]['uri'] == '../../assets/textures/generic/wall.png'
    bl, bt = struct.unpack_from('<II', b, 20 + jl)
    assert bl >= doc['buffers'][0]['byteLength']


class FakeConv:
    def meshes(self, m, t): return [M()], {}
    def report(self): pass
    def collision(self, m): return None


def test_build_chunks_skips_lod_and_interiors(tmp_path):
    ides = {1: IdeObject(1, 'hotel1', 'generic'), 2: IdeObject(2, 'lodhotel', 'generic')}
    pl = [Placement(1, 5, 5, 0, 0, 0, 0, 1, model='hotel1'),
          Placement(2, 5, 5, 0, 0, 0, 0, 1, model='lodhotel'),
          Placement(1, 9, 9, 0, 0, 0, 0, 1, interior=3, model='hotel1')]
    res, c = build_chunks(tmp_path, pl, ides, FakeConv(), 512, logging.getLogger('t'))
    assert sum(v['high_objects'] for v in res.values()) == 1   # interior skipped; lod kept separately


def test_spike_triangles_and_colors_are_handled(tmp_path):
    class Bad(M):
        positions = [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1), (90000, 0, 0)]
        normals = []
        texcoords = [(0, 0)] * 5
        indices = [0, 1, 2, 0, 2, 3, 0, 1, 4, 0, 1, 99]
        colors = [(255, 128, 0, 255)] * 5
        has_colors = True
    rec = mesh_records([Bad()])
    assert len(rec) == 1
    assert len(rec[0]['indices']) == 6            # spike + out-of-range index removed
    assert rec[0]['colors'][0][0] == 1.0          # prelit colour kept, normalised to 0..1
    assert len(rec[0]['normals']) == 4            # normals computed; unreferenced spike vertex compacted away
    glb = tmp_path / 'c.glb'
    export_records([_transform_record(rec[0], Placement(1, 0, 0, 0, 0, 0, 0, 1, model='x'))], glb)
    b = glb.read_bytes()
    jl, _ = struct.unpack_from('<II', b, 12)
    doc = json.loads(b[20:20 + jl])
    assert 'COLOR_0' in doc['meshes'][0]['primitives'][0]['attributes']
    assert doc['materials'][0]['doubleSided'] is True
    assert 'KHR_materials_unlit' in doc['materials'][0]['extensions']


def test_uv_layouts():
    from vc2godot.gltf import _try_uv_layouts
    n = 3
    pairs = [(0.0, 0.0), (1.0, 0.0), (1.0, 2.0)]
    assert _try_uv_layouts(pairs, n) == pairs
    assert _try_uv_layouts([[0, 0], [1, 0], [1, 2]], n) == pairs
    assert _try_uv_layouts([0, 0, 1, 0, 1, 2], n) == pairs                    # flat, one set
    assert _try_uv_layouts([0, 0, 1, 0, 1, 2, 9, 9, 9, 9, 9, 9], n) == pairs  # flat, two sets
    assert _try_uv_layouts([[0, 0, 1, 0, 1, 2], [5] * 6], n) == pairs        # per-set flat arrays
    assert _try_uv_layouts([pairs, pairs], n) == pairs                        # per-set pair lists
    assert _try_uv_layouts([(0, 0)], n) is None


def test_island_lod_is_lod():
    from vc2godot.world import is_lod
    assert is_lod('IslandLODmainland') and is_lod('islandLODbeach') and is_lod('LODntoon04')
    assert not is_lod('od_groyne01') and not is_lod('dt_shops') and not is_lod('mlamppost')


def test_lod_only_pieces_are_shown_near(tmp_path):
    from vc2godot.world import find_lod_only

    class Wall(M):
        positions = [(-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0)]
        normals = [(0, 0, 1)] * 4
        texcoords = [(0, 0), (1, 0), (1, 1), (0, 1)]
        indices = [0, 1, 2, 0, 2, 3]

    class Conv:
        def meshes(self, name, tex):
            return [Wall()], {}

    hd = IdeObject(1, 'hotel', 'tx'); paired = IdeObject(2, 'LODhotel', 'tx'); lonely = IdeObject(3, 'LODbridge', 'tx')
    p_hd = Placement(1, 0, 0, 0, 0, 0, 0, 1, model='hotel')
    p_paired = Placement(2, 2, 2, 0, 0, 0, 0, 1, model='LODhotel')       # sits on top of the hotel
    p_lonely = Placement(3, 500, 500, 0, 0, 0, 0, 1, model='LODbridge')  # nothing detailed around
    entries = [(p_hd, hd, 'high'), (p_paired, paired, 'lod'), (p_lonely, lonely, 'lod')]
    orphans, report = find_lod_only(entries, Conv(), logging.getLogger('t'))
    assert id(p_lonely) in orphans and id(p_paired) not in orphans
    assert report[0]['model'] == 'LODbridge'


def test_long_ground_quad_is_not_deleted_as_spike():
    # 40 small triangles (a fence) + one 600 m x 80 m ground quad (2 triangles).
    class Ground(M):
        positions = [(i * 0.5, 0, 0) for i in range(22)] + [(i * 0.5, 0, 1) for i in range(22)] + \
                    [(0, 0, -5), (600, 0, -5), (600, 80, -5), (0, 80, -5)]
        normals = []
        texcoords = [(0, 0)] * 48
        indices = []
        for i in range(21):
            indices += [i, i + 1, 22 + i, i + 1, 23 + i, 22 + i]
        indices += [44, 45, 46, 44, 46, 47]
    rec = mesh_records([Ground()], label='ground')
    assert len(rec[0]['indices']) == len(Ground.indices)
    from vc2godot.gltf import STATS
    assert STATS['spike'] == 2 or STATS['spike'] == 0   # only ever counts real spikes


def test_nan_vertices_never_reach_the_glb(tmp_path):
    from vc2godot.gltf import validate_glb
    class Nan(M):
        positions = [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1), (float('nan'), 0, 0)]
        normals = [(0, -1, 0)] * 4 + [(float('nan'), 0, 0)]
        texcoords = [(0, 0)] * 5
        indices = [0, 1, 2, 0, 2, 3, 0, 1, 4]
        colors = None
        has_colors = False
    rec = mesh_records([Nan()])
    assert len(rec[0]['positions']) == 4
    glb = tmp_path / 'c.glb'
    export_records(rec, glb)
    problems, stats = validate_glb(glb)
    assert problems == [] and stats['tris'] == 2


def test_ocean_beach_nonzero_interior_lod_pair_is_treated_as_exterior():
    from vc2godot.world import find_exterior_areas
    S = 'oceandrv.ipl'
    ides = {1: IdeObject(1, 'odhighsandgrs1', 'shared_beach'),
            2: IdeObject(2, 'LODanrda05_dy', 'LODodrive'),
            3: IdeObject(3, 'oceanrda05_dy', 'Generic'),
            4: IdeObject(4, 'hotelroom_inside', 'hotelroomint'),
            5: IdeObject(5, 'LODhotelroom_inside', 'LODhotel')}
    pl = [
        # Stock Ocean Beach pattern from holes_report: HD and LOD share a non-zero area id.
        Placement(1, 341, -1257, 11, 0, 0, 0, 1, interior=7, model='odhighsandgrs1', source=S),
        Placement(2, 237, -1252, 10, 0, 0, 0, 1, interior=7, model='LODanrda05_dy', source=S),
        Placement(3, 237, -1252, 10, 0, 0, 0, 1, interior=7, model='oceanrda05_dy', source=S),
        # No LOD twin: remains a hidden interior.
        Placement(4, 100, 100, 10, 0, 0, 0, 1, interior=18, model='hotelroom_inside', source=S),
        Placement(5, 200, 200, 10, 0, 0, 0, 1, interior=18, model='LODhotelroom_inside', source=S),
    ]
    keep, rep = find_exterior_areas(pl, ides)
    assert (S, 7) in keep
    assert (S, 18) not in keep
    row = next(r for r in rep if r['area'] == 7)
    assert row['lod_twins'] >= 1 and row['shown_in_world'] is True


def test_ocean_beach_area_pair_reaches_high_chunk(tmp_path):
    S = 'oceandrv.ipl'
    ides = {1: IdeObject(1, 'odhighsandgrs1', 'shared_beach'),
            2: IdeObject(2, 'LODanrda05_dy', 'LODodrive')}
    pl = [
        Placement(1, 340, -1257, 11, 0, 0, 0, 1, interior=7, model='odhighsandgrs1', source=S),
        Placement(2, 340, -1257, 11, 0, 0, 0, 1, interior=7, model='LODanrda05_dy', source=S),
    ]
    res, _ = build_chunks(tmp_path, pl, ides, FakeConv(), 512, logging.getLogger('t'), export_collision=False)
    assert sum(v['high_objects'] for v in res.values()) == 1
    assert sum(v['lod_objects'] for v in res.values()) == 0


def test_area_13_print_works_yard_is_shown_but_press_room_interior_is_not():
    from vc2godot.world import find_exterior_areas
    S = 'haiti.ipl'
    ides = {1: IdeObject(1, 'pw_printworks', 'x'), 2: IdeObject(2, 'LODprintworks', 'x'),
            3: IdeObject(3, 'pw_groundplane', 'x'), 4: IdeObject(4, 'pw_priint', 'x'),
            5: IdeObject(5, 'LODhafinrd', 'x'), 6: IdeObject(6, 'pw_backfence1', 'x')}
    pl = [Placement(1, -1090, -230, 17, 0, 0, 0, 1, interior=13, model='pw_printworks', source=S),
          Placement(2, -1090, -230, 17, 0, 0, 0, 1, interior=0, model='LODprintworks', source=S),
          Placement(3, -1067, -222, 10, 0, 0, 0, 1, interior=13, model='pw_groundplane', source=S),
          Placement(6, -1066, -270, 12, 0, 0, 0, 1, interior=13, model='pw_backfence1', source=S),
          Placement(4, -1072, -282, 13, 0, 0, 0, 1, interior=18, model='pw_priint', source=S),
          Placement(5, -1072, -289, 10, 0, 0, 0, 1, interior=0, model='LODhafinrd', source=S)]
    keep, rep = find_exterior_areas(pl, ides)
    assert (S, 13) in keep and (S, 18) not in keep      # 7 m from a LOD is not a twin
    import logging, tempfile
    res, _ = build_chunks(Path(tempfile.mkdtemp()), pl, ides, FakeConv(), 512, logging.getLogger('t'))
    assert sum(v['high_objects'] for v in res.values()) >= 3   # printworks + groundplane + fence (+ a LOD-only orphan is fine)
    assert (S, 18) not in keep


def test_island_lod_gets_lowered_base_copy_in_high_chunk(tmp_path):
    class Ground(M):   # 4 triangles: two underwater (z=-5), two on land (z=30)
        positions = [(0, 0, -5), (3000, 0, -5), (0, 3000, -5), (3000, 3000, -5), (0, 0, 30), (50, 0, 30), (0, 50, 30)]
        normals = []
        texcoords = [(0, 0)] * 7
        indices = [0, 1, 2, 1, 3, 2, 4, 5, 6]
    class GC(FakeConv):
        def meshes(self, m, t): return [Ground()], {}
    ides = {1: IdeObject(1, 'IslandLODmainland', 'islandlolodm')}
    pl = [Placement(1, 5, -5, 0, 0, 0, 0, 1, model='IslandLODmainland')]
    res, c = build_chunks(tmp_path, pl, ides, GC(), 512, logging.getLogger('t'))
    v = list(res.values())[0]
    assert 'lod' in v['paths'] and 'high' in v['paths']          # terrain is now also present near the camera
    assert v['high_meshes'] == 1 and v['lod_meshes'] == 1
