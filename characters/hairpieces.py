"""Minifig hair and beard pieces for the Luclin hair/facial-hair attachments in lgequip.s3d / lgequip2.s3d.

The client draws a hair style or beard as its own model (IT1000-1812 hair, IT2000-2784 facial hair), attached to
the race's head bone. Each of those meshes is replaced by a brick-style piece sitting on the minifig head:
short/medium/long hair (plus bangs, a bun or a ponytail), full or long beard, goatee, mustache or sideburns.
Robes, tunics and kilts (IT4000+) stay folded away.

The style comes from the original mesh's shape and texture names (har, bng, tal, brd, mst, sdb); where it sits comes
from the race whose head the original fits (the minifig head is placed differently on each race's head bone).
Hair and beard textures are grey and the client tints them with the chosen hair color, so each texture becomes a
flat grey of the original's brightness: the piece then takes the player's color.

    python -I hairpieces.py <lgequip.s3d.orig> <out lgequip.s3d> <brick_orig folder>
"""
import io, json, math, os, re, struct, sys
from collections import Counter
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import make_s3d, minifig, pfs, racescale, wld
from minifig import BX, Part, box, cylinder, dome, hexa

RACES = 'hum huf bam baf erm erf elm elf him hif ham haf dam daf dwm dwf trm trf ogm ogf hom hof gnm gnf ikm ikf kem kef'
RACES = RACES.split()
BEARDED = 'hum bam erm dwm trm ogm hom gnm ikm kem'.split()  # male races with a beard attach point
HT = 3.05  # minifig head top (Dwarf frame); the head runs from z 1.8 up, radius 0.72, face toward +X


# ------------------------------------------------------------------------------------------------ races
def load_heads(orig_dir):
    """Per race: head bone rest (R, T), the original head's vertices (posed), and the skeleton positions."""
    heads = {}
    for r in RACES:
        files = pfs.read(os.path.join(orig_dir, f'global{r}_chr.s3d.orig'))
        w = wld.Wld(next(b for n, b in files if n.endswith('.wld')))
        (sid, _), = w.of_type(0x10)
        bones, mids = w.skeleton(sid)
        P = r.upper()
        hb = next(k for k, b in enumerate(bones) if b[0] == f'{P}HEHEAD_DAG')
        body = next(i for i in mids if w.frags[i][1] == f'{P}_DMSPRITEDEF')
        m = w.mesh(body)
        desc = {hb}
        for k, b in enumerate(bones):
            if b[1] in desc:
                desc.add(k)
        pts = np.array([wld.add(wld.matvec(bones[bi][2][0], v), bones[bi][2][1])
                        for v, bi in zip(m['verts'], m['bones']) if bi in desc])
        frame = {n: (np.array(R, float), np.array(T, float)) for n, _p, (R, T) in bones}
        point = lambda k: frame.get(f'{P}{k}_POINT_DAG', frame.get(f'{P}HEAD_POINT_DAG'))
        heads[r] = dict(pts=pts, rest={n: T for n, _p, (_R, T) in bones}, hair=point('HAIR'), beard=point('BEARD'))
    return heads


def attach(n, head):
    """Where an attachment's root sits on a race: its hair or beard attach point (rest pose)."""
    return head['hair'] if n < 2000 else head['beard']


def placed(it, head):
    Rp, Tp = attach(it['n'], head)
    return it['V'] @ Rp.T + Tp


def fit_score(it, head):
    d = np.sqrt(((placed(it, head)[:, None, :] - head['pts'][None, :, :]) ** 2).sum(-1)).min(1)
    return float(np.median(d))


