from __future__ import annotations
from pathlib import Path
import json, logging, shutil
from .imgutil import open_img, locate_imgs
from .ide import find_ide_files, parse_ide
from .ipl import find_ipl_files, parse_ipl
from .converter import Converter
from .godot import make_project, make_world
from .world import build_chunks


def scan(game: Path):
    print(f'Game: {game}')
    imgs = locate_imgs(game)
    for p in imgs:
        print(f'IMG:  {p} -> {p.exists()}')
    ides = list(find_ide_files(game)); ipls = list(find_ipl_files(game))
    print(f'IMG archives: {len(imgs)}')
    print(f'IDE files: {len(ides)}')
    print(f'IPL files: {len(ipls)}')
    print(f'Collision dir: {game/"models"/"coll"} -> {(game/"models"/"coll").exists()}')


def run(game: Path, out: Path, chunk_size=512, max_models=0, export_collision=True):
    if out.exists():
        for name in ('assets/models', 'assets/textures', 'world/chunks', 'world/collision', 'world', 'data'):
            p = out/name
            if p.exists():
                shutil.rmtree(p)
    out.mkdir(parents=True, exist_ok=True)
    (out/'data').mkdir(parents=True, exist_ok=True)
    log = logging.getLogger('vc2godot')
    make_project(out)

    img = open_img(game)
    log.info('IMG archives opened: %d; total entries: %d', len(getattr(img, 'archives', [])), len(img.entries))
    for p in getattr(img, 'paths', []):
        log.info('IMG source: %s', p)

    ides = {}
    for p in find_ide_files(game):
        try:
            parsed = parse_ide(p)
            for oid, obj in parsed.items():
                if oid in ides and ides[oid].model.casefold() != obj.model.casefold():
                    log.warning('IDE duplicate id %d: %s -> %s (%s)', oid, ides[oid].model, obj.model, p)
                ides[oid] = obj
        except Exception:
            log.exception('IDE failed: %s', p)

    placements = []
    for p in find_ipl_files(game):
        try:
            placements.extend(parse_ipl(p))
        except Exception:
            log.exception('IPL failed: %s', p)

    by_name = {v.model.casefold(): v for v in ides.values()}
    resolved = []; unresolved = 0
    for p in placements:
        if p.object_id in ides:
            resolved.append(p)
        elif p.model and p.model.casefold() in by_name:
            p.object_id = by_name[p.model.casefold()].object_id
            resolved.append(p)
        else:
            unresolved += 1
    placements = resolved
    log.info('IDE objects: %d; IPL placements: %d; unresolved: %d', len(ides), len(placements), unresolved)

    if max_models:
        allowed = set()
        for p in placements:
            o = ides.get(p.object_id)
            if o and len(allowed) < max_models:
                allowed.add(o.model.casefold())
        placements = [p for p in placements if ides.get(p.object_id) and ides[p.object_id].model.casefold() in allowed]
        log.info('DEBUG max-models=%d -> placements=%d', max_models, len(placements))

    conv = Converter(img, game, out, log)
    chunks, center = build_chunks(out, placements, ides, conv, chunk_size, log, export_collision=export_collision)
    (out/'data/objects.json').write_text(json.dumps({str(k): vars(v) for k, v in ides.items()}, indent=2), encoding='utf-8')
    (out/'data/placements.json').write_text(json.dumps([vars(p) for p in placements], indent=2), encoding='utf-8')
    summary = {'ide_objects': len(ides), 'placements': len(placements), 'unresolved': unresolved, 'chunks': len(chunks), 'collision_enabled': bool(export_collision), 'img_archives': [str(p) for p in getattr(img, 'paths', [])]}
    (out/'data/import_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    make_world(out, center, chunk_size)
    log.info('WORLD: %d chunks, %d placements, collision=%s', len(chunks), len(placements), export_collision)
    log.info('DONE: %s  -> run: %s/run_godot.sh  (first start imports all assets, wait for it)', out, out)
