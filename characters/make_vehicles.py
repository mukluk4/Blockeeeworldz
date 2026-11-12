"""Brick vehicle mounts: each replaces one mount model (.eqg) of the client.

The mount keeps its skeleton, but every animation is frozen at the rest pose (the vehicle glides instead of
running like the animal), the rider bone (CHEST03_MOUNT01) is moved to the vehicle's seat, and the body is one
rigid brick mesh on the root bone. Every color texture of the archive becomes the brick atlas and every normal
map a flat one, so whichever texture variant the server asks for shows the vehicle.

    python -I make_vehicles.py <client folder> <out folder>

    motorcycle  -> mrp.eqg (raptor: Venomous Raptor Saddle)
    roadster    -> mrd.eqg (rotdog: Albino Rotdog Saddle)
    forklift    -> mkg.eqg (kangon: Desert Kangon Saddle)
"""
import os, re, struct, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
os.environ.setdefault('BAKED_HAIR', '1')
import minifig, make_s3d, pfs, eqgmds
from brickcreature import build_parts
from make_drakkin import qmat

RED = (201, 26, 9)
DARK_RED = (114, 14, 15)
BLACK = (27, 42, 52)
DARK_GREY = (99, 95, 98)
LIGHT_GREY = (160, 165, 169)
YELLOW = (242, 205, 55)
ORANGE = (254, 138, 24)
TRANS_BLUE = (174, 233, 239)
WHITE = (244, 244, 244)
MOUNT_BONE = 'CHEST03_MOUNT01'


class Grid:
    """Bricks by (x, y, z) cell: x forward, y left, z up."""

    def __init__(self):
        self.cells = {}

    def box(self, x0, x1, y0, y1, z0, z1, color):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    self.cells[(x, y, z)] = color

    def clear(self, x0, x1, y0, y1, z0, z1):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    self.cells.pop((x, y, z), None)

    def wheel(self, cx, cz, r, y0, y1, tire=BLACK, hub=LIGHT_GREY):
        """A wheel turning about the y axis, centered between cells."""
        for x in range(int(cx - r) - 1, int(cx + r) + 2):
            for z in range(int(cz - r) - 1, int(cz + r) + 2):
                d = ((x + 0.5 - cx) ** 2 + (z + 0.5 - cz) ** 2) ** 0.5
                if d <= r:
                    for y in range(y0, y1 + 1):
                        self.cells[(x, y, z)] = hub if d <= r * 0.45 else tire

    def line(self, a, b, color, thick=0):
        a, b = np.array(a, float), np.array(b, float)
        n = int(np.abs(b - a).max() * 2) + 1
        for t in np.linspace(0, 1, n):
            x, y, z = np.round(a + t * (b - a)).astype(int)
            for dy in range(-thick, thick + 1):
                self.cells[(int(x), int(y + dy), int(z))] = color

    def arrays(self):
        keys = np.array(list(self.cells))
        lo = keys.min(0)
        dims = keys.max(0) - lo + 1
        filled = np.zeros(dims, bool)
        colors = np.zeros(tuple(dims) + (3,), np.float32)
        for (x, y, z), c in self.cells.items():
            filled[x - lo[0], y - lo[1], z - lo[2]] = True
            colors[x - lo[0], y - lo[1], z - lo[2]] = c
        return lo, filled, colors


def motorcycle():
    g = Grid()
    g.wheel(4.5, 4.5, 4.2, 0, 1)                    # rear wheel
    g.wheel(21.5, 4.5, 4.2, 0, 1)                   # front wheel
    g.box(6, 17, 0, 1, 5, 7, RED)                   # frame
    g.box(9, 14, -1, 2, 2, 5, DARK_GREY)            # engine
    g.box(10, 13, -2, 3, 3, 4, LIGHT_GREY)          # cylinders
    g.box(13, 17, -1, 2, 8, 10, RED)                # tank
    g.box(14, 16, -1, 2, 11, 11, DARK_RED)          # tank top stripe
    g.box(5, 12, -1, 2, 8, 9, BLACK)                # seat
    g.box(2, 8, 0, 1, 8, 9, RED)                    # rear fender
    g.box(1, 2, 0, 1, 7, 8, RED)                    # tail light post
    g.box(0, 0, 0, 1, 7, 8, (255, 0, 0))            # tail light
    g.line((21, 0, 5), (18, 0, 13), LIGHT_GREY)     # front fork
    g.line((21, 1, 5), (18, 1, 13), LIGHT_GREY)
    g.box(17, 18, -4, 5, 13, 13, BLACK)             # handlebar
    g.box(19, 20, -1, 2, 11, 12, YELLOW)            # headlight
    g.box(20, 24, 0, 1, 9, 9, RED)                  # front fender
    g.box(2, 11, -2, -2, 3, 3, LIGHT_GREY)          # exhaust
    g.box(2, 3, -2, -2, 4, 4, LIGHT_GREY)
    return g, 0.3, (8.5, 0.5, 10)                   # grid, brick size, seat (cell coords, z = top of seat)


