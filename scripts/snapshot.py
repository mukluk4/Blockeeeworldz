"""Snapshot tester for model tweaks: render every model in built .s3d archives, compare with the last accepted
renders, and show what changed.

    python -I scripts/snapshot.py check  <archive.s3d or folder>... [--only BEA,SHA] [--store DIR] [--size N]
    python -I scripts/snapshot.py accept <archive.s3d or folder>... [--only BEA,SHA] [--store DIR]
    python -I scripts/snapshot.py show   <archive.s3d or folder>... [--only BEA,SHA] [--store DIR]

check   renders each model (rest pose: front, three-quarter, side) into <store>/new/<archive>/<MODEL>.png and
        compares it with <store>/base/<archive>/<MODEL>.png. Prints changed / new / missing / same, writes
        <store>/report/<archive>_<MODEL>.png (accepted | new | changed pixels in red) for every difference and a
        contact sheet <store>/report/report.png. Exit code 1 when anything differs, so it can gate a build.
accept  renders the same way and makes those renders the new baselines (all, or only the --only prefixes),
        keeping each one's camera framing (<MODEL>.json) so later checks draw from the same place.
show    renders only, into <store>/new, and makes a contact sheet <store>/report/show.png (a quick preview).

The store defaults to output/snapshots (ignored by git: the renders are made from game textures).
The three-quarter view looks down a little so tops (studs, hats, head pieces) show. A model is one skeleton in the archive (BEA_HS_DEF -> BEA). Old-format .s3d only; .eqg models are not drawn.
"""
import argparse, io, json, os, shutil, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, 'lib')]
import pfs, wld

BG = (52, 58, 70)
VIEWS = ((0, 0), (35, 22), (90, 0))  # (turn, look down) degrees: front, three-quarter from above, side
LIGHT = np.array([0.5, 0.7, 0.6]) / np.linalg.norm([0.5, 0.7, 0.6])
DIFF_LEVEL = 24        # a pixel counts as changed when a channel moves more than this
DIFF_SHARE = 0.0005    # a model counts as changed when more than this share of its pixels did


# --- reading ----------------------------------------------------------------------------------------------------
def textures_of(files):
    out = {}
    for n, blob in files.items():
        if n.lower().endswith(('.dds', '.bmp')):
            try:
                im = Image.open(io.BytesIO(blob))
                im.load()
                out[n.rsplit('.', 1)[0].lower()] = np.asarray(im.convert('RGBA'))
            except Exception:
                pass
    return out


def models_of(path, only=None):
    """{MODEL: (triangles Nx3x3 in EQ space, uvs Nx3x2, texture stem per triangle)} for each skeleton."""
    files = dict(pfs.read(path))
    wname = next((n for n in files if n.lower().endswith('.wld')), None)
    if not wname:
        return {}, {}
    w = wld.Wld(files[wname])
    textures = textures_of(files)
    out = {}
    for sid, (_t, name, _b) in w.of_type(0x10):
        model = name.split('_')[0].upper() or f'SKEL{sid}'
        if only and model not in only:
            continue
        try:
            bones, mesh_ids = w.skeleton(sid)
        except Exception as e:
            print(f'  {model}: skeleton not readable ({e})')
            continue
        tris, uvs, texs = [], [], []
        for mid in mesh_ids:
            m = w.mesh(mid)
            pos = []
            for k, v in enumerate(m['verts']):
                b = m['bones'][k] if k < len(m['bones']) else 0
                R, T = bones[b][2] if b < len(bones) else (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0))
                pos.append(wld.add(wld.matvec(R, v), T))
            for a, c, d, mi in m['faces']:
                mname, method, tex = m['materials'][mi] if mi < len(m['materials']) else ('', 0, None)
                if method == 0:
                    continue  # invisible (folded-away parts, boundaries)
                tri = (a, d, c)  # EQ winds the other way round
                tris.append([pos[v] for v in tri])
                uvs.append([m['uvs'][v] if v < len(m['uvs']) else (0, 0) for v in tri])
                texs.append(tex)
        if tris:
            key = model
            n = 2
            while key in out:  # two skeletons with one prefix
                key = f'{model}_{n}'
                n += 1
            out[key] = (np.array(tris, float), np.array(uvs, float), texs)
    return out, textures


