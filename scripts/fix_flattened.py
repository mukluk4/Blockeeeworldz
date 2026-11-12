"""Finish hiding meshes that an older flatten_mesh only half hid, in place, in every .s3d of a folder.

The old flatten_mesh moved every vertex to its bone's origin but kept the triangles. A mesh rigged to several bones
(NPC head variants, the Froglok's helms and shoulders) then drew thin triangles stretched between its joints. This
finds meshes whose vertices are all zero and points every triangle at one vertex (make_s3d.flatten_mesh as it is now).
Files with nothing to fix are left untouched.

    python -I fix_flattened.py <folder> [<folder> ...]
"""
import glob, os, struct, sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters')]
import make_s3d, pfs, wld


def collapsed(raw):
    nv, = struct.unpack_from('<H', raw, 76)
    return nv > 0 and not any(raw[96:96 + 6 * nv])


def fix_file(path):
    files = pfs.read(path)
    wld_name = next((n for n, _b in files if n.endswith('.wld')), None)
    if wld_name is None:
        return 0
    data = dict(files)[wld_name]
    w = wld.Wld(data)
    frags, fixed = [], 0
    for t, _name, raw in w.frags[1:]:
        if t == 0x36 and collapsed(raw):
            new = make_s3d.flatten_mesh(raw)
            if new != raw:
                fixed += 1
                raw = new
        frags.append((t, raw))
    if fixed:
        new_wld = make_s3d.write_wld(data, frags)
        raw_src = open(path, 'rb').read()
        dir_off = int.from_bytes(raw_src[:4], 'little')
        count = int.from_bytes(raw_src[dir_off:dir_off + 4], 'little')
        pfs.write(path, [(n, new_wld if n == wld_name else b) for n, b in files],
                  footer=raw_src[dir_off + 4 + 12 * count:])
    return fixed


def main():
    total = 0
    for folder in sys.argv[1:]:
        for path in sorted(glob.glob(os.path.join(folder, '*.s3d'))):
            try:
                n = fix_file(path)
            except Exception as e:  # an archive this reader can't parse: leave it as it is
                print(f'{os.path.basename(path)}: skipped ({type(e).__name__})')
                continue
            if n:
                print(f'{os.path.basename(path)}: {n} meshes')
                total += n
    print(f'{total} meshes fixed')


if __name__ == '__main__':
    main()