def roadster():
    g = Grid()
    g.box(0, 35, -6, 6, 2, 6, RED)                  # body
    g.box(22, 35, -6, 6, 7, 7, RED)                 # hood
    g.box(0, 9, -6, 6, 7, 7, RED)                   # rear deck
    g.box(23, 34, -1, 1, 8, 8, DARK_RED)            # hood stripe
    g.clear(10, 21, -4, 4, 4, 7)                    # cockpit
    g.box(11, 15, -3, 3, 3, 4, BLACK)               # seat cushion
    g.box(10, 10, -3, 3, 4, 9, BLACK)               # seat back
    g.box(9, 9, -2, 2, 8, 10, RED)                  # headrest fairing
    g.box(21, 21, -5, 5, 8, 10, TRANS_BLUE)         # windshield
    g.box(18, 19, 0, 0, 5, 7, BLACK)                # steering column
    g.box(18, 18, -2, 2, 8, 8, BLACK)               # steering wheel
    g.box(36, 36, -5, 5, 2, 5, LIGHT_GREY)          # grille / bumper
    g.box(36, 36, -6, -4, 5, 6, YELLOW)             # headlights
    g.box(36, 36, 4, 6, 5, 6, YELLOW)
    g.box(-1, -1, -6, -5, 4, 5, (255, 0, 0))        # tail lights
    g.box(-1, -1, 5, 6, 4, 5, (255, 0, 0))
    g.box(-1, -1, -3, 3, 2, 3, LIGHT_GREY)          # rear bumper
    for cx in (6.5, 29.5):                          # wheels outside the body
        g.wheel(cx, 3.0, 3.2, -8, -7)
        g.wheel(cx, 3.0, 3.2, 7, 8)
        for y0, y1 in ((-8, -7), (7, 8)):           # fenders over them
            g.box(int(cx) - 3, int(cx) + 3, y0, y1, 6, 6, RED)
    return g, 0.33, (13, 0, 5)


def forklift():
    g = Grid()
    g.box(0, 17, -5, 5, 1, 5, YELLOW)               # chassis
    g.box(0, 3, -5, 5, 1, 8, DARK_GREY)             # counterweight
    g.box(6, 9, -2, 2, 5, 6, BLACK)                 # seat
    g.box(5, 5, -2, 2, 6, 10, BLACK)                # seat back
    g.box(12, 12, 0, 0, 6, 9, BLACK)                # steering column
    g.box(12, 12, -2, 2, 9, 9, BLACK)               # steering wheel
    for x in (4, 15):                               # overhead guard posts
        for y in (-5, 5):
            g.box(x, x, y, y, 6, 16, BLACK)
    g.box(4, 15, -5, 5, 17, 17, BLACK)              # guard roof frame
    g.clear(5, 14, -4, 4, 17, 17)
    for x in (7, 10, 13):
        g.box(x, x, -4, 4, 17, 17, BLACK)
    g.box(18, 19, -4, -3, 1, 22, DARK_GREY)         # mast
    g.box(18, 19, 3, 4, 1, 22, DARK_GREY)
    for z in (11, 22):
        g.box(18, 19, -4, 4, z, z, DARK_GREY)
    g.box(20, 20, -4, 4, 1, 7, LIGHT_GREY)          # carriage
    g.box(21, 28, -3, -2, 0, 0, LIGHT_GREY)         # forks
    g.box(21, 28, 2, 3, 0, 0, LIGHT_GREY)
    g.box(16, 17, -5, 5, 6, 6, ORANGE)              # dash
    g.box(2, 3, -1, 1, 9, 9, ORANGE)                # warning light
    g.box(2, 3, 0, 0, 10, 10, (255, 120, 0))
    for cx in (4.5, 14.5):
        g.wheel(cx, 2.5, 2.7, -7, -6)
        g.wheel(cx, 2.5, 2.7, 6, 7)
    return g, 0.33, (7.5, 0, 7)