# --- drawing ----------------------------------------------------------------------------------------------------
def render(model, textures, size=300, ss=2, frame=None):
    """Three views side by side, z-buffered, texture sampled per pixel, simple plastic shading. frame = (middle,
    span) fixes the camera (the accepted render's), so a tweak shows as a change in place and not as a re-zoom.
    Returns (image, frame)."""
    tris, uvs, texs = model
    S = size * ss
    # EQ (x forward, y left, z up) -> view (x right, y up, z toward the camera): the model faces the camera.
    P = np.stack([tris[..., 1], tris[..., 2], tris[..., 0]], -1)
    if frame:
        mid, span = np.array(frame[0], float), float(frame[1])
    else:
        lo, hi = P.reshape(-1, 3).min(0), P.reshape(-1, 3).max(0)
        mid = (lo + hi) / 2
        span = float(max(hi - lo) * 1.12) or 1.0
    sheet = np.zeros((S, S * len(VIEWS), 3), np.float32) + BG
    tex_ids = sorted({t for t in texs if t})
    tex_index = np.array([tex_ids.index(t) if t in tex_ids else -1 for t in texs])
    for vi, (yaw, pitch) in enumerate(VIEWS):
        a, e = np.radians(yaw), np.radians(pitch)
        R = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]]) @             np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
        Q = (P - mid) @ R.T
        n = np.cross(Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0])
        ln = np.linalg.norm(n, axis=1)
        keep = ln > 1e-12
        n[keep] /= ln[keep, None]
        n[n[:, 2] < 0] *= -1  # two-sided
        shade = 0.45 + 0.55 * np.clip(n @ LIGHT, 0, None) + 0.25 * np.clip(n[:, 2], 0, None) ** 12
        xy = np.empty(Q.shape[:2] + (2,))
        xy[..., 0] = S / 2 + Q[..., 0] / span * S
        xy[..., 1] = S / 2 - Q[..., 1] / span * S
        zbuf = np.full((S, S), -np.inf)
        img = np.zeros((S, S, 3), np.float32) + BG
        for k in np.nonzero(keep)[0]:
            p = xy[k]
            x0, y0 = np.floor(p.min(0)).astype(int)
            x1, y1 = np.ceil(p.max(0)).astype(int)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, S - 1), min(y1, S - 1)
            if x0 > x1 or y0 > y1:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            (ax, ay), (bx, by), (cx, cy) = p
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * Q[k, 0, 2] + w1 * Q[k, 1, 2] + w2 * Q[k, 2, 2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            win = inside & (z > sub)
            if not win.any():
                continue
            sub[win] = z[win]
            ti = tex_index[k]
            if ti >= 0:
                t = textures.get(tex_ids[ti])
            else:
                t = None
            if t is not None:
                u = (w0 * uvs[k, 0, 0] + w1 * uvs[k, 1, 0] + w2 * uvs[k, 2, 0])[win] % 1.0
                v = (w0 * uvs[k, 0, 1] + w1 * uvs[k, 1, 1] + w2 * uvs[k, 2, 1])[win] % 1.0
                th, tw = t.shape[:2]
                col = t[np.minimum((v * th).astype(int), th - 1), np.minimum((u * tw).astype(int), tw - 1), :3]
            else:
                col = np.array([[200, 200, 200]])
            img[y0:y1 + 1, x0:x1 + 1][win] = np.clip(col * shade[k], 0, 255)
        sheet[:, vi * S:(vi + 1) * S] = img
    im = Image.fromarray(sheet.astype(np.uint8))
    im = im.resize((size * len(VIEWS), size), Image.LANCZOS) if ss > 1 else im
    return im, (mid.tolist(), span)


# --- comparing --------------------------------------------------------------------------------------------------
def compare(a_path, b_path):
    a = np.asarray(Image.open(a_path).convert('RGB')).astype(int)
    b = np.asarray(Image.open(b_path).convert('RGB')).astype(int)
    if a.shape != b.shape:
        return 1.0, None
    changed = (np.abs(a - b).max(2) > DIFF_LEVEL)
    return changed.mean(), changed


def diff_sheet(base_path, new_path, changed, title, out):
    a = Image.open(base_path).convert('RGB')
    b = Image.open(new_path).convert('RGB')
    if changed is None:  # sizes differ: show both as they are
        c = Image.new('RGB', b.size, BG)
    else:
        arr = np.asarray(b).astype(float) * 0.35
        arr[changed] = (235, 50, 50)
        c = Image.fromarray(arr.astype(np.uint8))
    W = max(a.width, b.width)
    sheet = Image.new('RGB', (W, a.height + b.height + c.height + 66), (30, 32, 38))
    d = ImageDraw.Draw(sheet)
    y = 0
    for label, im in ((f'{title}  accepted', a), ('new', b), ('changed pixels', c)):
        d.text((6, y + 4), label, fill=(240, 220, 120), font=FONT)
        sheet.paste(im, (0, y + 22))
        y += im.height + 22
    sheet.save(out)


def trim(im, margin=12):
    """Cut the empty background bands above and below the model (previews of long, flat creatures)."""
    a = np.asarray(im).astype(int)
    rows = np.nonzero((np.abs(a - BG).max(2) > 6).any(1))[0]
    if not len(rows):
        return im
    return im.crop((0, max(rows[0] - margin, 0), im.width, min(rows[-1] + margin + 1, im.height)))


def contact(entries, out, cols=2, width=900, crop=False):
    """entries: [(label, image path)] -> one sheet."""
    if not entries:
        return
    thumbs = []
    for label, p in entries:
        im = Image.open(p).convert('RGB')
        if crop:
            im = trim(im)
        im = im.resize((width, max(1, int(im.height * width / im.width))), Image.LANCZOS)
        thumbs.append((label, im))
    rows = [thumbs[i:i + cols] for i in range(0, len(thumbs), cols)]
    H = sum(max(t[1].height for t in r) + 24 for r in rows)
    sheet = Image.new('RGB', (cols * (width + 8), H), (30, 32, 38))
    d = ImageDraw.Draw(sheet)
    y = 0
    for r in rows:
        for i, (label, im) in enumerate(r):
            x = i * (width + 8)
            d.text((x + 6, y + 5), label, fill=(240, 220, 120), font=FONT)
            sheet.paste(im, (x, y + 22))
        y += max(t[1].height for t in r) + 24
    sheet.save(out)


try:
    FONT = ImageFont.truetype('arial.ttf', 14)
except Exception:
    FONT = ImageFont.load_default()


# --- main -------------------------------------------------------------------------------------------------------
def archives(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith('.s3d'))
        else:
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('check', 'accept', 'show'))
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--only', help='model prefixes, comma separated (BEA,SHA)')
    ap.add_argument('--store', default=os.path.join(_root, 'output', 'snapshots'))
    ap.add_argument('--size', type=int, default=300, help='pixels per view (default 300)')
    args = ap.parse_args()
    only = {s.strip().upper() for s in args.only.split(',')} if args.only else None
    base_dir, new_dir, rep_dir = (os.path.join(args.store, d) for d in ('base', 'new', 'report'))
    os.makedirs(rep_dir, exist_ok=True)
    for f in os.listdir(rep_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(rep_dir, f))
    counts = {'same': 0, 'changed': 0, 'new': 0, 'missing': 0}
    report, shown = [], []
    for arc in archives(args.paths):
        stem = os.path.splitext(os.path.basename(arc))[0]
        try:
            models, textures = models_of(arc, only)
        except Exception as e:
            print(f'{stem}: cannot read ({e})')
            continue
        if not models:
            continue
        nd, bd = os.path.join(new_dir, stem), os.path.join(base_dir, stem)
        os.makedirs(nd, exist_ok=True)
        for model in sorted(models):
            new_png = os.path.join(nd, model + '.png')
            base_png = os.path.join(bd, model + '.png')
            frame_json = base_png[:-4] + '.json'  # the accepted camera, reused by check
            frame = None
            if args.mode == 'check' and os.path.exists(frame_json):
                frame = json.load(open(frame_json))
            im, frame = render(models[model], textures, size=args.size, frame=frame)
            im.save(new_png)
            label = f'{stem} {model}'
            if args.mode == 'show':
                shown.append((label, new_png))
                print(f'  rendered {label}')
            elif args.mode == 'accept':
                os.makedirs(bd, exist_ok=True)
                shutil.copyfile(new_png, base_png)
                json.dump(frame, open(frame_json, 'w'))
                print(f'  accepted {label}')
            elif not os.path.exists(base_png):
                counts['new'] += 1
                print(f'  NEW      {label} (no accepted render yet: run accept)')
                report.append((label + '  NEW', new_png))
            else:
                share, changed = compare(base_png, new_png)
                if share > DIFF_SHARE:
                    counts['changed'] += 1
                    out = os.path.join(rep_dir, f'{stem}_{model}.png')
                    diff_sheet(base_png, new_png, changed, label, out)
                    report.append((f'{label}  changed {share:.2%}', out))
                    print(f'  CHANGED  {label}: {share:.2%} of pixels')
                else:
                    counts['same'] += 1
        if args.mode == 'check' and os.path.isdir(bd) and not only:
            for f in sorted(os.listdir(bd)):
                if f.endswith('.png') and f[:-4] not in models and not f.endswith('.json'):
                    counts['missing'] += 1
                    print(f'  MISSING  {stem} {f[:-4]} (accepted before, not in the archive now)')
    if args.mode == 'show':
        contact(shown, os.path.join(rep_dir, 'show.png'), cols=1, width=max(900, 3 * args.size), crop=True)
        print(f'{len(shown)} models -> {os.path.join(rep_dir, "show.png")}')
        return 0
    if args.mode == 'accept':
        return 0
    contact(report, os.path.join(rep_dir, 'report.png'), cols=1)
    print(', '.join(f'{v} {k}' for k, v in counts.items()))
    if report:
        print('report:', os.path.join(rep_dir, 'report.png'))
    return 1 if counts['changed'] or counts['new'] or counts['missing'] else 0


if __name__ == '__main__':
    sys.exit(main())
