from __future__ import annotations
import argparse
from pathlib import Path
from .log import setup_logging
from .importer import scan, run


def main():
    ap = argparse.ArgumentParser(prog='vc2godot')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan')
    s.add_argument('game', type=Path)
    i = sub.add_parser('import')
    i.add_argument('game', type=Path)
    i.add_argument('out', type=Path)
    i.add_argument('--chunk-size', type=int, default=512)
    i.add_argument('--max-models', type=int, default=0)
    i.add_argument('--no-collision', action='store_true')
    d = sub.add_parser('ipls', help='table: which IPL file covers which part of the map (1 second, text only)')
    d.add_argument('game', type=Path)
    q = sub.add_parser('inspect', help='list every placement near GTA coordinates X Y')
    q.add_argument('game', type=Path)
    q.add_argument('x', type=float)
    q.add_argument('y', type=float)
    q.add_argument('radius', type=float, nargs='?', default=120.0)
    w = sub.add_parser('where', help='which real models cover GTA point X Y (reads DFFs, ~1-2 min)')
    w.add_argument('game', type=Path)
    w.add_argument('x', type=float)
    w.add_argument('y', type=float)
    w.add_argument('radius', type=float, nargs='?', default=60.0)
    h = sub.add_parser('holes', help='find places where props stand on nothing (missing ground); writes holes_report.txt + holes_map.png')
    h.add_argument('game', type=Path)
    a = ap.parse_args()
    if a.cmd == 'holes':
        from . import diag
        text = diag.holes_report(a.game, 'holes_map.png')
        Path('holes_report.txt').write_text(text, encoding='utf-8')
        print(text)
        print('\n[saved to ./holes_report.txt and ./holes_map.png]')
        return
    if a.cmd == 'where':
        from . import diag
        text = diag.where_is(a.game, a.x, a.y, a.radius)
        Path('where_report.txt').write_text(text, encoding='utf-8')
        print(text)
        print('\n[saved to ./where_report.txt]')
        return
    if a.cmd in ('ipls', 'inspect'):
        from . import diag
        text = diag.ipl_report(a.game) if a.cmd == 'ipls' else diag.inspect_area(a.game, a.x, a.y, a.radius)
        name = 'ipl_report.txt' if a.cmd == 'ipls' else 'inspect_report.txt'
        Path(name).write_text(text, encoding='utf-8')
        print(text)
        print('\n[saved to ./%s]' % name)
        return
    if a.cmd == 'scan':
        scan(a.game)
        return
    setup_logging(a.out)
    run(a.game, a.out, a.chunk_size, a.max_models, not a.no_collision)
