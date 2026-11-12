"""Restyle a classic zone's textures as toy-brick plastic, keeping every texture's name, size, format and cut-outs.

- Ground (the zone file): built of plates. Each texture is snapped to a grid of 1x1 plates (8 per side), each
  plate one brick color picked from the original, with a stud on top: tiled over the terrain it reads as baseplates.
  Walls and cliffs (names with 'wall') get staggered bricks with seams instead of studs. Water (w1-w4 style names
  and 'water') becomes smooth translucent-looking blue tiles.
- Objects (the _obj file): flat brick colors in a few big regions, with a faint seam grid, cut-outs kept.

Formats: 8-bit paletted BMP stays paletted (index 0, the cut-out color, is kept where it was); DDS (DXT1/DXT5)
stays DDS of the same kind.

    python -I brickzone.py <in.s3d> <out.s3d> [ground|objects] [preview.png]
"""
import io, os, re, struct, sys
import numpy as np
from PIL import Image, ImageFilter

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import make_s3d, pfs

# Brick plastic colors
PALETTE = np.array([
    (27, 42, 52),     # black
    (99, 95, 98),     # dark bluish grey
    (160, 165, 169),  # light bluish grey
    (244, 244, 244),  # white
    (201, 26, 9),     # red
    (114, 14, 15),    # dark red
    (0, 85, 191),     # blue
    (90, 147, 219),   # medium blue
    (10, 52, 99),     # dark blue
    (35, 120, 65),    # green
    (24, 70, 50),     # dark green
    (75, 151, 74),    # bright green
    (165, 189, 80),   # lime-ish olive
    (88, 42, 18),     # reddish brown
    (53, 33, 0),      # dark brown
    (149, 138, 115),  # dark tan
    (228, 205, 158),  # tan
    (170, 127, 46),   # pearl gold
    (242, 205, 55),   # yellow
    (254, 138, 24),   # orange
    (160, 110, 60),   # medium nougat
    (104, 116, 79),   # olive green
], dtype=np.float32)
GRID = 8  # plates per texture side


def nearest(colors):
    """Nearest brick color for each RGB row (perceptually weighted)."""
    w = np.array([0.3, 0.59, 0.11], np.float32) * 3
    d = (((colors[:, None, :] - PALETTE[None, :, :]) ** 2) * w).sum(-1)
    return PALETTE[d.argmin(1)]


def boost(rgb):
    """Toy plastic is cleaner and brighter than the game's painted textures: lift and saturate before snapping."""
    a = rgb.astype(np.float32)
    grey = a.mean(-1, keepdims=True)
    a = grey + (a - grey) * 1.5
    return np.clip(a * 1.15 + 10, 0, 255)


TERRAIN = {'bright green': (75, 151, 74), 'green': (35, 120, 65), 'dark green': (24, 70, 50),
           'tan': (228, 205, 158), 'dark tan': (149, 138, 115), 'nougat': (160, 110, 60),
           'reddish brown': (88, 42, 18), 'light grey': (160, 165, 169), 'dark grey': (99, 95, 98),
           'blue': (0, 85, 191), 'red': (201, 26, 9), 'black': (27, 42, 52)}


