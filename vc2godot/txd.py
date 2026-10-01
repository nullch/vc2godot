"""Self-contained RenderWare TXD reader for the PC versions of GTA III / VC / SA.

Why this exists: rwfury's ``TxdTexture.to_rgba()`` was observed returning the raw,
still-compressed / still-palettised mip bytes (e.g. 16384 bytes of DXT3 for a
128x128 texture) which then got interpreted as RGBA and produced the familiar
"colourful noise in the top quarter of the image" textures.  Parsing the native
texture chunk ourselves removes that whole class of problem.

Supported: platform D3D8 (8, used by Vice City PC) and D3D9 (9), with
DXT1/2/3/4/5, PAL8, PAL4, 8888, 888, 565, 555, 1555, 4444 and LUM8 rasters.
Anything else (PS2, Xbox, mobile...) raises ``UnsupportedTxd`` so the caller can
fall back to another decoder.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

RW_STRUCT = 0x01
RW_TEXNATIVE = 0x15
RW_TEXDICT = 0x16

PLATFORM_D3D8 = 8
PLATFORM_D3D9 = 9

FOURCC_DXT = {
    0x31545844: 1,  # 'DXT1'
    0x32545844: 2,  # 'DXT2'
    0x33545844: 3,  # 'DXT3'
    0x34545844: 4,  # 'DXT4'
    0x35545844: 5,  # 'DXT5'
}


ALPHA_FIXED = []   # (texture name) whose alpha channel was entirely 0 and got forced opaque


class UnsupportedTxd(Exception):
    pass


@dataclass
class DecodedTexture:
    name: str
    mask: str
    width: int
    height: int
    rgba: bytes
    has_alpha: bool


# ----------------------------------------------------------------------------
# block / pixel decoders (all return RGBA bytes, top-left origin, len == w*h*4)
# ----------------------------------------------------------------------------

def _rgb565(c):
    r = (c >> 11) & 31
    g = (c >> 5) & 63
    b = c & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def decode_dxt(data, width, height, kind):
    """Decode DXT1 (kind 1), DXT2/3 (2, 3) or DXT4/5 (4, 5) into RGBA."""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    bsize = 8 if kind == 1 else 16
    need = bw * bh * bsize
    if len(data) < need:
        raise ValueError(f"DXT{kind} data too short: {len(data)} < {need} for {width}x{height}")
    out = bytearray(width * height * 4)
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            if kind == 1:
                cblock = pos
            else:
                cblock = pos + 8
            c0, c1, bits = struct.unpack_from('<HHI', data, cblock)
            p0 = _rgb565(c0)
            p1 = _rgb565(c1)
            if kind == 1 and c0 <= c1:
                p2 = tuple((p0[i] + p1[i]) // 2 for i in range(3))
                pal = [p0 + (255,), p1 + (255,), p2 + (255,), (0, 0, 0, 0)]
            else:
                p2 = tuple((2 * p0[i] + p1[i]) // 3 for i in range(3))
                p3 = tuple((p0[i] + 2 * p1[i]) // 3 for i in range(3))
                pal = [p0 + (255,), p1 + (255,), p2 + (255,), p3 + (255,)]

            alphas = None
            if kind in (2, 3):
                (a64,) = struct.unpack_from('<Q', data, pos)
                alphas = [((a64 >> (4 * i)) & 15) * 17 for i in range(16)]
            elif kind in (4, 5):
                a0 = data[pos]
                a1 = data[pos + 1]
                ab = int.from_bytes(data[pos + 2:pos + 8], 'little')
                if a0 > a1:
                    tab = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
                else:
                    tab = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
                alphas = [tab[(ab >> (3 * i)) & 7] for i in range(16)]

            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    break
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        break
                    i = py * 4 + px
                    r, g, b, a = pal[(bits >> (2 * i)) & 3]
                    if alphas is not None:
                        a = alphas[i]
                    o = (y * width + x) * 4
                    out[o] = r
                    out[o + 1] = g
                    out[o + 2] = b
                    out[o + 3] = a
            pos += bsize
    return bytes(out)


def decode_pal8(indices, palette, width, height):
    """palette: 256*4 bytes in RGBA order."""
    n = width * height
    if len(indices) < n:
        raise ValueError(f"PAL8 data too short: {len(indices)} < {n}")
    if len(palette) < 1024:
        raise ValueError("PAL8 palette too short")
    pal = [bytes(palette[i * 4:i * 4 + 4]) for i in range(256)]
    return b''.join(pal[indices[i]] for i in range(n))


def decode_pal4(data, palette, width, height):
    """PAL4: 2 pixels per byte, low nibble first. palette: >=16*4 bytes RGBA."""
    n = width * height
    if len(data) < (n + 1) // 2:
        raise ValueError("PAL4 data too short")
    if len(palette) < 64:
        raise ValueError("PAL4 palette too short")
    pal = [bytes(palette[i * 4:i * 4 + 4]) for i in range(16)]
    out = []
    for i in range(n):
        b = data[i >> 1]
        out.append(pal[(b >> 4) & 15 if i & 1 else b & 15])
    return b''.join(out)


def _bgra_to_rgba(data, n, force_opaque=False):
    if len(data) < n * 4:
        raise ValueError("32-bit data too short")
    d = bytes(data[:n * 4])
    out = bytearray(n * 4)
    out[0::4] = d[2::4]
    out[1::4] = d[1::4]
    out[2::4] = d[0::4]
    out[3::4] = b'\xff' * n if force_opaque else d[3::4]
    return bytes(out)


def _bgr24_to_rgba(data, n):
    if len(data) < n * 3:
        raise ValueError("24-bit data too short")
    d = bytes(data[:n * 3])
    out = bytearray(n * 4)
    out[0::4] = d[2::3]
    out[1::4] = d[1::3]
    out[2::4] = d[0::3]
    out[3::4] = b'\xff' * n
    return bytes(out)


def _decode16(data, n, fmt):
    if len(data) < n * 2:
        raise ValueError("16-bit data too short")
    vals = struct.unpack_from('<%dH' % n, data, 0)
    out = bytearray(n * 4)
    o = 0
    for v in vals:
        if fmt == 0x100:  # A1R5G5B5
            a = 255 if v & 0x8000 else 0
            r = (v >> 10) & 31; g = (v >> 5) & 31; b = v & 31
            r = (r << 3) | (r >> 2); g = (g << 3) | (g >> 2); b = (b << 3) | (b >> 2)
        elif fmt == 0x200:  # R5G6B5
            r, g, b = _rgb565(v); a = 255
        elif fmt == 0x300:  # A4R4G4B4
            a = ((v >> 12) & 15) * 17
            r = ((v >> 8) & 15) * 17; g = ((v >> 4) & 15) * 17; b = (v & 15) * 17
        else:  # 0x700 X1R5G5B5
            r = (v >> 10) & 31; g = (v >> 5) & 31; b = v & 31
            r = (r << 3) | (r >> 2); g = (g << 3) | (g >> 2); b = (b << 3) | (b >> 2)
            a = 255
        out[o] = r; out[o + 1] = g; out[o + 2] = b; out[o + 3] = a
        o += 4
    return bytes(out)


def _cstr(b):
    return b.split(b'\0', 1)[0].decode('latin-1')


# ----------------------------------------------------------------------------
# chunk parsing
# ----------------------------------------------------------------------------

def _decode_native(payload):
    """payload = body of the 0x15 Texture Native chunk."""
    if len(payload) < 12:
        raise ValueError("texture native chunk too small")
    stype, ssize, _ = struct.unpack_from('<III', payload, 0)
    if stype != RW_STRUCT:
        raise ValueError(f"expected struct chunk in texture native, got 0x{stype:x}")
    s = payload[12:12 + ssize]
    if len(s) < 88:
        raise ValueError("texture native struct too small")
    platform = struct.unpack_from('<I', s, 0)[0]
    if platform not in (PLATFORM_D3D8, PLATFORM_D3D9):
        raise UnsupportedTxd(f"platform 0x{platform:x}")

    name = _cstr(s[8:40])
    mask = _cstr(s[40:72])
    raster, field76 = struct.unpack_from('<II', s, 72)
    width, height = struct.unpack_from('<HH', s, 80)
    depth, levels, rtype, last = struct.unpack_from('<BBBB', s, 84)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise ValueError(f"{name}: bogus size {width}x{height}")
    if levels < 1:
        levels = 1

    dxt = 0
    if platform == PLATFORM_D3D8:
        has_alpha = field76 != 0
        if 1 <= last <= 5:
            dxt = last
    else:
        dxt = FOURCC_DXT.get(field76, 0)
        base = raster & 0xF00
        has_alpha = base in (0x100, 0x300, 0x500) or dxt in (2, 3, 4, 5)

    pos = 88
    pal_kind = 0
    palette = b''
    if not dxt:
        if raster & 0x2000:
            pal_kind = 8
            palette = s[pos:pos + 1024]; pos += 1024
        elif raster & 0x4000:
            pal_kind = 4
            palette = s[pos:pos + 128]; pos += 128

    if pos + 4 > len(s):
        raise ValueError(f"{name}: no mip data")
    (msize,) = struct.unpack_from('<I', s, pos)
    data = s[pos + 4:pos + 4 + msize]
    n = width * height
    base = raster & 0xF00

    if dxt:
        kind = {1: 1, 2: 3, 3: 3, 4: 5, 5: 5}[dxt]
        rgba = decode_dxt(data, width, height, kind)
    elif pal_kind == 8:
        rgba = decode_pal8(data, palette, width, height)
    elif pal_kind == 4:
        rgba = decode_pal4(data, palette, width, height)
    elif base == 0x500:
        rgba = _bgra_to_rgba(data, n)
    elif base == 0x600:
        rgba = _bgra_to_rgba(data, n, True) if (depth == 32 or len(data) >= n * 4) else _bgr24_to_rgba(data, n)
    elif base in (0x100, 0x200, 0x300, 0x700):
        rgba = _decode16(data, n, base)
    elif base == 0x400:
        if len(data) < n:
            raise ValueError("LUM8 data too short")
        out = bytearray(n * 4)
        out[0::4] = data[:n]; out[1::4] = data[:n]; out[2::4] = data[:n]; out[3::4] = b'\xff' * n
        rgba = bytes(out)
    else:
        raise UnsupportedTxd(f"raster format 0x{raster:x}")

    # Formats/flags that say "no alpha" must not carry garbage alpha (palette
    # entries and X8R8G8B8 often have alpha 0), otherwise textures go invisible.
    no_alpha = (not has_alpha) if platform == PLATFORM_D3D8 else (base in (0x200, 0x400, 0x600, 0x700))
    if no_alpha:
        b = bytearray(rgba)
        b[3::4] = b'\xff' * n
        rgba = bytes(b)
        has_alpha = False
    else:
        amax = max(rgba[3::4])
        if amax == 0:
            # A texture that is 100% transparent is never intentional; it is a
            # wrongly flagged alpha channel and would make whole roads/ground
            # vanish (MASK material discards every pixel).
            b = bytearray(rgba); b[3::4] = b'\xff' * n; rgba = bytes(b)
            ALPHA_FIXED.append(name)
            has_alpha = False
        else:
            has_alpha = min(rgba[3::4]) != 255

    return DecodedTexture(name, mask, width, height, rgba, has_alpha)


def decode_txd(data: bytes):
    """Return list[DecodedTexture]. Raises UnsupportedTxd/ValueError on failure."""
    if len(data) < 12:
        raise ValueError("TXD too small")
    typ, size, _ = struct.unpack_from('<III', data, 0)
    if typ != RW_TEXDICT:
        raise ValueError(f"not a TXD (chunk type 0x{typ:x})")
    end = min(len(data), 12 + size)
    ctyp, csize, _ = struct.unpack_from('<III', data, 12)
    if ctyp != RW_STRUCT:
        raise ValueError("TXD: missing struct chunk")
    count = struct.unpack_from('<H', data, 24)[0]
    pos = 24 + csize
    out = []
    while pos + 12 <= end and len(out) < count:
        t, s, _ = struct.unpack_from('<III', data, pos)
        body = pos + 12
        if t == RW_TEXNATIVE:
            out.append(_decode_native(data[body:body + s]))
        pos = body + s
    if len(out) != count:
        raise ValueError(f"TXD declares {count} textures, decoded {len(out)}")
    return out


def list_txd_names(data: bytes):
    """Texture names inside a TXD without decoding pixels (cheap)."""
    names = []
    try:
        typ, size, _ = struct.unpack_from('<III', data, 0)
        if typ != RW_TEXDICT:
            return names
        end = min(len(data), 12 + size)
        _, csize, _ = struct.unpack_from('<III', data, 12)
        pos = 24 + csize
        while pos + 12 <= end:
            t, s, _ = struct.unpack_from('<III', data, pos)
            body = pos + 12
            if t == RW_TEXNATIVE and body + 12 + 40 <= len(data):
                # native: struct header(12) then platform(4) filter(4) name[32]
                names.append(_cstr(data[body + 12 + 8:body + 12 + 40]))
            pos = body + s
    except Exception:
        pass
    return names
