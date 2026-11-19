"""Drawing and flags for review.py: each creature's stock model, its brick model, and the brick model mid-animation,
one picture per creature, plus automatic flags for the usual problems.

Flags (worst first in the review page):
  not built        the build skipped it (unreadable mesh, no body in that archive) or it has no brick model
  apart in motion  a limb's bricks move away from the bricks of the bone it hangs on during the walk/attack pose
  detached         a limb's bricks float away from the rest even standing still
  empty limb       a bone that carries a real share of the stock model has no bricks at all
  stretched        long thin sliver triangles (a half-hidden piece pulled across the model)
  size             the brick model is much bigger or smaller than the stock one along some axis
  sunk             the brick feet sit well below the stock feet
  few bricks       too few cubes for the shape to read
  few colors       one or two colors only
"""
import io, json, os, struct, sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'scripts')]
import pfs, wld, snapshot
from review import build_stats, source_of

ANIMS = ('L01', 'L02', 'L09', 'C01', 'C05', 'C02', 'C10', 'O01', 'P01')  # walk, run, swim, attacks, idle: the first one the model has
SIZE = 180            # pixels per view
JPEG_QUALITY = 82


class Model:
    """One skeleton of an archive: its bones and triangles (with the bone each corner rides), drawable at rest or at
    a frame of one of its animations."""

    def __init__(self, w, sid, textures):
        self.w, self.textures = w, textures
        _t, name, b = w.frags[sid]
        self.prefix = name.split('_')[0]
        flags, ntracks, _ref = struct.unpack_from('<IIi', b, 4)
        p = 16 + (12 if flags & 1 else 0) + (4 if flags & 2 else 0)
        self.names, self.tracks, self.parent = [], [], [-1] * ntracks
        kids = []
        for _ in range(ntracks):
            nref, _fl, track, _mesh, nchild = struct.unpack_from('<iIiiI', b, p)
            self.names.append(w.name(nref))
            self.tracks.append(track)
            kids.append(struct.unpack_from(f'<{nchild}i', b, p + 20))
            p += 20 + 4 * nchild
        for k, ch in enumerate(kids):
            for c in ch:
                self.parent[c] = k
        mesh_ids = []
        if flags & 0x200:
            n2, = struct.unpack_from('<I', b, p)
            for k in range(n2):
                ref, = struct.unpack_from('<i', b, p + 4 + 4 * k)
                mesh_ids.append(struct.unpack_from('<i', w.frags[ref][2], 4)[0])
        local, uvs, texs, bones = [], [], [], []
        for mid in mesh_ids:
            m = w.mesh(mid)
            for a, c, d, mi in m['faces']:
                _mn, method, tex = m['materials'][mi] if mi < len(m['materials']) else ('', 0, None)
                if method == 0:
                    continue
                tri = (a, d, c)
                if max(tri) >= len(m['verts']):
                    continue
                local.append([m['verts'][v] for v in tri])
                uvs.append([m['uvs'][v] if v < len(m['uvs']) else (0, 0) for v in tri])
                bones.append([m['bones'][v] if v < len(m['bones']) else 0 for v in tri])
                texs.append(tex)
        self.local = np.array(local, float).reshape(-1, 3, 3)
        self.uvs = np.array(uvs, float).reshape(-1, 3, 2)
        self.bones = np.array(bones, int).reshape(-1, 3)
        self.texs = texs
        self.track_names = {f[1]: i for i, f in enumerate(w.frags) if f and f[0] == 0x13}

    def frame_of(self, ref13, k):
        ref12, = struct.unpack_from('<i', self.w.frags[ref13][2], 4)
        b = self.w.frags[ref12][2]
        _flags, frames = struct.unpack_from('<II', b, 4)
        k = min(k, max(frames - 1, 0))
        rd, rx, ry, rz, sx, sy, sz, sd = struct.unpack_from('<8h', b, 12 + 16 * k)
        T = (sx / sd, sy / sd, sz / sd) if sd else (0.0, 0.0, 0.0)
        return np.array(wld.quat_matrix(rd, rx, ry, rz), float), np.array(T, float), frames

    def anim(self):
        """(code, frame count) of the first animation this skeleton has, or None."""
        for code in ANIMS:
            frames = [self.frame_of(self.track_names[code + self.w.frags[t][1]], 0)[2] for t in self.tracks
                      if code + self.w.frags[t][1] in self.track_names]
            if frames:
                return code, max(frames)  # the root often holds one frame while the limbs move
        return None

    def world(self, code=None, frame=0):
        out = []
        for k, t in enumerate(self.tracks):
            ref = self.track_names.get(code + self.w.frags[t][1]) if code else None
            R, T, _n = self.frame_of(ref if ref else t, frame if ref else 0)
            if self.parent[k] >= 0:
                PR, PT = out[self.parent[k]]
                R, T = PR @ R, PT + PR @ T
            out.append((R, T))
        return out

    def triangles(self, code=None, frame=0):
        W = self.world(code, frame)
        Rs = np.array([R for R, _T in W])
        Ts = np.array([T for _R, T in W])
        b = np.clip(self.bones, 0, len(W) - 1)
        return np.einsum('tvij,tvj->tvi', Rs[b], self.local) + Ts[b]

    def drawable(self, tris):
        return tris, self.uvs, self.texs