def terrain_color(rgb):
    """A ground color by kind: grass green, dirt and sand tan or brown, rock grey, water blue."""
    r, g, b = (float(c) / 255 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    v, s = mx, (mx - mn) / (mx or 1)
    if mx == mn:
        h = 0.0
    elif mx == r:
        h = (60 * (g - b) / (mx - mn)) % 360
    elif mx == g:
        h = 60 * (b - r) / (mx - mn) + 120
    else:
        h = 60 * (r - g) / (mx - mn) + 240
    if v < 0.16:
        return TERRAIN['black']
    if s < 0.16:
        return TERRAIN['light grey'] if v > 0.5 else TERRAIN['dark grey']
    if 58 <= h < 170:
        return TERRAIN['bright green'] if v > 0.5 else TERRAIN['green'] if v > 0.3 else TERRAIN['dark green']
    if 170 <= h < 260:
        return TERRAIN['blue']
    if 22 <= h < 58:
        return TERRAIN['tan'] if v > 0.62 else TERRAIN['dark tan'] if v > 0.42 else TERRAIN['reddish brown']
    return TERRAIN['red'] if s > 0.6 and v > 0.5 else TERRAIN['nougat'] if v > 0.4 else TERRAIN['reddish brown']


def mode_filter(cells):
    """Each plate takes the most common color among itself and its 8 neighbours (wrapping: the texture tiles)."""
    n = cells.shape[0]
    keys = cells[..., 0] * 65536 + cells[..., 1] * 256 + cells[..., 2]
    out = cells.copy()
    for y in range(n):
        for x in range(n):
            around = [keys[(y + dy) % n, (x + dx) % n] for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
            vals, counts = np.unique(around, return_counts=True)
            best = vals[counts.argmax()]
            if counts.max() >= 4 and best != keys[y, x]:
                out[y, x] = (best // 65536, best // 256 % 256, best % 256)
    return out


def shade(img, cells, studs=True, bricks=False):
    """Draw plate edges and studs (or brick seams) over a grid-snapped RGB float image."""
    h, w = img.shape[:2]
    ch, cw = h / cells, w / cells
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    out = img.copy()
    if bricks:
        row = (yy // (ch / 1)).astype(int)
        bw = cw * 2  # a brick is two plates long, rows offset by one plate
        off = (row % 2) * cw
        fx = ((xx + off) % bw) / bw
        fy = (yy % ch) / ch
        seam = (fx < 0.04) | (fy < 0.08)
        out[seam] *= 0.62
        top = (fy >= 0.08) & (fy < 0.16)
        out[top] = np.minimum(out[top] * 1.18, 255)
        return out
    fx, fy = (xx % cw) / cw, (yy % ch) / ch
    edge = (fx < 0.05) | (fy < 0.05)
    out[edge] *= 0.8
    if studs:
        dx, dy = fx - 0.5, fy - 0.5
        r = np.sqrt(dx * dx + dy * dy)
        stud = r < 0.3
        out[stud] = np.minimum(out[stud] * 1.08, 255)
        rim = (r >= 0.3) & (r < 0.36) & (dx + dy > 0)  # shadow on the lower right
        out[rim] *= 0.7
        hi = (r >= 0.2) & (r < 0.29) & (dx + dy < -0.1)  # highlight on the upper left
        out[hi] = np.minimum(out[hi] * 1.3 + 20, 255)
    return out


def ground(rgb, name):
    """Plates: the texture snapped to a GRID x GRID mosaic of brick colors, then studs or bricks or water tiles."""
    h, w = rgb.shape[:2]
    water = bool(re.match(r'^w\d', name)) or 'water' in name
    small = Image.fromarray(rgb.astype(np.uint8)).resize((GRID, GRID), Image.BOX)
    cells = np.array([terrain_color(c) for c in np.asarray(small).reshape(-1, 3)], np.int64).reshape(GRID, GRID, 3)
    cells = mode_filter(cells).astype(np.float32)
    if water:
        cells[:] = PALETTE[7] if cells.mean() > 90 else PALETTE[6]
    big = np.asarray(Image.fromarray(cells.astype(np.uint8)).resize((w, h), Image.NEAREST), np.float32)
    if water:
        return shade(big, GRID // 2, studs=False)
    return shade(big, GRID, studs=True, bricks='wall' in name)


def objects(rgb, name):
    """Flat plastic regions: smooth the texture into a few colors, snap each to a brick color, faint seam grid."""
    img = Image.fromarray(rgb.astype(np.uint8))
    for _ in range(3):
        img = img.filter(ImageFilter.MedianFilter(7))
    a = np.asarray(img, np.float32)
    q = Image.fromarray(a.astype(np.uint8)).quantize(4, method=Image.Quantize.MEDIANCUT)
    pal = np.array((q.getpalette() + [0] * 12)[:12], np.float32).reshape(4, 3)  # a flat texture has fewer colors
    snapped = np.array([terrain_color(c) for c in boost(pal) * 1.1], np.float32)
    out = snapped[np.asarray(q)]
    h, w = out.shape[:2]
    return shade(out, max(2, min(h, w) // 32), studs=False)


def dds_dxt5(rgba):
    """DXT5 (BC3): alpha in 8 levels between the block's extremes, color as DXT1."""
    a = np.asarray(rgba, np.float32)
    h, w = a.shape[:2]
    blocks = a.reshape(h // 4, 4, w // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4)
    al = blocks[:, :, 3]
    a0, a1 = al.max(1), al.min(1)
    same = a0 == a1
    a1 = np.where(same & (a0 > 0), a0 - 1, a1)
    a0 = np.where(same & (a0 == 0), 1, a0)
    levels = np.stack([a0, a1] + [((7 - k) * a0 + (k - 1) * a1) / 6 for k in range(2, 8)], 1)  # 8-level mode
    aidx = np.abs(al[:, :, None] - levels[:, None, :]).argmin(-1).astype(np.uint64)
    abits = (aidx << (3 * np.arange(16, dtype=np.uint64))).sum(1)
    color = make_s3d.dds_dxt1(Image.fromarray(a[..., :3].astype(np.uint8)))[128:]
    cblocks = np.frombuffer(color, np.uint8).reshape(-1, 8)
    body = bytearray()
    for k in range(len(blocks)):
        body += bytes([int(a0[k]), int(a1[k])]) + int(abits[k]).to_bytes(6, 'little') + cblocks[k].tobytes()
    pf = struct.pack('<II4sIIIII', 32, 0x4, b'DXT5', 0, 0, 0, 0, 0)
    header = struct.pack('<4sIIIIIII', b'DDS ', 124, 0x81007, h, w, w * h, 0, 0) + bytes(44) + pf + \
        struct.pack('<IIIII', 0x1000, 0, 0, 0, 0)
    return header + bytes(body)


def restyle(name, data, mode):
    im = Image.open(io.BytesIO(data))
    style = ground if mode == 'ground' else objects
    if data[:3] == b'DDS':
        rgba = np.asarray(im.convert('RGBA'))
        new = style(rgba[..., :3].astype(np.float32), name)
        kind = data[84:88]
        if kind == b'DXT5':
            out = np.dstack([np.clip(new, 0, 255), rgba[..., 3]]).astype(np.uint8)
            dds, img = dds_dxt5(out), Image.fromarray(out, 'RGBA')
        else:
            img = Image.fromarray(np.clip(new, 0, 255).astype(np.uint8))
            dds = make_s3d.dds_dxt1(img)
        # Keep the original header byte for byte (flags, pitch, mip fields); only the block data changes. A few files
        # carry extra bytes after the image (rung.bmp in lfaydark_obj: twice its size); those are kept as they were.
        assert len(dds) <= len(data), (name, len(dds), len(data))
        return data[:128] + dds[128:] + data[len(dds):], img
    # Paletted BMP: index 0 (the cut-out color in masked textures) stays where it was
    assert im.mode == 'P', (name, im.mode)
    idx = np.asarray(im)
    rgb = np.asarray(im.convert('RGB'), np.float32)
    new = np.clip(style(rgb, name), 0, 255).astype(np.uint8)
    # Same header, palette size and file length as the original; only palette entries 1.. and pixels change
    off = int.from_bytes(data[10:14], 'little')
    hsize = int.from_bytes(data[14:18], 'little')
    ncol = (off - 14 - hsize) // 4
    w, h = im.size
    q = Image.fromarray(new).quantize(ncol - 1, method=Image.Quantize.MEDIANCUT)
    qi = np.asarray(q).astype(np.uint8) + 1  # indexes 1..ncol-1
    qi[idx == 0] = 0
    qp = q.getpalette()[:(ncol - 1) * 3]
    qp += [0] * ((ncol - 1) * 3 - len(qp))
    pal = bytearray(data[14 + hsize:14 + hsize + 4])  # entry 0 as it was (BGRx)
    for k in range(ncol - 1):
        r, g, b = qp[3 * k:3 * k + 3]
        pal += bytes((b, g, r, 0))
    stride = (w + 3) // 4 * 4
    rows = b''.join(qi[y].tobytes() + b'\0' * (stride - w) for y in range(h - 1, -1, -1))
    out = data[:14 + hsize] + bytes(pal) + rows
    out += data[len(out):]  # any trailing bytes the original had
    assert len(out) == len(data), (name, len(out), len(data))
    img = Image.open(io.BytesIO(out))
    img.load()
    return out, img.convert('RGB')


def main():
    src, dst = sys.argv[1:3]
    mode = sys.argv[3] if len(sys.argv) > 3 else ('objects' if '_obj' in src else 'ground')
    preview = sys.argv[4] if len(sys.argv) > 4 else None
    files = pfs.read(src)
    out, shown = [], []
    for n, b in files:
        if n.endswith('.bmp') and n != 'palette.bmp' and not n.startswith('fire'):
            b, img = restyle(n, b, mode)
            shown.append(img.convert('RGB').resize((96, 96)))
        out.append((n, b))
    raw = open(src, 'rb').read()
    dir_off = int.from_bytes(raw[:4], 'little')
    count = int.from_bytes(raw[dir_off:dir_off + 4], 'little')
    pfs.write(dst, out, footer=raw[dir_off + 4 + 12 * count:])  # the original's footer (or none), as it was
    if preview and shown:
        cols = 10
        sheet = Image.new('RGB', (96 * cols, 96 * ((len(shown) + cols - 1) // cols)), (40, 40, 40))
        for k, im in enumerate(shown):
            sheet.paste(im, ((k % cols) * 96, (k // cols) * 96))
        sheet.save(preview)
    print(f'{len(shown)} textures restyled ({mode}) -> {dst}')


if __name__ == '__main__':
    main()
