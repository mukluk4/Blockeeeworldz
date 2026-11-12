"""Restyle a newer (.eqg) zone's textures as toy-brick plastic, like brickzone.py does for .s3d zones.

An .eqg zone keeps its terrain and its objects in one archive. Textures the terrain file (.ter) names are restyled
as ground (plates with studs), every other color texture as objects (flat brick regions). Normal maps and the other
helper maps (names ending _n, _b, _e and the like) are left alone: only color textures (_c or no suffix) change.

Every texture keeps its name, size, format, mip levels and alpha: DXT1 (with or without cut-outs), DXT3, DXT5 and
uncompressed 24/32-bit DDS. Each mip level is rebuilt from the restyled image.

    python -I eqgzone.py <in.eqg> <out.eqg> [preview.png]
"""
import io, os, re, struct, sys
import numpy as np
from PIL import Image

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import brickzone, make_s3d, pfs

# Textures a zone keeps as they were, by the user's call: The Void A's starfield walls keep their space look.
KEEP = {'thevoida': {'stars_02.dds'}}
HELPER = re.compile(r'_([a-bd-z])(_\d+)?\.dds$')  # _n normal, _b, _e ... : not color


def pad4(a):
    """Pad an image array to whole 4x4 blocks by repeating its edge."""
    h, w = a.shape[:2]
    H, W = max(4, (h + 3) // 4 * 4), max(4, (w + 3) // 4 * 4)
    return np.pad(a, ((0, H - h), (0, W - w), (0, 0)), mode='edge')


def dxt1(rgba, cutout):
    """DXT1 blocks. With cutout, blocks holding transparent pixels use three-color mode (index 3 = clear)."""
    a = pad4(rgba).astype(np.float32)
    H, W = a.shape[:2]
    data = np.frombuffer(make_s3d.dds_dxt1(Image.fromarray(a[..., :3].astype(np.uint8)))[128:], '<u4').reshape(-1, 2).copy()
    if not cutout:
        return data.tobytes()
    blocks = a.reshape(H // 4, 4, W // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4)
    clear = blocks[:, :, 3] < 128
    for k in np.nonzero(clear.any(1))[0]:
        px = blocks[k, :, :3]
        solid = px[~clear[k]]
        if len(solid) == 0:
            data[k] = (0, 0xFFFFFFFF)
            continue
        lum = solid @ np.array([0.299, 0.587, 0.114], np.float32)

        def to565(c):
            c = np.clip(np.round(c), 0, 255).astype(np.uint32)
            return int(((c[0] >> 3) << 11) | ((c[1] >> 2) << 5) | (c[2] >> 3))

        c0, c1 = sorted((to565(solid[lum.argmin()]), to565(solid[lum.argmax()])))  # c0 <= c1: three-color mode
        f = lambda v: np.array([((v >> 11) & 31) * 255 / 31, ((v >> 5) & 63) * 255 / 63, (v & 31) * 255 / 31])
        pal = np.stack([f(c0), f(c1), (f(c0) + f(c1)) / 2])
        idx = ((px[:, None, :] - pal[None]) ** 2).sum(-1).argmin(1).astype(np.uint32)
        idx[clear[k]] = 3
        data[k] = (c0 | (c1 << 16), int((idx << (2 * np.arange(16, dtype=np.uint32))).sum()))
    return data.astype('<u4').tobytes()


def dxt5(rgba):
    return brickzone.dds_dxt5(pad4(rgba).astype(np.uint8))[128:]


def dxt3(rgba):
    a = pad4(rgba)
    H, W = a.shape[:2]
    color = np.frombuffer(make_s3d.dds_dxt1(Image.fromarray(a[..., :3].astype(np.uint8)))[128:], np.uint8).reshape(-1, 8)
    al = a[..., 3].astype(np.uint32).reshape(H // 4, 4, W // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16) >> 4
    abits = (al.astype(np.uint64) << (4 * np.arange(16, dtype=np.uint64))).sum(1)
    out = bytearray()
    for k in range(len(color)):
        out += int(abits[k]).to_bytes(8, 'little') + color[k].tobytes()
    return bytes(out)


def raw(rgba, bits, masks):
    """Uncompressed pixels laid out by the header's channel masks."""
    a = rgba.astype(np.uint32)
    px = np.zeros(a.shape[:2], np.uint32)
    for ch, m in enumerate(masks):
        if m:
            shift = (m & -m).bit_length() - 1
            width = bin(m).count('1')
            px |= ((a[..., ch] >> (8 - width)) << shift) & m if width <= 8 else (a[..., ch] << shift) & m
    if bits == 32:
        return px.astype('<u4').tobytes()
    if bits == 24:
        return px.astype('<u4').view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    raise ValueError(f'{bits}-bit pixels')


def restyle_dds(name, data, mode):
    """The DDS with its color restyled: same header, same format, every mip level rebuilt. None if not handled."""
    h, w, _pitch, _depth, mips = struct.unpack_from('<5I', data, 12)
    flags = struct.unpack_from('<I', data, 8)[0]
    pf_flags, cc, bits = struct.unpack_from('<I4sI', data, 80)
    masks = struct.unpack_from('<4I', data, 92)
    levels = mips if flags & 0x20000 and mips else 1
    try:
        im = Image.open(io.BytesIO(data))
        rgba = np.asarray(im.convert('RGBA'))
    except Exception:
        return None
    if rgba.shape[:2] != (h, w):
        return None
    style = brickzone.ground if mode == 'ground' else brickzone.objects
    new = np.clip(style(rgba[..., :3].astype(np.float32), name), 0, 255).astype(np.uint8)
    full = Image.fromarray(np.dstack([new, rgba[..., 3]]), 'RGBA')
    cutout = cc == b'DXT1' and (rgba[..., 3] < 128).any()
    body = b''
    for lv in range(levels):
        img = full if lv == 0 else full.resize((max(1, w >> lv), max(1, h >> lv)), Image.LANCZOS)
        a = np.asarray(img)
        if cc == b'DXT1':
            body += dxt1(a, cutout)
        elif cc == b'DXT3':
            body += dxt3(a)
        elif cc == b'DXT5':
            body += dxt5(a)
        elif not pf_flags & 0x4 and bits in (24, 32):
            body += raw(a, bits, masks if pf_flags & 0x1 else masks[:3] + (0,))
        else:
            return None
    if 128 + len(body) > len(data):
        return None
    return data[:128] + body + data[128 + len(body):], img if levels == 1 else full


def main():
    src, dst = sys.argv[1:3]
    preview = sys.argv[3] if len(sys.argv) > 3 else None
    files = pfs.read(src)
    ter = b''.join(b for n, b in files if n.endswith('.ter')).lower()
    out, shown, kept = [], [], 0
    counts = {'ground': 0, 'objects': 0}
    for n, b in files:
        keep = KEEP.get(os.path.basename(src).split('.')[0].lower(), set())
        if n.endswith('.dds') and not HELPER.search(n) and b[:4] == b'DDS ' and n.lower() not in keep:
            mode = 'ground' if n.lower().encode() in ter else 'objects'
            r = restyle_dds(n, b, mode)
            if r is None:
                kept += 1
            else:
                b, img = r
                counts[mode] += 1
                shown.append(img.convert('RGB').resize((96, 96)))
        out.append((n, b))
    raw_src = open(src, 'rb').read()
    dir_off = int.from_bytes(raw_src[:4], 'little')
    count = int.from_bytes(raw_src[dir_off:dir_off + 4], 'little')
    pfs.write(dst, out, footer=raw_src[dir_off + 4 + 12 * count:])
    if preview and shown:
        cols = 10
        sheet = Image.new('RGB', (96 * cols, 96 * ((len(shown) + cols - 1) // cols)), (40, 40, 40))
        for k, im in enumerate(shown):
            sheet.paste(im, ((k % cols) * 96, (k // cols) * 96))
        sheet.save(preview)
    print(f"{counts['ground']} ground + {counts['objects']} object textures restyled, {kept} left as they were -> {dst}")


if __name__ == '__main__':
    main()
