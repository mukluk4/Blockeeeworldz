"""Toy hats for the Luclin helmets in lgequip_amr.s3d / lgequip_amr2.s3d.

The client draws a worn helmet on a Luclin-model player as its own model, IT5000 + 30 * race + type (type 0 troll
hood, 1 leather, 2 chain, 3 plate, 28/29 special helms). Each of those meshes becomes a brick hat on the minifig head:
  hood, leather  -> wizard hat (blue cone, yellow band, wide brim)
  chain          -> hardhat (yellow dome with a brim)
  plate, special -> knight helm (silver, cheek guards, nose guard, red feather plume)
Every other attachment in these archives (shoulder and arm pieces) stays folded away, as before.

The race of a mesh comes from its number (blocks of 30 in the client's race order). The hat is placed on the
race's HAIR_POINT frame, or HEAD_POINT for the races in HEAD_FRAME.

    python -I helmets.py <lgequip_amr.s3d.orig> <out .s3d> <brick_orig folder> [preview.png]
"""
import os, re, struct, sys
from collections import Counter
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import hairpieces, make_s3d, minifig, pfs, racescale, wld
from minifig import BX, Part, box, cylinder, dome

HT = hairpieces.HT
RACES = hairpieces.RACES
FRAMES = ('HEAD_POINT', 'HAIR_POINT', 'HEHEAD')
# Which frame a race's hat hangs on. On ten races HEAD_POINT and HAIR_POINT are 120 degrees apart, so the wrong one
# lays the hat on its side. In game (2026-11-11) the client does NOT give each race the hats of its own block: Erudite
# females wear a hat that changed only when the Troll/Ogre female hats moved to HEAD_POINT (and turned on its side),
# and Troll females stay sideways on either frame. Color-coded test hats (HAT_LABEL=1) showed no simple rule (and
# helm tints skew the colors). This set is the one that tested best: Halfling and Erudite females upright.
HEAD_FRAME = {'dwf', 'hof', 'ikf', 'kef'}

# Hats worn in game by another race than their block's: item number -> (wearer race, frame), built for the wearer's
# head instead. 2026-11-11: Alchemist Ezam (Troll female, helm 2) wears the Gnome female hardhat (grey cone in the
# color test) and it lay on its side; Cavalier Aodus (Erudite male, helm 0) wears that set's type 0/1 hat upright.
# A third value k turns the frame by k thirds of the HEAD_POINT -> HAIR_POINT axis cycle: on trf both points sit
# together, axes cycled x->y->z, and Ezam's hat lay on its side on HAIR (k 1) and HEAD (k 0), so k 2 is left.
# k 2 put the hat's top out the front (+x); a 90 degree tilt about y then put it out Ezam's right side. Both fit the
# game turning built axes z->x->y->z, so a fourth value n turns the built hat by n world axis cycles x->y->z first.
WEARER = {5692: ('trf', 'HEAD_POINT', 2, 1)}

# One small palette texture for every hat: 4x4 cells
COLORS = [(0, 85, 191), (242, 205, 55), (160, 165, 169), (99, 95, 98), (201, 26, 9), (27, 42, 52), (88, 42, 18),
          (170, 127, 46), (228, 228, 228)]
BLUE, YELLOW, GREY, DARK, RED, BLACK, BROWN, GOLD, SILVER = COLORS


