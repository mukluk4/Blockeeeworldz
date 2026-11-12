"""Brick every zone of one continent: the zone file as ground (plates, brick walls, water) and its _obj file as
objects, through brickzone.py. A newer zone kept as one <zone>.eqg (no .s3d) goes through eqgzone.py instead.

    python -I zones/build_continent.py <client folder> <continent> <out folder>

The zones are listed in zones/<continent>/zones.txt (one short name per line). Each archive is read from
<client>/brick_orig/<file>.orig when that exists (the untouched original), else from <client>/<file>.
"""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))


def source(client, name):
    orig = os.path.join(client, 'brick_orig', name + '.orig')
    return orig if os.path.exists(orig) else os.path.join(client, name)


def main():
    client, continent, out = sys.argv[1:4]
    with open(os.path.join(here, continent, 'zones.txt')) as f:
        zones = [z.strip() for z in f if z.strip() and not z.startswith('#')]
    os.makedirs(out, exist_ok=True)
    failed = []
    for z in zones:
        jobs = [(f'{z}.s3d', 'ground'), (f'{z}_obj.s3d', 'objects')]
        if not os.path.exists(source(client, f'{z}.s3d')) and os.path.exists(source(client, f'{z}.eqg')):
            jobs = [(f'{z}.eqg', None)]
        for name, mode in jobs:
            src = source(client, name)
            if not os.path.exists(src):
                print(f'{name}: not in the client, skipped')
                continue
            tool = [os.path.join(here, 'eqgzone.py'), src, os.path.join(out, name)] if mode is None else                 [os.path.join(here, 'brickzone.py'), src, os.path.join(out, name), mode]
            r = subprocess.run([sys.executable, '-I'] + tool, capture_output=True, text=True)
            print(f'{name}: ' + ('ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip().splitlines()[-1]))
            if r.returncode:
                failed.append(name)
    print(f'{continent}: {len(zones)} zones, {len(failed)} failed' + (f': {failed}' if failed else ''))


if __name__ == '__main__':
    main()
