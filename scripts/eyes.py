"""Brick eyes, picked by hand: find each brick creature's eye candidates on its stock head and draw them, then save
the picks to characters/creature_eyes.json, which brickcreature.py reads.

    python -I scripts/eyes.py sheet <client folder> [--only BEA,RAT]   # numbered candidates, sheets of 24 heads
    python -I scripts/eyes.py pick RAT=1 SNA=3 BEA=0 ...               # pair 1-5 for each creature, 0 = no eyes
    python -I scripts/eyes.py pick KOP=front MAM=side PUS=front:red    # eyes placed by the head's shape instead
    python -I scripts/eyes.py sheet <client folder> --none             # the heads with no candidates, to check

Candidates (best first) are marked on the stock head: 1 magenta, 2 cyan, 3 yellow, 4 green, 5 orange. A sheet run
keeps the candidates in <out>/eye_candidates.json, which pick reads. Minifigs, sculpted heads and painted faces are
left out: they have their own eyes.
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'scripts', 'characters', 'zones')]
import pfs, wld, snapshot, review, review_render as rr
import brickcreature as bc

MARKS = [(255, 0, 255), (0, 230, 255), (255, 230, 0), (60, 255, 60), (255, 140, 0)]
PICKS = os.path.join(_root, 'characters', 'creature_eyes.json')
TILE = 230  # pixels per view; two views (front, three-quarter) per head
try:
    FONT = ImageFont.truetype('arial.ttf', 14)
except Exception:
    FONT = ImageFont.load_default()


def wanted(idx, review_json, only):
    kinds = json.load(open(review_json)) if os.path.exists(review_json) else {}
    out = []
    for p, c in idx['creatures'].items():
        if not c['archive'] or (only and p not in only):
            continue
        if p in bc.PEOPLE or p in bc.SKIP or p in bc.HEADS or p in bc.VOXEL_FACES or p in bc.EXTRAS:
            continue
        if kinds.get(p, {}).get('kind', 'bricks') != 'bricks':
            continue
        out.append(p)
    return sorted(out)


def marker(c, r):
    """A small double pyramid at c (triangles)."""
    tris = []
    for d in np.eye(3):
        for s in (1, -1):
            o = [q for q in np.eye(3) if not np.allclose(q, d)]
            tris.append([c + s * d * r * 1.8, c + o[0] * r, c + o[1] * r])
            tris.append([c + s * d * r * 1.8, c - o[0] * r, c - o[1] * r])
    return tris


def sheet(client, idx, out, only, none=False):
    creatures = wanted(idx, os.path.join(out, 'review.json'), only)
    cpath = os.path.join(out, 'eye_candidates.json')
    cands = json.load(open(cpath)) if os.path.exists(cpath) else {}
    by_arc = {}
    for p in creatures:
        by_arc.setdefault(idx['creatures'][p]['archive'], []).append(p)
    tiles = []
    for arc, ps in sorted(by_arc.items()):
        src = review.source_of(client, arc)
        files = pfs.read(src)
        w = wld.Wld(next(b for n, b in files if n.lower().endswith('.wld')))
        tex = bc.texture_images(files)
        sw, st = rr.load(src)
        for p in ps:
            sid = next((i for i, _f in w.of_type(0x10) if w.frags[i][1].split('_')[0] == p), None)
            if sid is None:
                continue
            bones, mesh_ids = w.skeleton(sid)
            if p in cands:  # found in an earlier run
                found = [[tuple(np.array(v, float) if k != 2 else v for k, v in enumerate(eye)) for eye in pair]
                         for pair in cands[p]]
            else:
                try:
                    pts = bc.sample_surface(w, bones, mesh_ids, tex, step=1.0)[0]
                except (OverflowError, IndexError, ValueError) as ex:  # a malformed mesh (IVM)
                    print(f'{p}: unreadable ({type(ex).__name__})')
                    continue
                if not len(pts):
                    continue
                e = np.sort(pts.max(0) - pts.min(0))
                size = min(e[2] / bc.VOXELS.get(p, 18), e[1] / 5)
                found = bc.head_eye_candidates(w, bones, mesh_ids, tex, p, size)
                cands[p] = [[[np.asarray(v).tolist() if k != 2 else float(v) for k, v in enumerate(eye)]
                             for eye in pair] for pair in found]
                json.dump(cands, open(cpath, 'w'))
            m = rr.find(sw, st, p)
            if m is None or bool(found) == none:  # nothing to pick from (or, with --none, only those)
                continue
            names = [n for n, _p, _w in bones]
            heads = bc.head_bones(names, [q for _n, q, _w in bones], p)
            sel = np.isin(m.bones[:, 0], list(heads)) if heads else np.ones(len(m.bones), bool)
            if not sel.any():
                sel[:] = True
            T, U = m.triangles()[sel], m.uvs[sel]
            X = [t for t, k in zip(m.texs, sel) if k]
            span = float((T.reshape(-1, 3).max(0) - T.reshape(-1, 3).min(0)).max())
            textures = dict(m.textures)
            for rank, pair in enumerate(found):
                mk = [t for eye in pair for t in marker(eye[0], span * 0.018)]
                T = np.concatenate([T, np.array(mk)])
                U = np.concatenate([U, np.zeros((len(mk), 3, 2))])
                X = X + [f'__mark{rank}'] * len(mk)
                textures[f'__mark{rank}'] = np.full((4, 4, 3), MARKS[rank], np.uint8)
            im = snapshot.render((T, U, X), textures, size=TILE)[0].crop((0, 0, 2 * TILE, TILE))
            tile = Image.new('RGB', (2 * TILE, TILE + 18), (30, 32, 38))
            d = ImageDraw.Draw(tile)
            d.text((4, 1), p, fill=(240, 220, 120), font=FONT)
            for rank in range(len(found)):
                d.text((52 + 16 * rank, 1), str(rank + 1), fill=MARKS[rank], font=FONT)
            if not found:
                d.text((52, 1), 'none found', fill=(255, 120, 120), font=FONT)
            tile.paste(im, (0, 18))
            tiles.append(tile)
            print(f'{p}: {len(found)} candidates', flush=True)
    json.dump(cands, open(cpath, 'w'))
    cols, rows = (3, 6) if none else (2, 5)
    paths = []
    for k in range(0, len(tiles), cols * rows):
        page = tiles[k:k + cols * rows]
        sh = Image.new('RGB', (cols * 2 * TILE, ((len(page) + cols - 1) // cols) * (TILE + 18)), (30, 32, 38))
        for i, t in enumerate(page):
            sh.paste(t, ((i % cols) * 2 * TILE, (i // cols) * (TILE + 18)))
        path = os.path.join(out, f"eyes_{'none_' if none else ''}{k // (cols * rows) + 1:02d}.png")
        sh.save(path)
        paths.append(path)
    print('\n'.join(paths))


def pick(out, choices):
    cands = json.load(open(os.path.join(out, 'eye_candidates.json')))
    picks = json.load(open(PICKS)) if os.path.exists(PICKS) else {}
    for c in choices:
        p, n = c.split('=')
        p = p.upper()
        if not n[0].isdigit():  # front / side, with an optional color: shaped eyes
            shape, _s, color = n.partition(':')
            picks[p] = {'shape': shape, 'color': color or 'white'}
            continue
        n = int(n)
        if n == 0:
            picks[p] = None
        else:
            picks[p] = cands[p][n - 1]
    json.dump(dict(sorted(picks.items())), open(PICKS, 'w'), indent=1)
    print(f'{sum(1 for v in picks.values() if v)} creatures with eyes, {sum(1 for v in picks.values() if not v)} without'
          f' -> {PICKS}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('sheet', 'pick'))
    ap.add_argument('args', nargs='*')
    ap.add_argument('--only')
    ap.add_argument('--none', action='store_true')
    ap.add_argument('--out', default=os.path.join(_root, 'output', 'review'))
    a = ap.parse_args()
    if a.mode == 'sheet':
        idx = json.load(open(os.path.join(a.out, 'index.json')))
        sheet(a.args[0], idx, a.out, {s.strip().upper() for s in a.only.split(',')} if a.only else None, a.none)
    else:
        pick(a.out, a.args)


if __name__ == '__main__':
    main()