def palette():
    im = Image.new('RGB', (64, 64), COLORS[0])
    for k, c in enumerate(COLORS):
        im.paste(c, (16 * (k % 4), 16 * (k // 4), 16 * (k % 4) + 16, 16 * (k // 4) + 16))
    return im


def cell_uv(color):
    k = COLORS.index(tuple(color))
    return ((k % 4) * 16 + 8) / 64, ((k // 4) * 16 + 8) / 64


def style_of(n):
    t = (n - 5000) % 30
    return 'wizard' if t in (0, 1) else 'hardhat' if t == 2 else 'knight'


# Test builds (HAT_LABEL=1): every race block's hat is a wizard hat in its own cone and band colors, so a screenshot
# shows which block an NPC really wears. Block = cone index + 7 * band index.
LABEL = os.environ.get('HAT_LABEL') == '1'
LABEL_CONE = [BLUE, YELLOW, GREY, RED, BLACK, BROWN, SILVER]
LABEL_BAND = [YELLOW, RED, BLACK, BLUE]


def label_colors(block):
    return LABEL_CONE[block % 7], LABEL_BAND[block // 7]


def hat(style, colors=None):
    """Parts of a hat on the Dwarf-frame minifig head (top HT, radius 0.72, face toward +X). colors: (cone, band)
    for a test-build wizard hat."""
    parts = []
    cone_c, band_c = colors or (BLUE, YELLOW)

    def part(name, color, center):
        p = Part(name, 'DWMHEHEAD_DAG', color, center)
        p.group = 'head'
        parts.append(p)
        return p

    if style == 'wizard':
        cylinder(part('brim', cone_c, (BX, 0, HT - 0.12)), (BX, 0, HT - 0.17), (BX, 0, HT - 0.07), 1.3, seg=40)
        cylinder(part('band', band_c, (BX, 0, HT + 0.05)), (BX, 0, HT - 0.07), (BX, 0, HT + 0.17), 0.95, seg=40)
        cylinder(part('cone', cone_c, (BX - 0.15, 0, HT + 0.9)), (BX, 0, HT + 0.17), (BX - 0.35, 0, HT + 1.85),
                 0.95, 0.06, seg=40)
    elif style == 'hardhat':
        dome(part('shell', YELLOW, (BX, 0, HT + 0.3)), (BX, 0, HT - 0.15), 1.0, seg=40)
        cylinder(part('brim', YELLOW, (BX, 0, HT - 0.19)), (BX, 0, HT - 0.23), (BX, 0, HT - 0.15), 1.18, seg=40)
        box(part('ridge', YELLOW, (BX, 0, HT + 0.75)), (BX - 0.55, -0.09, HT + 0.5), (BX + 0.55, 0.09, HT + 0.9))
    else:
        top = HT - 0.2
        dome(part('dome', SILVER, (BX, 0, top + 0.3)), (BX, 0, top), 0.98, seg=40)
        box(part('back', SILVER, (BX - 0.65, 0, 2.38)), (BX - 0.98, -0.8, 1.9), (BX - 0.3, 0.8, top))
        for side in (1, -1):
            y0, y1 = sorted((side * 0.74, side * 0.94))
            box(part('cheek', SILVER, (BX + 0.05, side * 0.84, 2.38)), (BX - 0.6, y0, 1.95), (BX + 0.68, y1, top))
        box(part('brow', SILVER, (BX + 0.75, 0, top - 0.02)), (BX + 0.6, -0.9, top - 0.12), (BX + 0.98, 0.9, top + 0.08))
        box(part('nose', SILVER, (BX + 0.86, 0, 2.5)), (BX + 0.78, -0.09, 2.22), (BX + 0.94, 0.09, top - 0.1))
        cylinder(part('stalk', GOLD, (BX, 0, top + 1.05)), (BX, 0, top + 0.9), (BX, 0, top + 1.2), 0.13)
        for k, (x0, x1, z0, z1) in enumerate([(-0.25, 0.3, 1.15, 1.5), (-0.7, -0.15, 1.05, 1.42),
                                              (-1.05, -0.6, 0.75, 1.15), (-1.22, -0.92, 0.3, 0.8)]):
            box(part('plume', RED, (BX + (x0 + x1) / 2, 0, top + (z0 + z1) / 2)),
                (BX + x0, -0.11, top + z0), (BX + x1, 0.11, top + z1))
    return parts


def race_frames(orig_dir):
    out = {}
    for r in RACES:
        files = pfs.read(os.path.join(orig_dir, f'global{r}_chr.s3d.orig'))
        w = wld.Wld(next(b for n, b in files if n.endswith('.wld')))
        (sid, _), = w.of_type(0x10)
        bones, _m = w.skeleton(sid)
        fr = {n: (np.array(R, float), np.array(T, float)) for n, _p, (R, T) in bones}
        P = r.upper()
        out[r] = {k: fr.get(f'{P}{k}_DAG', fr[f'{P}HEAD_POINT_DAG']) for k in FRAMES}
    return out


def strip_pieces(raw):
    """A rigid mesh (no skeleton) keeps no bone runs."""
    c = struct.unpack_from('<10H', raw, 76)
    nv, nuv, nn, _x, npoly, npieces = c[:6]
    at = 96 + 6 * nv + 4 * nuv + 3 * nn + 8 * npoly
    out = bytearray(raw[:at] + raw[at + 4 * npieces:])
    struct.pack_into('<H', out, 86, 0)
    return bytes(out)


def main():
    src, dst, orig_dir = sys.argv[1:4]
    heads = hairpieces.load_heads(orig_dir)
    frames = race_frames(orig_dir)
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    skel_of = {}
    for sid, _fr in w.of_type(0x10):
        bones, mids = w.skeleton(sid)
        for mi in mids:
            skel_of[mi] = [(name, parent, (np.array(R, float), np.array(T, float))) for name, parent, (R, T) in bones]

    items = {}
    for i, fr in w.of_type(0x36):
        n = int(re.search(r'\d+', fr[1]).group())
        if not 5000 <= n < 6000:
            continue
        m = w.mesh(i)
        sk = skel_of.get(i)
        if sk:
            V = np.array([sk[bi][2][0] @ np.array(v, float) + sk[bi][2][1] for v, bi in zip(m['verts'], m['bones'])])
        else:
            V = np.array(m['verts'], float)
        sub = V[::max(1, len(V) // 120)]
        scores = []
        for r in RACES:
            pts = heads[r]['pts']
            for k, (R, T) in frames[r].items():
                d = np.sqrt((((sub @ R.T + T)[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).min(1)
                scores.append((float(np.median(d)), r, k))
        scores.sort()
        items[i] = dict(n=n, m=m, skel=sk, best=scores[0], scores=scores)
    # Blocks of 30 follow the client's race numbers, male then female
    order = 'hum huf bam baf erm erf elm elf him hif dam daf ham haf dwm dwf trm trf ogm ogf hom hof gnm gnf ikm ikf kem kef'
    block_race = dict(enumerate(order.split()))

    frags, report = [], []
    shrink = {}  # mesh id: k, for the races racescale.py shrinks
    for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
        if ftype == 0x36:
            it = items.get(i)
            if it is None:
                raw = make_s3d.flatten_mesh(raw)
            else:
                race = block_race[(it['n'] - 5000) // 30]
                race, frame, *turn = WEARER.get(it['n'], (race, 'HEAD_POINT' if race in HEAD_FRAME else 'HAIR_POINT'))
                if racescale.factor(race):
                    shrink[i] = racescale.factor(race)
                fit = next(sc for sc in it['scores'] if sc[1] == race and sc[2] == frame)
                Rp, Tp = frames[race][frame]
                if turn:
                    cyc = frames[race]['HEAD_POINT'][0].T @ frames[race]['HAIR_POINT'][0]
                    Rp = Rp @ np.linalg.matrix_power(cyc, turn[0])
                if len(turn) > 1:  # turn the built hat about Tp by world axis cycles (x->y, y->z, z->x)
                    cyc_w = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float)
                    Rp = np.linalg.matrix_power(cyc_w, turn[1]) @ Rp
                style = style_of(it['n'])
                parts = hat('wizard', label_colors((it['n'] - 5000) // 30)) if LABEL else hat(style)
                P = race.upper()
                if P != 'DWM':
                    minifig.fit(parts, P, heads[race]['rest'])
                mat = it['m']['materials'][0][0]
                uv = lambda c, u, v: cell_uv(c)
                if it['skel']:
                    chain = [(nm, par, (Rp @ R, Rp @ T + Tp)) for nm, par, (R, T) in it['skel']]
                    for p in parts:
                        p.bone = chain[1][0]
                    raw = make_s3d.mesh_body(w, i, parts, chain, uv, mat)
                else:
                    for p in parts:
                        p.bone = 'ROOT'
                    raw = make_s3d.mesh_body(w, i, parts, [('ROOT', -1, (Rp, Tp))], uv, mat)
                    if struct.unpack_from('<H', w.frags[i][2], 86)[0] == 0:
                        raw = strip_pieces(raw)
                report.append(f'{name}: {race} {style} on {fit[2]} (fit {it["best"][0]:.2f} {it["best"][1]})')
        frags.append((ftype, raw))
    racescale.scale_attachments(w, frags, shrink)  # Ogre, Troll, Barbarian pieces shrink with their heads
    new_wld = make_s3d.write_wld(wld_data, frags)
    pal = make_s3d.dds_dxt1(palette())
    helm_tex = re.compile(r'^(it5\d{3}|ithelm).*\.dds$')
    out = [(n, new_wld if n == wld_name else pal if helm_tex.match(n.lower()) else b) for n, b in files]
    pfs.write(dst, out)
    print('\n'.join(report))
    print(f'{len(report)} helmets -> {dst}')


def preview(path):
    """The Dwarf minifig in each hat."""
    race = minifig.RACES['dwm']
    files = []
    for style in ('wizard', 'hardhat', 'knight'):
        minifig.use(race)
        parts = minifig.build(race) + hat(style)
        f = f'{path}.{style}.png'
        minifig.preview(f, parts, size=320, ss=1)
        files.append(f)
    ims = [Image.open(f).convert('RGB') for f in files]
    sheet = Image.new('RGB', (sum(i.size[0] for i in ims), max(i.size[1] for i in ims)))
    x = 0
    for im in ims:
        sheet.paste(im, (x, 0))
        x += im.size[0]
    sheet.save(path)
    for f in files:
        os.remove(f)


if __name__ == '__main__':
    if sys.argv[1] == 'preview':
        preview(sys.argv[2])
    else:
        main()
