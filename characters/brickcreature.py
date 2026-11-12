"""Brick-built creatures: rebuild each creature in an old-style .s3d character archive out of 1x1 bricks.

Each creature's rest-pose model (body plus its default head) is filled with a grid of cubes. A cube takes the color
of the texture under it, snapped to a brick color, and rides the bone nearest it, so the stock animations still
move legs, heads and tails. Exposed tops get studs. Faces are drawn where a cube meets empty space or a cube on
another bone (those come apart when the creature moves). Every texture of the creature gets the color atlas, so
texture variations look the same; extra head meshes are folded away.

    python -I brickcreature.py <in _chr.s3d> <out _chr.s3d> [voxels along the longest side or -, default 18] [only: BEA,ORC,...]
Writes <out>_<PREFIX>_preview.png for each creature.
"""
import copy, io, math, os, re, struct, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import minifig, make_s3d, pfs, wld
from brickzone import nearest, boost

os.environ.setdefault('BAKED_HAIR', '1')  # old-style NPCs have no hair attachments: the minifig wears its own
SKIP = {'WIL', 'OGS', 'ELS', 'GNS', 'GSF', 'GSM', 'GSN'}  # WIL: a sprite, no body; OGS, ELS, GNS: ships; GS?: empty
# Townsfolk and guards become minifigs (base look, clothes colored from their outfit); everything else is bricks
# Creatures with fixed plastic: their few main colors go, light to dark, onto these (light to dark)
FIXED_COLORS = {'SKE': [(244, 244, 244), (228, 205, 158), (160, 165, 169), (149, 138, 115)]}
# Humanoids become minifigs: base look, clothes colored from their outfit; 'head' = skin colored from the head
WHITE, LIGHT_GREY = (244, 244, 244), (160, 165, 169)
PEOPLE = {'FPM': ('hum', {}), 'QCM': ('hum', {}), 'QCF': ('huf', {}),
          'BGM': ('hum', {}), 'NGM': ('dam', {}), 'NGF': ('daf', {}), 'GIA': ('hum', {'skin': 'upper'}),
          'BRM': ('ham', {}), 'BRF': ('haf', {}), 'RIM': ('ham', {}), 'RIF': ('haf', {}),
          'HHM': ('hum', {}), 'HLM': ('bam', {}), 'HLF': ('baf', {}),
          'GRM': ('trm', {}), 'GRF': ('trf', {}), 'OKM': ('ogm', {}), 'OKF': ('ogf', {}),
          'FRO': ('frm', {}), 'FRG': ('frm', {}), 'LIZ': ('ikm', {}),
          'VSM': ('kem', {}), 'VSF': ('kef', {}), 'NYM': ('elf', {}), 'NYD': ('elf', {}),
          'GNN': ('kem', {'skin': (160, 110, 60), 'hair_color': (160, 110, 60)}),
          'KOB': ('kem', {'skin': (88, 42, 18), 'hair_color': (88, 42, 18), 'hair': 'dog', 'ears': 'dog'}),
          'GOB': ('hum', {'skin': 'head'}), 'SCA': ('hum', {'skin': 'head', 'head': 'pumpkin'}), 'EGM': ('erm', {}),
          'ORC': ('hum', {'skin': (106, 138, 58), 'face': 'orc', 'ears': 'elf', 'hair': None, 'brows': (40, 30, 20)}), 'GHU': ('hum', {'skin': 'head'}),
          'ZOM': ('hum', {'skin': 'head'}), 'ZOF': ('huf', {'skin': 'head'}),
          # Faydwer: Kaladim dwarves, Felwithe high elves, Kelethin wood elves, Ak'Anon royalty (gnomes),
          # Unrest's ghost dwarves and Mistmoore's vampires (skin from their pale heads)
          'KA': ('dwm', {}), 'KAM': ('dwm', {}), 'KAF': ('dwf', {}), 'FEM': ('him', {}), 'FEF': ('hif', {}),
          'GFM': ('elm', {}), 'GFF': ('elf', {}), 'CL': ('gnm', {}), 'GDM': ('dwm', {'skin': 'head'}),
          'DVM': ('dam', {'skin': 'head'}),
          'CPM': ('kem', {}), 'CPF': ('kef', {}), 'GEM': ('erm', {'skin': 'head'}), 'GEF': ('erf', {}),
          'DEN': ('hum', {'head': 'squid'}),  # race 99, the Amygdalans of Fear, Justice, Time
          'ICM': ('ikm', {}), 'ICF': ('ikf', {}), 'ICN': ('ikm', {}), 'SIM': ('ikm', {}),
          'BGG': ('hum', {'skin': 'head'}), 'KGO': ('hum', {'skin': 'head'}), 'FGI': ('frm', {}),
          'SRW': ('dkm', {'skin': 'head'}), 'SSK': ('dkm', {'skin': 'head'}), 'SSN': ('dkm', {'skin': 'head'}),
          'COM': ('dwm', {}), 'COF': ('dwf', {}), 'FSG': ('hum', {'skin': 'head'}), 'STG': ('hum', {'skin': 'head'}),
          'STM': ('hum', {'skin': 'head'}),
          'MUH': ('hum', {'skin': 'head'}), 'SER': ('hum', {'skin': 'head'}),
          # Zebuxoruk, the chained god: pale, long black hair and full beard, green eyes, chain mail and a red loincloth
          'ZEB': ('hum', {'skin': (205, 195, 180), 'look': 2, 'baked_hair': True, 'hair': 'long',
                          'hair_color': (27, 27, 30), 'brows': (27, 27, 30), 'eye_color': (60, 200, 70),
                          'shirt': (99, 95, 98), 'trim': LIGHT_GREY, 'print': 'mail', 'arms': (205, 195, 180),
                          'legs': (114, 14, 15), 'hips': LIGHT_GREY, 'chains': LIGHT_GREY}),
          'SKE': ('hum', {'skin': WHITE, 'hair': None, 'shirt': WHITE, 'arms': WHITE, 'legs': WHITE,
                          'hips': WHITE, 'trim': WHITE, 'face': 'skull', 'print': 'ribs', 'bony': True})}
# Old-style humanoid bone (prefix stripped) for each bone the minifig is designed on; ? = side
OLD_BONES = {'THTHIGH': 'TH_?', 'CACALF': 'CA_?', 'BOFOOT': 'BO_?', 'BIBICEP': 'BI_?', 'FOFOREARM': 'FO_?',
             'FIHAND': 'FI_?', 'PEPELVIS': 'PE', 'CHCHEST': 'CH', 'NENECK': 'NE', 'HEHEAD': 'HE'}


def texture_images(files):
    out = {}
    for n, b in files:
        if n.lower().endswith(('.bmp', '.dds')):
            try:
                out[n.lower().rsplit('.', 1)[0]] = np.asarray(Image.open(io.BytesIO(b)).convert('RGB'), np.float32)
            except Exception:
                pass
    return out


def sample_surface(w, bones, mesh_ids, textures, step, glass=None):
    """Points on the rest-pose surface: [(position, color, bone)]. glass: a material name; then also a flag per point,
    True where it lies on that material."""
    pts, cols, bns, on_glass = [], [], [], []
    for mi in mesh_ids:
        m = w.mesh(mi)
        world = []
        for v, b in zip(m['verts'], m['bones']):
            R, T = bones[b][2]
            world.append(np.array(R, float) @ np.array(v, float) + np.array(T, float))
        uvs = m['uvs'] if len(m['uvs']) == len(m['verts']) else [(0.0, 0.0)] * len(m['verts'])
        for a, b, c, mat in m['faces']:
            _name, method, tex = m['materials'][mat]
            is_glass = _name == glass
            if method == 0 or tex is None:  # invisible / boundary materials
                continue
            img = textures.get(tex)
            A, B, Cc = world[a], world[b], world[c]
            n = max(1, int(math.ceil(max(np.linalg.norm(B - A), np.linalg.norm(Cc - A), np.linalg.norm(Cc - B)) / step)))
            for i in range(n + 1):
                for j in range(n + 1 - i):
                    k = n - i - j
                    l0, l1, l2 = i / n, j / n, k / n
                    p = l0 * A + l1 * B + l2 * Cc
                    if img is not None:
                        u = l0 * uvs[a][0] + l1 * uvs[b][0] + l2 * uvs[c][0]
                        v = l0 * uvs[a][1] + l1 * uvs[b][1] + l2 * uvs[c][1]
                        h, wd = img.shape[:2]
                        col = img[int((v % 1.0) * h) % h, int((u % 1.0) * wd) % wd]
                    else:
                        col = np.array((128, 128, 128), np.float32)
                    pts.append(p)
                    cols.append(col)
                    bns.append(m['bones'][(a, b, c)[int(np.argmax((l0, l1, l2)))]])
                    on_glass.append(is_glass)
    if glass:
        return np.array(pts), np.array(cols, np.float32), np.array(bns), np.array(on_glass, bool)
    return np.array(pts), np.array(cols, np.float32), np.array(bns)


