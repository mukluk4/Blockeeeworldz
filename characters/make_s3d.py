"""Put the minifig into a copy of a player race's global<race>_chr.s3d.

- The body mesh (<RACE>_DMSPRITEDEF) is replaced by the minifig parts, fitted to that race's skeleton
  (minifig.fit). Each vertex is stored in its bone's rest-pose space, so the stock animations move the parts.
- Every polygon uses one material, and every texture in the archive (all faces, skins and armor variants the client
  can swap to) keeps its name but gets the atlas as its content. Wearing armor or picking a face then changes nothing.
- The eye meshes are folded to a point so they don't poke through the minifig head (KEEP_EYES=1 keeps them).
- A file with several skeletons (the player Froglok file holds both genders) gets a figure for each.

    python -I make_s3d.py <original global<race>_chr.s3d> <out.s3d> [race code, default from the skeleton]
"""
import io, math, os, re, struct, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import minifig, pfs, racescale, wld

PLACEHOLDER = (13, 251, 7)  # stand-in skin while building races with several skin colors  # only used by the SAME_NAMES=0 test layout


# ------------------------------------------------------------------------------------------------ atlas
def make_atlas(parts):
    """512x512: face print on the top half, torso print bottom left, one 32x32 swatch per solid color bottom right."""
    atlas = Image.new('RGB', (512, 512), minifig.YELLOW)
    atlas.paste(minifig.TEXTURES['face'].resize((512, 256)), (0, 0))
    atlas.paste(minifig.TEXTURES['torso'].resize((256, 256)), (0, 256))
    colors = sorted({tuple(p.material) for p in parts if not isinstance(p.material, str)})
    swatch = {}
    for k, c in enumerate(colors):
        x, y = 256 + (k % 8) * 32, 256 + (k // 8) * 32
        atlas.paste(Image.new('RGB', (32, 32), c), (x, y))
        swatch[c] = ((x + 16) / 512, (y + 16) / 512)

    def uv(material, u, v):
        unprinted = (u, v) == (0.02, 0.02)  # faces of a printed part that carry no print
        if material == 'face':
            return u, 0.01 + v * 0.47  # stay off the torso print below
        if material == 'torso':
            return (0.25, 0.97) if unprinted else (0.02 + u * 0.46, 0.5 + 0.02 + v * 0.46)
        return swatch[tuple(material)]
    return atlas, uv


def dds_rgba(im):
    w, h = im.size
    pf = struct.pack('<II4sIIIII', 32, 0x41, b'\0\0\0\0', 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header = struct.pack('<4sIIIIIII', b'DDS ', 124, 0x100F, h, w, w * 4, 0, 0) + b'\0' * 44 + pf + \
        struct.pack('<IIIII', 0x1000, 0, 0, 0, 0)
    r, g, b, a = im.convert('RGBA').split()
    return header + Image.merge('RGBA', (b, g, r, a)).tobytes()


def dds_dxt1(im):
    """DXT1 (BC1) DDS, no mipmaps: the compressed format the client's own textures use."""
    a = np.asarray(im.convert('RGB'), dtype=np.float32)
    h, w = a.shape[:2]
    blocks = a.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    lum = blocks @ np.array([0.299, 0.587, 0.114], np.float32)
    hi = blocks[np.arange(len(blocks)), lum.argmax(1)]
    lo = blocks[np.arange(len(blocks)), lum.argmin(1)]

    def to565(c):
        c = np.clip(np.round(c), 0, 255).astype(np.uint32)
        return ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 2) << 5) | (c[:, 2] >> 3)

    def from565(v):
        return np.stack([((v >> 11) & 31) * 255 / 31, ((v >> 5) & 63) * 255 / 63, (v & 31) * 255 / 31], 1)

    c0, c1 = to565(hi), to565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    same = c0 == c1  # a flat block: bump c0 so the block stays in four-color mode
    c0 = np.where(same & (c0 < 0xFFFF), c0 + 1, c0)
    c1 = np.where(same & (c0 == 0xFFFF), c1 - 1, c1)
    p0, p1 = from565(c0), from565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)  # [n, 4, 3]
    idx = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1).argmin(-1).astype(np.uint32)  # [n, 16]
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    body = np.zeros((len(blocks), 2), np.uint32)
    body[:, 0] = c0 | (c1 << 16)
    body[:, 1] = bits
    pf = struct.pack('<II4sIIIII', 32, 0x4, b'DXT1', 0, 0, 0, 0, 0)
    header = struct.pack('<4sIIIIIII', b'DDS ', 124, 0x81007, h, w, w * h // 2, 0, 0) + bytes(44) + pf + struct.pack('<IIIII', 0x1000, 0, 0, 0, 0)
    return header + body.astype('<u4').tobytes()


# ------------------------------------------------------------------------------------------------ mesh
def mesh_body(w, frag_index, parts, bones, uvmap, material):
    _t, name, old = w.frags[frag_index]
    m = w.mesh(frag_index)
    mat_of = material if callable(material) else (lambda _p: material)  # material name per part
    mat_ids = {n: i for i, (n, _m, _t2) in enumerate(m['materials'])}
    bone_index = {n: i for i, (n, _p, _w) in enumerate(bones)}

    # Vertices grouped by bone (the mesh stores runs of vertices per bone), each in that bone's rest-pose space
    by_bone = {}
    for p in parts:
        bi = bone_index[p.bone]
        R, T = bones[bi][2]
        Rt = np.array(R, dtype=float).T
        T = np.array(T, dtype=float)
        mi = mat_ids[mat_of(p)]
        for tri in p.tris:
            local = [(Rt @ (v - T), Rt @ n, uvmap(p.material, *uv)) for v, n, uv in tri]
            by_bone.setdefault(bi, {}).setdefault(mi, []).append(local)
    verts, norms, uvs, polys, pieces, vruns = [], [], [], [], [], []
    for bi in sorted(by_bone):
        start = len(verts)
        for mi in sorted(by_bone[bi]):  # within a bone, one run of vertices per material
            mstart = len(verts)
            seen = {}  # shared corners: the same spot, normal and texture point within this bone and material
            for tri in by_bone[bi][mi]:
                ids = []
                for v, n, uv in tri:
                    key = (tuple(np.round(v, 4)), tuple(np.round(n, 3)), tuple(np.round(uv, 4)))
                    if key not in seen:
                        seen[key] = len(verts)
                        verts.append(v); norms.append(n); uvs.append(uv)
                    ids.append(seen[key])
                polys.append((mi, (ids[0], ids[2], ids[1])))  # the client winds triangles the other way round
            if vruns and vruns[-1][1] == mi:  # merge with the previous run on the same material
                vruns[-1] = (vruns[-1][0] + len(verts) - mstart, mi)
            else:
                vruns.append((len(verts) - mstart, mi))
        pieces.append((len(verts) - start, bi))
    polys.sort(key=lambda x: x[0])  # polygons grouped by material, one run each
    pruns = []
    for mi, _f in polys:
        if pruns and pruns[-1][1] == mi:
            pruns[-1][0] += 1
        else:
            pruns.append([1, mi])
    polys = [f for _mi, f in polys]
    assert len(verts) < 65536

    # Rest-pose bounds, for the header (the client culls with them)
    world = [np.array(v) for p in parts for t in p.tris for v, _n, _u in t]
    lo, hi = np.min(world, 0), np.max(world, 0)
    radius = max(np.linalg.norm(v) for v in world)

    scale = 12  # vertex = int16 / 4096: room for +-8 units; bigger models (creatures) get a coarser step
    reach = max((abs(c) for v in verts for c in v), default=0.0)
    while scale > 0 and reach * (1 << scale) > 32000:
        scale -= 1
    head = bytearray(old[:96])
    struct.pack_into('<3f', head, 24, 0.0, 0.0, 0.0)               # center
    struct.pack_into('<f', head, 48, float(radius))                # max distance
    struct.pack_into('<3f', head, 52, *map(float, lo))
    struct.pack_into('<3f', head, 64, *map(float, hi))
    # Polygon runs and vertex runs per material
    struct.pack_into('<10H', head, 76, len(verts), len(uvs), len(norms), 0, len(polys), len(pieces), len(pruns),
                     len(vruns), 0, scale)
    out = bytearray(head)
    q = float(1 << scale)
    for v in verts:
        out += struct.pack('<3h', *(int(round(c * q)) for c in v))
    for u, v in uvs:
        out += struct.pack('<2h', int(round(u * 256)), int(round(v * 256)))
    for n in norms:
        n = n / (np.linalg.norm(n) or 1)
        out += struct.pack('<3b', *(int(round(c * 127)) for c in n))
    for a, b, c in polys:
        out += struct.pack('<4H', 0, a, b, c)
    for count, bi in pieces:
        out += struct.pack('<2H', count, bi)
    for count, mi in pruns:
        out += struct.pack('<2H', count, mi)
    for count, mi in vruns:
        out += struct.pack('<2H', count, mi)
    expected = (96 + 6 * len(verts) + 4 * len(uvs) + 3 * len(norms) + 8 * len(polys) + 4 * len(pieces)
                + 4 * len(pruns) + 4 * len(vruns))
    assert len(out) == expected, (len(out), expected)
    print(f'mesh: {len(verts)} vertices, {len(polys)} triangles, {len(pieces)} bone runs')
    return bytes(out)


def flatten_mesh(old):
    """The same mesh drawing nothing, same layout: every vertex at its center and every triangle's three corners on
    one vertex. Collapsing the vertices alone isn't enough: they are stored per bone, so a piece rigged to several
    bones (the Froglok helms and shoulders) kept triangles stretched between its joints."""
    nv, nt, nn, nc, npoly = struct.unpack_from('<5H', old, 76)
    out = bytearray(old)
    out[96:96 + 6 * nv] = bytes(6 * nv)
    for uv in (4, 8):  # old (int16) or new (float) texture coordinates: the one whose faces index real vertices
        p = 96 + 6 * nv + uv * nt + 3 * nn + 4 * nc
        if p + 8 * npoly <= len(old) and all(max(struct.unpack_from('<3H', old, p + 8 * k + 2)) < nv
                                             for k in range(npoly)):
            for k in range(npoly):
                struct.pack_into('<3H', out, p + 8 * k + 2, 0, 0, 0)
            break
    else:
        raise ValueError('mesh layout not recognized')
    return bytes(out)


def bitmap_body(old, filename):
    name_ref, n = struct.unpack_from('<iI', old, 0)
    raw = wld.decode(filename.encode('latin-1') + b'\0')  # the same XOR undoes itself
    return struct.pack('<iIH', name_ref, n, len(raw)) + raw


def write_wld(data, frags):
    """The original header and string table, then every fragment (its size recomputed)."""
    magic, version, count, bsp, unk, hash_size, unk2 = struct.unpack_from('<7I', data, 0)
    out = bytearray(data[:28 + hash_size])
    for ftype, body in frags:
        out += struct.pack('<II', len(body), ftype) + body
    return bytes(out)


# ------------------------------------------------------------------------------------------------ armor
# Armor shows like minifig clothing: the top half (torso, arms) follows the chest slot, the bottom half (hips,
# legs, feet) the legs slot. The client picks a slot's look by texture name, <race><slot><set><n>, e.g. humch0201
# = human chest, set 02 (chain). Every set gets an atlas of its own, painted from that set's original texture.
STAND_IN = {'shirt': (3, 4, 9), 'arms': (3, 1, 9), 'legs': (3, 2, 9), 'hips': (3, 3, 9)}
BOTTOM = ('leg', 'foot', 'hips', 'hip pin', 'knee')
SET_PRINT = {1: 'leather', 2: 'mail', 3: 'plate'}  # 00 keeps the race's own clothes; 04 and up: by their colors
ARMOR_FILES = [f'global{n}_amr.s3d' for n in range(17, 24)]


def armor_textures(src):
    """{texture name: RGB image} for every armor texture: the race file and the client's armor set archives."""
    client = os.path.dirname(os.path.dirname(os.path.abspath(src)))  # src is <client>/brick_orig/<file>.orig
    out = {}
    for f in [src] + [os.path.join(client, a) for a in ARMOR_FILES]:
        if not os.path.exists(f):
            continue
        for n, b in pfs.read(f):
            n = n.lower()
            if re.match(r'^[a-z]{3}(ch|lg|ua)\d{4}\.(dds|bmp)$', n):
                try:
                    out[n.rsplit('.', 1)[0]] = Image.open(io.BytesIO(b)).convert('RGB')
                except Exception:
                    pass
    return out


ARMOR_EXTRA = [(0, 143, 155), (63, 54, 145), (160, 110, 185)]  # dark turquoise, dark purple, lavender (robes)


def snapped_counts(imgs):
    """{brick color: pixel count} over some textures (each counted at 32x32)."""
    from brickzone import PALETTE, boost
    pal = np.concatenate([PALETTE, np.array(ARMOR_EXTRA, np.float32)])
    w = np.array([0.3, 0.59, 0.11], np.float32) * 3

    def nearest(c):
        return pal[(((c[:, None, :] - pal[None, :, :]) ** 2) * w).sum(-1).argmin(1)]
    out = {}
    for img in imgs:
        px = np.asarray(img.resize((32, 32)), np.float32).reshape(-1, 3)
        vals, counts = np.unique(nearest(boost(px)), axis=0, return_counts=True)
        for c, n in zip(vals, counts):
            c = tuple(int(x) for x in c)
            out[c] = out.get(c, 0) + int(n)
    return out


def main_colors(img, k=2):
    """The k most common brick colors of a texture."""
    return top_colors(snapped_counts([img]), k)


def top_colors(counts, k=2, skip=()):
    picks = [c for c, _n in sorted(counts.items(), key=lambda cn: -cn[1]) if c not in skip][:k]
    return picks + picks[-1:] * (k - len(picks)) if picks else []


def armor_sets(pre, tex):
    """{set number: (top race changes, bottom race changes)} for every armor set of a race.
    A set's chest textures are partly bare skin (robes: ch??01 is all skin) or white placeholder, so the top colors
    come from all its chest and upper-arm textures with the race's skin tones and near-white left out."""
    def named(slot, v):
        return [tex[n] for n in sorted(tex) if n.startswith(f'{pre}{slot}{v:02d}')]

    skin_src = named('ch', 10) or named('ch', 0)[:1]
    skin = set(top_colors(snapped_counts(skin_src[:1]), 3)) if skin_src else set()
    white = {c for c in snapped_counts([im for v in range(5) for im in named('ch', v)]) if min(c) >= 230}
    skip = skin | white
    sets = {}
    for n in tex:
        m = re.match(rf'^{pre}(ch|lg|ua)(\d\d)\d\d$', n)
        if m and int(m.group(2)) > 0:
            sets.setdefault(int(m.group(2)), {})
    for v in sorted(sets):
        top_imgs = named('ch', v) + named('ua', v)
        lg = named('lg', v)
        top = {}
        if top_imgs:
            counts = snapped_counts(top_imgs)
            picks = top_colors(counts, 2, skip)
            if not picks and lg:  # e.g. set 04: bare chest; dress it like its legs
                picks = top_colors(snapped_counts(lg), 2, skip)
            if picks:
                shirt, trim = picks
                if trim == shirt:
                    trim = minifig.GOLD
                arms = top_colors(snapped_counts(named('ua', v)), 1, skip) or [shirt]
                pr = SET_PRINT.get(v, 'tunic' if 10 <= v <= 16 else 'plate' if v >= 17 else 'tunic')
                top = dict(shirt=shirt, trim=trim, arms=arms[0], print=pr, belt=(53, 33, 0))
                if pr == 'plate':
                    top['belt'] = trim
                    if v == 3:  # plate: silver over the chain arms
                        top.update(shirt=(160, 165, 169), trim=(99, 95, 97), belt=(99, 95, 97))
        bottom = {}
        if lg:
            picks = top_colors(snapped_counts(lg[:1]), 2, white)
            if picks:
                bottom = dict(legs=picks[0], hips=picks[1], belt=picks[1])
        sets[v] = (top, bottom)
    return sets


def grip_fixes(w, r):
    """Weapons hang on the R_POINT / L_POINT bones, children of the hands, placed where the original big hand
    closes. The minifig's C-grip hand sits elsewhere relative to the hand bone, so every animation track of those
    points gets the grip's offset in hand space (the rotation, which aims the weapon, is kept).
    Returns {0x12 fragment index: (x, y, z)}."""
    P = r['prefix']
    world = {n: (np.array(R, float), np.array(T, float)) for n, _p, (R, T) in r['bones']}
    parent = {n: r['bones'][k][0] for n, k, _w in r['bones'] if k >= 0}
    fixes = {}
    for tag in 'RL':
        hand = [p for p in r['parts'] if p.name == f'hand {tag}']
        holder = parent.get(f'{P}{tag}_POINT_DAG')  # usually the hand bone
        if not hand or holder is None:
            continue
        c = np.mean([v for t in hand[0].tris for v, _n, _u in t], 0)
        R, T = world[holder]
        local = R.T @ (c - T)
        suffix = f'{P}{tag}_POINT_TRACK'
        for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
            if ftype == 0x13 and name.endswith(suffix):
                ref12, = struct.unpack_from('<i', raw, 4)
                fixes[ref12] = tuple(float(x) for x in local)
    return fixes


def set_track_offset(raw, xyz):
    """Every frame of a 0x12 track: same rotation, translation xyz (stored as int16 / 256)."""
    flags, frames = struct.unpack_from('<II', raw, 4)
    out = bytearray(raw)
    sx, sy, sz = (max(-32767, min(32767, int(round(v * 256)))) for v in xyz)
    for k in range(frames):
        struct.pack_into('<4h', out, 12 + 16 * k + 8, sx, sy, sz, 256)
    return bytes(out)


# Races whose non-skin head pieces (eyes, mouth, throat) go on the eye material instead of the head material. Empty:
# tested in game on the Froglok (2026-11-11), the eye material takes the CHEST's dye (a red breastplate turned the eyes
# red), while the head material showed no helm dye. Head pieces stay on <P>HE0001_MDF. Kept for other races if needed;
# a race listed here also needs its other eye-color textures given the atlas (hide_attachments.py with an atlas).
EYE_HEAD = {}


def build_race(w, skel_id, code=None):
    """The fitted minifig for one skeleton: (prefix, race code, parts, atlas, uvmap, skin colors, body mesh, eyes)."""
    bones, mesh_ids = w.skeleton(skel_id)
    prefix = w.frags[skel_id][1].split('_')[0]  # DWM_HS_DEF -> DWM
    code = code or prefix.lower()
    race = minifig.RACES[code]
    body = next(i for i in mesh_ids if w.frags[i][1] == f'{prefix}_DMSPRITEDEF')
    eyes = {i for i in mesh_ids if w.frags[i][1].startswith(f'{prefix}EYE')}
    # Races with several skin colors: build with a stand-in skin, put the skin parts on the head material (the face
    # choice swaps its texture), and give each head texture the atlas in one color
    colors = race.skin_colors
    if colors:
        import copy
        race = copy.copy(race)
        race.skin = PLACEHOLDER
        if race.hair == 'lizard' or race.ears == 'cat':  # the lizard's tail and the cat's ears and tail are skin too
            race.hair_color = PLACEHOLDER
    import copy as _copy
    figure = _copy.copy(race)  # clothing in stand-in colors; each armor atlas paints its own over them
    for role, c in STAND_IN.items():
        setattr(figure, role, c)
    figure.belt = STAND_IN['hips']
    minifig.use(figure)
    parts = minifig.build(figure)
    rest = {n: T for n, _p, (_R, T) in bones}
    if prefix != 'DWM':  # the figure is designed on the male Dwarf skeleton
        minifig.fit(parts, prefix, rest)
        minifig.tail(parts, race, prefix, rest, {n: (bones[p][0] if p >= 0 else None) for n, p, _w in bones})
    for p in parts:  # a bone this skeleton lacks (the Froglok has no neck): ride the chest
        if p.bone not in rest:
            p.bone = f'{prefix}CHCHEST_DAG'
    fake_atlas, uvmap = make_atlas(parts)
    fake = np.asarray(fake_atlas.convert('RGB'))

    def paint(top, bottom):
        a = fake.copy()
        for role, who in (('shirt', top), ('arms', top), ('legs', bottom), ('hips', bottom)):
            a[np.all(fake == STAND_IN[role], axis=-1)] = getattr(who, role)
        img = Image.fromarray(a)
        img.paste(minifig.torso_texture(top).resize((256, 256)), (0, 256))
        return img

    atlas = paint(race, race)
    for p in parts:  # remember each stand-in part's clothing role
        if not isinstance(p.material, str):
            for role, c in STAND_IN.items():
                if tuple(p.material) == c:
                    p.role = role  # the mesh keeps the stand-in color (the atlas lookup); previews use the role
    return dict(prefix=prefix, code=code, race=race, bones=bones, parts=parts, atlas=atlas, uvmap=uvmap,
                colors=colors, body=body, eyes=eyes, paint=paint)


def texture_sheets(r, tex):
    """Function texture name -> DDS for one race. Chest textures of set N get the atlas with set N's top half,
    leg textures of set N the one with set N's bottom half; head textures of races with several skin colors get
    the atlas in their face's color (<race>he<set or 'sk'><face><part>); everything else the race's own clothes."""
    import copy
    pre, race, colors = r['prefix'].lower(), r['race'], r['colors']
    sets = armor_sets(pre, tex)

    def dressed(changes):
        x = copy.copy(race)
        for k, v in changes.items():
            setattr(x, k, v)
        return x

    imgs = {('base', 0): r['atlas']}
    for v, (top, bottom) in sets.items():
        if top:
            imgs[('ch', v)] = r['paint'](dressed(top), race)
        if bottom:
            imgs[('lg', v)] = r['paint'](race, dressed(bottom))
    r['sets'] = {v: (dressed(t), dressed(b)) for v, (t, b) in sets.items()}

    def finish(img, face=0):
        if not colors:
            return img
        px = np.asarray(img.convert('RGB')).copy()
        px[np.all(px == PLACEHOLDER, axis=-1)] = colors[face]
        return Image.fromarray(px)

    r['armor_atlases'] = {k: finish(v) for k, v in imgs.items()}
    cache = {}

    def sheet(key, face=0):
        if (key, face) not in cache:
            cache[key, face] = dds_dxt1(finish(imgs.get(key, r['atlas']), face))
        return cache[key, face]

    head_tex = re.compile(rf"^{pre}he(?:sk|\d\d)(\d)\d\.dds$")
    slot_tex = re.compile(rf"^{pre}(ch|lg)(\d\d)\d\d\.dds$")

    def pick(n):
        h = head_tex.match(n)
        if h and colors:
            return sheet(('base', 0), int(h.group(1)) % len(colors))
        m = slot_tex.match(n)
        if m and int(m.group(2)) > 0:
            return sheet((m.group(1), int(m.group(2))))
        return sheet(('base', 0))

    r['atlas'] = finish(r['atlas'])
    return pick


def armor_preview(path, r, count=40):
    """The figure in its own clothes, then in the first few armor sets (chest and legs of the same set)."""
    import copy
    rows = [(r['race'], r['race'])] + [r['sets'][v] for v in sorted(r['sets'])[:count]]
    files = []
    for k, (top, bottom) in enumerate(rows):
        parts = []
        for p in r['parts']:
            q = copy.copy(p)
            role = getattr(p, 'role', None)
            if role:
                q.material = getattr(top if role in ('shirt', 'arms') else bottom, role)
            if not isinstance(q.material, str) and tuple(q.material) == PLACEHOLDER and r['colors']:
                q.material = r['colors'][0]
            parts.append(q)
        minifig.use(top)
        f = f'{path}.{k}.png'
        minifig.preview(f, parts, size=240, ss=1)
        files.append(f)
    ims = [Image.open(f).convert('RGB').crop((0, 0, 240, 240)) for f in files]  # the front view of each
    sheet = Image.new('RGB', (240 * len(ims), 240))
    for k, im in enumerate(ims):
        sheet.paste(im, (240 * k, 0))
    sheet.save(path)
    for f in files:
        os.remove(f)


def main():
    src, dst = sys.argv[1:3]
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    skels = w.of_type(0x10)  # usually one race per file; the player Froglok file holds both genders
    code = sys.argv[3] if len(sys.argv) > 3 and len(skels) == 1 else None
    races = [build_race(w, sid, code) for sid, _f in skels]

    bodies = {r['body']: r for r in races}
    grips = {}
    for r in races:
        grips.update(grip_fixes(w, r))
    eyes = set().union(*(r['eyes'] for r in races))
    frags = []
    for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
        if i in bodies:
            r = bodies[i]
            P = r['prefix']
            mats = {n for n, _m, _t in w.mesh(i)['materials']}

            def slot_mat(p, P=P, r=r, mats=mats):  # the top half on the chest slot, the bottom half on the legs
                if r['colors'] and not isinstance(p.material, str) and tuple(p.material) == PLACEHOLDER:
                    return f'{P}HE0001_MDF'
                if getattr(p, 'group', None) == 'head' and P in EYE_HEAD and EYE_HEAD[P] in mats:
                    return EYE_HEAD[P]  # head pieces off the helm-dyed head material (skin stays there: face color)
                if getattr(p, 'group', None) == 'head' and f'{P}HE0001_MDF' in mats:
                    return f'{P}HE0001_MDF'  # face, eyes, head pieces: not tinted with the chest armor's dye
                if p.name.startswith(BOTTOM) and f'{P}LG0001_MDF' in mats:
                    return f'{P}LG0001_MDF'
                return f'{P}CH0001_MDF'
            raw = mesh_body(w, i, r['parts'], r['bones'], r['uvmap'], slot_mat)
        elif i in eyes and os.environ.get('KEEP_EYES') != '1':
            raw = flatten_mesh(raw)
        elif i in grips:
            raw = set_track_offset(raw, grips[i])
        frags.append((ftype, raw))
    k = racescale.factor(races[0]['prefix']) if len(races) == 1 else None
    if k:  # Ogre, Troll, Barbarian: shrunk to about Human height (racescale.py)
        racescale.scale_race_file(w, frags, races[0]['prefix'], k, racescale.ground(w, skels[0][0]))
    new_wld = write_wld(wld_data, frags)

    # Every texture keeps its name and gets its race's atlas (DXT1) as its content, so whichever one the client
    # picks (armor set, face) shows the atlas. Textures go to the race whose prefix they start with.
    tex = armor_textures(src)
    picks = [(r['prefix'].lower(), texture_sheets(r, tex)) for r in races]
    def pick(n):
        return next((f for pre, f in picks if n.startswith(pre)), picks[0][1])(n)
    eye_tex = {EYE_HEAD[r['prefix']].lower()[:-4] + '.dds': r for r in races if r['prefix'] in EYE_HEAD}
    if len({id(r) for r in eye_tex.values()}) > 1:  # one eye texture for both genders: their atlases must agree
        assert len({r['atlas'].tobytes() for r in races}) == 1, 'eye-material head pieces need one shared atlas'

    def tex_for(n, b):
        if n in eye_tex:
            return dds_dxt1(eye_tex[n]['atlas'])
        return pick(n) if not n.startswith('chr_eye') else b
    out = [(n, new_wld if n == wld_name else (tex_for(n, b) if n.endswith('.dds') else b)) for n, b in files]
    pfs.write(dst, out)
    stem = os.path.splitext(dst)[0]
    for r in races:
        tag = '' if len(races) == 1 else '_' + r['code']
        r['atlas'].save(stem + tag + '_atlas.png')
        adir = stem + tag + '_armor'
        os.makedirs(adir, exist_ok=True)
        for (slot, v), img in r['armor_atlases'].items():  # for the armor set archives (make_armor_sets.py)
            img.save(os.path.join(adir, f"{r['prefix'].lower()}_{slot}{v:02d}.png"))
        armor_preview(stem + tag + '_armor.png', r)
        if r['colors']:  # the preview shows the first color
            for p in r['parts']:
                if not isinstance(p.material, str) and tuple(p.material) == PLACEHOLDER:
                    p.material = r['colors'][0]
        for p in r['parts']:  # the mesh is written: show the race's own clothes
            if getattr(p, 'role', None):
                p.material = getattr(r['race'], p.role)
        minifig.use(r['race'])
        minifig.preview(stem + tag + '_preview.png', r['parts'])
        print(f"{r['code']}: {len(r['parts'])} parts into {r['prefix']}_DMSPRITEDEF; {len(r['eyes'])} eye meshes "
              f"flattened")
    print(f'{len(out)} files -> {dst}')


if __name__ == '__main__':
    main()
