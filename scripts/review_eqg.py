"""Mob review for creatures stored as newer .eqg models: the same pictures and flags as review.py, for the .eqg
creatures that the bricked zones (zones/*/zones.txt) and the client's global load list use.

    python -I scripts/review_eqg.py index  <client folder>     # which .eqg archive each creature model comes from
    python -I scripts/review_eqg.py build  <client folder>     # brick them into <out>/brick (resumable) [-j 4]
    python -I scripts/review_eqg.py render <client folder>     # stock + brick + walking pose per creature, with flags
    python -I scripts/review_eqg.py all    <client folder>

Options: --only BAS,WLF, --out DIR (default output/review_eqg), -j N (archives built at a time).
The client folder is only read. Pictures go to <out>/img/<CODE>.jpg, flags to <out>/review.json, in the same
format as review.py's, so one review page can show both.
"""
import argparse, glob, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'scripts', 'characters', 'zones')]
import pfs, eqgmod, eqgmds, eqgbones, snapshot
import review_render as rr

ANIMS = ('walk', 'nrun', 'swim', 'idle', 'stnd')  # the first one the model has
OUT = os.path.join(_root, 'output', 'review_eqg')


def source_of(client, name):
    orig = os.path.join(client, 'brick_orig', name + '.orig')
    return orig if os.path.exists(orig) else os.path.join(client, name)


def chr_list(path, client):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, errors='ignore').read().splitlines()[1:]:
        if ',' in line:
            code, arch = (s.strip().lower() for s in line.split(',')[:2])
            if os.path.exists(os.path.join(client, arch + '.eqg')):
                out[code] = arch
    return out


def bricked_zones():
    zones = set()
    for f in glob.glob(os.path.join(_root, 'zones', '*', 'zones.txt')):
        for l in open(f):
            l = l.split('#')[0].strip()
            if l:
                zones.add(l.split()[0].lower())
    return zones


def index(client, out):
    found = chr_list(os.path.join(client, 'Resources', 'GlobalLoad_chr.txt'), client)
    for z in sorted(bricked_zones()):
        for code, arch in chr_list(os.path.join(client, f'{z}_chr.txt'), client).items():
            found.setdefault(code, arch)
    idx = {'client': client, 'creatures': {}}
    for code, arch in sorted(found.items()):
        names = {n.lower() for n, _b in pfs.read(source_of(client, arch + '.eqg'))}
        kind = 'mds' if f'{code}.mds' in names else 'mod' if f'{code}.mod' in names else None
        idx['creatures'][code.upper()] = {'archive': arch + '.eqg' if kind else None, 'kind': kind, 'copies': [arch + '.eqg']}
    json.dump(idx, open(os.path.join(out, 'index.json'), 'w'), indent=1)
    have = [c for c, v in idx['creatures'].items() if v['archive']]
    print(f'{len(have)} .eqg creatures in {len({idx["creatures"][c]["archive"] for c in have})} archives; '
          f'{len(idx["creatures"]) - len(have)} listed without a model')
    return idx


def build(client, idx, out, only=None, jobs=4):
    bdir = os.path.join(out, 'brick')
    os.makedirs(bdir, exist_ok=True)
    tool = os.path.join(_root, 'characters', 'eqgcreature.py')
    by_arc = {}
    for c, v in idx['creatures'].items():
        if v['archive'] and (not only or c in only):
            by_arc.setdefault(v['archive'], []).append(c)
    todo = [(a, cs) for a, cs in sorted(by_arc.items())
            if only or not (os.path.exists(os.path.join(bdir, a)) and os.path.exists(os.path.join(bdir, a + '.log')))]

    def one(job):
        arc, codes = job
        t = time.time()
        r = subprocess.run([sys.executable, '-I', tool, '--archive', source_of(client, arc), os.path.join(bdir, arc),
                            ','.join(sorted(c.lower() for c in codes))], capture_output=True, text=True)
        open(os.path.join(bdir, arc + '.log'), 'w').write(r.stdout + ('\n--- errors ---\n' + r.stderr if r.returncode else ''))
        state = 'ok' if r.returncode == 0 else 'FAILED: ' + (r.stderr.strip().splitlines() or ['?'])[-1]
        print(f'{arc} {",".join(sorted(codes))}: {state} ({time.time() - t:.0f}s)', flush=True)

    with ThreadPoolExecutor(jobs) as pool:
        list(pool.map(one, todo))