def voxelize(pts, cols, bns, size):
    """Grid of cubes: surface cubes from the samples, then the inside filled. -> (origin, filled, color, bone)."""
    lo = pts.min(0) - size
    idx = np.floor((pts - lo) / size).astype(int)
    dims = idx.max(0) + 2
    filled = np.zeros(dims, bool)
    color = np.zeros(tuple(dims) + (3,), np.float32)
    bone = -np.ones(dims, int)
    keys = idx[:, 0] * dims[1] * dims[2] + idx[:, 1] * dims[2] + idx[:, 2]
    order = np.argsort(keys)
    keys, idx_s, cols_s, bns_s = keys[order], idx[order], cols[order], bns[order]
    starts = np.r_[0, np.nonzero(np.diff(keys))[0] + 1, len(keys)]
    for s, e in zip(starts[:-1], starts[1:]):
        x, y, z = idx_s[s]
        filled[x, y, z] = True
        color[x, y, z] = cols_s[s:e].mean(0)
        vals, counts = np.unique(bns_s[s:e], return_counts=True)
        bone[x, y, z] = vals[counts.argmax()]
    # Inside: whatever the outside can't reach (flood from the padded border)
    outside = np.zeros(dims, bool)
    stack = [(0, 0, 0)]
    outside[0, 0, 0] = True
    while stack:
        x, y, z = stack.pop()
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nx, ny, nz = x + dx, y + dy, z + dz
            if 0 <= nx < dims[0] and 0 <= ny < dims[1] and 0 <= nz < dims[2] and not outside[nx, ny, nz] \
                    and not filled[nx, ny, nz]:
                outside[nx, ny, nz] = True
                stack.append((nx, ny, nz))
    inside = ~outside & ~filled
    # Inside cubes take the bone and color of the nearest surface cube (breadth-first from the surface)
    frontier = list(zip(*np.nonzero(filled)))
    while frontier and inside.any():
        nxt = []
        for x, y, z in frontier:
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nx, ny, nz = x + dx, y + dy, z + dz
                if 0 <= nx < dims[0] and 0 <= ny < dims[1] and 0 <= nz < dims[2] and inside[nx, ny, nz]:
                    inside[nx, ny, nz] = False
                    filled[nx, ny, nz] = True
                    bone[nx, ny, nz] = bone[x, y, z]
                    color[nx, ny, nz] = color[x, y, z]
                    nxt.append((nx, ny, nz))
        frontier = nxt
    return lo, filled, color, bone


