"""Brick Drakkin: the minifig with a dragon head, colored by the face choice (green, red, black, blue, repeating).

Drakkin are newer EQG models (dkm.eqg / dkf.eqg). The base model dkm.mod / dkf.mod gets the minifig, fitted to the
Drakkin skeleton and skinned one bone per vertex (EQG vertices are in model space; the client skins them from the
rest pose). Every triangle uses the 'head' material, whose texture the client swaps with the face choice
(c_dk?_head_sNN_m01_c.dds): each of those gets the brick atlas with the skin swatch in one dragon color, so picking a
face picks the color. Hair, facial hair, horns/crests ("facial attachments"), tattoos and the armor pieces are folded
to a point (they draw nothing).

    python -I make_drakkin.py <original dkm.eqg> <out dkm.eqg>
"""
import io, os, re, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import eqgmod, make_s3d, minifig, pfs

COLORS = [minifig.GREEN, (200, 30, 30), (40, 40, 44), (30, 90, 200)]  # green, red, black, blue
PLACEHOLDER = (13, 251, 7)  # skin color while building; replaced per texture

# Dwarf-skeleton bone (the figure's design) -> Drakkin bone
BONES = {'THTHIGH': 'LEG?_THGH', 'CACALF': 'LEG?_CALF', 'BOFOOT': 'LEG?_FOOT', 'BIBICEP': 'ARM?_BCEP',
         'FOFOREARM': 'ARM?_FARM', 'FIHAND': 'ARM?_HAND', 'PEPELVIS': 'PELV', 'CHCHEST': 'CHEST_CHEST02',
         'NENECK': 'NECK_NECK', 'HEHEAD': 'HEAD_HEAD'}


def qmat(x, y, z, w):
    """The client's bone rotation (the transpose of the usual quaternion matrix)."""
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]).T


def rest_pose(m):
    """{bone name: (index, world position)} from the bone tree (first child / next sibling links)."""
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

    return {eqgmod.name(m, b[0]): (k, get(k)[1]) for k, b in enumerate(m.bones)}


def drakkin_bone(dwarf_bone):
    core = dwarf_bone[3:-4]  # DWMTHTHIGHL_DAG -> THTHIGHL
    side = core[-1] if core[-1] in 'LR' and core[:-1] in BONES else ''
    key = core[:-1] if side else core
    if key in BONES:
        return BONES[key].replace('?', side)
    return 'HEAD_HEAD' if key.startswith(('HE', 'FA')) else 'CHEST_CHEST02'


def collapse(data):
    """A model that draws nothing: every vertex at one spot."""
    m = eqgmod.read(data)
    for v in m.verts:
        v[0] = (0.0, 0.0, 3.0)
    return eqgmod.write(m)


def main():
    src, dst = sys.argv[1:3]
    files = pfs.read(src)
    code = os.path.basename(src)[:3].lower()  # dkm / dkf
    names = dict(files)
    m = eqgmod.read(names[f'{code}.mod'])
    rest = rest_pose(m)

    race = minifig.RACES[code]
    race.skin = PLACEHOLDER
    minifig.use(race)
    parts = minifig.build(race)
    # fit() reads the four landmark joints under the figure's own (Dwarf) naming, with a stand-in prefix
    pos = {f'DKX{d}{s}_DAG': rest[BONES[d].replace('?', s)][1] for d in ('BOFOOT', 'THTHIGH', 'BIBICEP', 'FIHAND')
           for s in 'LR'}
    # Soles on the original model's floor line: the figure's feet reach 0.79 below its foot joint
    floor = min(v[0][2] for v in m.verts)
    for s_ in 'LR':
        pos[f'DKXBOFOOT{s_}_DAG'] = np.array([*pos[f'DKXBOFOOT{s_}_DAG'][:2], floor + 0.79])
    minifig.fit(parts, 'DKX', pos)
    for p in parts:
        p.bone = drakkin_bone('DWM' + p.bone[3:])
    atlas, uvmap = make_s3d.make_atlas(parts)

    head_mat = next(i for i, mm in enumerate(m.materials) if eqgmod.name(m, mm[1]) in ('head', f'{code}_head'))
    verts, tris, weights, seen = [], [], [], {}
    for p in parts:
        bi = rest[p.bone][0]
        for tri in p.tris:
            ids = []
            for v, n, uv in tri:
                u, w = uvmap(p.material, *uv)
                w = 1.0 - w  # EQG textures count rows from the bottom (old .s3d models from the top)
                key = (tuple(np.round(v, 4)), tuple(np.round(n, 3)), round(u, 4), round(w, 4), bi)
                if key not in seen:
                    seen[key] = len(verts)
                    n = n / (np.linalg.norm(n) or 1)
                    verts.append([tuple(map(float, v)), tuple(map(float, n)), 0xFFFFFFFF, (u, w), (0.0, 0.0)])
                    weights.append([1, [(bi, 1.0), (0, 0.0), (0, 0.0), (0, 0.0)]])
                ids.append(seen[key])
            tris.append([ids[0], ids[1], ids[2], head_mat, 65536])  # counter-clockwise outward, like the original
    m.verts, m.tris, m.weights = verts, tris, weights
    new_mod = eqgmod.write(m)

    # One atlas per dragon color; the head textures in face order take them in turn
    px = np.asarray(atlas.convert('RGB')).copy()
    mask = np.all(px == PLACEHOLDER, axis=-1)
    sheets = []
    for c in COLORS:
        a = px.copy()
        a[mask] = c
        sheets.append(make_s3d.dds_dxt1(Image.fromarray(a)))
    flat_normal = make_s3d.dds_dxt1(Image.new('RGB', (128, 128), (128, 128, 255)))
    head_tex = re.compile(rf'^c_{code}_head_s(\d+)_m01_c\.dds$')
    out = []
    for n, b in files:
        hm = head_tex.match(n)
        if n == f'{code}.mod':
            b = new_mod
        elif n.endswith('.mod'):
            b = collapse(b)
        elif hm:
            b = sheets[int(hm.group(1)) % len(COLORS)]
        elif re.match(rf'^c_{code}_head_s\d+_m01_n\.dds$', n):
            b = flat_normal
        out.append((n, b))
    pfs.write(dst, out)
    stem = os.path.splitext(dst)[0]
    atlas.save(stem + '_atlas.png')
    for p in parts:  # the preview shows the first color
        if not isinstance(p.material, str) and tuple(p.material) == PLACEHOLDER:
            p.material = COLORS[0]
    minifig.preview(stem + '_preview.png', parts)
    print(f'{code}: {len(parts)} parts, {len(verts)} vertices, {len(tris)} triangles; '
          f'{sum(1 for n, _ in files if head_tex.match(n))} head textures; {len(out)} files -> {dst}')


if __name__ == '__main__':
    main()
