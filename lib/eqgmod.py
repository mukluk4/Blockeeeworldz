"""Read and write EQG models (.mod, magic EQGM), as used by the Drakkin.

Layout (version 3 as found in dkm.eqg / dkf.eqg):
    header   'EQGM', version, string table size, material count, vertex count, triangle count, bone count
    strings  zero-terminated names; everything else points at them by byte offset
    material index, name, shader, property count, then (name, type, value) per property
    vertex   position xyz, normal xyz, color (u32, version 3 only), uv, second uv (version 3 only)
    triangle three vertex indexes, material index, flags
    bone     name, next sibling, flags, first child, position xyz, rotation quaternion xyzw, scale xyz
    weights  per vertex (when there are bones): count, then four (bone, weight) pairs

    python -I eqgmod.py <archive.eqg>      round-trips every .mod in the archive and reports
"""
import struct, sys


class Mod:
    pass


def read(data):
    m = Mod()
    magic, m.version, slen, nmat, nvert, ntri, nbone = struct.unpack_from('<4s6I', data, 0)
    assert magic == b'EQGM', magic
    off = 28
    m.strings = data[off:off + slen]
    off += slen
    m.materials = []
    for _ in range(nmat):
        index, name, shader, nprop = struct.unpack_from('<4I', data, off)
        off += 16
        props = []
        for _ in range(nprop):
            props.append(data[off:off + 12])  # name, type, value (u32 or float by type) kept as bytes
            off += 12
        m.materials.append([index, name, shader, props])
    vsize = 44 if m.version >= 3 else 32
    m.verts = []
    for _ in range(nvert):
        if m.version >= 3:
            px, py, pz, nx, ny, nz, color, u, v, u2, v2 = struct.unpack_from('<6fI4f', data, off)
            m.verts.append([(px, py, pz), (nx, ny, nz), color, (u, v), (u2, v2)])
        else:
            px, py, pz, nx, ny, nz, u, v = struct.unpack_from('<8f', data, off)
            m.verts.append([(px, py, pz), (nx, ny, nz), 0xFFFFFFFF, (u, v), (0.0, 0.0)])
        off += vsize
    m.tris = []
    for _ in range(ntri):
        a, b, c, mat, flags = struct.unpack_from('<3IiI', data, off)
        m.tris.append([a, b, c, mat, flags])
        off += 20
    m.bones = []
    for _ in range(nbone):
        name, link, flags, child = struct.unpack_from('<IiIi', data, off)
        pos = struct.unpack_from('<3f', data, off + 16)
        rot = struct.unpack_from('<4f', data, off + 28)
        scale = struct.unpack_from('<3f', data, off + 44)
        m.bones.append([name, link, flags, child, pos, rot, scale])
        off += 56
    m.weights = []
    if nbone:
        for _ in range(nvert):
            count = struct.unpack_from('<I', data, off)[0]
            pairs = [struct.unpack_from('<If', data, off + 4 + 8 * k) for k in range(4)]
            m.weights.append([count, pairs])
            off += 36
    m.tail = data[off:]
    return m


def name(m, offset):
    end = m.strings.index(b'\0', offset)
    return m.strings[offset:end].decode('latin-1')


def write(m):
    out = bytearray(struct.pack('<4s6I', b'EQGM', m.version, len(m.strings), len(m.materials), len(m.verts),
                                len(m.tris), len(m.bones)))
    out += m.strings
    for index, nm, shader, props in m.materials:
        out += struct.pack('<4I', index, nm, shader, len(props))
        for p in props:
            out += p
    for pos, nrm, color, uv, uv2 in m.verts:
        if m.version >= 3:
            out += struct.pack('<6fI4f', *pos, *nrm, color, *uv, *uv2)
        else:
            out += struct.pack('<8f', *pos, *nrm, *uv)
    for a, b, c, mat, flags in m.tris:
        out += struct.pack('<3IiI', a, b, c, mat, flags)
    for nm, link, flags, child, pos, rot, scale in m.bones:
        out += struct.pack('<IiIi3f4f3f', nm, link, flags, child, *pos, *rot, *scale)
    if m.bones:
        for count, pairs in m.weights:
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
    ok = bad = 0
    for n, b in pfs.read(sys.argv[1]):
        if n.endswith('.mod'):
            m = read(b)
            same = write(m) == b
            ok += same
            bad += not same
            if not same or len(m.tail):
                print(n, 'round-trip', same, 'tail', len(m.tail))
    print(f'{ok} round-trip exactly, {bad} differ')


if __name__ == '__main__':
    main()