def build_stats(out, arc):
    stats = {}
    log = os.path.join(out, 'brick', arc + '.log')
    if os.path.exists(log):
        for line in open(log):
            m = re.match(r'(\w+): (\d+) bricks of ([\d.]+), (\d+) color classes', line)
            if m:
                stats[m.group(1).upper()] = dict(bricks=int(m.group(2)), size=float(m.group(3)), classes=int(m.group(4)))
            m = re.match(r'(\w+): (no surface.*|no \w+\.mod.*)', line.strip())
            if m:
                stats[m.group(1).upper()] = dict(problem=m.group(2))
    return stats


# --- the model ----------------------------------------------------------------------------------------------------
class Model:
    """review_render.Model for an .eqg creature: bones, triangles with the bone each corner rides, animations."""

    def __init__(self, files, code):
        fd = {n.lower(): b for n, b in files}
        self.prefix = code.upper()
        kind = 'mds' if f'{code}.mds' in fd else 'mod'
        lib = eqgmds if kind == 'mds' else eqgmod
        m = lib.read(fd[f'{code}.{kind}'])
        self.m = m
        self.names = [lib.name(m, b[0]) for b in m.bones] or ['ROOT']
        self.bone_list = m.bones or [[0, -1, 0, -1, (0, 0, 0), (0, 0, 0, 1), (1, 1, 1)]]
        self.parent = eqgbones.parents(self.bone_list)
        self.kin = eqgbones.helper_kin(self.parent)
        self.rest = eqgbones.world(self.bone_list, self.parent)
        self.textures = snapshot.textures_of(fd)
        mats = []
        for _i, _n, _s, props in m.materials:
            tex = None
            for pr in props:
                pn, pt, pv = __import__('struct').unpack('<3I', pr)
                if lib.name(m, pn) == 'e_TextureDiffuse0' and pt == 2:
                    tex = lib.name(m, pv).lower().rsplit('.', 1)[0]
            mats.append(tex)
        if kind == 'mod':
            pieces = [(m.verts, m.tris, m.weights)]
        else:
            drawn = [p for p in m.pieces if p['main']] or m.pieces
            pieces = [(p['verts'], p['tris'], p['weights']) for p in drawn]
        local, uvs, bones, texs = [], [], [], []
        for verts, tris, weights in pieces:
            top = [max(w[1][:max(1, w[0])], key=lambda bw: bw[1])[0] for w in weights] if weights else [0] * len(verts)
            for a, b, c, mat, _fl in tris:
                if max(a, b, c) >= len(verts):
                    continue
                corner, cb = [], []
                for v in (a, c, b):  # wound the other way, as the renderer draws them
                    k = min(top[v], len(self.rest) - 1)
                    R, T = self.rest[k]
                    corner.append(R.T @ (np.array(verts[v][0], float) - T))
                    cb.append(k)
                local.append(corner)
                bones.append(cb)
                uvs.append([(verts[v][3][0], 1.0 - verts[v][3][1]) for v in (a, c, b)])
                texs.append(mats[mat] if 0 <= mat < len(mats) else None)
        self.local = np.array(local, float).reshape(-1, 3, 3)
        self.uvs = np.array(uvs, float).reshape(-1, 3, 2)
        self.bones = np.array(bones, int).reshape(-1, 3)
        self.texs = texs
        self.anims = {}
        for n, b in files:
            mm = re.match(r'([a-z0-9]{4})_ba_1_' + re.escape(code) + r'\.ani$', n.lower())
            if mm:
                try:
                    self.anims[mm.group(1)] = eqgbones.read_ani(b)
                except Exception:
                    pass

    def anim(self):
        for code in ANIMS:
            a = self.anims.get(code)
            if a:
                return code, max(len(f) for f in a.values())
        return None

    def world(self, code=None, frame=0):
        if not code or code not in self.anims:
            return self.rest
        local = {}
        by_name = {n: k for k, n in enumerate(self.names)}
        for name, frames in self.anims[code].items():
            k = by_name.get(name)
            if k is not None and frames:
                _ms, pos, rot = frames[min(frame, len(frames) - 1)]
                local[k] = (pos, rot)
        return eqgbones.world(self.bone_list, self.parent, local)

    def triangles(self, code=None, frame=0):
        W = self.world(code, frame)
        Rs = np.array([R for R, _T in W])
        Ts = np.array([T for _R, T in W])
        b = np.clip(self.bones, 0, len(W) - 1)
        return np.einsum('tvij,tvj->tvi', Rs[b], self.local) + Ts[b]

    def drawable(self, tris):
        return tris, self.uvs, self.texs


