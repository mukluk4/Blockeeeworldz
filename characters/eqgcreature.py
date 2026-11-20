"""Brick creatures stored as newer .eqg models (.mod: one mesh; .mds: a body piece plus head pieces).

The same bricks as brickcreature.py: the model's surface is sampled in its bind pose (EQG vertices are stored in model
space, z up, feet at 0), voxelized, colored from its diffuse textures and built as studded bricks. Each brick rides the
bone that most of its surface follows, so the creature's own animations (.ani) still move it.

Writing: the bricks replace the body (.mod) or the first drawn body piece (.mds); every other piece (head choices,
spare parts) becomes one hidden triangle. Texture names are global in the client, so every material and every entry
of the variant table (.lay) points at the creature's own new textures c_<code>_brick_c.dds / _n.dds instead of
painting over shared names. All texture variants show the first variant's colors (variants come later).

    python -I eqgcreature.py <client folder> <out folder> <zone> [zone ...] [--global] [--read-only]
    python -I eqgcreature.py --archive <archive.eqg> <out.eqg> code[,code...]

Models come from each zone's <zone>_chr.txt (lines "model,archive"), and with --global also from the client's
Resources/GlobalLoad_chr.txt; .s3d archives there are brickcreature.py's job. Archives are read from
<client>/brick_orig/<archive>.eqg.orig when it exists, else the client copy is backed up there first (never with
--read-only). --archive bricks the named models of one archive (scripts/review_eqg.py uses it).

Like brickcreature.py: stray clumps of bricks follow the limb they touch and floating limbs get a short bridge to
their parent (anchor_limbs), and the head gets built eyes where the stock texture shows a pair (best candidate, or
the hand pick in creature_eyes.json under "eqg:<code>"; null there means none). Distance models (<code>_lod1.mod...)
get the same bricks, so a creature doesn't turn back into its stock self far away.
"""
import math, os, re, shutil, struct, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import io
import brickcreature as bc
import eqgbones, eqgmds, eqgmod, make_s3d, minifig, pfs

VOXELS = 18
SKIP = set()


def strings_of(m, off):
    return m.strings[off:m.strings.index(b'\0', off)].decode('latin-1')


def material_textures(m, files):
    """[material index] -> RGB image of its diffuse texture (None when the texture isn't in the archive)."""
    out = []
    for _i, _n, _s, props in m.materials:
        img = None
        for pr in props:
            pn, pt, pv = struct.unpack('<3I', pr)
            if strings_of(m, pn) == 'e_TextureDiffuse0' and pt == 2:
                data = files.get(strings_of(m, pv).lower())
                if data:
                    try:
                        img = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'), np.float32)
                    except Exception:
                        img = None
        out.append(img)
    return out


def meshes(m, kind):
    """[(verts, tris, weights)] of the drawn geometry: the .mod, or the .mds pieces drawn by default."""
    if kind == 'mod':
        return [(m.verts, m.tris, m.weights)]
    drawn = [p for p in m.pieces if p['main']] or m.pieces  # single-piece models often mark none as drawn
    return [(p['verts'], p['tris'], p['weights']) for p in drawn]