# ------------------------------------------------------------------------------------------------ styles
def classify(it, head):
    """Style of one original attachment, from its shape on the race's original head and its texture names."""
    n, tex, pts = it['n'], it['tex'], head['pts']
    Wp = placed(it, head)
    zt, zb = pts[:, 2].max(), pts[:, 2].min()
    H = zt - zb
    top = (Wp[:, 2].max() - zt) / H
    low = (zt - Wp[:, 2].min()) / H
    width = (Wp[:, 1].max() - Wp[:, 1].min()) / H
    if n < 2000:
        return ['short' if low < 0.95 else 'long', low]  # blocky hair: short or long (bald is the no-hair choice)
    return ['mustache'] if 'mst' in tex else ['beard', 'mustache']  # mustache, beard, or none


def pieces(style):
    """Parts on the Dwarf-frame minifig head for a style. Hair encloses the race's own (built-in) hair piece."""
    parts = []

    def part(name, center):
        p = Part(name, 'DWMHEHEAD_DAG', 'hair', center)
        p.group = 'head'
        parts.append(p)
        return p

    R = 0.86
    if style[0] in ('short', 'medium', 'long'):
        cylinder(part('cap', (BX, 0, HT)), (BX, 0, 2.72), (BX, 0, HT + 0.17), R, seg=40)
        cylinder(part('crown', (BX, 0, HT + 0.25)), (BX, 0, HT + 0.17), (BX, 0, HT + 0.38), R, 0.62, seg=40,
                 caps=(False, True))
        low = {'short': 1.92, 'medium': 1.65, 'long': 1.28}[style[0]]
        box(part('back', (BX - 0.6, 0, (low + 2.85) / 2)), (BX - 0.9, -0.88, low), (BX - 0.28, 0.88, 2.85))
        if style[0] == 'long':
            for side in (1, -1):
                y0, y1 = sorted((side * 0.64, side * 0.96))
                box(part('lock', (BX - 0.1, side * 0.8, 2.1)), (BX - 0.52, y0, low + 0.15), (BX + 0.27, y1, 2.85))
        if 'bangs' in style:
            box(part('bangs', (BX + 0.7, 0, 2.84)), (BX + 0.5, -0.62, 2.7), (BX + 0.9, 0.62, 2.98))
        if 'bun' in style:
            c = (BX - 0.2, 0, HT + 0.32)
            cylinder(part('bun', (BX - 0.2, 0, HT + 0.55)), c, (BX - 0.2, 0, HT + 0.62), 0.38)
            dome(part('bun top', (BX - 0.2, 0, HT + 0.7)), (BX - 0.2, 0, HT + 0.62), 0.38)
        if 'tail' in style:
            cylinder(part('tail band', (BX - 0.95, 0, 2.55)), (BX - 0.86, 0, 2.55), (BX - 1.0, 0, 2.5), 0.24)
            cylinder(part('tail', (BX - 1.05, 0, 1.9)), (BX - 1.0, 0, 2.45), (BX - 1.1, 0, 1.25), 0.24, 0.12)
        return parts
    for s in style:
        if s == 'mustache':
            hexa(part('mustache', (BX + 0.85, 0, 2.33)),
                 [(BX + 0.68, -0.58, 2.2), (BX + 0.98, -0.58, 2.2), (BX + 0.98, 0.58, 2.2), (BX + 0.68, 0.58, 2.2),
                  (BX + 0.68, -0.36, 2.44), (BX + 0.98, -0.34, 2.44), (BX + 0.98, 0.34, 2.44),
                  (BX + 0.68, 0.36, 2.44)])
        elif s in ('beard', 'long beard'):
            bottom = 0.4 if s == 'long beard' else 1.35
            hexa(part(s, (BX + 0.72, 0, (bottom + 2.3) / 2)),
                 [(BX + 0.45, -0.22 if s == 'long beard' else -0.45, bottom), (BX + 0.88, -0.16, bottom),
                  (BX + 0.88, 0.16, bottom), (BX + 0.45, 0.22 if s == 'long beard' else 0.45, bottom),
                  (BX + 0.4, -0.78, 2.3), (BX + 0.95, -0.66, 2.3), (BX + 0.95, 0.66, 2.3), (BX + 0.4, 0.78, 2.3)])
        elif s == 'dwarf beard':
            hexa(part('beard', (BX + 0.75, 0, 1.4)),
                 [(BX + 0.5, -0.2, 0.35), (BX + 0.85, -0.14, 0.35), (BX + 0.85, 0.14, 0.35), (BX + 0.5, 0.2, 0.35),
                  (BX + 0.6, -0.68, 2.3), (BX + 0.98, -0.64, 2.3), (BX + 0.98, 0.64, 2.3), (BX + 0.6, 0.68, 2.3)])
            hexa(part('mustache', (BX + 0.9, 0, 2.35)),
                 [(BX + 0.72, -0.6, 2.22), (BX + 1.02, -0.6, 2.22), (BX + 1.02, 0.6, 2.22), (BX + 0.72, 0.6, 2.22),
                  (BX + 0.72, -0.38, 2.46), (BX + 1.02, -0.36, 2.46), (BX + 1.02, 0.36, 2.46),
                  (BX + 0.72, 0.38, 2.46)])
        elif s == 'goatee':
            box(part('goatee', (BX + 0.78, 0, 1.85)), (BX + 0.6, -0.22, 1.5), (BX + 0.94, 0.22, 2.12))
        elif s == 'sideburns':
            for side in (1, -1):
                y0, y1 = sorted((side * 0.66, side * 0.86))
                box(part('sideburn', (BX + 0.2, side * 0.76, 2.45)), (BX - 0.05, y0, 2.1), (BX + 0.45, y1, 2.8))
    return parts


