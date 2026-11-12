"""Brick creatures stored as newer .eqg models (.mod: one mesh; .mds: a body piece plus head pieces).

The same bricks as brickcreature.py: the model's surface is sampled in its bind pose (EQG vertices are stored in model
space, z up, feet at 0), voxelized, colored from its diffuse textures and built as studded bricks. Each brick rides the
bone that most of its surface follows, so the creature's own animations (.ani) still move it.

Writing: the bricks replace the body (.mod) or the first drawn body piece (.mds); every other piece (head choices,
spare parts) becomes one hidden triangle. Texture names are global in the client, so every material and every entry
of the variant table (.lay) points at the creature's own new textures c_<code>_brick_c.dds / _n.dds instead of
painting over shared names. All texture variants show the first variant's colors (variants come later).

    python -I eqgcreature.py <client folder> <out folder> <zone> [zone ...]

Models come from each zone's <zone>_chr.txt (lines "model,archive"); .s3d archives there are brickcreature.py's job.
Archives are read from <client>/brick_orig/<archive>.eqg.orig when it exists, else the client copy is backed up there
first.
"""
import math, os, re, shutil, struct, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import io
import brickcreature as bc
import eqgmds, eqgmod, make_s3d, minifig, pfs

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


def sample_points(m, kind, texs, step):
    pts, cols, bns = [], [], []
    for verts, tris, weights in meshes(m, kind):
        P = np.array([v[0] for v in verts], float)
        UV = np.array([v[3] for v in verts], float)
        top = [max(w[1][:max(1, w[0])], key=lambda bw: bw[1])[0] for w in weights] if weights else [0] * len(verts)
        for a, b, c, mat, _fl in tris:
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


def brick_model(m, kind, files, voxels=VOXELS, ncolors=5, sculpt=None):
    """The bricks for one model: (parts, atlas image, uvmap, bricks, brick size), or None without a surface.
    sculpt(head points, head bone, jaw bone) -> (colors by role, [(Part, role)]) replaces the voxel head (the drawn
    HE piece of an .mds) with a sculpted one."""
    texs = material_textures(m, files)
    pts, cols, bns = sample_points(m, kind, texs, step=1.0)
    if len(pts) == 0:
        return None
    ext = np.sort(pts.max(0) - pts.min(0))
    size = max(min(ext[2] / voxels, ext[1] / 5), 0.05)
    pts, cols, bns = sample_points(m, kind, texs, step=size / 3)
    lo, filled, color, bone = bc.voxelize(pts, cols, bns, size)
    snapped = bc.smooth_colors(filled, bc.palette_colors(color, filled, ncolors))
    classes, cls = {}, np.zeros(color.shape, np.float32)
    for x, y, z in zip(*np.nonzero(filled)):
        cls[x, y, z] = bc.fake(classes.setdefault(tuple(int(a) for a in snapped[x, y, z]), len(classes)))
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
    parts = bc.build_parts(lo, size, filled, cls, bone, names) + head
    imgs, pos = bc.class_atlases(list(classes), 1)
    uvmap = lambda material, u, v: pos[bc.unfake(material)]
    for p in parts:  # preview colors
        p.color = list(classes)[bc.unfake(p.material)]
    return parts, imgs[0], uvmap, int(filled.sum()), size


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
            tris.append([ids[0], ids[1], ids[2], 0, 65536])
    return verts, tris, weights


def own_textures(m, code):
    diffuse, normal = f'c_{code}_brick_c.dds', f'c_{code}_brick_n.dds'
    shader = eqgmds.add_string(m, 'Opaque_MaxCBS1.fx')
    d_off, n_off = eqgmds.add_string(m, diffuse), eqgmds.add_string(m, normal)
    for mat in m.materials:
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
        built = brick_model(m, kind, fd, bc.VOXELS.get(code.upper(), VOXELS), sculpt=HEADS.get(code.upper()))
        if built is None:
            report.append(f'{code}: no surface, left as it was')
            continue
        parts, atlas, uvmap, nb, size = built
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
        report.append(f'{code}: {kind}, {nb} bricks of {size:.2f}')
    out = [(n, b) for n, b in out_files.items()] + [(n, b) for n, b in extra.items() if n.lower() not in fd]
    pfs.write(dst, out)
    return report


def main():
    client, out = sys.argv[1:3]
    zones = sys.argv[3:]
    os.makedirs(out, exist_ok=True)
    by_archive = {}
    for z in zones:
        path = os.path.join(client, f'{z}_chr.txt')
        for line in open(path, errors='ignore').read().splitlines()[1:]:
            if ',' not in line:
                continue
            code, arch = (s.strip().lower() for s in line.split(',')[:2])
            if code.upper() in SKIP or not os.path.exists(os.path.join(client, arch + '.eqg')):
                continue
            by_archive.setdefault(arch, set()).add(code)
    failed = []
    for arch, codes in sorted(by_archive.items()):
        name = arch + '.eqg'
        orig = os.path.join(client, 'brick_orig', name + '.orig')
        if not os.path.exists(orig):
            shutil.copy2(os.path.join(client, name), orig)
        try:
            rep = build_archive(orig, os.path.join(out, name), sorted(codes),
                                preview=os.path.join(out, arch))
            print(f'{name}: ' + '; '.join(rep), flush=True)
        except Exception as e:
            failed.append(name)
            print(f'{name}: FAILED {type(e).__name__}: {e}', flush=True)
    print(f'{len(by_archive)} archives, {len(failed)} failed' + (f': {failed}' if failed else ''))


if __name__ == '__main__':
    main()
