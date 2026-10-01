import logging
from vc2godot.converter import Converter


class FakeImg:
    def read(self, name):
        raise KeyError(name)


class FakeTex:
    name = 'test'
    width = 2
    height = 2
    raster_format = 0x0500
    depth = 32
    d3d_format = 21
    mipmaps = [bytes(16)]

    def to_rgba(self):
        return [bytes([255, 0, 0, 255] * 4)], True


class FakePal8:
    """128x128 PAL8: raw source mip is 4096 indexed bytes, decoded RGBA is 65536 bytes."""
    name = 'pal8'
    width = 128
    height = 128
    raster_format = 0x2000
    depth = 8
    d3d_format = 41
    mipmaps = [bytes(128 * 128)]

    def to_rgba(self):
        rgba = bytearray(128 * 128 * 4)
        for y in range(128):
            for x in range(128):
                p = (y * 128 + x) * 4
                rgba[p:p + 4] = bytes((255, 0, 0, 255))
        return [bytes(rgba)], True


class FakeBrokenPal8:
    """Simulates the exact bad assumption from 0.4.6: decoded buffer is full-size, raw storage is not."""
    name = 'pal8broken'
    width = 128
    height = 128
    raster_format = 0x2000
    depth = 8
    d3d_format = 41
    mipmaps = [bytes(128 * 32)]

    def to_rgba(self):
        rgba = bytearray(128 * 128 * 4)
        for y in range(128):
            for x in range(128):
                p = (y * 128 + x) * 4
                rgba[p:p + 4] = bytes((255, 0, 0, 255))
        return [bytes(rgba)], True


def make_converter(tmp_path):
    return Converter(FakeImg(), tmp_path, tmp_path, logging.getLogger('test'))


def test_current_rwfury_shape(tmp_path):
    c = make_converter(tmp_path)
    rgba, w, h = c._decode_texture(FakeTex())
    assert (w, h) == (2, 2)
    assert len(rgba) == 16


def test_pal8_uses_decoded_header_dimensions_not_raw_storage_size(tmp_path):
    c = make_converter(tmp_path)
    rgba, w, h = c._decode_texture(FakePal8())
    assert (w, h) == (128, 128)
    assert len(rgba) == 128 * 128 * 4
    assert all(rgba[i + 3] == 255 for i in range(0, len(rgba), 4))


def test_inconsistent_raw_storage_does_not_crop_decoded_rgba(tmp_path):
    c = make_converter(tmp_path)
    rgba, w, h = c._decode_texture(FakeBrokenPal8())
    assert (w, h) == (128, 128)
    assert len(rgba) == 128 * 128 * 4