def load(path):
    files = dict(pfs.read(path))
    wname = next((n for n in files if n.lower().endswith('.wld')), None)
    if not wname:
        return None, {}
    return wld.Wld(files[wname]), snapshot.textures_of(files)


def find(w, textures, prefix):
    for sid, (_t, name, _b) in w.of_type(0x10):
        if name.split('_')[0].upper() == prefix:
            try:
                m = Model(w, sid, textures)
            except Exception:
                return None
            return m if len(m.local) else None
    return None


# --- flags ------------------------------------------------------------------------------------------------------
def surface_points(tris, step, cap=2500):
    """Points spread over the triangles about `step` apart (corners alone miss the faces of big bricks)."""
    out = [tris.reshape(-1, 3)]
    edges = np.linalg.norm(tris - np.roll(tris, 1, axis=1), axis=2).max(1)
    for n in sorted(set(np.clip(np.ceil(edges / step), 1, 12).astype(int).tolist())):
        if n < 2:
            continue
        sel = tris[np.clip(np.ceil(edges / step), 1, 12).astype(int) == n]
        ij = [(i, j) for i in range(n + 1) for j in range(n + 1 - i)]
        w = np.array([(i / n, j / n, 1 - (i + j) / n) for i, j in ij])
        out.append(np.einsum('kv,tvc->tkc', w, sel).reshape(-1, 3))
    pts = np.concatenate(out)
    if len(pts) > cap:
        pts = pts[np.random.default_rng(1).choice(len(pts), cap, replace=False)]
    return pts


def gap(a, b):
    """Smallest distance between two point sets."""
    best = np.inf
    for k in range(0, len(a), 400):
        d = ((a[k:k + 400, None, :] - b[None, :, :]) ** 2).sum(-1).min()
        best = min(best, d)
    return float(np.sqrt(best))


def limb_gaps(model, tris, step=0.2):
    """{bone: distance from its bricks to the nearest bricks on any of its ancestor bones} for every bone with bricks.
    Folded-away meshes (spare heads flattened to nothing) don't count."""
    rest = model.triangles()
    shown = np.linalg.norm(np.cross(rest[:, 1] - rest[:, 0], rest[:, 2] - rest[:, 0]), axis=1) > 1e-6
    tb = np.where(shown, model.bones[:, 0], -1)  # a brick triangle rides one bone
    has = {k: surface_points(tris[tb == k], step) for k in set(tb.tolist()) if k >= 0}
    out = {}
    for k in has:  # any ancestor counts: some skeletons hang the thighs off the chest, the bricks touch the pelvis
        anc, p = [], model.parent[k] if k < len(model.parent) else -1
        while p >= 0:
            if p in has:
                anc.append(has[p])
            p = model.parent[p] if p < len(model.parent) else -1
        anc += [has[q] for q in getattr(model, 'kin', {}).get(k, ()) if q in has]  # helper bones (eqg)
        if anc:
            out[k] = gap(has[k], np.concatenate(anc))
    return out


