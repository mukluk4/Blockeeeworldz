"""Fold away the classic (pre-Luclin) body and head meshes of some races in global_chr.s3d.

The client draws the classic model in the same spot as the minifig, and where the classic model is bigger it
pokes through (the Ogre's belly). Each mesh keeps its layout but every vertex goes to its center, so it draws nothing.

    python -I hide_classic.py <original global_chr.s3d> <out.s3d> OGM OGF ...
"""
import os, re, sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import make_s3d, pfs, wld


def main():
    src, dst, prefixes = sys.argv[1], sys.argv[2], [p.upper() for p in sys.argv[3:]]
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    pattern = re.compile(r'^(%s)(\d\d|HE\d\d)?_DMSPRITEDEF$' % '|'.join(prefixes))
    frags, hidden = [], []
    for i, (ftype, name, raw) in enumerate(w.frags[1:], start=1):
        if ftype == 0x36 and pattern.match(name):
            raw = make_s3d.flatten_mesh(raw)
            hidden.append(name)
        frags.append((ftype, raw))
    new_wld = make_s3d.write_wld(wld_data, frags)
    pfs.write(dst, [(n, new_wld if n == wld_name else b) for n, b in files])
    print(f'hid {len(hidden)} meshes: {", ".join(sorted(hidden))} -> {dst}')


if __name__ == '__main__':
    main()