def load(path, code):
    try:
        m = Model(pfs.read(path), code.lower())
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'
    return (m if len(m.local) else None), None


def render_all(client, idx, out, only=None):
    img_dir = os.path.join(out, 'img')
    os.makedirs(img_dir, exist_ok=True)
    rpath = os.path.join(out, 'review.json')
    review = json.load(open(rpath)) if os.path.exists(rpath) else {}
    todo = sorted(c for c, v in idx['creatures'].items() if v['archive'] and (not only or c in only))
    for k, c in enumerate(todo, 1):
        arc = idx['creatures'][c]['archive']
        stock, err = load(source_of(client, arc), c)
        bpath = os.path.join(out, 'brick', arc)
        brick, berr = load(bpath, c) if os.path.exists(bpath) else (None, 'not built')
        s = build_stats(out, arc).get(c, {})
        if berr and 'problem' not in s:
            s['problem'] = berr
        entry = dict(archive=arc, copies=1, kind='bricks', bricks=s.get('bricks'), classes=s.get('classes'),
                     variants=1, anim=None, img=False, format='eqg')
        if stock is None:
            entry['flags'] = [['not built', f'stock model unreadable ({err})' if err else 'stock model has no triangles']]
            review[c] = entry
            print(f'[{k}/{len(todo)}] {c}: {entry["flags"][0][1]}', flush=True)
            continue
        a = brick.anim() if brick is not None else None
        pose = (a[0], max(a[1] // 3, 0)) if a else None
        try:
            flags = rr.flags_for(stock, brick, s, pose)
            rr.picture(c, stock, brick, pose).save(os.path.join(img_dir, c + '.jpg'), quality=rr.JPEG_QUALITY)
            entry['img'] = True
        except Exception as e:
            flags = [('not built', f'drawing failed: {type(e).__name__}: {e}')]
        entry['flags'] = [list(x) for x in flags]
        entry['anim'] = pose[0] if pose else None
        review[c] = entry
        print(f'[{k}/{len(todo)}] {c}: ' + ('; '.join(f'{a} ({b})' for a, b in flags) or 'clean'), flush=True)
        if k % 10 == 0:
            json.dump(review, open(rpath, 'w'), indent=1)
    json.dump(review, open(rpath, 'w'), indent=1)
    print(f'{sum(1 for r in review.values() if r["flags"])} of {len(review)} flagged -> {rpath}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('index', 'build', 'render', 'all'))
    ap.add_argument('client')
    ap.add_argument('--only')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('-j', type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    only = {s.strip().upper() for s in a.only.split(',')} if a.only else None
    ipath = os.path.join(a.out, 'index.json')
    idx = index(a.client, a.out) if a.mode in ('index', 'all') or not os.path.exists(ipath) else json.load(open(ipath))
    if a.mode in ('build', 'all'):
        build(a.client, idx, a.out, only, a.j)
    if a.mode in ('render', 'all'):
        render_all(a.client, idx, a.out, only)


if __name__ == '__main__':
    main()