def flags_for(stock, brick, stats, pose):
    f = []
    if brick is None:
        f.append(('not built', stats.get('problem', 'no brick model in the built archive')))
        return f
    size = stats.get('size') or 0.4
    rest = brick.triangles()
    sp = stock.triangles().reshape(-1, 3)
    bp = rest.reshape(-1, 3)
    step = max(size / 2, 0.05)
    gaps_rest = limb_gaps(brick, rest, step)
    loose = [brick.names[k] for k, d in gaps_rest.items() if d > 1.6 * size]
    if pose:
        posed = brick.triangles(*pose)
        gaps_pose = limb_gaps(brick, posed, step)
        apart = [brick.names[k] for k, d in gaps_pose.items() if d > gaps_rest.get(k, 0) + 1.6 * size]
        if apart:
            f.append(('apart in motion', ', '.join(short(n, brick.prefix) for n in apart[:6])))
    if loose:
        f.append(('detached', ', '.join(short(n, brick.prefix) for n in loose[:6])))
    sb = stock.bones.reshape(-1)
    bb = set(brick.bones.reshape(-1).tolist())
    empty = [stock.names[k] for k in set(sb.tolist())
             if (sb == k).mean() > 0.06 and k not in bb and k < len(stock.names)]
    if empty and 'minifig' not in stats:
        f.append(('empty limb', ', '.join(short(n, stock.prefix) for n in empty[:6])))
    ext = bp.max(0) - bp.min(0)
    # slivers: long and very thin (a piece pulled across the model), unlike a big brick or minifig face. Folded-away
    # meshes (zero area) don't show; thin pieces the stock model has too (staff and spear shafts) are its own.
    def slivers(tris, ext):
        edges = np.linalg.norm(tris - np.roll(tris, 1, axis=1), axis=2).max(1)
        area = np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1) / 2
        height = 2 * area / np.maximum(edges, 1e-9)
        return int(((edges > max(0.3 * ext.max(), 4 * size)) & (height < 0.05 * edges) & (area > 1e-6)).sum())
    stock_tris = stock.triangles()
    long_ = slivers(rest, ext) - slivers(stock_tris, sp.max(0) - sp.min(0))
    if long_ > 0:
        f.append(('stretched', f'{long_} triangles'))
    se = sp.max(0) - sp.min(0)
    ratio = ext / np.maximum(se, 1e-6)
    off = [f'{a} x{r:.2f}' for a, r, s in zip('lwh', ratio, se) if s > 0.5 and (r < 0.7 or r > 1.45)]
    if off and 'minifig' not in stats:
        f.append(('size', ', '.join(off)))
    if bp[:, 2].min() < sp[:, 2].min() - 1.5 * size:
        f.append(('sunk', f'{sp[:, 2].min() - bp[:, 2].min():.1f} below stock feet'))
    if 'bricks' in stats and stats['bricks'] < 45:
        f.append(('few bricks', str(stats['bricks'])))
    if 'classes' in stats and stats['classes'] <= 2:
        f.append(('few colors', str(stats['classes'])))
    return f


def short(name, prefix):
    n = name[len(prefix):] if name.startswith(prefix) else name
    return n[:-4] if n.endswith('_DAG') else n


# --- drawing ----------------------------------------------------------------------------------------------------
try:
    FONT = ImageFont.truetype('arial.ttf', 13)
except Exception:
    FONT = ImageFont.load_default()