def sample_points(m, kind, texs, step, only=None):
    """Surface points, their texture colors and the bone each rides. only: bones whose triangles alone are sampled."""
    pts, cols, bns = [], [], []
    for verts, tris, weights in meshes(m, kind):
        P = np.array([v[0] for v in verts], float)
        UV = np.array([v[3] for v in verts], float)
        top = [max(w[1][:max(1, w[0])], key=lambda bw: bw[1])[0] for w in weights] if weights else [0] * len(verts)
        for a, b, c, mat, _fl in tris:
            if only is not None and not {top[a], top[b], top[c]} & only:
                continue
            img = texs[mat] if 0 <= mat < len(texs) else None
            A, B, Cc = P[a], P[b], P[c]
            n = max(1, int(math.ceil(max(np.linalg.norm(B - A), np.linalg.norm(Cc - A), np.linalg.norm(Cc - B)) / step)))
            for i in range(n + 1):
                for j in range(n + 1 - i):
                    k = n - i - j
                    l = (i / n, j / n, k / n)
                    pts.append(l[0] * A + l[1] * B + l[2] * Cc)
                    if img is not None:
                        u, v = l[0] * UV[a] + l[1] * UV[b] + l[2] * UV[c]
                        h, wd = img.shape[:2]
                        cols.append(img[int((1.0 - v % 1.0) * h) % h, int((u % 1.0) * wd) % wd])  # rows from the bottom
                    else:
                        cols.append(np.array((128, 128, 128), np.float32))
                    bns.append(top[(a, b, c)[int(np.argmax(l))]])  # the bone of the nearest corner
    return np.array(pts, float), np.array(cols, np.float32), np.array(bns, int)


def metal(rgb):
    """Browns and tans as toy metal: greys by lightness (review 2026-11-19, SWC)."""
    r, g, b = rgb
    if max(rgb) - min(rgb) < 25:  # already grey
        return rgb
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    return (27, 42, 52) if lum < 45 else (99, 95, 98) if lum < 95 else (137, 135, 136) if lum < 150 else (160, 165, 169)


def gold(rgb):
    """Greys as gold, by lightness (review 2026-11-19, ROB); colored cubes stay."""
    r, g, b = rgb
    if max(rgb) - min(rgb) >= 25:
        return rgb
    lum = (r + g + b) / 3
    return (124, 92, 70) if lum < 60 else (170, 127, 46) if lum < 140 else (220, 188, 129)


RECOLOR = {'ROB': gold, 'SWC': metal}
# Painted details on the front (+x) cubes: (height as a share of the model, radius in cubes, color).
FRONT_DOT = {'CNP': (0.55, 1, (53, 33, 21), True)}  # the satchel's clasp, a ring
# Creatures whose limbs get a path of bricks in to their joint, so they turn around it (bc.pivot_bridge).
PIVOT = {'SWC'}
# Models built from another creature's stock surface: (archive, creature, translucent material index here).
# The newer portal looks like the Rift Portal in The Void (the classic BoT portal, its window in fire glass).
SURFACE_FROM = {'PRT': ('bothunder_chr.s3d', 'BTP', 1)}


def borrowed_surface(client, archive, prefix, step):
    """(points, colors, glass flags) on another creature's stock .s3d surface, or None."""
    import wld
    path = next((p for p in (os.path.join(client, 'brick_orig', archive + '.orig'), os.path.join(client, archive))
                 if os.path.exists(p)), None)
    if not path:
        return None
    files = pfs.read(path)
    w = wld.Wld(next(b for n, b in files if n.endswith('.wld')))
    textures = bc.texture_images(files)
    for sid, _f in w.of_type(0x10):
        if w.frags[sid][1].split('_')[0] == prefix:
            bones, mesh_ids = w.skeleton(sid)
            pts, cols, _b, glass = bc.sample_surface(w, bones, mesh_ids, textures, step, glass=bc.GLASS.get(prefix))
            return pts, cols, glass
    return None