VEHICLES = [('motorcycle', 'mrp', motorcycle), ('roadster', 'mrd', roadster), ('forklift', 'mkg', forklift)]


def bone_world(m):
    parent = {}
    for k, b in enumerate(m.bones):
        c = b[3]
        while c != -1:
            parent[c] = k
            c = m.bones[c][1]
    world = {}

    def get(k):
        if k not in world:
            R, T = qmat(*m.bones[k][5]), np.array(m.bones[k][4], float)
            if k in parent:
                PR, PT = get(parent[k])
                world[k] = (PR @ R, PR @ T + PT)
            else:
                world[k] = (R, T)
        return world[k]

    for k in range(len(m.bones)):
        get(k)
    return parent, world


def frozen_ani(data, rest):
    """The same animation (bones, frame times) with every frame at the bone's rest pose."""
    magic, ver, slen, nbone, strict = struct.unpack_from('<4s4I', data, 0)
    assert magic == b'EQGA', magic
    strings = data[20:20 + slen]
    out = bytearray(data[:20 + slen])
    off = 20 + slen
    for _ in range(nbone):
        nframe, nm = struct.unpack_from('<2I', data, off)
        out += data[off:off + 8]
        off += 8
        bname = strings[nm:strings.index(b'\0', nm)].decode('latin-1')
        for _ in range(nframe):
            ms = struct.unpack_from('<I', data, off)[0]
            if bname in rest:
                pos, rot, scale = rest[bname]
                out += struct.pack('<I3f4f3f', ms, *pos, *rot, *scale)
            else:
                out += data[off:off + 44]
            off += 44
    assert off == len(data), (off, len(data))
    return bytes(out)


def own_textures(m, code):
    """Point every material at this vehicle's own texture names. Texture names are global in the client: the
    mount's original names (c_rdg_..., c_rpt_...) also belong to the creature of the same kind, and whichever
    archive loads first wins, so shared names would paint the vehicle with animal skin."""
    diffuse, normal = f'c_v{code}_brick_c.dds', f'c_v{code}_brick_n.dds'
    shader = eqgmds.add_string(m, 'Opaque_MaxCBS1.fx')
    d_off, n_off = eqgmds.add_string(m, diffuse), eqgmds.add_string(m, normal)
    for mat in m.materials:
        mat[2] = shader
        props = []
        for pr in mat[3]:
            pname, ptype = struct.unpack_from('<2I', pr, 0)
            key = eqgmds.name(m, pname)
            if key == 'e_TextureDiffuse0':
                pr = struct.pack('<3I', pname, ptype, d_off)
            elif key == 'e_TextureNormal0':
                pr = struct.pack('<3I', pname, ptype, n_off)
            props.append(pr)
        mat[3] = props
    return diffuse, normal


def own_layers(data, diffuse, normal):
    """The texture-variant table (.lay) with every variant's diffuse and normal slots on this vehicle's textures."""
    magic, ver, slen, count = struct.unpack_from('<4s3I', data, 0)
    strings = data[16:16 + slen]
    entries = [list(struct.unpack_from('<8I', data, 16 + slen + 32 * k)) for k in range(count)]
    assert 16 + slen + 32 * count == len(data), 'unexpected .lay layout'
    table, where = bytearray(), {}

    def put(text):
        if text not in where:
            where[text] = len(table)
            table.extend(text.encode('latin-1') + b'\0')
        return where[text]

    def old(off):
        return strings[off:strings.index(b'\0', off)].decode('latin-1')

    for e in entries:
        e[0] = put(old(e[0]))  # layer name
        e[1], e[2] = put(diffuse.upper()), put(normal.upper())
        if e[7] < slen and (e[7] == 0 or strings[e[7] - 1] == 0):
            e[7] = put(old(e[7]))
    out = bytearray(struct.pack('<4s3I', magic, ver, len(table), count)) + table
    for e in entries:
        out += struct.pack('<8I', *e)
    return bytes(out)


