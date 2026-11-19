"""Bones and animations of EQG models (.mod/.mds skeletons, .ani tracks).

Bones: (name, next sibling, flags, first child, position, rotation (x, y, z, w), scale), each relative to its parent.
Vertices are stored in model space at the rest pose, so a vertex on bone b moves by world(b, pose) @ world(b, rest)^-1.

.ani ('EQGA'): version, string table size, bone count, strict flag; strings; then per bone a frame count and its
name, and per frame: time (ms), position, rotation, scale (44 bytes).
"""
import struct
import numpy as np


def qmat(x, y, z, w):
    """The client's bone rotation (the transpose of the usual quaternion matrix)."""
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]).T


def parents(bones):
    """[parent index or -1] from the first child / next sibling links."""
    out = [-1] * len(bones)
    for k, b in enumerate(bones):
        c, seen = b[3], set()
        while 0 <= c < len(bones) and c not in seen:
            seen.add(c)
            out[c] = k
            c = bones[c][1]
    return out


def world(bones, parent, local=None):
    """[(R, T)] per bone in model space. local: {bone index: (position, rotation)} overriding the rest pose."""
    out = [None] * len(bones)

    def get(k):
        if out[k] is None:
            pos, rot = (local or {}).get(k, (bones[k][4], bones[k][5]))
            R, T = qmat(*rot), np.array(pos, float)
            if parent[k] >= 0:
                PR, PT = get(parent[k])
                R, T = PR @ R, PR @ T + PT
            out[k] = (R, T)
        return out[k]

    for k in range(len(bones)):
        get(k)
    return out


def read_ani(data):
    """{bone name: [(ms, position, rotation)]}."""
    magic, _ver, slen, nbone, _strict = struct.unpack_from('<4s4I', data, 0)
    assert magic == b'EQGA', magic
    strings = data[20:20 + slen]
    off = 20 + slen
    out = {}
    for _ in range(nbone):
        nframe, nm = struct.unpack_from('<2I', data, off)
        off += 8
        name = strings[nm:strings.index(b'\0', nm)].decode('latin-1')
        frames = []
        for _ in range(nframe):
            v = struct.unpack_from('<I3f4f3f', data, off)
            frames.append((v[0], v[1:4], v[4:8]))
            off += 44
        out[name] = frames
    return out