def drop_crumbs(filled, bone, parent, kin, most=2, near=3):
    """Remove clumps of at most `most` cubes that are more than `near` cells from every cube of their bone's
    ancestors (a lone cape-hem cube anchor_limbs could not bridge: MYG). -> cubes removed."""
    removed = 0
    for b in set(bone[filled].tolist()):
        anc, p = set(kin.get(b, set())), parent[b] if 0 <= b < len(parent) else -1
        while p >= 0:
            anc.add(p)
            p = parent[p]
        mine = np.argwhere(filled & (bone == b))
        others = np.argwhere(filled & np.isin(bone, list(anc))) if anc else np.zeros((0, 3), int)
        if not len(others) or len(mine) > 40:
            continue
        left = {tuple(c) for c in mine}
        while left:  # face-connected clumps of this bone
            start = left.pop()
            clump, stack = [start], [start]
            while stack:
                x, y, z = stack.pop()
                for q in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z), (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
                    if q in left:
                        left.discard(q)
                        clump.append(q)
                        stack.append(q)
            if len(clump) <= most and np.abs(np.array(clump)[:, None] - others[None]).sum(2).min() > near:
                for q in clump:
                    filled[q] = False
                removed += len(clump)
    return removed


def front_dot(filled, snapped, height, radius, rgb, ring=False):
    """Recolor the frontmost cube of each row in a small disc on the middle of the front (ring: not its middle)."""
    xs, ys, zs = np.nonzero(filled)
    zc = int(round(zs.min() + height * (zs.max() - zs.min())))
    yc = int(round(ys.mean()))
    for dy in range(-radius, radius + 1):
        for dz in range(-radius, radius + 1):
            if dy * dy + dz * dz > radius * radius + radius or (ring and not (dy or dz)):
                continue
            y, z = yc + dy, zc + dz
            if 0 <= y < filled.shape[1] and 0 <= z < filled.shape[2] and filled[:, y, z].any():
                snapped[np.nonzero(filled[:, y, z])[0].max(), y, z] = rgb


def brick_model(m, kind, files, voxels=VOXELS, ncolors=5, sculpt=None, pick=None, code='', client=None):
    """The bricks for one model: (parts, atlas image, uvmap, bricks, brick size), or None without a surface.
    sculpt(head points, head bone, jaw bone) -> (colors by role, [(Part, role)]) replaces the voxel head (the drawn
    HE piece of an .mds) with a sculpted one. code/client: for the per-creature tables above."""
    code = code.upper()
    texs = material_textures(m, files)
    pts, cols, bns = sample_points(m, kind, texs, step=1.0)
    if len(pts) == 0:
        return None
    glass_flags = None
    if code in SURFACE_FROM and client:  # another creature's surface, fitted into this one's height and place
        arch, prefix, _mat = SURFACE_FROM[code]
        got = borrowed_surface(client, arch, prefix, 1.0)
        if got is not None:
            lo0, hi0 = pts.min(0), pts.max(0)
            ride = int(np.bincount(bns).argmax())
            b0 = got[0]
            scale = (hi0[2] - lo0[2]) / max(np.ptp(b0[:, 2]), 1e-6)
            fit = lambda p, b0=b0: (p - np.array([(b0[:, 0].min() + b0[:, 0].max()) / 2,
                                                  (b0[:, 1].min() + b0[:, 1].max()) / 2, b0[:, 2].min()])) * scale + \
                np.array([(lo0[0] + hi0[0]) / 2, (lo0[1] + hi0[1]) / 2, lo0[2]])
            ext = np.sort(np.ptp(fit(b0), 0))
            size = max(min(ext[2] / voxels, ext[1] / 5), 0.05)
            p2, cols, glass_flags = borrowed_surface(client, arch, prefix, size / 3 / scale)
            pts, bns = fit(p2), np.full(len(p2), ride)
            pick = False
    if glass_flags is None:
        ext = np.sort(pts.max(0) - pts.min(0))
        size = max(min(ext[2] / voxels, ext[1] / 5), 0.05)
        pts, cols, bns = sample_points(m, kind, texs, step=size / 3)
    lo, filled, color, bone = bc.voxelize(pts, cols, bns, size)
    parent = eqgbones.parents(m.bones) if m.bones else [-1]
    bone[bone >= len(parent)] = 0  # weights on a bone past the skeleton (I00) ride the root
    kin = eqgbones.helper_kin(parent) if m.bones else None
    anchored = bc.anchor_limbs(filled, bone, parent, color, kin=kin)
    if m.bones:
        anchored += drop_crumbs(filled, bone, parent, kin)
    if code in PIVOT and m.bones:
        rest = eqgbones.world(m.bones, parent)
        anchored += bc.pivot_bridge(filled, bone, color, [(None, parent[k], rest[k]) for k in range(len(parent))],
                                    lo, size)
    glass = np.zeros(filled.shape, bool)
    if glass_flags is not None and glass_flags.any():  # cubes whose samples are mostly on the window
        idx = np.clip(np.floor((pts - lo) / size).astype(int), 0, np.array(filled.shape) - 1)
        votes = np.zeros(filled.shape, int)
        np.add.at(votes, tuple(idx.T), np.where(glass_flags, 1, -1))
        glass = filled & (votes > 0)
        fire = bc.fire_colors(glass) if glass.any() else {}
    snapped = bc.smooth_colors(filled, bc.palette_colors(color, filled, ncolors))
    if code in RECOLOR:
        for x, y, z in zip(*np.nonzero(filled)):
            snapped[x, y, z] = RECOLOR[code](tuple(int(a) for a in snapped[x, y, z]))
    if code in FRONT_DOT:
        front_dot(filled, snapped, *FRONT_DOT[code])
    classes, cls = {}, np.zeros(color.shape, np.float32)
    for x, y, z in zip(*np.nonzero(filled)):
        key = tuple(int(a) for a in snapped[x, y, z])
        if glass[x, y, z]:  # glass classes stay apart from frame classes of the same color
            key = tuple(fire[x, y, z]) + ('glass',)
        cls[x, y, z] = bc.fake(classes.setdefault(key, len(classes)))
    names = [str(k) for k in range(max(1, len(m.bones)))]
    head = []
    if sculpt and kind == 'mds' and m.bones:
        bnames = [eqgmds.name(m, b[0]) for b in m.bones]
        hp = [p for p in m.pieces if p['main'] and 'HE' in strings_of(m, p['name'])[3:]]
        hb = bnames.index('HEAD_HEAD') if 'HEAD_HEAD' in bnames else None
        if hp:  # a separate head piece (MYG)
            pts_h = np.array([v[0] for p in hp for v in p['verts']], float)
        elif hb is not None:  # one mesh (AMY): the vertices that mostly follow the head bone
            pts_h = np.array([v[0] for verts, _t, ws in meshes(m, kind) for v, w in zip(verts, ws)
                              if max(w[1][:max(1, w[0])], key=lambda bw: bw[1])[0] == hb], float)
        if hb is not None and (hp or len(pts_h) >= 8):
            on = [k for k, n in enumerate(bnames) if n.startswith('HEAD') or n in ('JAW', 'EARL', 'EARR')]
            filled = filled & ~np.isin(bone, on)
            scheme, parts_h = sculpt(pts_h, str(bnames.index('HEAD_HEAD')), str(bnames.index(next(
                (n for n in ('JAW',) if n in bnames), 'HEAD_HEAD'))))
            for p, role in parts_h:
                p.material = bc.fake(classes.setdefault(scheme[role], len(classes)))
            head = [p for p, _r in parts_h]
    extra = []
    if not head and m.bones and pick is not False:
        spots = pick or auto_eyes(m, kind, texs, parent, size)
        if spots:
            heads = head_set(m, parent)
            extra = bc.brick_eyes(spots, lo, size, filled, bone, names, heads)
    for p, rgb in extra:
        p.material = bc.fake(classes.setdefault(tuple(int(v) for v in rgb), len(classes)))
    parts = bc.build_parts(lo, size, filled, cls, bone, names) + head + [p for p, _r in extra]
    imgs, pos = bc.class_atlases(list(classes), 1)
    uvmap = lambda material, u, v: pos[bc.unfake(material)]
    keys = list(classes)
    for p in parts:  # preview colors; glass bricks go on the model's translucent material
        key = keys[bc.unfake(p.material)]
        p.color = key[:3]
        if key[-1] == 'glass':
            p.mat_index = SURFACE_FROM[code][2]
    return parts, imgs[0], uvmap, int(filled.sum()), size, dict(classes=len(classes), anchored=anchored,
                                                                eyes=len(extra) // 3)


def head_set(m, parent):
    """Indices of the head bone(s) (HEAD...) and everything hanging from them (jaw, ears)."""
    names = [eqgmds.name(m, b[0]) for b in m.bones]
    top = {k for k, n in enumerate(names) if n.upper().startswith('HEAD')}
    out = set(top)
    for k in range(len(names)):
        p = parent[k]
        while p >= 0:
            if p in top:
                out.add(k)
                break
            p = parent[p]
    return out


def auto_eyes(m, kind, texs, parent, size):
    """The best eye pair the stock head texture shows (brickcreature.eye_candidates), or []."""
    heads = head_set(m, parent)
    if not heads:
        return []
    names = [eqgmds.name(m, b[0]) for b in m.bones]
    hp = sample_points(m, kind, texs, 1.0, only=heads)[0]
    if len(hp) < 10:
        return []
    fine = float((hp.max(0) - hp.min(0)).max()) / 60
    hp, hc, hb = sample_points(m, kind, texs, min(size / 3, fine), only=heads)
    rest = eqgbones.world(m.bones, parent)
    he = min(k for k in heads if names[k].upper().startswith('HEAD'))
    jaw = {k for k in heads if names[k].upper().startswith(('JAW', 'TONG', 'TEETH', 'MOUTH'))}
    found = bc.eye_candidates(hp, hc, hb, heads, size, rest[he], jaw, 1)
    return found[0] if found else []


def eye_pick(code):
    """The hand pick for this model: a list of two eyes, False for none, None when not picked."""
    key = f'eqg:{code.lower()}'
    if key not in bc.EYE_PICKS:
        return None
    v = bc.EYE_PICKS[key]
    if not v or isinstance(v, dict):  # null: no eyes (shaped eyes are for .s3d heads only)
        return False
    return [tuple(np.array(x, float) if k != 2 else float(x) for k, x in enumerate(e)) for e in v]


HEADS = {'MYG': bc.squid_head, 'AMY': bc.squid_head}


def geometry(parts, uvmap, has_bones):
    verts, tris, weights, seen = [], [], [], {}
    for p in parts:
        bi = int(p.bone)
        for tri in p.tris:
            ids = []
            for v, n, uv in tri:
                u, w = uvmap(p.material, *uv)
                w = 1.0 - w  # EQG rows from the bottom
                key = (tuple(np.round(v, 4)), tuple(np.round(n, 3)), round(u, 4), round(w, 4), bi)
                if key not in seen:
                    seen[key] = len(verts)
                    nn = np.array(n, float)
                    nn = nn / (np.linalg.norm(nn) or 1)
                    verts.append([tuple(map(float, v)), tuple(map(float, nn)), 0xFFFFFFFF, (u, w), (0.0, 0.0)])
                    if has_bones:
                        weights.append([1, [(bi, 1.0), (0, 0.0), (0, 0.0), (0, 0.0)]])
                ids.append(seen[key])
            tris.append([ids[0], ids[1], ids[2], getattr(p, 'mat_index', 0), 65536])
    return verts, tris, weights


def own_textures(m, code):
    diffuse, normal = f'c_{code}_brick_c.dds', f'c_{code}_brick_n.dds'
    shader = eqgmds.add_string(m, 'Opaque_MaxCBS1.fx')
    d_off, n_off = eqgmds.add_string(m, diffuse), eqgmds.add_string(m, normal)
    keep = SURFACE_FROM.get(code.upper(), (None, None, None))[2]  # the glass bricks' material keeps its blending
    for k, mat in enumerate(m.materials):
        if k != keep:
            mat[2] = shader
        props = []
        for pr in mat[3]:
            pname, ptype = struct.unpack_from('<2I', pr, 0)
            key = strings_of(m, pname)
            if key == 'e_TextureDiffuse0':
                pr = struct.pack('<3I', pname, ptype, d_off)
            elif key == 'e_TextureNormal0':
                pr = struct.pack('<3I', pname, ptype, n_off)
            props.append(pr)
        mat[3] = props
    return diffuse, normal


def own_layers(data, diffuse, normal):
    """The texture-variant table (.lay, version 2 with 64-byte entries or 3 with 32-byte ones) with every variant's
    texture slots on the creature's own textures: a slot naming a _N texture gets the normal map, any other the
    diffuse. The layer names and every other field stay as they were."""
    magic, ver, slen, count = struct.unpack_from('<4s3I', data, 0)
    strings = data[16:16 + slen]
    size = (len(data) - 16 - slen) // max(count, 1)
    assert size in (32, 64) and 16 + slen + size * count == len(data), 'unexpected .lay layout'
    n = size // 4
    entries = [list(struct.unpack_from(f'<{n}I', data, 16 + slen + size * k)) for k in range(count)]
    table, where = bytearray(), {}

    def put(text):
        if text not in where:
            where[text] = len(table)
            table.extend(text.encode('latin-1') + b'\0')
        return where[text]

    def old(off):
        return strings[off:strings.index(b'\0', off)].decode('latin-1')

    def is_str(off):
        return off < slen and (off == 0 or strings[off - 1] == 0)

    for e in entries:
        e[0] = put(old(e[0]))
        for k in (1, 2):
            if is_str(e[k]) and old(e[k]):
                e[k] = put((normal if re.search(r'_N(_\d+)?\.DDS$', old(e[k]).upper()) else diffuse).upper())
        if size == 32 and is_str(e[7]):
            e[7] = put(old(e[7]))
    out = bytearray(struct.pack('<4s3I', magic, ver, len(table), count)) + table
    for e in entries:
        out += struct.pack(f'<{n}I', *e)
    return bytes(out)


def build_archive(src, dst, codes, preview=None):
    """Brick the named models of one archive. Returns a report line per model."""
    files = pfs.read(src)
    fd = {n.lower(): b for n, b in files}
    out_files, report, extra = dict((n, b) for n, b in files), [], {}
    for code in codes:
        kind = 'mds' if f'{code}.mds' in fd else 'mod' if f'{code}.mod' in fd else None
        if kind is None:
            report.append(f'{code}: no {code}.mod/.mds in {os.path.basename(src)}')
            continue
        lib = eqgmds if kind == 'mds' else eqgmod
        m = lib.read(fd[f'{code}.{kind}'])
        built = brick_model(m, kind, fd, bc.VOXELS.get(code.upper(), VOXELS), sculpt=HEADS.get(code.upper()),
                            pick=eye_pick(code), code=code, client=client_of(src))
        if built is None:
            report.append(f'{code}: no surface, left as it was')
            continue
        parts, atlas, uvmap, nb, size, info = built
        verts, tris, weights = geometry(parts, uvmap, bool(m.bones))
        if kind == 'mod':
            m.verts, m.tris, m.weights = verts, tris, weights
        else:
            drawn = [k for k, p in enumerate(m.pieces) if p['main']] or list(range(len(m.pieces)))
            body = next((k for k in drawn if 'HE' not in strings_of(m, m.pieces[k]['name'])[3:]), drawn[0])
            tiny = [[(0.0, 0.0, -0.01), (0.0, 0.0, 1.0), 0xFFFFFFFF, (0.0, 0.0), (0.0, 0.0)] for _ in range(3)]
            for k, piece in enumerate(m.pieces):
                if k == body:
                    piece['verts'], piece['tris'], piece['weights'] = verts, tris, weights
                else:
                    piece['verts'] = [list(v) for v in tiny]
                    piece['tris'] = [[0, 1, 2, 0, 65536]]
                    piece['weights'] = [[1, [(0, 1.0), (0, 0.0), (0, 0.0), (0, 0.0)]] for _ in range(3)] if m.bones else []
        diffuse, normal = own_textures(m, code)
        name = next(n for n, _b in files if n.lower() == f'{code}.{kind}')
        out_files[name] = lib.write(m)
        lods = []
        if kind == 'mod':  # distance models: the same bricks (animations find the bones by name)
            for n, _b in files:
                if re.fullmatch(re.escape(code) + r'_lod\d+\.mod', n.lower()):
                    out_files[n] = out_files[name]
                    lods.append(n)
        lay = next((n for n, _b in files if n.lower() == f'{code}.lay'), None)
        if lay:
            out_files[lay] = own_layers(out_files[lay], diffuse, normal)
        extra[diffuse] = make_s3d.dds_dxt1(atlas)
        extra[normal] = make_s3d.dds_dxt1(Image.new('RGB', (128, 128), (128, 128, 255)))
        if preview:
            pp = []
            for p in parts:
                q = minifig.Part(p.name, p.bone, p.color, p.center)
                q.tris = p.tris
                pp.append(q)
            minifig.preview(f'{preview}_{code}.png', pp, size=320, ss=1)
        report.append(f'{code}: {nb} bricks of {size:.3f}, {info["classes"]} color classes ({kind}, '
                      f'{info["anchored"]} cubes anchored, {info["eyes"]} eyes, {len(lods)} distance models)')
    out = [(n, b) for n, b in out_files.items()] + [(n, b) for n, b in extra.items() if n.lower() not in fd]
    pfs.write(dst, out)
    return report


def client_of(src):
    """The client folder of an archive path (<client>/x.eqg or <client>/brick_orig/x.eqg.orig)."""
    d = os.path.dirname(os.path.abspath(src))
    return os.path.dirname(d) if os.path.basename(d).lower() == 'brick_orig' else d


def chr_models(path, client):
    out = []
    for line in open(path, errors='ignore').read().splitlines()[1:]:
        if ',' in line:
            code, arch = (s.strip().lower() for s in line.split(',')[:2])
            if code.upper() not in SKIP and os.path.exists(os.path.join(client, arch + '.eqg')):
                out.append((code, arch))
    return out


def main():
    args = sys.argv[1:]
    if args and args[0] == '--archive':  # one archive: --archive <src.eqg> <dst.eqg> code,code
        src, dst, codes = args[1:4]
        for line in build_archive(src, dst, codes.split(',')):
            print(line, flush=True)
        return
    read_only, use_global = '--read-only' in args, '--global' in args
    args = [x for x in args if x not in ('--read-only', '--global')]
    client, out = args[:2]
    lists = [os.path.join(client, f'{z}_chr.txt') for z in args[2:]]
    if use_global:
        lists.append(os.path.join(client, 'Resources', 'GlobalLoad_chr.txt'))
    os.makedirs(out, exist_ok=True)
    by_archive = {}
    for path in lists:
        if os.path.exists(path):
            for code, arch in chr_models(path, client):
                by_archive.setdefault(arch, set()).add(code)
    failed = []
    for arch, codes in sorted(by_archive.items()):
        name = arch + '.eqg'
        orig = os.path.join(client, 'brick_orig', name + '.orig')
        src = orig if os.path.exists(orig) else os.path.join(client, name)
        if not read_only and not os.path.exists(orig):
            shutil.copy2(src, orig)
            src = orig
        try:
            rep = build_archive(src, os.path.join(out, name), sorted(codes), preview=os.path.join(out, arch))
            print(f'{name}: ' + '; '.join(rep), flush=True)
        except Exception as e:
            failed.append(name)
            print(f'{name}: FAILED {type(e).__name__}: {e}', flush=True)
    print(f'{len(by_archive)} archives, {len(failed)} failed' + (f': {failed}' if failed else ''))


if __name__ == '__main__':
    main()
