"""Repaint the armor set archives (global17_amr.s3d .. global23_amr.s3d) for the brick minifigs.

The client shows armor set VV on a race by swapping the race's chest/leg texture for <race><slot><VV><NN>. For the
minifigs, the chest texture is the whole top-half atlas and the legs texture the bottom-half atlas, so every
<race>ch<VV>NN in these archives becomes that race's chest atlas for set VV, every <race>lg<VV>NN its legs atlas.
The atlases come from make_s3d.py (<races dir>/global<race>_chr_armor/<race>_<slot><VV>.png). Other textures
(arms, hands, feet, head) are unused by the minifig mesh and stay as they are.

usage: make_armor_sets.py <client dir> <races dir> <out dir>
Reads each archive from <client>/brick_orig/<file>.orig when that exists, else from <client>/<file>.
"""
import glob
import io
import os
import re
import sys

from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]

import pfs  # noqa: E402

ARMOR_FILES = [f'global{n}_amr.s3d' for n in range(17, 24)]
TEX = re.compile(r'^([a-z]{3})(ch|lg)(\d\d)\d\d\.(bmp|dds)$')


def bmp8(img):
    """An 8-bit palettized BMP, the format these archives use."""
    buf = io.BytesIO()
    img.convert('RGB').quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(buf, 'BMP')
    return buf.getvalue()


def main():
    client, races, out = sys.argv[1:4]
    atlases = {}
    for f in glob.glob(os.path.join(races, '*_armor', '*.png')):
        m = re.match(r'^([a-z]{3})_(ch|lg)(\d\d)\.png$', os.path.basename(f))
        if m:
            atlases[m.group(1), m.group(2), int(m.group(3))] = f
    os.makedirs(out, exist_ok=True)
    cache = {}
    for name in ARMOR_FILES:
        src = os.path.join(client, 'brick_orig', name + '.orig')
        if not os.path.exists(src):
            src = os.path.join(client, name)
        files, changed, missing = [], 0, set()
        for n, b in pfs.read(src):
            m = TEX.match(n.lower())
            if m:
                key = (m.group(1), m.group(2), int(m.group(3)))
                if key in atlases:
                    if key not in cache:
                        cache[key] = bmp8(Image.open(atlases[key]))
                    b = cache[key]
                    changed += 1
                else:
                    missing.add(key)
            files.append((n, b))
        pfs.write(os.path.join(out, name), files)
        print(f'{name}: {changed} textures repainted' + (f'; no atlas for {sorted(missing)}' if missing else ''))


if __name__ == '__main__':
    main()
