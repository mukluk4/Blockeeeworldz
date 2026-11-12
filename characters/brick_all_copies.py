"""Rebuild every copy of the given creatures in every character archive of the client (zone _chr files and globals),
so it doesn't matter which file the game loads a creature from. Originals are backed up to brick_orig first.

    python -I brick_all_copies.py <client folder> <out folder> BEA,ORC,... [only files with: CPT,DRV,...]

The optional last list rebuilds only the archives holding one of those creatures (still with every wanted creature
in them), to add new types without redoing every file.
"""
import glob, os, shutil, subprocess, sys
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import pfs, wld

client, out, wanted = sys.argv[1], sys.argv[2], sys.argv[3]
if wanted.startswith('@'):  # @characters/creatures.txt: the full list, one prefix per line
    wanted = ','.join(l.split('#')[0].strip() for l in open(wanted[1:]) if l.split('#')[0].strip())
wanted = set(wanted.split(','))
touching = set(sys.argv[4].split(',')) if len(sys.argv) > 4 else None
tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'brickcreature.py')
for p in sorted(glob.glob(os.path.join(client, '*.s3d'))):
    b = os.path.basename(p)
    if 'chr' not in b.lower():
        continue
    orig = os.path.join(client, 'brick_orig', b + '.orig')
    src = orig if os.path.exists(orig) else p
    try:
        files = pfs.read(src)
        hits = set()
        for n, d in files:
            if n.endswith('.wld'):
                w = wld.Wld(d)
                hits |= {w.frags[i][1].split('_')[0] for i, _f in w.of_type(0x10)} & wanted
    except BaseException as e:
        print('SKIP', b, e)
        continue
    if not hits or (touching and not hits & touching):
        continue
    if not os.path.exists(orig):
        shutil.copy2(p, orig)
    r = subprocess.run([sys.executable, '-I', tool, orig, os.path.join(out, b), '-', ','.join(sorted(hits))],
                       capture_output=True, text=True)
    status = 'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip().splitlines()[-1]
    print(b, sorted(hits), status, flush=True)
