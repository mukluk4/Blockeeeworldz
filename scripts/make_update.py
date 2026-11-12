"""Put only the files that changed since the last transfer into small update folders.

    python -I make_update.py "<Brick Minifigs folder>" [max MB per batch, default 100]

Compares models\\ with sent_manifest.txt (sha1 of each file as last sent), copies new or changed files to
update_<date-time>[_partNofM]\\models (and originals of brand-new files to ...\\originals, for undo), then records
them as sent. Copy each update folder to the other PC and copy its models\\ into the game folder, game closed.
"""
import datetime, hashlib, os, shutil, sys

root = sys.argv[1]
limit = float(sys.argv[2]) * 1e6 if len(sys.argv) > 2 else 100e6
models = os.path.join(root, 'models')
manifest = os.path.join(root, 'sent_manifest.txt')
sent = {}
if os.path.exists(manifest):
    for line in open(manifest, encoding='utf-8'):
        digest, name = line.rstrip('\n').split(None, 1)
        sent[name.lstrip('*')] = digest


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


now = {n: sha1(os.path.join(models, n)) for n in sorted(os.listdir(models))}
changed = [n for n, d in now.items() if sent.get(n) != d]
if not changed:
    sys.exit('Nothing changed since the last transfer.')

batches, cur, cur_size = [], [], 0
for n in changed:  # each folder stays under the limit (a single bigger file gets one of its own)
    sz = os.path.getsize(os.path.join(models, n))
    if cur and cur_size + sz > limit:
        batches.append(cur)
        cur, cur_size = [], 0
    cur.append(n)
    cur_size += sz
batches.append(cur)

stamp = 'update_' + datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
for k, batch in enumerate(batches, 1):
    out = os.path.join(root, stamp + (f'_part{k}of{len(batches)}' if len(batches) > 1 else ''))
    os.makedirs(os.path.join(out, 'models'))
    os.makedirs(os.path.join(out, 'originals'))
    size = 0
    for n in batch:
        shutil.copy2(os.path.join(models, n), os.path.join(out, 'models', n))
        size += os.path.getsize(os.path.join(models, n))
        orig = os.path.join(root, 'originals', n)
        if n not in sent and os.path.exists(orig):  # a file the other PC never had from us: its original too
            shutil.copy2(orig, os.path.join(out, 'originals', n))
    with open(os.path.join(out, 'WHAT CHANGED.txt'), 'w', encoding='utf-8') as f:
        f.write('Copy everything in models\\ into the game folder with the game CLOSED.\n')
        f.write('originals\\ only holds originals of files that are new in this update (for undo).\n')
        if len(batches) > 1:
            f.write(f'This is part {k} of {len(batches)}; the parts can go in any order.\n')
        f.write('\n' + '\n'.join(('NEW      ' if n not in sent else 'CHANGED  ') + n for n in batch) + '\n')
    print(f'{len(batch)} files, {size / 1e6:.0f} MB -> {out}')

with open(manifest, 'w', encoding='utf-8') as f:
    f.writelines(f'{d}  {n}\n' for n, d in now.items())