def palette_colors(color, filled, ncolors, fixed=None):
    """A few main colors per creature (median cut over its cubes), each snapped to a brick color."""
    cells = color[filled]
    row = Image.fromarray(np.clip(cells, 0, 255).astype(np.uint8)[None, :, :])
    q = row.quantize(ncolors, method=Image.Quantize.MEDIANCUT)
    pal = np.array((q.getpalette() + [0] * 3 * ncolors)[:3 * ncolors], np.float32).reshape(ncolors, 3)
    if fixed:  # light to dark main colors onto the creature's own plastics, light to dark
        rank = np.argsort(-(pal @ np.array([0.3, 0.59, 0.11], np.float32)))
        snapped_pal = np.zeros_like(pal)
        for k, i in enumerate(rank):
            snapped_pal[i] = fixed[min(len(fixed) - 1, k * len(fixed) // ncolors)]
    else:
        snapped_pal = nearest(boost(pal))
    out = np.zeros_like(color)
    out[filled] = snapped_pal[np.asarray(q)[0]]
    return out


def smooth_colors(filled, snapped):
    """Each surface cube takes the most common brick color among itself and its neighbours, if that is clear."""
    out = snapped.copy()
    keys = (snapped[..., 0] * 65536 + snapped[..., 1] * 256 + snapped[..., 2]).astype(np.int64)
    for x, y, z in zip(*np.nonzero(filled)):
        around = keys[max(0, x - 1):x + 2, max(0, y - 1):y + 2, max(0, z - 1):z + 2][
            filled[max(0, x - 1):x + 2, max(0, y - 1):y + 2, max(0, z - 1):z + 2]]
        vals, counts = np.unique(around, return_counts=True)
        if counts.max() >= max(4, len(around) // 2) and vals[counts.argmax()] != keys[x, y, z]:
            k = vals[counts.argmax()]
            out[x, y, z] = (k // 65536, k // 256 % 256, k % 256)
    return out


FACES = {  # direction: four corners of the unit cube face, counter-clockwise seen from outside
    (1, 0, 0): [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
    (-1, 0, 0): [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)],
    (0, 1, 0): [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)],
    (0, -1, 0): [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],
    (0, 0, 1): [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
    (0, 0, -1): [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)],
}


def build_parts(lo, size, filled, colors, bone, bone_names, studs=True):
    parts = {}

    def part(b, c):
        key = (b, c)
        if key not in parts:
            parts[key] = minifig.Part(f'brick_{b}_{c}', bone_names[b], c, (0, 0, 0))
        return parts[key]

    def add_quad(p, corners, n):
        a, b_, c, d = (np.array(q, float) for q in corners)
        nn = np.array(n, float)
        uv = (0.02, 0.02)
        p.tris.append([(a, nn, uv), (b_, nn, uv), (c, nn, uv)])
        p.tris.append([(a, nn, uv), (c, nn, uv), (d, nn, uv)])

    dims = filled.shape
    for x, y, z in zip(*np.nonzero(filled)):
        b = bone[x, y, z]
        c = tuple(int(v) for v in colors[x, y, z])
        p = part(b, c)
        base = lo + size * np.array((x, y, z), float)
        for d, corners in FACES.items():
            nx, ny, nz = x + d[0], y + d[1], z + d[2]
            inside = 0 <= nx < dims[0] and 0 <= ny < dims[1] and 0 <= nz < dims[2] and filled[nx, ny, nz]
            if inside and bone[nx, ny, nz] == b:
                continue
            add_quad(p, [base + size * np.array(q, float) for q in corners], d)
            if studs and d == (0, 0, 1) and not inside:
                top = base + size * np.array((0.5, 0.5, 1.0))
                r, hgt, seg = size * 0.3, size * 0.18, 8
                ring = [(math.cos(2 * math.pi * k / seg), math.sin(2 * math.pi * k / seg)) for k in range(seg)]
                for k in range(seg):
                    (c0, s0), (c1, s1) = ring[k], ring[(k + 1) % seg]
                    q0 = top + r * np.array((c0, s0, 0)); q1 = top + r * np.array((c1, s1, 0))
                    add_quad(p, [q0, q1, q1 + (0, 0, hgt), q0 + (0, 0, hgt)],
                             ((c0 + c1) / 2, (s0 + s1) / 2, 0))
                    uv = (0.02, 0.02)
                    up = np.array((0, 0, 1.0))
                    p.tris.append([(top + (0, 0, hgt), up, uv), (q0 + (0, 0, hgt), up, uv), (q1 + (0, 0, hgt), up, uv)])
    return list(parts.values())


def body_mesh(w, prefix, mesh_ids):
    """The body mesh: <P>_DMSPRITEDEF, or <P>MESH_DMSPRITEDEF in some files, else the biggest non-head mesh."""
    names = {w.frags[i][1]: i for i in mesh_ids}
    for n in (f'{prefix}_DMSPRITEDEF', f'{prefix}MESH_DMSPRITEDEF'):
        if n in names:
            return names[n]
    rest = [i for i in mesh_ids if not w.frags[i][1].startswith(f'{prefix}HE')] or mesh_ids
    return max(rest, key=lambda i: len(w.mesh(i)['verts']))


def outfit(w, sid, textures):
    """Clothing colors from the model's own textures: the main brick color on chest, arms, legs and hips."""
    bones, mesh_ids = w.skeleton(sid)
    prefix = w.frags[sid][1].split('_')[0]
    pts, cols, bns = sample_surface(w, bones, mesh_ids, textures, step=0.08)
    snapped = nearest(boost(cols))
    names = [n[len(prefix):-4] for n, _p, _w in bones]
    groups = {'shirt': ('CH',), 'arms': ('BI', 'FO'), 'legs': ('TH', 'CA'), 'hips': ('PE',), 'head': ('HE',),
              'upper': ('BI',)}
    out = {}
    for key, starts in groups.items():
        sel = np.array([names[b].startswith(starts) for b in bns])
        if sel.any():
            vals, counts = np.unique(snapped[sel], axis=0, return_counts=True)
            out[key] = tuple(int(c) for c in vals[counts.argmax()])
    return out


def chain_links(bones, prefix, color, parts):
    """Brick chain links along a skeleton's chain bones (<P>_CHAIN01.., <P>_FICHAINL01..): one link per bone, from it
    toward the next in its chain, alternately flat and upright like real links. For Zebuxoruk, whose chains were in
    the body mesh the minifig replaces."""
    rest = [(n, np.array(T, float)) for n, _p, (_R, T) in bones]
    where = dict(rest)

    def shift(core):  # the minifig's hand (or calf) sits elsewhere than the model's: move that side's chains with it
        bone = next((n for n in (f'{prefix}_{core}_DAG', f'{prefix}{core}_DAG') if n in where), None)
        pts = [v[0] for q in parts if q.bone == bone for t in q.tris for v in t]
        return np.mean(pts, 0) - where[bone] if pts else np.zeros(3)
    offsets = {'L': shift('FIHANDL'), 'R': shift('FIHANDR'), 'legL': shift('CACALFL'), 'legR': shift('CACALFR')}
    chains = {}
    for n, T in rest:
        core = n[len(prefix):-4].lstrip('_')
        if 'CHAIN' not in core:
            continue
        key = re.sub(r'\d+$', '', core)
        key = 'LEG' + key[1:] if key.startswith('LCHAIN') else key  # LCHAINL01 then LEGCHAINL02..
        chains.setdefault(key, []).append((n, T))
    out = []
    for key, links in chains.items():
        side = key[-1] if key[-1] in 'LR' else 'R'  # the long chain (CHAIN01..) hangs from the right hand
        off = offsets[('leg' + side) if key.startswith('LEG') else side]
        for k, ((n, a), (_n2, b)) in enumerate(zip(links, links[1:])):
            a, b = a + off, b + off
            d = b - a
            ax = int(np.argmax(np.abs(d)))
            half = np.full(3, 0.07)
            half[ax] = abs(d[ax]) * 0.55
            half[(ax + 1 + k % 2) % 3] = 0.16  # wide one way, then the other
            c = (a + b) / 2
            p = minifig.Part(f'chain {key} {k}', n, color, c)
            minifig.box(p, c - half, c + half)
            out.append(p)
    return out


def build_person(w, sid, textures):
    import copy
    bones, mesh_ids = w.skeleton(sid)
    prefix = w.frags[sid][1].split('_')[0]
    rest = {n: np.array(T, float) for n, _p, (_R, T) in bones}
    base, opts = PEOPLE[prefix]

    def dressed(tex):
        race = copy.copy(minifig.RACES[base])
        look = outfit(w, sid, tex)
        race.shirt = look.get('shirt', race.shirt)
        race.arms = look.get('arms', race.shirt)
        race.legs = look.get('legs', race.legs)
        race.hips = race.belt = look.get('hips', race.belt)
        for k, v in opts.items():
            if k == 'skin' and v in ('head', 'upper'):  # skin from the model's own head or upper-arm texture
                race.skin = look.get(v, race.skin)
            elif k == 'hips':
                race.hips = race.belt = v
            else:
                setattr(race, k, v)
        return race

    vlist = [0] + variants_of(textures, prefix)
    races = [dressed(textures if v == 0 else textures_for(textures, prefix, v)) for v in vlist]
    for k, r in enumerate(races):  # each variant its own face print (variant 0 keeps the plain face)
        r.look = opts.get('look', k)
    race = races[0]
    look = {k: getattr(race, k) for k in ('skin', 'shirt', 'arms', 'legs', 'hips')}
    # Clothing the variants change (anything the options don't pin) is built in stand-in colors, then each
    # variant's atlas paints its own colors over them (swatches and prints alike)
    free = lambda r: r not in opts or (r == 'skin' and opts[r] in ('head', 'upper'))
    roles = [r for r in ('skin', 'shirt', 'arms', 'legs', 'hips') if free(r) and len({getattr(x, r) for x in races}) > 1]
    stand_in = {r: (3, 1 + k, 7) for k, r in enumerate(roles)}
    figure = copy.copy(race)
    for r, c in stand_in.items():
        setattr(figure, r, c)
        if r == 'hips':
            figure.belt = c
    minifig.use(figure)
    parts = minifig.build(figure)

    def old(core):  # THTHIGHL -> <prefix>THTHIGHL_DAG if the skeleton has it, else old style <prefix>TH_L_DAG
        for n in (f'{prefix}{core}_DAG', f'{prefix}_{core}_DAG', f'{prefix}_{core}02_DAG', f'{prefix}_{core}01_DAG'):
            if n in rest:  # ZEB_THTHIGHL_DAG, ZEB_CHCHEST02_DAG: newer skeletons with an underscore and numbered bones
                return n
        side = core[-1] if core[-1] in 'LR' and core[:-1] in OLD_BONES else ''
        key = core[:-1] if side else core
        if key in OLD_BONES:
            name = f"{prefix}{OLD_BONES[key].replace('?', side)}_DAG"
        else:
            name = f'{prefix}HE_DAG' if key.startswith(('HE', 'FA')) else f'{prefix}CH_DAG'
        for n in (name, f'{prefix}HEHEAD_DAG' if 'HE' in name else f'{prefix}CHCHEST_DAG', f'{prefix}CH_DAG'):
            if n in rest:
                return n
        return bones[0][0]
    pos = {f'NPX{d}{s}_DAG': rest[old(d + s)] for d in ('BOFOOT', 'THTHIGH', 'BIBICEP', 'FIHAND') for s in 'LR'}
    minifig.fit(parts, 'NPX', pos)
    for p in parts:
        p.bone = old(p.bone[3:-4])
    if opts.get('head') in ('pumpkin', 'squid'):  # Samhain's jack-o'-lantern, the Amygdalan's squid head: in place
        head = [p for p in parts if getattr(p, 'group', '') == 'head']  # of the minifig head (and its hair)
        vs = np.array([v[0] for p in head for t in p.tris for v in t])
        parts = [p for p in parts if getattr(p, 'group', '') != 'head']
        if opts['head'] == 'pumpkin':
            scheme, sculpted = pumpkin_scheme(None, None), pumpkin_parts(vs.min(0), vs.max(0), head[0].bone)
        else:
            scheme, sculpted = squid_head(vs, head[0].bone, head[0].bone, reach=0.5)
        for p, role in sculpted:
            p.material, p.group = scheme[role], 'head'
            parts.append(p)
    if opts.get('chains'):
        parts += chain_links(bones, prefix, opts['chains'], parts)
    atlas, uvmap = make_s3d.make_atlas(parts)
    px = np.asarray(atlas.convert('RGB'))
    atlases, previews = {}, []
    for v, r in zip(vlist, races):
        a = px.copy()
        for role, c in stand_in.items():
            a[np.all(px == c, axis=-1)] = getattr(r, role)
        atlases[v] = Image.fromarray(a)
        if len(vlist) > 1:  # the top half is the face print: this variant's own face and skin
            atlases[v].paste(minifig.face_texture(r).resize((512, 256)), (0, 0))
        pp = []
        for p in parts:
            q = copy.copy(p)
            if not isinstance(p.material, str):
                for role, c in stand_in.items():
                    if tuple(p.material) == c:
                        q.material = getattr(r, role)
            pp.append(q)
        previews.append((v, r, pp))
    body = body_mesh(w, prefix, mesh_ids)
    return dict(prefix=prefix, bones=bones, parts=parts, body=body, atlases=atlases, uvmap=uvmap, cubes=0, size=0,
                look=look, race=race, previews=previews)


def fire_beetle(filled, colors, bone, bone_names):
    """All-black legs; a glowing red body (orange-red along the top of the shell)."""
    BLACK, DARK_RED, RED, GLOW = (27, 42, 52), (114, 14, 15), (201, 26, 9), (255, 80, 30)
    names = [n[3:-4] for n in bone_names]  # BETTH1L_DAG -> TH1L
    leg = np.array([n[:2] in ('TH', 'CA', 'BO', 'TO') and n[2:3].isdigit() for n in names] + [False])
    out = colors.copy()
    dims = filled.shape
    # The body's footprint (cells on body bones): anything inside it is shell, whatever bone is nearest
    core = filled & ~leg[bone] & (bone >= 0)
    cx, cy, cz = np.nonzero(core)
    ylo, yhi = np.percentile(cy, 5), np.percentile(cy, 95)
    zlo = np.percentile(cz, 10)
    for x, y, z in zip(*np.nonzero(filled)):
        b = bone[x, y, z]
        n = names[b] if b >= 0 else ''
        if leg[b] and not (ylo <= y <= yhi and z >= zlo):
            out[x, y, z] = BLACK
        else:  # body, and the head (it rides on the mandible bones)
            top = z + 1 >= dims[2] or not filled[x, y, z + 1]
            out[x, y, z] = GLOW if top else RED
    return out


def dragon_scheme(filled, colors):
    """The dragon's colors: red (Nagafen and most) or, when the textures are mostly blue, ice (Lady Vox)."""
    seen = colors[filled].mean(0)
    s = dict(dark=(27, 42, 52), mid=(114, 14, 15), main=(201, 26, 9), belly=(169, 85, 0))
    if seen[2] > seen[0]:
        s = dict(dark=(0, 57, 94), mid=(90, 147, 219), main=(244, 244, 244), belly=(159, 195, 233))
    s.update(jaw=s['mid'], mouth=(5, 19, 29), tooth=(244, 244, 244), iris=(242, 205, 55), pupil=(5, 19, 29),
             glint=(244, 244, 244))
    return s


def own_scheme(filled, colors):
    """A sculpted head's colors from the creature's own bricks: main = its most common color, dark = the darkest
    common one, mid = the second most common, belly = the lightest common one; teeth, eyes and mouth as the dragon's."""
    cs = [tuple(int(a) for a in c) for c in colors[filled]]
    if not cs:
        return dragon_scheme(filled, colors)
    from collections import Counter
    common = [c for c, _n in Counter(cs).most_common(5)]
    lum = lambda c: 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    main = common[0]
    mid = common[1] if len(common) > 1 else main
    dark = min(common, key=lum)
    if dark == main:
        dark = (27, 42, 52)
    belly = max(common, key=lum)
    return dict(dark=dark, mid=mid, main=main, belly=belly, jaw=mid, mouth=(5, 19, 29), tooth=(244, 244, 244),
                iris=(242, 205, 55), pupil=(5, 19, 29), glint=(244, 244, 244))


def dragon(filled, colors, bone, bone_names):
    """Several reds and blacks so the dragon doesn't read as one blob: black wing arms, dark red wing skin, black
    claws, toes, spine spikes, horn ridge and tail tip, a dark orange belly, and a dark red scale pattern."""
    s = dragon_scheme(filled, colors)
    BLACK, DARK_RED, RED, BELLY = s['dark'], s['mid'], s['main'], s['belly']
    names = [n[3:-4] for n in bone_names] + ['']
    out = colors.copy()
    dims = filled.shape
    body = np.array([not (n.startswith('W') or n[:2] in ('C1', 'C2', 'C3', 'T1', 'T2', 'T3')) for n in names])
    ys = np.nonzero(filled & body[bone])[1]
    mid = np.median(ys) if len(ys) else dims[1] / 2
    for x, y, z in zip(*np.nonzero(filled)):
        n = names[bone[x, y, z]]
        top = z + 1 >= dims[2] or not filled[x, y, z + 1]
        under = z == 0 or not filled[x, y, z - 1]
        if n.startswith('W'):
            c = BLACK if n[1:3] in ('01', '02', '03', '04', '05') else DARK_RED
        elif n[:2] in ('C1', 'C2', 'C3', 'T1', 'T2', 'T3'):
            c = BLACK
        elif n.startswith('TA') and n[2:].isdigit() and int(n[2:]) >= 9:
            c = BLACK
        elif top and abs(y - mid) <= 0.6 and (n.startswith(('PE', 'WA', 'CH', 'NE', 'TA', 'HE'))):
            c = BLACK  # spine spikes and the horn ridge
        elif under and n.startswith(('PE', 'WA', 'CH', 'NE')):
            c = BELLY
        elif n == 'JA':
            c = DARK_RED
        else:
            c = DARK_RED if (x // 2 + y // 2 + z) % 4 == 0 else RED  # scales
        out[x, y, z] = c
    return out


DRA_HEAD_BOX = {'HE': ((-1.14, -0.98, -0.14), (1.87, 1.05, 0.95)), 'JA': ((-0.45, -0.61, -0.39), (1.83, 0.58, 0.48))}


def head_fit(bones, w, mesh_ids):
    """How to fit the classic dragon's sculpted head to another dragon: the size ratio r of its head bone's mesh to
    the classic dragon's (geometric mean over the three axes, in bone space) and, per bone (HE, JA), the offset that
    puts the sculpted piece's box center on that bone's mesh box center."""
    names = [n[3:-4] for n, _p, _t in bones]
    pts = {'HE': [], 'JA': []}
    for mi in mesh_ids:
        m = w.mesh(mi)
        for v, bi in zip(m['verts'], m['bones']):
            if names[bi] in pts:
                pts[names[bi]].append(v)
    if not pts['HE'] or not pts['JA']:
        return None
    box = {k: (np.min(v, 0), np.max(v, 0)) for k, v in pts.items()}
    ext = lambda b: np.maximum(np.asarray(b[1], float) - np.asarray(b[0], float), 1e-3)
    r = float(np.prod(ext(box['HE']) / ext(DRA_HEAD_BOX['HE'])) ** (1 / 3))
    mid = lambda b: (np.asarray(b[0], float) + np.asarray(b[1], float)) / 2
    return r, {k: mid(box[k]) - r * mid(DRA_HEAD_BOX[k]) for k in ('HE', 'JA')}, mid(box['HE'])


# Dragons whose own head is small for their bricks (the Velious dragons' wings span 60): their sculpted head is made
# this many times bigger, about the head's middle, so the snout reads at their brick size.
HEAD_BOOST = {'DR2': 2.2, 'BWD': 2.2, 'CCD': 2.2, 'PRI': 2.2, 'TRK': 2.2, 'DRU': 1.6}


def fitted_head(bones, w=None, mesh_ids=()):
    """The sculpted dragon head on another dragon's skeleton, sized and placed from its own head and jaw meshes."""
    fit = head_fit(bones, w, mesh_ids) if w is not None else None
    return dragon_head(bones, fit=fit, boost=HEAD_BOOST.get(bones[0][0][:3], 1)) if fit else []


def head_points(bones, w, mesh_ids, bone='HE'):
    """World-space (rest pose) points of the mesh on one bone, or None."""
    names = [n[3:-4] for n, _p, _t in bones]
    fr = [(np.array(R, float), np.array(T, float)) for _n, _p, (R, T) in bones]
    pts = []
    for mi in mesh_ids:
        m = w.mesh(mi)
        for v, bi in zip(m['verts'], m['bones']):
            if names[bi] == bone:
                R, T = fr[bi]
                pts.append(R @ np.array(v, float) + T)
    return np.array(pts) if pts else None


SQUID = dict(mantle=(132, 70, 148), spot=(92, 44, 108), eye=(236, 226, 186), pupil=(22, 20, 30),
             tentacle=(158, 92, 166), tip=(214, 156, 204))


def squid_head(pts, head, jaw, reach=1.0):
    """A squid's head in place of an Amygdalan's (DEN minifigs; MYG and AMY in eqgcreature.py): a tall purple mantle swept up and back with dark spots, two
    big pale eyes with dark pupils on the front (+x), and six tapering tentacles hanging over the chest from under
    the eyes. pts: the head's points (world space, face toward +x). The mantle and eyes ride the head bone, the tentacles
    the jaw. Returns (colors, [(Part, role)])."""
    lo, hi = pts.min(0), pts.max(0)
    R = 0.5 * (hi[2] - lo[2])
    cx, cy, cz = float(np.median(pts[:, 0])), float((lo[1] + hi[1]) / 2), float((lo[2] + hi[2]) / 2)
    out = []

    def part(name, bone, role, center):
        p = minifig.Part(name, bone, role, center)
        out.append((p, role))
        return p

    # mantle: stacked frustums from the face up to a rounded point, leaning back
    rings = [(-0.55, 0.55), (-0.2, 0.78), (0.25, 0.84), (0.75, 0.74), (1.25, 0.56), (1.7, 0.34), (2.0, 0.12)]
    axis = lambda t: np.array((cx - 0.32 * R * max(t, 0), cy, cz + t * R))
    for (t0, r0), (t1, r1) in zip(rings, rings[1:]):
        minifig.cylinder(part('mantle', head, 'mantle', axis((t0 + t1) / 2)), axis(t0), axis(t1), r0 * R, r1 * R, seg=14)
    # side fins near the tip
    for s in (1, -1):
        a = axis(1.45)
        ring = [a + (-0.25 * R, s * 0.3 * R, -0.25 * R), a + (0.05 * R, s * 0.3 * R, -0.25 * R),
                a + (0.05 * R, s * 0.62 * R, 0.05 * R), a + (-0.25 * R, s * 0.62 * R, 0.05 * R),
                a + (-0.25 * R, s * 0.3 * R, 0.25 * R), a + (0.05 * R, s * 0.3 * R, 0.25 * R),
                a + (0.05 * R, s * 0.5 * R, 0.3 * R), a + (-0.25 * R, s * 0.5 * R, 0.3 * R)]
        minifig.hexa(part('fin', head, 'mantle', a + (0, s * 0.45 * R, 0)), ring)
    # spots on the mantle's sides and front
    for t, ang in ((0.5, 0.6), (0.5, -0.6), (1.0, 1.4), (1.0, -1.4), (0.9, 0.0), (1.4, 0.7), (1.4, -0.7)):
        r = dict(rings)[min(dict(rings), key=lambda k: abs(k - t))] * R
        c = axis(t) + np.array((math.cos(ang), math.sin(ang), 0.0)) * r * 0.97
        minifig.cylinder(part('spot', head, 'spot', c), c - np.array((math.cos(ang), math.sin(ang), 0)) * 0.05 * R,
                         c + np.array((math.cos(ang), math.sin(ang), 0)) * 0.08 * R, 0.11 * R, seg=8)
    # eyes: big pale discs with pupils, on the front sides
    for s in (1, -1):
        d = np.array((math.cos(0.75), s * math.sin(0.75), 0.0))
        c = np.array((cx, cy, cz + 0.12 * R)) + d * 0.72 * R
        minifig.cylinder(part('eye', head, 'eye', c), c, c + d * 0.16 * R, 0.24 * R, seg=12)
        minifig.cylinder(part('pupil', head, 'pupil', c + d * 0.17 * R), c + d * 0.15 * R, c + d * 0.2 * R,
                         0.12 * R, seg=10)
    # tentacles: two tapered segments each, curling a little outward, from a ring under the eyes
    for k, ang in enumerate((-1.0, -0.6, -0.2, 0.2, 0.6, 1.0)):
        d = np.array((math.cos(ang), math.sin(ang), 0.0))
        root = np.array((cx, cy, cz - 0.42 * R)) + d * 0.5 * R
        length = (1.7 if k in (2, 3) else 1.35) * R * reach  # reach < 1: shorter, over a minifig's chest
        mid = root + d * 0.18 * R + np.array((0, 0, -0.55 * length))
        end = mid + d * 0.12 * R + np.array((0.08 * R, 0, -0.45 * length))
        minifig.cylinder(part('tentacle', jaw, 'tentacle', (root + mid) / 2), root, mid, 0.14 * R, 0.1 * R, seg=8)
        minifig.cylinder(part('tentacle', jaw, 'tentacle', (mid + end) / 2), mid, end, 0.1 * R, 0.06 * R, seg=8)
        minifig.cylinder(part('tip', jaw, 'tip', end), end, end + (end - mid) * 0.15, 0.06 * R, 0.02 * R, seg=6)
    # a face plate between the tentacle roots and the mantle, so no gap shows
    minifig.cylinder(part('face', head, 'mantle', (cx, cy, cz - 0.4 * R)), (cx, cy, cz - 0.6 * R),
                     (cx, cy, cz - 0.3 * R), 0.62 * R, 0.62 * R, seg=12)
    return SQUID, out


def pumpkin_scheme(filled, colors):
    return dict(pumpkin=(254, 138, 24), rib=(214, 96, 14), stem=(88, 42, 18), glow=(242, 205, 55),
                dark=(27, 42, 52))


def pumpkin_head(bones, w=None, mesh_ids=()):
    """A carved jack-o'-lantern in place of the head (Samhain, the scarecrow model SCA): a ribbed orange pumpkin
    as tall as the original head, a brown stem, glowing triangle eyes and nose and a toothy grin on the front (+x).
    Rides the head bone. Returns [(Part, color role)]."""
    pts = head_points(bones, w, mesh_ids) if w is not None else None
    if pts is None or len(pts) < 8:
        return []
    lo, hi = pts.min(0), pts.max(0)
    return pumpkin_parts(lo, hi, f'{bones[0][0][:3]}HE_DAG', float(np.median(pts[:, 0])))


def pumpkin_parts(lo, hi, bone, cx=None):
    """The jack-o'-lantern filling the box lo..hi (world space, face toward +x) on one bone: [(Part, role)]."""
    R = 0.5 * (hi[2] - lo[2]) * 1.05  # radius: half the head's height
    cx = float((lo[0] + hi[0]) / 2) if cx is None else cx
    cy, cz = float((lo[1] + hi[1]) / 2), float((lo[2] + hi[2]) / 2)
    out = []

    def part(name, role, center):
        p = minifig.Part(name, bone, role, center)
        out.append((p, role))
        return p

    # body: a squashed sphere from stacked frustums
    rings = [(-0.82, 0.55), (-0.6, 0.88), (-0.25, 1.05), (0.15, 1.05), (0.5, 0.9), (0.78, 0.55)]
    for (z0, r0), (z1, r1) in zip(rings, rings[1:]):
        a, b = (cx, cy, cz + z0 * R), (cx, cy, cz + z1 * R)
        minifig.cylinder(part('pumpkin', 'pumpkin', (cx, cy, cz + (z0 + z1) / 2 * R)), a, b, r0 * R, r1 * R, seg=16)
    # ribs: darker grooves around the middle
    base = np.array((cx, cy, cz))
    for k in range(8):
        ang = 2 * math.pi * (k + 0.5) / 8
        d = np.array((math.cos(ang), math.sin(ang), 0.0))
        t = np.array((-d[1], d[0], 0.0))
        c0, c1 = base + d * 0.98 * R, base + d * 1.08 * R
        lo_z, hi_z = np.array((0, 0, -0.45 * R)), np.array((0, 0, 0.35 * R))
        ring = [c0 - t * 0.06 * R + lo_z, c1 - t * 0.06 * R + lo_z, c1 + t * 0.06 * R + lo_z, c0 + t * 0.06 * R + lo_z,
                c0 - t * 0.06 * R + hi_z, c1 - t * 0.06 * R + hi_z, c1 + t * 0.06 * R + hi_z, c0 + t * 0.06 * R + hi_z]
        minifig.hexa(part('rib', 'rib', base + d * R), ring)
    # stem
    minifig.cylinder(part('stem', 'stem', (cx, cy, cz + 0.95 * R)), (cx, cy, cz + 0.7 * R),
                     (cx - 0.08 * R, cy, cz + 1.12 * R), 0.16 * R, 0.11 * R, seg=8)
    # face on the front: plates just outside the surface
    xf0, xf1 = cx + 0.96 * R, cx + 1.06 * R

    def tri(name, yc, zb, zt, hw):  # a triangle pointing up
        ring = [(xf0, yc - hw, zb), (xf1, yc - hw, zb), (xf1, yc + hw, zb), (xf0, yc + hw, zb),
                (xf0, yc, zt), (xf1, yc, zt), (xf1, yc, zt), (xf0, yc, zt)]
        minifig.hexa(part(name, 'glow', ((xf0 + xf1) / 2, yc, (zb + zt) / 2)), ring)

    for s in (1, -1):
        tri('eye', cy + s * 0.42 * R, cz + 0.12 * R, cz + 0.5 * R, 0.2 * R)
    tri('nose', cy, cz - 0.1 * R, cz + 0.12 * R, 0.1 * R)
    mz0, mz1 = cz - 0.5 * R, cz - 0.24 * R
    minifig.box(part('mouth', 'glow', ((xf0 + xf1) / 2, cy, (mz0 + mz1) / 2)), (xf0, cy - 0.55 * R, mz0),
                (xf1, cy + 0.55 * R, mz1))
    for ty, top in ((-0.25, True), (0.2, False)):  # two pumpkin teeth across the grin
        z0, z1 = (mz1 - 0.12 * R, mz1 + 0.005) if top else (mz0 - 0.005, mz0 + 0.12 * R)
        minifig.box(part('tooth', 'pumpkin', (xf1 + 0.01, cy + ty * R, (z0 + z1) / 2)),
                    (xf0 + 0.02, cy + (ty - 0.08) * R, z0), (xf1 + 0.03, cy + (ty + 0.08) * R, z1))
    return out


def dragon_head(bones, scale=1.2, fit=None, boost=1):
    """A sculpted brick head in place of the dragon's voxel head (too few cubes for a face): a long pointed snout,
    yellow slit eyes under dark brows, swept-back horns, nostrils, white teeth along both jaws and a dark mouth.
    The upper head rides the head bone, the lower jaw (with its teeth) the jaw bone, so the mouth still opens.
    Returns [(Part, color role)], or [] when the skeleton has no head and jaw bones."""
    frame = {n[3:-4]: (np.array(R, float), np.array(T, float)) for n, _p, (R, T) in bones}
    if 'HE' not in frame or 'JA' not in frame:
        return []
    P = bones[0][0][:3]
    (Rh, Th), (Rj, Tj) = frame['HE'], frame['JA']
    C = 0.08  # the head's middle across (its y center)
    if fit:  # another dragon: scale r in bone space, each piece moved onto its bone's own mesh
        r, off, center = fit
        scale = 1.2 * r * boost
        cw = Rh @ center + Th  # the head's middle in world space: boost scales about it
        grow = lambda p: cw + boost * (p - cw)
        H = lambda x, y, z: grow(Rh @ (r * np.array((x, y + C, z)) + off['HE']) + Th)
        J = lambda x, y, z: grow(Rj @ (r * np.array((x, y + C, z)) + off['JA']) + Tj)
    else:  # the classic dragon (DRA): scaled 1.2 about the head joint, as tuned in game
        big = lambda p: Th + scale * (np.asarray(p, float) - Th)
        H = lambda x, y, z: big(Rh @ np.array((x, y + C, z)) + Th)  # head-bone space -> world
        J = lambda x, y, z: big(Rj @ np.array((x, y + C, z)) + Tj)  # jaw-bone space -> world
    out = []

    def part(name, bone, role, center):
        p = minifig.Part(name, f'{P}{bone}_DAG', role, center)
        out.append((p, role))
        return p

    def block(name, bone, role, f, back, front):
        """Tapered block along x: back/front = (x, half width, z bottom, z top)."""
        (x0, w0, b0, t0), (x1, w1, b1, t1) = back, front
        ring = [f(x0, -w0, b0), f(x1, -w1, b1), f(x1, w1, b1), f(x0, w0, b0),
                f(x0, -w0, t0), f(x1, -w1, t1), f(x1, w1, t1), f(x0, w0, t0)]
        minifig.hexa(part(name, bone, role, np.mean(ring, 0)), ring)

    def spike(name, bone, role, f, base, tip, r):
        a, b = f(*base), f(*tip)
        minifig.cylinder(part(name, bone, role, (2 * a + b) / 3), a, b, r * scale, 0.004, seg=4)

    block('cranium', 'HE', 'main', H, (-1.0, 0.85, 0.05, 0.95), (0.45, 0.72, 0.05, 0.9))
    block('snout', 'HE', 'main', H, (0.45, 0.6, 0.3, 0.85), (2.15, 0.14, 0.33, 0.52))
    block('mouth', 'HE', 'mouth', H, (0.2, 0.5, 0.0, 0.32), (1.85, 0.12, 0.05, 0.34))
    block('jaw', 'JA', 'jaw', J, (-0.3, 0.55, -0.3, 0.2), (2.0, 0.13, 0.0, 0.2))
    hw = lambda x: 0.6 + (0.14 - 0.6) * (x - 0.45) / 1.7      # snout half width
    jw = lambda x: 0.55 + (0.13 - 0.55) * (x + 0.3) / 2.3     # jaw half width
    for s in (1, -1):
        # eye: a yellow disc on the side of the head, black slit pupil, white glint, dark brow over it
        ex, ez, ey = 0.22, 0.62, 0.74
        a, b = H(ex, s * (ey - 0.06), ez), H(ex, s * (ey + 0.1), ez)
        minifig.cylinder(part('eye', 'HE', 'iris', (a + b) / 2), a, b, 0.21 * scale, seg=16)
        block('pupil', 'HE', 'pupil', lambda x, y, z, s=s: H(x, s * (ey + 0.112 + y), z),
              (ex - 0.035, 0.012, ez - 0.17, ez + 0.17), (ex + 0.035, 0.012, ez - 0.17, ez + 0.17))
        block('glint', 'HE', 'glint', lambda x, y, z, s=s: H(x, s * (ey + 0.13 + y), z),
              (ex + 0.06, 0.012, ez + 0.06, ez + 0.11), (ex + 0.11, 0.012, ez + 0.06, ez + 0.11))
        block('brow', 'HE', 'dark', lambda x, y, z, s=s: H(x, s * (0.62 + y), z),
              (-0.15, 0.2, 0.84, 1.06), (0.6, 0.16, 0.8, 0.96))
        spike('horn', 'HE', 'dark', H, (-0.6, s * 0.48, 0.8), (-1.95, s * 0.78, 1.4), 0.22)
        block('nostril', 'HE', 'dark', lambda x, y, z, s=s: H(x, s * (0.08 + y), z),
              (1.82, 0.035, 0.5, 0.56), (1.98, 0.03, 0.47, 0.52))
        # teeth: down from the upper jaw, up from the lower; a long fang near the front of each
        for x in (0.75, 1.05, 1.35, 1.65, 1.95):
            fang = abs(x - 1.65) < 0.01
            y = s * (hw(x) - 0.07)
            spike('tooth', 'HE', 'tooth', H, (x, y, 0.33), (x, y, 0.33 - (0.32 if fang else 0.17)), 0.08 if fang else 0.06)
        for x in (0.8, 1.1, 1.4, 1.7):
            fang = abs(x - 1.4) < 0.01
            y = s * (jw(x) - 0.06)
            spike('tooth', 'JA', 'tooth', J, (x, y, 0.2), (x, y, 0.2 + (0.28 if fang else 0.15)), 0.08 if fang else 0.06)
    return out


# See-through parts: a creature's translucent material (by name) is bricked as glass bricks drawn with that same
# material, in fire colors (bottom to top). The portal's (BTP) window.
GLASS = {'BTP': 'TSFUNGTRANS02_MDF'}
FIRE = [(242, 205, 55), (254, 138, 24), (201, 26, 9)]  # yellow, orange, red
# Textures a creature's materials use that don't carry its prefix: they get its atlas too.
OWN_TEXTURES = {'tsfungtrans01': 'btp', 'tsfungtrans02': 'btp'}


def fire_colors(glass):
    """Fire colors for the glass cubes: yellow low, red high, with a scatter so it reads as flames."""
    zs = np.nonzero(glass)[2]
    z0, z1 = zs.min(), max(zs.max(), zs.min() + 1)
    out = {}
    rng = np.random.default_rng(7)
    for x, y, z in zip(*np.nonzero(glass)):
        f = (z - z0) / (z1 - z0) * 3 + rng.normal(0, 0.6)
        out[x, y, z] = FIRE[int(np.clip(f, 0, 2))]
    return out


# Voxel creatures with a face painted on the front of their head cubes (head bones: <P>HE...): eyes, a mouth, fangs.
VOXEL_FACES = {'NMG': dict(eyes=(220, 40, 30), mouth=(27, 27, 30), teeth=(244, 244, 244))}  # Nightmare hobgoblin


def paint_face(stack, filled, bone, bone_names, prefix, nvar, eyes, mouth, teeth=None):
    """Recolor the front cubes of the head (+x faces forward) in every variant: two eyes high, a mouth low with a
    fang at each end."""
    on = [k for k, n in enumerate(bone_names) if n[len(prefix):].lstrip('_').startswith('HE')]
    head = filled & np.isin(bone, on)
    if head.sum() < 6:
        return
    xs, ys, zs = np.nonzero(head)
    z0, z1 = zs.min(), zs.max()
    yc = int(round(ys.mean()))
    half = max(1, (ys.max() - ys.min()) // 4)

    def put(y, z, c):
        col = head[:, y, z]
        if col.any():
            x = np.nonzero(col)[0].max()  # the frontmost head cube in that row
            stack[x, y, z] = c * nvar

    ze = z0 + int(round(0.62 * (z1 - z0)))
    zm = z0 + int(round(0.25 * (z1 - z0)))
    for side in (-1, 1):
        put(yc + side * half, ze, eyes)
    for y in range(yc - half, yc + half + 1):
        put(y, zm, mouth)
    if teeth and z1 - z0 >= 5:  # on a small head the fangs beside the mouth read as a second pair of eyes
        for side in (-1, 1):
            put(yc + side * half, zm, teeth)


COLOR_RULES = {'BET': fire_beetle, 'DRA': dragon}
# Creatures with a sculpted head instead of voxels: (color scheme, head builder(bones, w, mesh_ids), bones it replaces).
# The other dragons, drakes, wurms and wyverns get the classic dragon's head fitted to their own head (2026-11-11).
HEADS = {'DRA': (dragon_scheme, lambda bones, w, mesh_ids: dragon_head(bones), ('HE', 'JA'))}
HEADS.update({p: (own_scheme, fitted_head, ('HE', 'JA'))
              for p in ('DR2', 'BWD', 'CCD', 'PRI', 'TRK', 'DRU', 'GDR', 'DRK', 'WUR', 'WYV')})
VOXELS = {'NMG': 30, 'DRA': 30, 'TRK': 45, 'CCD': 45, 'PRI': 45, 'DR2': 45, 'BWD': 45, 'DRU': 45, 'TMT': 30, 'GDR': 30}  # big creatures that need finer bricks to keep their shape


# Texture variants: <prefix><part><variant><index>, e.g. giach0101 = giant chest, variant 1. The NPC's texture
# number picks the variant; the meshes always name variant 00 and the client swaps the digits.
# Old two-letter models (KA, CL) name textures ka + ch + 0001: kafa0001 is KA's face, kafch0001 KAF's chest.
VARIANT = re.compile(r'^([a-z]{2,3})([a-z]{2})(\d\d)(\d\d)$')


def variants_of(textures, prefix):
    found = {int(m.group(3)) for m in map(VARIANT.match, textures) if m and m.group(1) == prefix.lower()}
    return sorted(found - {0})


def textures_for(textures, prefix, v):
    """The texture set as variant v sees it: each variant-00 texture of the prefix replaced by its variant-v twin."""
    out = dict(textures)
    for n in textures:
        m = VARIANT.match(n)
        if m and m.group(1) == prefix.lower() and m.group(3) == '00':
            alt = f'{m.group(1)}{m.group(2)}{v:02d}{m.group(4)}'
            if alt in textures:
                out[n] = textures[alt]
    return out


def texture_owner(name, sheets):
    """The built creature a texture file belongs to (its prefix, lower case), or None."""
    stem = name.lower().rsplit('.', 1)[0]
    if OWN_TEXTURES.get(stem) in sheets:
        return OWN_TEXTURES[stem]
    m = VARIANT.match(stem)
    if m:
        return m.group(1) if m.group(1) in sheets else None
    return name[:3].lower() if name[:3].lower() in sheets else None


def variant_material(mats, textures, prefix):
    """The material the brick body is drawn with. The client shows texture variant N by swapping a material's
    <part>00<index> texture for <part>NN<index>, so the body needs a material whose texture has a twin in every
    variant (chest first); the first textured one (often a head texture with no variants, as on the giants) left
    every NPC in variant 0's colors."""
    vl = variants_of(textures, prefix)
    good = []
    for n, method, tex in mats:
        m = VARIANT.match((tex or '').lower())
        if method and m and m.group(1) == prefix.lower() and m.group(3) == '00' and all(
                f'{m.group(1)}{m.group(2)}{v:02d}{m.group(4)}' in textures for v in vl):
            good.append((m.group(2) != 'ch', n))
    if good:
        return min(good)[1]
    return next((n for n, method, tex in mats if tex and method), mats[0][0])


def class_atlases(classes, nvar):
    """One 512x512 atlas per variant, one swatch per color class (a class = a cube's colors in every variant)."""
    n = len(classes)
    cell = 32 if n <= 256 else 16 if n <= 1024 else 8
    grid = 512 // cell
    assert n <= grid * grid, f'{n} color classes'
    pos = []
    imgs = [Image.new('RGB', (512, 512), (128, 128, 128)) for _ in range(nvar)]
    for k, key in enumerate(classes):
        x, y = (k % grid) * cell, (k // grid) * cell
        for j in range(nvar):
            imgs[j].paste(Image.new('RGB', (cell, cell), key[3 * j:3 * j + 3]), (x, y))
        pos.append(((x + cell / 2) / 512, (y + cell / 2) / 512))
    return imgs, pos


def fake(k):  # a class number as the stand-in color of its brick parts
    return (k % 256, k // 256, 1)


def unfake(material):
    return int(material[0]) + 256 * int(material[1])


def build_creature(w, sid, textures, voxels, ncolors=5):
    bones, mesh_ids = w.skeleton(sid)
    prefix = w.frags[sid][1].split('_')[0]
    pts, cols, bns = sample_surface(w, bones, mesh_ids, textures, step=1.0)  # coarse first, for the size
    if len(pts) == 0:  # a skeleton without a body in this file (its mesh lives elsewhere): leave it alone
        print(f'{prefix}: no body here, skipped')
        return None
    ext = np.sort(pts.max(0) - pts.min(0))
    size = min(ext[2] / voxels, ext[1] / 5)  # thin creatures (snakes) are sized by their thickness
    glass_mat = GLASS.get(prefix)
    pts, cols, bns, *g = sample_surface(w, bones, mesh_ids, textures, step=size / 3, glass=glass_mat)
    lo, filled, color, bone = voxelize(pts, cols, bns, size)
    glass = np.zeros(filled.shape, bool)
    if glass_mat:  # cubes whose samples are mostly on the translucent material
        idx = np.floor((pts - lo) / size).astype(int)
        votes = np.zeros(filled.shape, int)
        np.add.at(votes, tuple(idx.T), np.where(g[0], 1, -1))
        glass = filled & (votes > 0)
        fire = fire_colors(glass) if glass.any() else {}
    bone_names = [n for n, _p, _w in bones]

    schemes = []  # per variant: the colors of a sculpted head

    def finish(grid):
        snapped = palette_colors(grid, filled, ncolors, FIXED_COLORS.get(prefix))
        snapped = smooth_colors(filled, snapped)
        if prefix in HEADS:
            schemes.append(HEADS[prefix][0](filled, snapped))
        if prefix in COLOR_RULES:
            snapped = COLOR_RULES[prefix](filled, snapped, bone, bone_names)
        return snapped

    vlist = [0] + variants_of(textures, prefix)
    grids = [finish(color)]
    for v in vlist[1:]:  # the same surface points, colored from the variant's textures
        _p, cols_v, _b = sample_surface(w, bones, mesh_ids, textures_for(textures, prefix, v), step=size / 3)
        grids.append(finish(voxelize(pts, cols_v, bns, size)[2]))
    stack = np.concatenate(grids, axis=-1)
    if prefix in VOXEL_FACES:
        paint_face(stack, filled, bone, bone_names, prefix, len(vlist), **VOXEL_FACES[prefix])
    classes, cls = {}, np.zeros(color.shape, np.float32)
    for x, y, z in zip(*np.nonzero(filled)):
        key = tuple(int(a) for a in stack[x, y, z])
        if glass[x, y, z]:  # glass classes stay apart from frame classes of the same color
            key = tuple(fire[x, y, z]) * len(vlist) + ('glass',)
        cls[x, y, z] = fake(classes.setdefault(key, len(classes)))
    head = HEADS[prefix][1](bones, w, mesh_ids) if prefix in HEADS else []
    if head:  # the sculpted head replaces the cubes on its bones
        on = [k for k, n in enumerate(bone_names) if n[3:-4] in HEADS[prefix][2]]
        filled = filled & ~np.isin(bone, on)
        for p, role in head:
            p.material = fake(classes.setdefault(tuple(c for s in schemes for c in s[role]), len(classes)))
    classes = list(classes)
    parts = build_parts(lo, size, filled, cls, bone, bone_names) + [p for p, _r in head]
    for p in parts:
        if not isinstance(p.material, str) and classes[unfake(p.material)][-1] == 'glass':
            p.glass = glass_mat
    imgs, pos = class_atlases(classes, len(vlist))
    uvmap = lambda material, u, v: pos[unfake(material)]
    previews = []
    for j, v in enumerate(vlist):
        pp = []
        for p in parts:
            q = copy.copy(p)
            q.material = classes[unfake(p.material)][3 * j:3 * j + 3]
            pp.append(q)
        previews.append((v, None, pp))
    body = body_mesh(w, prefix, mesh_ids)
    return dict(prefix=prefix, bones=bones, parts=parts, body=body, cubes=int(filled.sum()), size=size, glass=int(glass.sum()),
                atlases=dict(zip(vlist, imgs)), uvmap=uvmap, previews=previews, classes=len(classes))


def main():
    src, dst = sys.argv[1:3]
    voxels = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != '-' else 18
    skip = SKIP
    only = set(sys.argv[4].split(',')) if len(sys.argv) > 4 else None  # rebuild just these creatures
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    textures = texture_images(files)
    creatures = []
    for sid, _f in w.of_type(0x10):
        prefix = w.frags[sid][1].split('_')[0]
        if prefix in skip or (only and prefix not in only):
            continue
        if prefix in PEOPLE:
            creatures.append(build_person(w, sid, textures))
        else:
            try:
                c = build_creature(w, sid, textures, VOXELS.get(prefix, voxels))
            except (OverflowError, struct.error, IndexError) as e:  # a malformed mesh (IVM in global_chr)
                print(f'{prefix}: unreadable mesh ({type(e).__name__}), left as it was')
                c = None
            if c:
                creatures.append(c)
    built = {c['prefix'] for c in creatures}
    bodies = {c['body']: c for c in creatures}
    grips = {}  # minifig NPCs: weapons in the C-grip hands
    for c in creatures:
        if c['prefix'] in PEOPLE:
            grips.update(make_s3d.grip_fixes(w, c))
    frags = []
    for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
        if i in bodies:
            c = bodies[i]
            uvmap = c['uvmap']
            mats = w.mesh(i)['materials']
            mat = variant_material(mats, textures, c['prefix'])
            if c.get('glass'):  # glass bricks on the translucent material, the rest on the body's
                mat = (lambda m0: lambda p: getattr(p, 'glass', None) or m0)(mat)
            raw = make_s3d.mesh_body(w, i, c['parts'], c['bones'], uvmap, mat)
        elif i in grips:
            raw = make_s3d.set_track_offset(raw, grips[i])
        elif ftype == 0x36 and name[:3] in built:  # head variations and other pieces: the bricks are the whole body
            raw = make_s3d.flatten_mesh(raw)
        frags.append((ftype, raw))
    new_wld = make_s3d.write_wld(wld_data, frags)
    kept_tex = set()  # textures of pieces left as they were (Zeb's hook and chain): not overwritten with an atlas
    for i, (ftype, name, _raw) in enumerate(w.frags[1:], start=1):
        if ftype == 0x36 and i not in bodies and name[:3] not in built:
            m = w.mesh(i)
            kept_tex |= {(m['materials'][f[-1]][2] or '').lower() for f in m['faces']}
    sheets = {c['prefix'].lower(): {v: make_s3d.dds_dxt1(a) for v, a in c['atlases'].items()} for c in creatures}
    out = []
    for n, b in files:
        if n == wld_name:
            b = new_wld
        elif n.lower().endswith(('.bmp', '.dds')) and texture_owner(n, sheets) and                 n.lower().rsplit('.', 1)[0] not in kept_tex:
            m = VARIANT.match(n.lower().rsplit('.', 1)[0])
            by_variant = sheets[texture_owner(n, sheets)]
            b = by_variant.get(int(m.group(3)) if m else 0, by_variant[0])
        out.append((n, b))
    pfs.write(dst, out)
    stem = os.path.splitext(dst)[0]
    for c in creatures:
        rows = []
        for k, (v, race, pp) in enumerate(c['previews']):
            if race is not None:  # the prints are shared module state: point them at this variant's figure
                minifig.use(race)
            path = f"{stem}_{c['prefix']}_preview.png" if k == 0 else f"{stem}_{c['prefix']}_v{v}.png"
            minifig.preview(path, pp, size=320, ss=1)
            rows.append(path)
        if len(rows) > 1:  # one sheet with every variant, top to bottom
            ims = [Image.open(r).convert('RGB') for r in rows]
            sheet = Image.new('RGB', (ims[0].width, sum(i.height for i in ims)))
            y = 0
            for i in ims:
                sheet.paste(i, (0, y))
                y += i.height
            sheet.save(f"{stem}_{c['prefix']}_variants.png")
            for r in rows[1:]:
                os.remove(r)
        nv = len(c['previews'])
        print(f"{c['prefix']}: " + (f"minifig {c['look']}" if 'look' in c else
                                    f"{c['cubes']} bricks of {c['size']:.2f}, {c['classes']} color classes")
              + (f', {nv} variants' if nv > 1 else ''))
    print(f'{len(out)} files -> {dst}')


if __name__ == '__main__':
    main()
