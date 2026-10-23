r"""
Give the faces of an Object Builder model (MLOD .p3d) that have no texture and no
material a _co texture and an .rvmat - for a model that was exported before the
materials were assigned.

Only resolution (visual) LODs are touched, and only faces with both paths empty;
faces of proxy selections ("proxy:...") stay empty (they are the proxy triangles).
Everything else is copied byte for byte. MLOD v257 layout: see p3d_reader.
"""

import os
import shutil
import struct

from .p3d_reader import _asciiz


def _proxy_faces(data, pos, points, faces):
    """Face indices in proxy selections, and the position after the LOD's TAGG list
    and resolution. ``pos`` = start of "TAGG"."""
    if data[pos:pos + 4] != b"TAGG":
        raise ValueError("TAGG expected")
    pos += 4
    proxy = set()
    while True:
        pos += 1                                                # active flag
        name, pos = _asciiz(data, pos)
        size = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if name.lower().startswith("proxy:") and size == points + faces:
            weights = data[pos + points:pos + points + faces]   # one byte per vertex, then per face
            proxy.update(i for i, w in enumerate(weights) if w)
        pos += size
        if name == "#EndOfFile#":
            break
    resolution = struct.unpack_from("<f", data, pos)[0]
    return proxy, resolution, pos + 4


def fill_empty_faces(path, texture, rvmat, backup=True):
    """Writes ``texture`` / ``rvmat`` (game paths, e.g. mod\\data\\x_co.paa) into every
    empty face of the visual LODs. Returns the number of faces changed (0 = file untouched).
    With ``backup`` the original is kept as <name>.p3d.bak first."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MLOD":
        raise ValueError(f"{os.path.basename(path)} is not an Object Builder P3D (binarized models can't be edited)")
    tex_b = texture.encode("latin-1") + b"\0"
    mat_b = rvmat.encode("latin-1") + b"\0"
    count = struct.unpack_from("<i", data, 8)[0]
    out = bytearray(data[:12])
    pos, changed = 12, 0
    for _ in range(count):
        if data[pos:pos + 4] != b"P3DM":
            raise ValueError("unsupported LOD block in " + os.path.basename(path))
        header_size = struct.unpack_from("<i", data, pos + 4)[0]     # 28, "P3DM" included
        points, normals, faces = struct.unpack_from("<iii", data, pos + 12)
        face_start = pos + header_size + points * 16 + normals * 12
        # first pass: where every face's strings are, then the TAGGs (proxy faces, resolution)
        spans, p = [], face_start
        for _f in range(faces):
            p += 4 + 64 + 4                                     # vertex count, 4 vertices, flags
            t0 = p
            tex, p = _asciiz(data, p)
            mat, p = _asciiz(data, p)
            spans.append((t0, p, not tex and not mat))
        proxy, resolution, end = _proxy_faces(data, p, points, faces)
        visual = resolution < 1000
        # second pass: copy, with the empty faces' strings replaced
        out += data[pos:face_start]
        cur = face_start
        for i, (t0, t1, empty) in enumerate(spans):
            out += data[cur:t0]
            if visual and empty and i not in proxy:
                out += tex_b + mat_b
                changed += 1
            else:
                out += data[t0:t1]
            cur = t1
        out += data[cur:end]
        pos = end
    out += data[pos:]                                           # anything after the LODs
    if changed:
        if backup:
            shutil.copy2(path, path + ".bak")
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, path)
    return changed


def empty_face_count(path):
    """Faces without texture and material in the visual LODs (proxy faces not counted)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MLOD":
        return 0
    count = struct.unpack_from("<i", data, 8)[0]
    pos, total = 12, 0
    for _ in range(count):
        header_size = struct.unpack_from("<i", data, pos + 4)[0]
        points, normals, faces = struct.unpack_from("<iii", data, pos + 12)
        p = pos + header_size + points * 16 + normals * 12
        empty = []
        for i in range(faces):
            p += 4 + 64 + 4
            tex, p = _asciiz(data, p)
            mat, p = _asciiz(data, p)
            if not tex and not mat:
                empty.append(i)
        proxy, resolution, pos = _proxy_faces(data, p, points, faces)
        if resolution < 1000:
            total += sum(1 for i in empty if i not in proxy)
    return total
