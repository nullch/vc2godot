from __future__ import annotations
from math import sqrt


def vc_vec3(v):
    return (float(v[0]), float(v[2]), -float(v[1]))


def vc_normal(v):
    x, y, z = vc_vec3(v)
    l = sqrt(x*x + y*y + z*z)
    return (x/l, y/l, z/l) if l else (0.0, 1.0, 0.0)
