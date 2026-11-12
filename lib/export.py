"""Pose an EQ character archive's model on its skeleton and write a .glb, plus a quick flat-shaded preview.

    python -I export.py <archive.s3d> <out.glb> <preview.png>
"""
import io, json, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import pfs, wld


def build(archive, armor_set=0):
    files = dict(pfs.read(archive))
    w = wld.Wld(files[next(n for n in files if n.endswith('.wld'))])
    (skel_id, _), = w.of_type(0x10)
    bones, mesh_ids = w.skeleton(skel_id)
    textures = {}
    for n, blob in files.items():
        if n.endswith('.dds') or n.endswith('.bmp'):
            try:
                im = Image.open(io.BytesIO(blob)); im.load()
                textures[n.rsplit('.', 1)[0].lower()] = im.convert('RGBA')
            except Exception:
                pass
    prims = {}  # texture stem -> (positions, uvs, indices)
    for mid in mesh_ids:
        m = w.mesh(mid)
        pos = []
        for k, v in enumerate(m['verts']):
            R, T = bones[m['bones'][k]][2] if k < len(m['bones']) else (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0))
            pos.append(wld.add(wld.matvec(R, v), T))
        for a, b, c, mi in m['faces']:
            name, method, tex = m['materials'][mi] if mi < len(m['materials']) else ('', 0, None)
            if method == 0 or tex is None:
                continue  # invisible
            base = name[:9].lower()  # DWMCH0001_MDF: race+gender, body part, armor set 00, piece 01
            if armor_set and base[3:5] not in ('he', 'fa') and base[5:7] == '00':
                dressed = base[:5] + f'{armor_set:02d}' + base[7:]  # e.g. dwmch0001 -> dwmch0201
                if dressed in textures:
                    tex = dressed
            P, U, I = prims.setdefault(tex, ([], [], []))
            for v in (a, c, b):  # EQ winds the other way round
                I.append(len(P))
                P.append(pos[v])
                U.append(m['uvs'][v] if v < len(m['uvs']) else (0, 0))
    return prims, textures


def to_gltf_space(p):
    x, y, z = p
    return (y, z, x)  # EQ is Z-up and models face +X; glTF is Y-up and faces +Z


def write_glb(path, prims, textures):
    bin_ = bytearray()
    gl = {'asset': {'version': '2.0', 'generator': 'brickify'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
          'nodes': [{'mesh': 0, 'name': 'model'}], 'meshes': [{'primitives': []}], 'buffers': [],
          'bufferViews': [], 'accessors': [], 'materials': [], 'textures': [], 'images': [],
          'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 10497, 'wrapT': 10497}]}

    def view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        gl['bufferViews'].append({'buffer': 0, 'byteOffset': len(bin_), 'byteLength': len(data)} |
                                 ({'target': target} if target else {}))
        bin_.extend(data)
        return len(gl['bufferViews']) - 1

    def accessor(arr, ctype, typ, target):
        v = view(arr.tobytes(), target)
        acc = {'bufferView': v, 'componentType': ctype, 'count': len(arr), 'type': typ}
        if typ == 'VEC3':
            acc['min'], acc['max'] = arr.min(0).tolist(), arr.max(0).tolist()
        gl['accessors'].append(acc)
        return len(gl['accessors']) - 1

    for tex, (P, U, I) in sorted(prims.items()):
        pos = np.array([to_gltf_space(p) for p in P], dtype=np.float32)
        uv = np.array(U, dtype=np.float32)
        idx = np.array(I, dtype=np.uint32)
        prim = {'attributes': {'POSITION': accessor(pos, 5126, 'VEC3', 34962),
                               'TEXCOORD_0': accessor(uv, 5126, 'VEC2', 34962)},
                'indices': accessor(idx, 5125, 'SCALAR', 34963)}
        mat = {'name': tex, 'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 0.6},
               'doubleSided': True}
        if tex in textures:
            png = io.BytesIO()
            textures[tex].save(png, 'PNG')
            gl['images'].append({'bufferView': view(png.getvalue()), 'mimeType': 'image/png'})
            gl['textures'].append({'source': len(gl['images']) - 1, 'sampler': 0})
            mat['pbrMetallicRoughness']['baseColorTexture'] = {'index': len(gl['textures']) - 1}
        gl['materials'].append(mat)
        prim['material'] = len(gl['materials']) - 1
        gl['meshes'][0]['primitives'].append(prim)
    while len(bin_) % 4:
        bin_.append(0)
    gl['buffers'].append({'byteLength': len(bin_)})
    js = json.dumps(gl, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(bin_), 0x004E4942) + bytes(bin_)
    open(path, 'wb').write(out)


def preview(path, prims, textures, size=520):
    """Front and side views, flat shaded with each triangle's texture color at its middle."""
    tris = []
    for tex, (P, U, I) in prims.items():
        im = textures.get(tex)
        for k in range(0, len(I), 3):
            pts = [to_gltf_space(P[I[k + j]]) for j in range(3)]
            col = (200, 200, 200)
            if im:
                u = sum(U[I[k + j]][0] for j in range(3)) / 3 % 1.0
                v = sum(U[I[k + j]][1] for j in range(3)) / 3 % 1.0
                col = im.getpixel((min(int(u * im.width), im.width - 1), min(int(v * im.height), im.height - 1)))[:3]
            tris.append((np.array(pts), col))
    allp = np.concatenate([t[0] for t in tris])
    lo, hi = allp.min(0), allp.max(0)
    sheet = Image.new('RGB', (size * 2, size), (50, 55, 65))
    light = np.array([0.4, 0.6, 0.7]) / np.linalg.norm([0.4, 0.6, 0.7])
    for view_i, (ax, depth, flip, toward) in enumerate([(0, 2, 1, 1), (2, 0, -1, 1)]):  # front from +Z, side from +X
        d = ImageDraw.Draw(sheet)
        span = max(hi[1] - lo[1], hi[ax] - lo[ax]) * 1.1
        def pt(p):
            x = (flip * (p[ax] - (lo[ax] + hi[ax]) / 2)) / span * size + size / 2 + view_i * size
            y = size / 2 - (p[1] - (lo[1] + hi[1]) / 2) / span * size
            return (x, y)
        order = sorted(tris, key=lambda t: toward * t[0][:, depth].mean())  # far first
        for pts, col in order:
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            ln = np.linalg.norm(n)
            shade = 0.55 + 0.45 * abs(n @ light) / ln if ln else 1
            d.polygon([pt(p) for p in pts], fill=tuple(int(c * shade) for c in col))
    sheet.save(path)


if __name__ == '__main__':
    prims, textures = build(sys.argv[1], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    write_glb(sys.argv[2], prims, textures)
    preview(sys.argv[3], prims, textures)
    print(sum(len(p[2]) // 3 for p in prims.values()), 'triangles,', len(prims), 'materials ->', sys.argv[2])