def picture(prefix, stock, brick, pose):
    """Rows: stock, brick, brick mid-animation; one camera for all three so sizes compare."""
    rows = [('stock', stock, stock.triangles())]
    if brick is not None:
        rows.append(('brick', brick, brick.triangles()))
        if pose:
            rows.append((f'brick, {pose[0]} frame {pose[1]}', brick, brick.triangles(*pose)))
    allp = np.concatenate([t.reshape(-1, 3) for _l, _m, t in rows])
    P = np.stack([allp[:, 1], allp[:, 2], allp[:, 0]], -1)
    lo, hi = P.min(0), P.max(0)
    frame = (((lo + hi) / 2).tolist(), float(max(hi - lo) * 1.12) or 1.0)
    ims = [snapshot.render(m.drawable(tris), m.textures, size=SIZE, frame=frame)[0] for _l, m, tris in rows]
    # one crop for every row (the band any row draws in), so long flat creatures don't come out mostly empty
    band = [np.nonzero((np.abs(np.asarray(im).astype(int) - snapshot.BG).max(2) > 6).any(1))[0] for im in ims]
    band = [b for b in band if len(b)]
    top = max(min(b[0] for b in band) - 8, 0) if band else 0
    bot = min(max(b[-1] for b in band) + 9, SIZE) if band else SIZE
    H = bot - top
    W = SIZE * len(snapshot.VIEWS)
    sheet = Image.new('RGB', (W, (H + 18) * len(rows)), (30, 32, 38))
    d = ImageDraw.Draw(sheet)
    for r, ((label, _m, _t), im) in enumerate(zip(rows, ims)):
        y = r * (H + 18)
        d.text((5, y + 2), label, fill=(240, 220, 120), font=FONT)
        sheet.paste(im.crop((0, top, W, bot)), (0, y + 18))
    return sheet


def render_all(client, idx, out, only=None):
    img_dir = os.path.join(out, 'img')
    os.makedirs(img_dir, exist_ok=True)
    rpath = os.path.join(out, 'review.json')
    review = json.load(open(rpath)) if os.path.exists(rpath) else {}
    by_arc = {}
    for p, c in idx['creatures'].items():
        if c['archive'] and (not only or p in only):
            by_arc.setdefault(c['archive'], []).append(p)
    done = 0
    total = sum(len(v) for v in by_arc.values())
    for arc, prefixes in sorted(by_arc.items()):
        t = time.time()
        try:
            sw, st = load(source_of(client, arc))
        except Exception as e:
            print(f'  {arc}: stock unreadable ({e})')
            continue
        bpath = os.path.join(out, 'brick', arc)
        bw, bt = load(bpath) if os.path.exists(bpath) else (None, {})
        stats = build_stats(out, arc)
        for p in sorted(prefixes):
            done += 1
            stock = find(sw, st, p)
            if stock is None:
                prev = os.path.join(out, 'brick', os.path.splitext(arc)[0] + f'_{p}_preview.png')
                if bw and find(bw, bt, p) is not None and os.path.exists(prev):  # stock unreadable (IVM): the build's own preview
                    Image.open(prev).convert('RGB').save(os.path.join(img_dir, p + '.jpg'), quality=JPEG_QUALITY)
                    review[p] = dict(archive=arc, flags=[], copies=len(idx['creatures'][p]['copies']), kind='bricks',
                                     bricks=0, classes=stats.get(p, {}).get('classes'), variants=1, anim=None, img=True)
                    print(f'[{done}/{total}] {p}: stock not drawable, brick preview only', flush=True)
                    continue
                review[p] = dict(archive=arc, flags=[['not built', 'no stock model drawable']], copies=len(idx['creatures'][p]['copies']), img=False)
                continue
            brick = find(bw, bt, p) if bw else None
            a = brick.anim() if brick is not None else None
            pose = (a[0], max(a[1] // 3, 0)) if a else None
            s = stats.get(p, {})
            img = False
            try:
                flags = flags_for(stock, brick, s, pose)
                picture(p, stock, brick, pose).save(os.path.join(img_dir, p + '.jpg'), quality=JPEG_QUALITY)
                img = True
            except Exception as e:
                flags = [['not built', f'drawing failed: {type(e).__name__}: {e}']]
            review[p] = dict(archive=arc, flags=[list(x) for x in flags], copies=len(idx['creatures'][p]['copies']),
                             kind='minifig' if 'minifig' in s else 'bricks', bricks=s.get('bricks'),
                             classes=s.get('classes'), variants=s.get('variants', 1), anim=pose[0] if pose else None, img=img)
            print(f'[{done}/{total}] {p}: ' + ('; '.join(f'{a} ({b})' for a, b in flags) or 'clean'), flush=True)
        json.dump(review, open(rpath, 'w'), indent=1)
    print(f'{sum(1 for r in review.values() if r["flags"])} of {len(review)} flagged -> {rpath}')
