"""Restyle an EQ character archive's textures as toy-brick plastic, and repack it.

    python -I brickify.py <in.s3d> <out.s3d> <preview.png>
"""
import io, os, re, struct, sys
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import pfs

# Brick-plastic colors (generic toy palette)
PALETTE = np.array([
    (27, 42, 52), (5, 19, 29),          # black-ish
    (99, 95, 98), (160, 165, 169),      # dark / light bluish grey
    (244, 244, 244),                    # white
    (201, 26, 9), (114, 14, 15),        # red, dark red
    (0, 85, 191), (10, 52, 99),         # blue, dark blue
    (35, 120, 65),                      # green
    (88, 42, 18), (149, 138, 115),      # reddish brown, dark tan
    (228, 205, 158), (170, 127, 46),    # tan, pearl gold
    (242, 205, 55), (254, 138, 24),     # yellow, orange
], dtype=np.float32)
SKIN = np.array((242, 205, 55), dtype=np.float32)  # minifig yellow


def is_skin(name):
    # Mouth (07) and teeth (08) keep their own colors
    return bool(re.search(r'sk\d', name)) and not re.search(r'hesk0[78]$', name[:-4])


def is_face(name):
    return bool(re.search(r'hesk\d1$', name[:-4]))


def plastic(rgb, k=4):
    """Cut the texture into k big regions, each one brick color, brighter than the original."""
    img = Image.fromarray(rgb.astype(np.uint8))
    for _ in range(3):
        img = img.filter(ImageFilter.MedianFilter(7))
    a = np.asarray(img, dtype=np.float32).reshape(-1, 3)
    # k-means from evenly spread starting colors (sorted by brightness)
    order = np.argsort(a.mean(1))
    centers = a[order[np.linspace(0, len(a) - 1, k).astype(int)]].copy()
    for _ in range(12):
        lab = ((a[:, None] - centers[None]) ** 2).sum(-1).argmin(1)
        for i in range(k):
            if (lab == i).any():
                centers[i] = a[lab == i].mean(0)
    # Brighten and saturate each region's color before choosing its brick color: EQ leather and iron are
    # dark, toy plastic is not
    grey = centers.mean(1, keepdims=True)
    lifted = np.clip((grey + (centers - grey) * 1.4) * 1.35 + 20, 0, 255)
    pick = ((lifted[:, None] - PALETTE[None]) ** 2).sum(-1).argmin(1)
    h, w = rgb.shape[:2]
    return PALETTE[pick][lab].reshape(h, w, 3)


def outline(flat):
    img = Image.fromarray(flat.astype(np.uint8)).convert('L')
    edges = np.asarray(img.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    return edges > 18


def sheen(h, w):
    y = np.linspace(-1, 1, h)[:, None]
    x = np.linspace(-1, 1, w)[None, :]
    # A broad highlight toward the top left, as on molded plastic
    return 1.0 + 0.12 * np.exp(-((x + 0.35) ** 2 + (y + 0.35) ** 2) / 0.35) - 0.06 * (y > 0.6)


def restyle(name, im):
    rgba = np.asarray(im.convert('RGBA'), dtype=np.float32)
    rgb, alpha = rgba[:, :, :3], rgba[:, :, 3:]
    h, w = rgb.shape[:2]
    if name.startswith('chr_eye'):
        lum = rgb.mean(axis=2, keepdims=True)
        out = np.where(lum < 120, 10.0, 245.0) * np.ones(3)  # black dot eye
    elif is_skin(name):
        lum = rgb.mean(axis=2)
        smooth = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32)
        base = np.median(smooth)
        # Features (brows, beard, mouth, nostrils) on the face are much darker than the skin around them: draw
        # them flat black. Body skin is plain plastic, so its shading goes
        feature = (smooth < base * 0.55) if is_face(name) else np.zeros_like(smooth, dtype=bool)
        out = np.where(feature[:, :, None], np.array((20, 20, 20), np.float32), SKIN)
    else:
        out = plastic(rgb)
        if min(h, w) >= 32:
            out = np.where(outline(out)[:, :, None], out * 0.55, out)
    if min(h, w) >= 32:
        out = out * sheen(h, w)[:, :, None]
    out = np.clip(out, 0, 255)
    return Image.fromarray(np.concatenate([out, alpha], axis=2).astype(np.uint8), 'RGBA')


def dds_rgba(im):
    """Uncompressed 32-bit DDS (A8R8G8B8), no mipmaps, as the client reads."""
    w, h = im.size
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x8  # caps, height, width, pixelformat, pitch
    pf = struct.pack('<II4sIIIII', 32, 0x41, b'\0\0\0\0', 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header = struct.pack('<4sIIIIIII', b'DDS ', 124, flags, h, w, w * 4, 0, 0) + b'\0' * 44 + pf + \
        struct.pack('<IIIII', 0x1000, 0, 0, 0, 0)
    r, g, b, a = im.split()
    return header + Image.merge('RGBA', (b, g, r, a)).tobytes()


def main():
    src, dst, preview = sys.argv[1:4]
    files = pfs.read(src)
    out, pairs = [], []
    for name, blob in files:
        if name.endswith('.dds'):
            im = Image.open(io.BytesIO(blob))
            im.load()
            new = restyle(name, im)
            out.append((name, dds_rgba(new)))
            pairs.append((name, im.convert('RGBA'), new))
        else:
            out.append((name, blob))
    pfs.write(dst, out)

    show = [p for p in pairs if p[1].width >= 64]
    cols, cell = 6, 120
    rows = (len(show) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cell * 2 + cols * 6, rows * (cell + 14)), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    for i, (n, a, b) in enumerate(show):
        x, y = (i % cols) * (cell * 2 + 6), (i // cols) * (cell + 14)
        sheet.paste(a.convert('RGB').resize((cell - 2, cell - 2)), (x, y))
        sheet.paste(b.convert('RGB').resize((cell - 2, cell - 2)), (x + cell, y))
        d.text((x + 2, y + cell - 2), n, fill=(255, 255, 0))
    sheet.save(preview)
    print(f'{len(pairs)} textures restyled -> {dst}')


if __name__ == '__main__':
    main()
