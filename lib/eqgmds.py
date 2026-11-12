"""Read and write EQG skinned models with several pieces (.mds, magic EQGS), as used by mounts.

Layout:
    header   'EQGS', version, string table size, material count, bone count, piece count
    strings, materials, bones   as in .mod (see eqgmod.py)
    piece    main flag, name, vertex count, triangle count, weight count,
             vertices (32 bytes; 44 with color and second uv from version 3), triangles (20 bytes),
             weights (count, then four (bone, weight) pairs; 36 bytes)

    python -I eqgmds.py <archive.eqg>      round-trips every .mds in the archive and reports
"""
import struct, sys


class Mds:
    pass


def read(data):
    m = Mds()
    magic, m.version, slen, nmat, nbone, npiece = struct.unpack_from('<4s5I', data, 0)
    assert magic == b'EQGS', magic
    off = 24
    m.strings = data[off:off + slen]
    off += slen
    m.materials = []
    for _ in range(nmat):
        index, name, shader, nprop = struct.unpack_from('<4I', data, off)
        off += 16
        props = [data[off + 12 * k:off + 12 * k + 12] for k in range(nprop)]
        off += 12 * nprop
        m.materials.append([index, name, shader, props])
    m.bones = []
    for _ in range(nbone):
        name, link, flags, child = struct.unpack_from('<IiIi', data, off)
        pos = struct.unpack_from('<3f', data, off + 16)
        rot = struct.unpack_from('<4f', data, off + 28)
        scale = struct.unpack_from('<3f', data, off + 44)
        m.bones.append([name, link, flags, child, pos, rot, scale])
        off += 56
    m.pieces = []
    for _ in range(npiece):
        main, name, nvert, ntri, nweight = struct.unpack_from('<5I', data, off)
        off += 20
        p = {'main': main, 'name': name, 'verts': [], 'tris': [], 'weights': []}
        for _ in range(nvert):
            if m.version >= 3:
                px, py, pz, nx, ny, nz, color, u, v, u2, v2 = struct.unpack_from('<6fI4f', data, off)
                p['verts'].append([(px, py, pz), (nx, ny, nz), color, (u, v), (u2, v2)])
                off += 44
            else:
                px, py, pz, nx, ny, nz, u, v = struct.unpack_from('<8f', data, off)
                p['verts'].append([(px, py, pz), (nx, ny, nz), 0xFFFFFFFF, (u, v), (0.0, 0.0)])
                off += 32
        for _ in range(ntri):
            p['tris'].append(list(struct.unpack_from('<3IiI', data, off)))
            off += 20
        for _ in range(nweight):
            count = struct.unpack_from('<I', data, off)[0]
            p['weights'].append([count, [struct.unpack_from('<If', data, off + 4 + 8 * k) for k in range(4)]])
            off += 36
        m.pieces.append(p)
    m.tail = data[off:]
    return m


def name(m, offset):
    end = m.strings.index(b'\0', offset)
    return m.strings[offset:end].decode('latin-1')


def add_string(m, s):
    """Offset of s in the string table, appending it if needed."""
    b = s.encode('latin-1') + b'\0'
    i = m.strings.find(b)
    while i > 0 and m.strings[i - 1] != 0:
        i = m.strings.find(b, i + 1)
    if i < 0:
        i = len(m.strings)
        m.strings = m.strings + b
    return i


def write(m):
    out = bytearray(struct.pack('<4s5I', b'EQGS', m.version, len(m.strings), len(m.materials), len(m.bones),
                                len(m.pieces)))
    out += m.strings
    for index, nm, shader, props in m.materials:
        out += struct.pack('<4I', index, nm, shader, len(props))
        for p in props:
            out += p
    for nm, link, flags, child, pos, rot, scale in m.bones:
        out += struct.pack('<IiIi3f4f3f', nm, link, flags, child, *pos, *rot, *scale)
    for p in m.pieces:
        out += struct.pack('<5I', p['main'], p['name'], len(p['verts']), len(p['tris']), len(p['weights']))
        for pos, nrm, color, uv, uv2 in p['verts']:
            if m.version >= 3:
                out += struct.pack('<6fI4f', *pos, *nrm, color, *uv, *uv2)
            else:
                out += struct.pack('<8f', *pos, *nrm, *uv)
        for a, b, c, mat, flags in p['tris']:
            out += struct.pack('<3IiI', a, b, c, mat, flags)
        for count, pairs in p['weights']:
            out += struct.pack('<I', count)
            for bone, weight in pairs:
                out += struct.pack('<If', bone, weight)
    out += m.tail
    return bytes(out)


def main():
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
    import pfs
    for n, b in pfs.read(sys.argv[1]):
        if n.endswith('.mds'):
            m = read(b)
            print(n, 'v', m.version, 'same' if write(m) == b else 'DIFFERENT', 'tail', len(m.tail),
                  [(name(m, p['name']), p['main'], len(p['verts']), len(p['tris']), len(p['weights']))
                   for p in m.pieces])


if __name__ == '__main__':
    main()
