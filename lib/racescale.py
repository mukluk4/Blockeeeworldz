"""Shrink the big player races (Ogre, Troll, Barbarian) to about Human height, so they fit Sol B and dungeons.

The model is shrunk uniformly by a factor k: every bone offset in every animation frame (0x12) and every mesh vertex
(0x36, stored in its bone's space) are multiplied by k, so the skeleton, the animations and the mesh stay together.
The root bone sits at the model origin above the feet, so shrinking alone would lift the feet; every root frame is
moved down by (1 - k) times the feet's depth to keep them on the ground. Hair, beard and helmet attachments hang on
the head's attach points and are shrunk by the same k (their own small skeletons and meshes).

Barbarians shrink by 6/7 (Barbarian 7 / Human 6 default sizes). Trolls and Ogres shrink to the Barbarians' height
(2026-11-11: 6/8 and 6/9 left them well below it, the brick figures on their skeletons were already about Human
height): factor = Barbarian height / the race's unshrunk height, per gender.
"""
import struct

SCALE = {'bam': 6 / 7, 'baf': 6 / 7, 'trm': 0.812, 'trf': 0.814, 'ogm': 0.925, 'ogf': 0.886}


def factor(race):
    """k for a race code like 'ogm' / 'OGF', or None for races that keep their size."""
    return SCALE.get(race[:3].lower())


def scale_track(raw, k, drop=None):
    """A 0x12 track definition with every frame's offset times k. drop: also move every frame down by this much
    (root frames). Frames are 8 int16: rotation w x y z, shift x y z, bone scale.

    The client reads the offset as shift / 256 and the last value as the bone's scale (value / 256): the originals
    scale the shoulder bones up (333) and squash the butt bone (6). An earlier version took it for a divisor and
    raised it to shrink the offsets; in game every bone grew instead, compounding down the skeleton, and the heads of
    the shrunk races came out huge (2026-11-11). So only the shifts change; the scale stays."""
    flags, nframes = struct.unpack_from('<II', raw, 4)
    assert flags & 8, f'track flags {flags:#x}'
    out = bytearray(raw)
    for f in range(nframes):
        at = 12 + 16 * f
        rd, rx, ry, rz, sx, sy, sz, sd = struct.unpack_from('<8h', raw, at)
        t = [c * k for c in (sx, sy, sz)]
        if drop is not None:
            t[2] -= drop * 256
        sx, sy, sz = (max(-32768, min(32767, round(c))) for c in t)
        struct.pack_into('<8h', out, at, rd, rx, ry, rz, sx, sy, sz, sd)
    return bytes(out)


def scale_mesh(raw, k):
    """A 0x36 mesh with its vertices, center and bounds times k (vertices are in their bone's space)."""
    out = bytearray(raw)
    cx, cy, cz = struct.unpack_from('<3f', raw, 24)
    struct.pack_into('<3f', out, 24, cx * k, cy * k, cz * k)
    vals = struct.unpack_from('<7f', raw, 48)  # max distance, min xyz, max xyz
    struct.pack_into('<7f', out, 48, *(v * k for v in vals))
    nv, = struct.unpack_from('<H', raw, 76)
    for v in range(nv):
        at = 96 + 6 * v
        xyz = struct.unpack_from('<3h', raw, at)
        struct.pack_into('<3h', out, at, *(round(c * k) for c in xyz))
    return bytes(out)


def track_refs(w, sid):
    """The 0x12 ids a skeleton's rest tracks use (0x10 -> 0x13 -> 0x12), root first."""
    _t, _name, b = w.frags[sid]
    flags, ntracks, _ref = struct.unpack_from('<IIi', b, 4)
    p = 16 + (12 if flags & 1 else 0) + (4 if flags & 2 else 0)
    out = []
    for _ in range(ntracks):
        _nref, _fl, track, _mesh, nchild = struct.unpack_from('<iIiiI', b, p)
        out.append(struct.unpack_from('<i', w.frags[track][2], 4)[0])
        p += 20 + 4 * nchild
    return out


def scale_race_file(w, frags, prefix, k, foot_z):
    """Shrink a whole race archive (global<race>_chr.s3d or its _chr2 animation file): every track and mesh in it.
    frags: [(type, raw)] for fragments 1.., changed in place. prefix: 'OGM'. foot_z: the feet's height below the
    origin in the unscaled model (negative)."""
    drop = (1 - k) * -foot_z
    root = {f'{prefix}_TRACK'}
    roots = set()
    for i, (t, name, b) in enumerate(w.frags[1:], start=1):
        if t == 0x13 and (name in root or name.endswith(f'_{prefix}_TRACK')):
            roots.add(struct.unpack_from('<i', b, 4)[0])
    for i, (t, raw) in enumerate(frags, start=1):
        if t == 0x12:
            frags[i - 1] = (t, scale_track(raw, k, drop if i in roots else None))
        elif t == 0x36:
            frags[i - 1] = (t, scale_mesh(raw, k))
    return len(roots)


def scale_attachments(w, frags, k_of_mesh):
    """Shrink attachment meshes (hair, beards, helmets) and their own small skeletons. k_of_mesh: {0x36 id: k}."""
    mesh_skel = {}
    for sid, _f in w.of_type(0x10):
        _bones, mids = w.skeleton(sid)
        for mi in mids:
            mesh_skel[mi] = sid
    track_k = {}
    for mi, k in k_of_mesh.items():
        sid = mesh_skel.get(mi)
        if sid is not None:
            for t in track_refs(w, sid):
                assert track_k.get(t, k) == k, f'track {t} shared by races of different size'
                track_k[t] = k
    for i, (t, raw) in enumerate(frags, start=1):
        if t == 0x36 and i in k_of_mesh:
            frags[i - 1] = (t, scale_mesh(raw, k_of_mesh[i]))
        elif t == 0x12 and i in track_k:
            frags[i - 1] = (t, scale_track(raw, track_k[i]))


FOOT_BELOW_JOINT = 3.1 - 2.31  # the minifig sole sits this far below the race's foot joint (minifig.fit)


def ground(w, sid):
    """The minifig's sole height in a race's unscaled model, from its skeleton's left foot joint."""
    prefix = w.frags[sid][1].split('_')[0]
    bones, _m = w.skeleton(sid)
    T = next(T for n, _p, (_R, T) in bones if n == f'{prefix}BOFOOTL_DAG')
    return T[2] - FOOT_BELOW_JOINT


def main():
    """Shrink a race's extra animation archive (global<race>_chr2.s3d) to match its shrunk race file.

        python -I racescale.py <global<race>_chr.s3d original, for the skeleton> <global<race>_chr2.s3d> <out>
    """
    import os, sys
    sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
    import pfs, wld
    race_src, src, dst = sys.argv[1:4]
    rw = wld.Wld(next(b for n, b in pfs.read(race_src) if n.endswith('.wld')))
    (sid, _f), = rw.of_type(0x10)
    prefix = rw.frags[sid][1].split('_')[0]
    k = factor(prefix)
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    frags = [(t, raw) for t, _n, raw in w.frags[1:]]
    nroots = scale_race_file(w, frags, prefix, k, ground(rw, sid))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'characters'))
    import make_s3d
    new = make_s3d.write_wld(wld_data, frags)
    pfs.write(dst, [(n, new if n == wld_name else b) for n, b in files])
    print(f'{prefix} x{k:.3f}: {sum(t == 0x12 for t, _r in frags)} tracks ({nroots} root) -> {dst}')


if __name__ == '__main__':
    main()
