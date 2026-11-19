"""Mob review: build, draw and flag every brick creature so the ones that need a tweak can be found quickly.

    python -I scripts/review.py index  <client folder>      # which stock archive each creature comes from
    python -I scripts/review.py build  <client folder>      # brick every creature into <out>/brick (slow; resumable)
    python -I scripts/review.py render <client folder>      # stock + brick + walking pose per creature, with flags
    python -I scripts/review.py all    <client folder>      # the three in a row

Options: --only BEA,SHA (just these creatures), --out DIR (default output/review), --list FILE (default
characters/creatures.txt).

The client folder is only read (originals from <client>/brick_orig/<archive>.orig when there, else the client copy).
Each creature is built and drawn once, from one stock archive: its own <prefix>_chr.s3d when there is one, else the
archive that holds the most creatures still unplaced. Creatures found only in .eqg files are listed as not drawn.
Results: <out>/index.json, <out>/brick/*.s3d (+ build logs), <out>/review.json and <out>/img/<PREFIX>.jpg.
"""
import argparse, glob, json, os, re, struct, subprocess, sys, time

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'scripts')]
import pfs, wld


def wanted_list(path):
    return [l.split('#')[0].strip() for l in open(path) if l.split('#')[0].strip()]


def source_of(client, name):
    orig = os.path.join(client, 'brick_orig', name + '.orig')
    return orig if os.path.exists(orig) else os.path.join(client, name)


def skeleton_names(path):
    """Model prefixes in an archive, read from the WLD string table only (fast)."""
    out = set()
    for n, b in pfs.read(path):
        if n.lower().endswith('.wld'):
            hs, = struct.unpack_from('<I', b, 20)
            for m in re.finditer(rb'([A-Z0-9]{2,3})_HS_DEF', wld.decode(b[28:28 + hs])):
                out.add(m.group(1).decode())
    return out


# --- index ------------------------------------------------------------------------------------------------------
def index(client, wanted, out):
    t = time.time()
    holders = {}
    for p in sorted(glob.glob(os.path.join(client, '*.s3d'))):
        b = os.path.basename(p)
        if 'chr' not in b.lower():
            continue
        try:
            names = skeleton_names(source_of(client, b))
        except Exception as e:
            print('  skip', b, e)
            continue
        for n in names & set(wanted):
            holders.setdefault(n, []).append(b)
    left = {p for p in wanted if p in holders}
    pick = {}
    for p in sorted(left):  # its own archive first
        own = f'{p.lower()}_chr.s3d'
        if own in holders[p]:
            pick[p] = own
    left -= set(pick)
    while left:  # then the archive covering the most of the rest (fewer builds)
        counts = {}
        for p in left:
            for a in holders[p]:
                counts[a] = counts.get(a, 0) + 1
        best = max(sorted(counts), key=lambda a: (counts[a], a.startswith('global')))
        for p in [p for p in left if best in holders[p]]:
            pick[p] = best
            left.discard(p)
    idx = {'client': client, 'creatures': {p: {'archive': pick.get(p), 'copies': sorted(holders.get(p, []))}
                                           for p in wanted}}
    json.dump(idx, open(os.path.join(out, 'index.json'), 'w'), indent=1)
    missing = [p for p in wanted if p not in holders]
    print(f'{len(pick)} creatures in {len(set(pick.values()))} archives ({time.time() - t:.0f}s); '
          f'{len(missing)} not in any .s3d (eqg or gone): {",".join(missing)}')
    return idx


# --- build ------------------------------------------------------------------------------------------------------
def build(client, idx, out, only=None):
    bdir = os.path.join(out, 'brick')
    os.makedirs(bdir, exist_ok=True)
    tool = os.path.join(_root, 'characters', 'brickcreature.py')
    jobs = {}
    for p, c in idx['creatures'].items():
        if c['archive']:
            jobs.setdefault(c['archive'], []).append(p)
    if only:  # an archive is always rebuilt whole, so its other creatures stay bricked
        jobs = {a: ps for a, ps in jobs.items() if set(ps) & only}
    for k, (arc, prefixes) in enumerate(sorted(jobs.items()), 1):
        dst = os.path.join(bdir, arc)
        log = dst + '.log'
        if not only and os.path.exists(dst) and os.path.exists(log):
            continue  # done in an earlier run
        t = time.time()
        r = subprocess.run([sys.executable, '-I', tool, source_of(client, arc), dst, '-', ','.join(sorted(prefixes))],
                           capture_output=True, text=True)
        open(log, 'w').write(r.stdout + ('\n--- errors ---\n' + r.stderr if r.returncode else ''))
        state = 'ok' if r.returncode == 0 else 'FAILED: ' + (r.stderr.strip().splitlines() or ['?'])[-1]
        print(f'[{k}/{len(jobs)}] {arc} {",".join(sorted(prefixes))}: {state} ({time.time() - t:.0f}s)', flush=True)


def build_stats(out, arc):
    """{prefix: {'bricks', 'size', 'classes', 'variants', 'minifig'}} from a build log."""
    stats = {}
    log = os.path.join(out, 'brick', arc + '.log')
    if not os.path.exists(log):
        return stats
    for line in open(log):
        m = re.match(r'(\w+): (\d+) bricks of ([\d.]+), (\d+) color classes(?:, (\d+) variants)?', line)
        if m:
            stats[m.group(1)] = dict(bricks=int(m.group(2)), size=float(m.group(3)), classes=int(m.group(4)),
                                     variants=int(m.group(5) or 1))
            continue
        m = re.match(r'(\w+): minifig (.*?)(?:, (\d+) variants)?$', line.strip())
        if m:
            stats[m.group(1)] = dict(minifig=m.group(2), variants=int(m.group(3) or 1))
            continue
        m = re.match(r'(\w+): (unreadable mesh.*|no body here.*)', line.strip())
        if m:
            stats[m.group(1)] = dict(problem=m.group(2))
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('index', 'build', 'render', 'all'))
    ap.add_argument('client')
    ap.add_argument('--only')
    ap.add_argument('--out', default=os.path.join(_root, 'output', 'review'))
    ap.add_argument('--list', default=os.path.join(_root, 'characters', 'creatures.txt'))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    only = {s.strip().upper() for s in args.only.split(',')} if args.only else None
    wanted = wanted_list(args.list)
    ipath = os.path.join(args.out, 'index.json')
    if args.mode in ('index', 'all') or not os.path.exists(ipath):
        idx = index(args.client, wanted, args.out)
    else:
        idx = json.load(open(ipath))
    if args.mode in ('build', 'all'):
        build(args.client, idx, args.out, only)
    if args.mode in ('render', 'all'):
        import review_render
        review_render.render_all(args.client, idx, args.out, only)


if __name__ == '__main__':
    main()
