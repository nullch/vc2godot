import struct
from vc2godot.txd import decode_txd, decode_dxt, UnsupportedTxd


def chunk(t, payload, ver=0x1803FFFF):
    return struct.pack('<III', t, len(payload), ver) + payload


def native(name, w, h, raster, alpha, depth, comp, mip, palette=b'', platform=8, levels=1):
    s = struct.pack('<II', platform, 0x1106)
    s += name.encode().ljust(32, b'\0') + b''.ljust(32, b'\0')
    s += struct.pack('<IIHHBBBB', raster, alpha, w, h, depth, levels, 4, comp)
    s += palette + struct.pack('<I', len(mip)) + mip
    return chunk(0x15, chunk(1, s) + chunk(3, b''))


def txd(*natives):
    body = chunk(1, struct.pack('<HH', len(natives), 9)) + b''.join(natives) + chunk(3, b'')
    return chunk(0x16, body)


def px(t, w, x, y):
    o = (y * w + x) * 4
    return tuple(t.rgba[o:o + 4])


def test_dxt3_128_is_not_raw_bytes():
    # exactly the size that produced the "noise in top 32 rows" bug
    w = h = 128
    c0 = 0xF800  # red
    block = b'\xff' * 8 + struct.pack('<HHI', c0, 0, 0)  # alpha 255, all pixels colour0
    t = decode_txd(txd(native('knifeAfterDark', w, h, 0x0500, 1, 16, 3, block * (32 * 32))))[0]
    assert (t.width, t.height, len(t.rgba)) == (128, 128, 128 * 128 * 4)
    assert t.name == 'knifeAfterDark'
    assert px(t, w, 0, 0) == (255, 0, 0, 255)
    assert px(t, w, 127, 127) == (255, 0, 0, 255)


def test_dxt1_alpha_and_dxt5():
    blk = struct.pack('<HHI', 0x001F, 0x07E0, 0xFFFFFFFF)  # c0=blue c1=green, c0>c1? 0x1F<0x7E0 -> 3-colour mode
    t = decode_dxt(blk, 4, 4, 1)
    assert tuple(t[0:4]) == (0, 0, 0, 0)  # index 3 -> transparent
    a5 = bytes([255, 0]) + bytes(6) + struct.pack('<HHI', 0xFFFF, 0xFFFF, 0)
    t = decode_dxt(a5, 4, 4, 5)
    assert tuple(t[0:4]) == (255, 255, 255, 255)


def test_pal8_and_mask_alpha():
    pal = bytes([255, 0, 0, 255, 0, 255, 0, 0] + [0, 0, 0, 0] * 254)  # entry1 green alpha 0
    idx = bytes([0, 1, 0, 1] * 4)
    t = decode_txd(txd(native('p8', 4, 4, 0x2500, 1, 8, 0, idx, pal)))[0]
    assert px(t, 4, 0, 0) == (255, 0, 0, 255)
    assert px(t, 4, 1, 0) == (0, 255, 0, 0)
    # no-alpha flag -> forced opaque
    t = decode_txd(txd(native('p8', 4, 4, 0x2600, 0, 8, 0, idx, pal)))[0]
    assert px(t, 4, 1, 0) == (0, 255, 0, 255)
    assert not t.has_alpha


def test_8888_bgra_and_565():
    d = bytes([0, 0, 255, 128]) * 4  # BGRA -> red, a=128
    t = decode_txd(txd(native('a', 2, 2, 0x0500, 1, 32, 0, d)))[0]
    assert px(t, 2, 0, 0) == (255, 0, 0, 128) and t.has_alpha
    d = struct.pack('<H', 0xF800) * 4
    t = decode_txd(txd(native('b', 2, 2, 0x0200, 0, 16, 0, d)))[0]
    assert px(t, 2, 1, 1) == (255, 0, 0, 255)


def test_unsupported_platform():
    try:
        decode_txd(txd(native('ps2', 2, 2, 0x0500, 1, 32, 0, bytes(16), platform=0x325350)))
    except UnsupportedTxd:
        return
    raise AssertionError('expected UnsupportedTxd')


def test_fully_transparent_texture_is_forced_opaque():
    from vc2godot.txd import ALPHA_FIXED
    d = bytes([10, 20, 30, 0]) * 4   # flagged as alpha, but every alpha byte is 0
    t = decode_txd(txd(native('ghost', 2, 2, 0x0500, 1, 32, 0, d)))[0]
    assert px(t, 2, 0, 0) == (30, 20, 10, 255)
    assert 'ghost' in ALPHA_FIXED and not t.has_alpha
