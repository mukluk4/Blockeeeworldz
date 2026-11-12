"""Brick robe skirts for the Luclin robe attachments in lgequip.s3d / lgequip2.s3d.

A worn robe (armor sets 10-16) is drawn on a Luclin-model player as its own model (IT4000 and up) with a body
texture (ROB), a collar (CLR) and sleeves (SLV). The top half of the minifig already shows the robe colors through
the chest texture; this covers the bottom half: every robe mesh becomes a long minifig skirt from the waist to just
above the feet, in the robe's own body color, with a hem in its collar color. The skirt rides the pelvis (legs swing
inside it). Tunics and anything that isn't a robe stay folded away.

The race of each robe is the race whose skeleton matches the robe's own copy of the skeleton best.

    python -I robes.py <lgequip.s3d with hair pieces> <out .s3d> <brick_orig folder>
"""
import io, os, re, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import hairpieces, make_s3d, minifig, pfs, wld
from minifig import BX, Part, hexa

FOOT, WAIST = -3.1, -0.45
# Robe blocks (IT4000 + 30 * block + robe 0-6 = armor sets 10-16), from the races named in the original mesh names;
# only these races have robe models
ROBE_BLOCKS = {0: 'gnm', 1: 'gnf', 6: 'dam', 7: 'daf', 10: 'him', 11: 'hif', 12: 'hum', 13: 'huf', 14: 'ikm', 15: 'ikf',
               16: 'erm', 17: 'erf'}


def skirt(body, hem):
    parts = []

    def part(name, color, center):
        p = Part(name, 'DWMPEPELVIS_DAG', color, center)
        p.group = 'body'
        parts.append(p)
        return p

    bottom, top = FOOT + 0.62, WAIST + 0.05
    hexa(part('skirt', body, (BX, 0, (bottom + top) / 2)),
         [(BX - 0.95, -1.42, bottom), (BX + 0.98, -1.42, bottom), (BX + 0.98, 1.42, bottom), (BX - 0.95, 1.42, bottom),
          (BX - 0.66, -1.28, top), (BX + 0.66, -1.28, top), (BX + 0.66, 1.28, top), (BX - 0.66, 1.28, top)])
    lo = bottom - 0.02
    hexa(part('hem', hem, (BX, 0, lo + 0.12)),
         [(BX - 1.0, -1.47, lo), (BX + 1.03, -1.47, lo), (BX + 1.03, 1.47, lo), (BX - 1.0, 1.47, lo),
          (BX - 0.97, -1.45, lo + 0.24), (BX + 1.0, -1.45, lo + 0.24), (BX + 1.0, 1.45, lo + 0.24),
          (BX - 0.97, 1.45, lo + 0.24)])
    return parts


def race_skeletons(orig_dir):
    out = {}
    for r in hairpieces.RACES:
        files = pfs.read(os.path.join(orig_dir, f'global{r}_chr.s3d.orig'))
        w = wld.Wld(next(b for n, b in files if n.endswith('.wld')))
        (sid, _), = w.of_type(0x10)
        bones, _m = w.skeleton(sid)
        P = r.upper()
        out[r] = {n[len(P):]: (np.array(R, float), np.array(T, float)) for n, _p, (R, T) in bones if n.startswith(P)}
    return out


def flat(color, size=8):
    return make_s3d.dds_dxt1(Image.new('RGB', (size, size), color))


def main():
    src, dst, orig_dir = sys.argv[1:4]
    skels = race_skeletons(orig_dir)
    files = pfs.read(src)
    names = {n.lower(): b for n, b in files}
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    skel_of = {}
    for sid, _fr in w.of_type(0x10):
        bones, mids = w.skeleton(sid)
        for mi in mids:
            skel_of[mi] = [(name, parent, (np.array(R, float), np.array(T, float))) for name, parent, (R, T) in bones]

    def color_of(mat):
        b = names.get(mat.lower().replace('_mdf', '.dds'))
        if b is None:
            return None
        img = Image.open(io.BytesIO(b)).convert('RGB')
        c = make_s3d.top_colors(make_s3d.snapped_counts([img]), 1)
        return c[0] if c else None

    frags, report, new_tex = [], [], {}
    for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
        if ftype == 0x36:
            m = re.match(r'IT(\d+)', name)
            n = int(m.group(1)) if m else 0
            mats = [mt for mt, _a, _b in w.mesh(i)['materials']]
            rob = next((mt for mt in mats if 'ROB' in mt.upper()), None)
            sk = skel_of.get(i)
            block, kind = divmod(n - 4000, 30)
            if 4000 <= n < 5000 and rob and sk and block in ROBE_BLOCKS and kind <= 6:
                race = ROBE_BLOCKS[block]
                clr = next((mt for mt in mats if 'CLR' in mt.upper()), rob)
                body = color_of(rob) or (10, 52, 99)
                hem = color_of(clr) or minifig.GOLD
                if hem == body:
                    hem = minifig.GOLD
                parts = skirt(body, hem)
                if race != 'dwm':
                    minifig.fit(parts, race.upper(), {race.upper() + k: T for k, (_R, T) in skels[race].items()})
                # The robe's skeleton is the race's with the pelvis moved to the origin: the robe hangs from the
                # character's pelvis. The skirt is stored in pelvis space, so place it with the race's own pelvis.
                pelvis = next(nm for nm, _p, _w in sk if nm.endswith('PEPELVIS_DAG'))
                sk = [(nm, par, skels[race]['PEPELVIS_DAG'] if nm == pelvis else tf) for nm, par, tf in sk]
                for p in parts:
                    p.bone = pelvis
                mat_of = lambda p, rob=rob, clr=clr: rob if p.name == 'skirt' else clr
                raw = make_s3d.mesh_body(w, i, parts, sk, lambda _c, u, v: (0.5, 0.5), mat_of)
                new_tex[rob.lower().replace('_mdf', '.dds')] = flat(body)
                new_tex.setdefault(clr.lower().replace('_mdf', '.dds'), flat(hem))
                report.append(f'{name}: {race} robe {kind + 10} body {body} hem {hem}')
            elif n >= 4000:
                raw = make_s3d.flatten_mesh(raw)
        frags.append((ftype, raw))
    new_wld = make_s3d.write_wld(wld_data, frags)
    out = [(n, new_wld if n == wld_name else new_tex.get(n.lower(), b)) for n, b in files]
    pfs.write(dst, out)
    print('\n'.join(report))
    print(f'{len(report)} robes -> {dst}')


if __name__ == '__main__':
    main()