def build(client, out_dir, label, code, design):
    grid, size, seat = design()
    lo, filled, colors = grid.arrays()
    # Model space: x forward, y left, z up, the vehicle centered on the origin and standing on the ground
    dims = np.array(filled.shape)
    lo_world = np.array([-(dims[0] * size) / 2, (lo[1]) * size, 0.0])
    parts = list(build_parts(lo_world, size, filled, colors, np.zeros(filled.shape, int), ['ROOT_BONE']))
    seat_world = lo_world + size * (np.array(seat, float) - lo + np.array([0.5, 0.5, 0]))
    seat_world[2] = (seat[2] - lo[2]) * size

    files = pfs.read(os.path.join(client, 'brick_orig', code + '.eqg.orig'))
    fd = dict(files)
    m = eqgmds.read(fd[code + '.mds'])
    names = [eqgmds.name(m, b[0]) for b in m.bones]
    root = names.index('ROOT_BONE')
    mount = names.index(MOUNT_BONE)
    parent, world = bone_world(m)
    # Rider bone onto the seat (keeps its rotation; position given in its parent's frame)
    PR, PT = world[parent[mount]]
    m.bones[mount][4] = tuple(float(v) for v in PR.T @ (seat_world - PT))
    rest = {n: (tuple(b[4]), tuple(b[5]), tuple(b[6])) for n, b in zip(names, m.bones)}

    minifig.use(minifig.RACES['hum'])
    atlas, uvmap = make_s3d.make_atlas(parts)
    verts, tris, weights, seen = [], [], [], {}
    for p in parts:
        for tri in p.tris:
            ids = []
            for v, n, uv in tri:
                u, w = uvmap(p.material, *uv)
                w = 1.0 - w  # EQG textures count rows from the bottom (old .s3d models from the top)
                key = (tuple(np.round(v, 4)), tuple(np.round(n, 3)), round(u, 4), round(w, 4))
                if key not in seen:
                    seen[key] = len(verts)
                    nn = np.array(n, float)
                    nn = nn / (np.linalg.norm(nn) or 1)
                    verts.append([tuple(map(float, v)), tuple(map(float, nn)), 0xFFFFFFFF, (u, w), (0.0, 0.0)])
                    weights.append([1, [(root, 1.0), (0, 0.0), (0, 0.0), (0, 0.0)]])
                ids.append(seen[key])
            tris.append([ids[0], ids[1], ids[2], 0, 65536])
    tiny = [[(0.0, 0.0, -0.01), (0.0, 0.0, 1.0), 0xFFFFFFFF, (0.0, 0.0), (0.0, 0.0)] for _ in range(3)]
    for k, piece in enumerate(m.pieces):
        if k == 0:
            piece['verts'], piece['tris'], piece['weights'] = verts, tris, weights
        else:  # heads and other pieces: one hidden, empty triangle
            piece['verts'] = [list(v) for v in tiny]
            piece['tris'] = [[0, 1, 2, 0, 65536]]
            piece['weights'] = [[1, [(root, 1.0), (0, 0.0), (0, 0.0), (0, 0.0)]] for _ in range(3)]
    diffuse, normal = own_textures(m, code)
    new_mds = eqgmds.write(m)

    sheet = make_s3d.dds_dxt1(atlas)
    flat_normal = make_s3d.dds_dxt1(Image.new('RGB', (128, 128), (128, 128, 255)))
    out = []
    for n, b in files:
        if n == code + '.mds':
            b = new_mds
        elif n.endswith('.mds'):
            continue  # spare copies (mpu_bak.mds style) would only confuse
        elif n.endswith('.ani'):
            b = frozen_ani(b, rest)
        elif n.endswith('.lay'):
            b = own_layers(b, diffuse, normal)
        elif n.endswith('.dds'):
            continue  # the animal's textures stay with the animal's own archive
        out.append((n, b))
    out += [(diffuse, sheet), (normal, flat_normal)]
    dst = os.path.join(out_dir, code + '.eqg')
    pfs.write(dst, out)
    minifig.preview(os.path.join(out_dir, f'{label}_preview.png'), parts, size=320, ss=1)
    print(f'{label}: {int(filled.sum())} bricks of {size}, {len(verts)} vertices, seat at {np.round(seat_world, 2)} '
          f'-> {dst}')


def main():
    client, out_dir = sys.argv[1:3]
    os.makedirs(out_dir, exist_ok=True)
    for label, code, design in VEHICLES:
        build(client, out_dir, label, code, design)


if __name__ == '__main__':
    main()
