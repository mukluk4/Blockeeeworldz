"""RETIRED 2026-11-11: rebuild the big races with make_s3d.py (and racescale.py for _chr2) instead. This splice
put back the stock hand attach points (losing the minifig weapon grip) and, with --meshes, swapped in body meshes
from an older unshrunk build (Ogre armor pieces showed on the face).

Redo the shrink of the big races' animation tracks in already built archives, in place.

racescale.scale_track used to raise each frame's last value to shrink the offsets; the client reads that value as the
bone's scale, so the shrunk races' bones grew and their heads came out huge. This takes every track (0x12) from the
original archive, shrinks it with the fixed scale_track and puts it into the built archive. Meshes are left alone.

    python -I fix_track_scale.py <brick_orig folder> [--meshes <unshrunk build folder>] <built .s3d> [...]

Each built file is global<race>_chr.s3d or global<race>_chr2.s3d; its original is <brick_orig>/<name>.orig.
With --meshes, the meshes are also redone: taken from the same-named unshrunk build (make_s3d without the shrink,
e.g. output/races) and shrunk by the race's current factor, for when the factor changes.
"""
import os, re, struct, sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters')]
import make_s3d, pfs, racescale, wld


def load(path):
    files = pfs.read(path)
    name = next(n for n, _b in files if n.endswith('.wld'))
    return files, name, dict(files)[name]


def fix(orig_dir, path, mesh_dir=None):
    base = os.path.basename(path)
    race = re.match(r'global(\w{3})_chr2?\.s3d$', base).group(1)
    k = racescale.factor(race)
    assert k, f'{base}: not a shrunk race'
    rw = wld.Wld(load(os.path.join(orig_dir, f'global{race}_chr.s3d.orig'))[2])
    (sid, _f), = rw.of_type(0x10)
    drop = (1 - k) * -racescale.ground(rw, sid)
    prefix = race.upper()

    ow = wld.Wld(load(os.path.join(orig_dir, base + '.orig'))[2])
    roots = set()
    for i, (t, name, b) in enumerate(ow.frags[1:], start=1):
        if t == 0x13 and (name == f'{prefix}_TRACK' or name.endswith(f'_{prefix}_TRACK')):
            roots.add(struct.unpack_from('<i', b, 4)[0])
    orig_tracks = {}  # (name, occurrence): scaled raw
    seen = {}
    for i, (t, name, b) in enumerate(ow.frags[1:], start=1):
        if t == 0x12:
            n = seen[name] = seen.get(name, -1) + 1
            orig_tracks[(name, n)] = racescale.scale_track(b, k, drop if i in roots else None)

    files, wld_name, data = load(path)
    w = wld.Wld(data)
    unshrunk = None
    if mesh_dir and os.path.exists(os.path.join(mesh_dir, base)):
        uw = wld.Wld(load(os.path.join(mesh_dir, base))[2])
        assert len(uw.frags) == len(w.frags), f'{base}: unshrunk build has other fragments'
        unshrunk = uw.frags
    frags, seen, done, meshes = [], {}, 0, 0
    for i, (t, name, raw) in enumerate(w.frags[1:], start=1):
        if t == 0x36 and unshrunk:
            assert unshrunk[i][:2] == (t, name), f'{base}: fragment {i} differs'
            raw, meshes = racescale.scale_mesh(unshrunk[i][2], k), meshes + 1
        if t == 0x12:
            n = seen[name] = seen.get(name, -1) + 1
            new = orig_tracks[(name, n)]
            assert len(new) == len(raw) and new[:12] == raw[:12], f'{base}: {name} differs from the original'
            raw, done = new, done + 1
        frags.append((t, raw))
    assert done == len(orig_tracks), f'{base}: {done} tracks, original has {len(orig_tracks)}'
    new_wld = make_s3d.write_wld(data, frags)
    raw_src = open(path, 'rb').read()
    dir_off = int.from_bytes(raw_src[:4], 'little')
    count = int.from_bytes(raw_src[dir_off:dir_off + 4], 'little')
    pfs.write(path, [(n, new_wld if n == wld_name else b) for n, b in files],
              footer=raw_src[dir_off + 4 + 12 * count:])
    print(f'{base}: {done} tracks, {meshes} meshes, k {k:.3f}, {len(roots)} root tracks lowered {drop:.2f}')


if __name__ == '__main__':
    args = sys.argv[2:]
    mesh_dir = None
    if args[:1] == ['--meshes']:
        mesh_dir, args = args[1], args[2:]
    for p in args:
        fix(sys.argv[1], p, mesh_dir)