# ------------------------------------------------------------------------------------------------ archive
def flat_texture(data):
    """Same size, flat color: the original's average (grey for tinted hair), a little brighter for a plastic look."""
    im = Image.open(io.BytesIO(data)).convert('RGB')
    w, h = max(im.size[0], 4), max(im.size[1], 4)
    mean = np.asarray(im, np.float32).reshape(-1, 3).mean(0)
    color = tuple(int(min(255, c * 1.12 + 8)) for c in mean)
    return make_s3d.dds_dxt1(Image.new('RGB', (w, h), color))


def main():
    src, dst, orig_dir = sys.argv[1:4]
    heads = load_heads(orig_dir)
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)

    # Each attachment mesh has its own little skeleton (root, NULL, then lip/jaw/beard/hair bones); its vertices are
    # in their bone's space, and the root hangs on the race's hair or beard attach point
    skel_of = {}
    for sid, _fr in w.of_type(0x10):
        bones, mids = w.skeleton(sid)
        for mi in mids:
            skel_of[mi] = [(name, parent, (np.array(R, float), np.array(T, float))) for name, parent, (R, T) in bones]

    # Pass 1: every hair/beard mesh, its best-fitting race; then one race per block of styles
    items = {}
    for i, fr in w.of_type(0x36):
        n = int(re.search(r'\d+', fr[1]).group())
        if n >= 4000:
            continue
        m = w.mesh(i)
        sk = skel_of[i]
        V = np.array([sk[bi][2][0] @ np.array(v, float) + sk[bi][2][1] for v, bi in zip(m['verts'], m['bones'])])
        tex = {re.sub(r'^it\d+|\d*_mdf$', '', mat[0].lower()) for mat in m['materials']}
        it = dict(n=n, V=V, tex=tex, m=m, skel=sk)
        cands = BEARDED if n >= 2000 else [r for r in RACES if not r.startswith('ik')]
        scores = sorted((fit_score(it, heads[r]), r) for r in cands)
        it['best'], it['score'] = scores[0][1], scores[0][0]
        items[i] = it
    block_of = lambda n: (n - 1000) // 30 if n < 2000 else 1000 + (n - 2000) // 10  # hair sets of 3, beard sets of 5
    votes = {}
    for it in items.values():
        votes.setdefault(block_of(it['n']), []).append(it['best'])
    block_race = {b: Counter(v).most_common(1)[0][0] for b, v in votes.items()}
    # Hair sets are NOT in a race order. Taking the race from the position (tried 2026-11-11) put the sets that fit
    # Ogre heads (IT1690, IT1750) and Barbarian heads (IT1360) on other races, unshrunk: in game Ogres, Trolls and
    # Barbarians wore hair like giant heads. IT1000/1030 fit Gnome and Dwarf heads, not Human. The vote stays.

    # Styles; every race's hair set gets a long choice (its longest original) next to the short ones
    for it in items.values():
        it['style'] = classify(it, heads[block_race[block_of(it['n'])]])
    for b in {block_of(it['n']) for it in items.values() if it['n'] < 2000}:
        hair = [it for it in items.values() if it['n'] < 2000 and block_of(it['n']) == b]
        if all(it['style'][0] == 'short' for it in hair):
            max(hair, key=lambda it: it['style'][1])['style'][0] = 'long'
        if all(it['style'][0] == 'long' for it in hair):
            min(hair, key=lambda it: it['style'][1])['style'][0] = 'short'
    for it in items.values():
        if it['n'] < 2000:
            it['style'] = it['style'][:1]
    # Facial hair: three looks only. In each set the first choice is none (hidden), the second the mustache, the
    # rest the beard (the client fixes how many choices there are)
    for b in {block_of(it['n']) for it in items.values() if it['n'] >= 2000}:
        ns = sorted(it['n'] for it in items.values() if it['n'] >= 2000 and block_of(it['n']) == b)
        ns = sorted(set(ns))
        for it in items.values():
            if it['n'] >= 2000 and block_of(it['n']) == b:
                k = ns.index(it['n'])
                it['style'] = ['none'] if k == 0 else ['mustache'] if k == 1 else ['beard', 'mustache']

    frags, report = [], []
    shrink = {}  # mesh id: k, for the races racescale.py shrinks
    for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
        if ftype == 0x36:
            it = items.get(i)
            race = it and block_race[block_of(it['n'])]
            if race and racescale.factor(race):
                shrink[i] = racescale.factor(race)
            if it is None or it['style'] == ['none']:
                raw = make_s3d.flatten_mesh(raw)
                if it:
                    report.append(f'{name}: {race} none (hidden)')
            else:
                style = it['style']
                if race == 'dwm' and style[0] == 'beard':
                    style = ['dwarf beard']  # every Dwarf option is his triangle beard; pick it or none, then color
                parts = pieces(style)
                P = race.upper()
                if P != 'DWM':
                    minifig.fit(parts, P, heads[race]['rest'])
                # The piece rides the NULL bone, rigid with the attach point; mesh_body stores it in that bone's
                # rest space (attach point after the attachment's own NULL transform)
                Rp, Tp = attach(it['n'], heads[race])
                chain = [(nm, par, (Rp @ R, Rp @ T + Tp)) for nm, par, (R, T) in it['skel']]
                for p in parts:
                    p.bone = chain[1][0]
                raw = make_s3d.mesh_body(w, i, parts, chain, lambda _m, u, v: (0.5, 0.5), it['m']['materials'][0][0])
                report.append(f'{name}: {race} {"+".join(style)} (fit {it["score"]:.3f} {it["best"]})')
        frags.append((ftype, raw))
    racescale.scale_attachments(w, frags, shrink)  # Ogre, Troll, Barbarian pieces shrink with their heads
    new_wld = make_s3d.write_wld(wld_data, frags)
    hair_tex = re.compile(r'^it(1\d{3}|2\d{3})\D.*\.dds$')
    out = [(n, new_wld if n == wld_name else flat_texture(b) if hair_tex.match(n) else b) for n, b in files]
    pfs.write(dst, out)
    print('\n'.join(report))
    print(f'{len(report)} hair/beard meshes; {sum(1 for n, _ in files if hair_tex.match(n))} textures -> {dst}')
    with open(os.path.splitext(dst)[0] + '_styles.json', 'w') as f:
        json.dump(report, f, indent=0)


if __name__ == '__main__':
    main()
