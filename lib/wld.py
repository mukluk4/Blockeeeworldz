"""Read character meshes, materials and the rest-pose skeleton from an EQ .wld (old format, 0x00015500)."""
import math, struct

KEY = bytes([0x95, 0x3A, 0xC5, 0x2A, 0x95, 0x7A, 0x95, 0x6A])


def decode(b):
    return bytes(c ^ KEY[i % 8] for i, c in enumerate(b))


class Wld:
    def __init__(self, data):
        magic, self.version, count, _bsp, _unk, hash_size, _unk2 = struct.unpack_from('<7I', data, 0)
        assert magic == 0x54503D02
        self.new = self.version != 0x00015500
        p = 28
        self.strings = decode(data[p:p + hash_size])
        p += hash_size
        self.frags = [None]  # fragment refs are 1-based
        for _ in range(count):
            size, ftype = struct.unpack_from('<II', data, p)
            body = data[p + 8:p + 8 + size]
            name_ref, = struct.unpack_from('<i', body, 0)
            self.frags.append((ftype, self.name(name_ref), body))
            p += 8 + size

    def name(self, ref):
        if ref >= 0:
            return ''
        s = -ref
        e = self.strings.index(b'\0', s)
        return self.strings[s:e].decode('latin-1')

    def of_type(self, t):
        return [(i, f) for i, f in enumerate(self.frags) if f and f[0] == t]

    # --- materials -------------------------------------------------------------------------------------
    def bitmap_names(self, i):
        _t, _n, b = self.frags[i]
        n, = struct.unpack_from('<I', b, 4)
        p, out = 8, []
        for _ in range(max(n, 1)):
            ln, = struct.unpack_from('<H', b, p)
            out.append(decode(b[p + 2:p + 2 + ln]).rstrip(b'\0').decode('latin-1'))
            p += 2 + ln
        return out

    def material(self, i):
        """(name, render method, texture file stem or None)"""
        _t, name, b = self.frags[i]
        flags, method = struct.unpack_from('<II', b, 4)
        ref5, = struct.unpack_from('<i', b, 24)
        tex = None
        if ref5 > 0 and self.frags[ref5][0] == 0x05:
            ref4, = struct.unpack_from('<i', self.frags[ref5][2], 4)
            fb = self.frags[ref4][2]
            f4, cnt = struct.unpack_from('<II', fb, 4)
            q = 12 + (4 if f4 & 0x4 else 0) + (4 if f4 & 0x8 else 0)
            ref3, = struct.unpack_from('<i', fb, q)
            tex = self.bitmap_names(ref3)[0].rsplit('.', 1)[0].lower()
        return name, method, tex

    def material_list(self, i):
        _t, _n, b = self.frags[i]
        n, = struct.unpack_from('<I', b, 8)
        return [struct.unpack_from('<i', b, 12 + 4 * k)[0] for k in range(n)]

    # --- meshes ----------------------------------------------------------------------------------------
    def mesh(self, i):
        _t, name, b = self.frags[i]
        flags, mlist, _anim, _u1, _u2 = struct.unpack_from('<Ii3i', b, 4)
        cx, cy, cz = struct.unpack_from('<3f', b, 24)
        (nv, nt, nn, nc, npoly, npieces, nptex, nvtex, _s9, scale) = struct.unpack_from('<10H', b, 76)
        p = 96
        s = 1.0 / (1 << scale)
        verts = []
        for k in range(nv):
            x, y, z = struct.unpack_from('<3h', b, p + 6 * k)
            verts.append((cx + x * s, cy + y * s, cz + z * s))
        p += 6 * nv
        uvs = []
        for k in range(nt):
            if self.new:
                u, v = struct.unpack_from('<2f', b, p + 8 * k)
            else:
                u, v = struct.unpack_from('<2h', b, p + 4 * k)
                u, v = u / 256.0, v / 256.0
            uvs.append((u, v))
        p += (8 if self.new else 4) * nt
        p += 3 * nn + 4 * nc
        polys = []
        for k in range(npoly):
            fl, a, c, d = struct.unpack_from('<4H', b, p + 8 * k)
            polys.append((fl, a, c, d))
        p += 8 * npoly
        pieces = [struct.unpack_from('<2H', b, p + 4 * k) for k in range(npieces)]
        p += 4 * npieces
        ptex = [struct.unpack_from('<2H', b, p + 4 * k) for k in range(nptex)]
        bones = []
        for count, bone in pieces:
            bones += [bone] * count
        mats = [self.material(r) for r in self.material_list(mlist)]
        faces, k = [], 0
        for count, m in ptex:
            for f in polys[k:k + count]:
                faces.append((f[1], f[2], f[3], m))
            k += count
        return dict(name=name, verts=verts, uvs=uvs, bones=bones, faces=faces, materials=mats)

    # --- skeleton --------------------------------------------------------------------------------------
    def skeleton(self, i):
        """Bones as [(name, parent, world matrix as (rotation 3x3, translation))], plus mesh fragment ids."""
        _t, name, b = self.frags[i]
        flags, ntracks, _ref = struct.unpack_from('<IIi', b, 4)
        p = 16 + (12 if flags & 1 else 0) + (4 if flags & 2 else 0)
        raw = []
        for _ in range(ntracks):
            nref, fl, track, mesh, nchild = struct.unpack_from('<iIiiI', b, p)
            children = list(struct.unpack_from(f'<{nchild}i', b, p + 20))
            raw.append((self.name(nref), track, children))
            p += 20 + 4 * nchild
        meshes = []
        if flags & 0x200:
            n2, = struct.unpack_from('<I', b, p)
            for k in range(n2):
                ref, = struct.unpack_from('<i', b, p + 4 + 4 * k)
                meshes.append(struct.unpack_from('<i', self.frags[ref][2], 4)[0])  # 0x2D -> 0x36
        parent = [-1] * len(raw)
        for k, (_n, _t2, ch) in enumerate(raw):
            for c in ch:
                parent[c] = k
        world = [None] * len(raw)
        for k, (bname, track, _c) in enumerate(raw):  # parents come before their children
            R, T = self.track_frame(track)
            if parent[k] >= 0:
                PR, PT = world[parent[k]]
                R, T = matmul(PR, R), add(PT, matvec(PR, T))
            world[k] = (R, T)
        return [(raw[k][0], parent[k], world[k]) for k in range(len(raw))], meshes

    def track_frame(self, ref13):
        ref12, = struct.unpack_from('<i', self.frags[ref13][2], 4)
        b = self.frags[ref12][2]
        flags, frames = struct.unpack_from('<II', b, 4)
        rd, rx, ry, rz, sx, sy, sz, sd = struct.unpack_from('<8h', b, 12)
        T = (sx / sd, sy / sd, sz / sd) if sd else (0.0, 0.0, 0.0)
        return quat_matrix(rd, rx, ry, rz), T


def quat_matrix(w, x, y, z):
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0:
        return ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    w, x, y, z = w / n, x / n, y / n, z / n
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def matmul(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def matvec(A, v):
    return tuple(sum(A[i][k] * v[k] for k in range(3)) for i in range(3))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))
