from __future__ import annotations
from pathlib import Path
import re
from rwfury import Dff, Txd, Col
from PIL import Image
from .txd import decode_txd, list_txd_names, ALPHA_FIXED


def _norm_name(value):
    return str(value).replace('\\', '/').strip().casefold()


class Converter:
    def __init__(self, img, game_root: Path, out: Path, log):
        self.img = img
        self.game_root = Path(game_root)
        self.out = out
        self.log = log
        self.txd_cache = {}
        self.mesh_cache = {}
        self.collision_cache = {}
        self.external_files = {}
        self.external_collision_models = {}
        self.missing_tex = {}
        self.failures = {}      # model (casefold) -> reason it could not be converted
        self.debug_dumped = False
        self._tex_owner = None
        (out / 'assets/textures').mkdir(parents=True, exist_ok=True)
        self._index_external_files()
        self._index_img_collision()
        self._index_external_collision()

    def _index_external_files(self):
        # The stock VC install keeps several useful dictionaries and collision
        # files loose on disk. On Linux their case must not matter.
        roots = [self.game_root / 'models', self.game_root / 'data' / 'maps']
        for root in roots:
            if not root.exists():
                continue
            for p in root.rglob('*'):
                if not p.is_file() or p.suffix.lower() not in {'.col', '.dff', '.txd'}:
                    continue
                self.external_files.setdefault(p.name.casefold(), p)
                self.external_files.setdefault(str(p.relative_to(self.game_root)).replace('\\', '/').casefold(), p)

    def _index_img_collision(self):
        for e in getattr(self.img, 'entries', []):
            name = str(getattr(e, 'name', ''))
            if not name.casefold().endswith('.col'):
                continue
            try:
                col = Col.from_bytes(self.img.read(name))
                for model in col.models:
                    self.external_collision_models.setdefault(model.name.casefold(), model)
            except Exception as e:
                self.log.warning('COL parse failed %s: %s', name, e)

    def _index_external_collision(self):
        for p in self.external_files.values():
            if not isinstance(p, Path) or p.suffix.lower() != '.col':
                continue
            try:
                col = Col.from_bytes(p.read_bytes())
                for model in col.models:
                    self.external_collision_models.setdefault(model.name.casefold(), model)
            except Exception as e:
                self.log.warning('COL parse failed %s: %s', p, e)

    def find_bytes(self, name):
        n = _norm_name(name)
        # 1) IMG archives, case-insensitive.
        try:
            return self.img.read(n)
        except Exception:
            pass
        # 2) Loose files by basename or game-relative path.
        candidates = [n, Path(n).name.casefold()]
        for key in candidates:
            p = self.external_files.get(key)
            if p and p.is_file():
                try:
                    return p.read_bytes()
                except Exception:
                    pass
        # 3) Direct case-insensitive path walk for odd mod layouts.
        rel = Path(str(name).replace('\\', '/'))
        for base in (self.game_root, self.game_root / 'models', self.game_root / 'data' / 'maps'):
            q = base / rel
            if q.is_file():
                try:
                    return q.read_bytes()
                except Exception:
                    pass
        return None

    @staticmethod
    def _decode_texture(tex):
        result = tex.to_rgba()
        if not isinstance(result, tuple):
            raise ValueError(f'unsupported rwfury to_rgba() result: {type(result)!r}')
        if len(result) == 2:
            rgba_mipmaps, _has_alpha = result
            if not isinstance(rgba_mipmaps, (list, tuple)) or not rgba_mipmaps:
                raise ValueError('rwfury returned no RGBA mipmaps')
            rgba = bytes(rgba_mipmaps[0]); width = int(tex.width); height = int(tex.height)
            if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
                raise ValueError(f'bad RGBA mip: {len(rgba)} bytes for {width}x{height}')
            return rgba, width, height
        if len(result) == 3:
            rgba, width, height = bytes(result[0]), int(result[1]), int(result[2])
            if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
                raise ValueError(f'bad legacy RGBA: {len(rgba)} bytes for {width}x{height}')
            return rgba, width, height
        raise ValueError(f'unsupported to_rgba tuple length: {len(result)}')

    def txd(self, txd_name):
        key = (txd_name or '').casefold()
        if not key:
            return {}
        if key in self.txd_cache:
            return self.txd_cache[key]
        data = self.find_bytes(key if key.endswith('.txd') else key + '.txd')
        if data is None:
            self.log.warning('TXD missing: %s', txd_name)
            self.txd_cache[key] = {}
            return {}

        folder = self.out / 'assets/textures' / Path(txd_name).stem
        folder.mkdir(parents=True, exist_ok=True)
        mapping = {}

        def save_png(name, rgba, width, height):
            orig = Path(str(name).replace('\\', '/')).name
            safe = re.sub(r'[^A-Za-z0-9_.-]', '_', orig) or 'tex'   # '&', '%', '#', spaces break glTF URIs
            key_name = Path(orig).stem.casefold()
            png = folder / (safe + '.png')
            tmp = folder / (safe + '.png.tmp')
            Image.frombytes('RGBA', (width, height), rgba).save(tmp, 'PNG', optimize=False)
            with Image.open(tmp) as check:
                check.load()
                if check.mode != 'RGBA' or check.size != (width, height):
                    raise ValueError(f'PNG validation mismatch: {check.size} {check.mode}')
            tmp.replace(png)
            mapping[key_name] = png
            mapping[orig.casefold()] = png

        try:
            decoded = decode_txd(data)
            for t in decoded:
                try:
                    save_png(t.name, t.rgba, t.width, t.height)
                except Exception as e:
                    self.log.warning('TXD save failed %s/%s: %s', txd_name, t.name, e)
            self.txd_cache[key] = mapping
            self.log.info('TXD %s: %d textures (VC native decoder)', txd_name, len(mapping))
            return mapping
        except Exception as e:
            self.log.warning('Native TXD decoder failed for %s: %s; falling back to rwfury', txd_name, e)

        try:
            txd = Txd.from_bytes(data)
            for tex in txd.textures:
                try:
                    rgba, w, h = self._decode_texture(tex)
                    save_png(tex.name, rgba, w, h)
                except Exception as e:
                    self.log.warning('TXD decode failed %s/%s: %s', txd_name, getattr(tex, 'name', '?'), e)
        except Exception as e:
            self.log.warning('TXD failed %s: %s', txd_name, e)
        self.txd_cache[key] = mapping
        self.log.info('TXD %s: %d textures', txd_name, len(mapping))
        return mapping

    def _build_tex_owner(self):
        """texture name -> [txd names], scanned once from every TXD we can read."""
        owner = {}
        names = [str(getattr(e, 'name', '')) for e in getattr(self.img, 'entries', [])]
        names += [p.name for p in self.external_files.values() if isinstance(p, Path)]
        seen = set()
        for n in names:
            if not n.casefold().endswith('.txd') or n.casefold() in seen:
                continue
            seen.add(n.casefold())
            data = self.find_bytes(n)
            if not data:
                continue
            for t in list_txd_names(data):
                owner.setdefault(t.casefold(), []).append(Path(n).stem)
        self.log.info('Texture owner index: %d textures in %d TXD files', len(owner), len(seen))
        return owner

    def _fallback_texture(self, tex_name, texmap):
        """Find a texture that is not in the object's own TXD (VC shares many)."""
        if self._tex_owner is None:
            self._tex_owner = self._build_tex_owner()
        for txd_stem in self._tex_owner.get(tex_name, []):
            m = self.txd(txd_stem)
            if tex_name in m:
                texmap[tex_name] = m[tex_name]
                return True
        return False

    def meshes(self, name, txd_name=None):
        key = name.casefold()
        if key in self.mesh_cache:
            return self.mesh_cache[key]
        data = self.find_bytes(key if key.endswith('.dff') else key + '.dff')
        if data is None:
            self.log.warning('DFF missing: %s', name)
            self.failures[key] = 'DFF missing in IMG/loose files'
            self.mesh_cache[key] = None
            return None
        try:
            dff = Dff.from_bytes(data)
            meshes = dff.to_generic_meshes()
            if not self.debug_dumped and meshes:
                self.debug_dumped = True
                m = meshes[0]
                self.log.info('DEBUG GenericMesh attrs: %s', [a for a in dir(m) if not a.startswith('_')])

            # Own dictionary first, then stock shared dictionaries. They may be
            # loose files outside gta3.img, which find_bytes() now resolves.
            texmap = {}
            for shared in ('generic', 'particle'):
                texmap.update(self.txd(shared))
            own = self.txd(txd_name)
            texmap.update(own)

            for m in meshes:
                nm = getattr(m, 'texture_name', None) or getattr(m, 'material_name', None) or ''
                if nm:
                    n = Path(str(nm).replace('\\', '/')).stem.casefold()
                    if n not in texmap and not self._fallback_texture(n, texmap):
                        self.missing_tex[n] = self.missing_tex.get(n, 0) + 1
            self.mesh_cache[key] = (meshes, texmap)
            return self.mesh_cache[key]
        except Exception as e:
            self.log.warning('DFF failed %s: %s', name, e)
            self.failures[key] = 'DFF failed: %s' % str(e).replace('\n', ' ')[:60]
            self.mesh_cache[key] = None
            return None

    def collision(self, name):
        key = name.casefold()
        if key in self.collision_cache:
            return self.collision_cache[key]

        model = self.external_collision_models.get(key)
        if model is None:
            p = self.external_files.get((key + '.col').casefold())
            if p and p.exists():
                try:
                    col = Col.from_bytes(p.read_bytes())
                    for m in col.models:
                        if m.name.casefold() == key or len(col.models) == 1:
                            model = m
                            break
                except Exception as e:
                    self.log.warning('COL failed %s: %s', p, e)
        if model is None:
            data = self.find_bytes(key + '.dff')
            if data:
                try:
                    dff = Dff.from_bytes(data)
                    blob = getattr(dff, 'collision', None)
                    if blob:
                        parsed = blob.parse()
                        if parsed:
                            model = parsed
                except Exception as e:
                    self.log.debug('Embedded COL unavailable for %s: %s', name, e)
        self.collision_cache[key] = model
        return model

    def report(self):
        if ALPHA_FIXED:
            self.log.warning('%d textures had an all-transparent alpha channel and were forced opaque: %s', len(ALPHA_FIXED), sorted(set(ALPHA_FIXED))[:60])
        if self.missing_tex:
            top = sorted(self.missing_tex.items(), key=lambda kv: -kv[1])[:50]
            self.log.warning('%d texture names could not be resolved (top 50): %s', len(self.missing_tex), top)
