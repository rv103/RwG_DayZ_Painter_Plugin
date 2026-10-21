r"""
Materials of an Object Builder model (MLOD .p3d), so the plugin can tell which
.rvmat and _co texture a texture set has to produce.

MLOD v257: "MLOD", version, LOD count, then per LOD a P3DM block (points,
normals, faces - each face ends with its texture and material path as
zero-terminated strings) followed by TAGG sections (named selections; proxies
are selections named "proxy:\path\model.001") and the LOD resolution.

Only the first visual LOD is read. Proxy models are followed one level deep:
on a weapon the stock, handguard, magazine ... are proxies with their own P3D
and data folder, but usually painted in the same Painter project.
"""

import ntpath
import os
import struct


def _asciiz(data, pos):
    end = data.index(b"\0", pos)
    return data[pos:end].decode("latin-1"), end + 1


def read_lods(path):
    """[(resolution, [(texture, material, face count)], [proxy model paths])] per LOD."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MLOD":
        raise ValueError(f"{os.path.basename(path)} is not an Object Builder P3D (binarized models are not supported)")
    count = struct.unpack_from("<i", data, 8)[0]
    pos = 12
    lods = []
    for _ in range(count):
        if data[pos:pos + 4] != b"P3DM":
            raise ValueError("unsupported LOD block in " + os.path.basename(path))
        header_size = struct.unpack_from("<i", data, pos + 4)[0]     # 28, "P3DM" included
        points, normals, faces = struct.unpack_from("<iii", data, pos + 12)
        pos += header_size + points * 16 + normals * 12
        mats = {}
        for _f in range(faces):
            pos += 4 + 64 + 4                                   # vertex count, 4 vertices, flags
            tex, pos = _asciiz(data, pos)
            mat, pos = _asciiz(data, pos)
            key = (tex, mat)
            mats[key] = mats.get(key, 0) + 1
        if data[pos:pos + 4] != b"TAGG":
            raise ValueError("TAGG expected in " + os.path.basename(path))
        pos += 4
        proxies = []
        while True:
            pos += 1                                            # active flag
            name, pos = _asciiz(data, pos)
            size = struct.unpack_from("<i", data, pos)[0]
            pos += 4 + size
            if name == "#EndOfFile#":
                break
            if name.lower().startswith("proxy:"):
                model = name[6:].rsplit(".", 1)[0]               # drop the .001 index
                if model and model not in proxies:
                    proxies.append(model)
        resolution = struct.unpack_from("<f", data, pos)[0]
        pos += 4
        lods.append((resolution, [(t, m, n) for (t, m), n in mats.items()], proxies))
    return lods


def _abs(ref, drive, ext=""):
    """Mod path (\\mod\\x or mod\\x) -> absolute path on the work drive."""
    ref = ref.strip().lstrip("\\/").replace("/", "\\")
    if ext and not ref.lower().endswith(ext):
        ref += ext
    d = ntpath.splitdrive(ntpath.normpath(drive))[0] or "P:"
    return ntpath.normpath(d + "\\" + ref)


def model_materials(p3d, drive="P:\\"):
    """Materials of the model and of its proxies (first visual LOD each).

    Returns a list of dicts: rvmat (absolute), texture (absolute _co), faces,
    model (the .p3d the faces are in), proxy (proxy name, or None for the model
    itself). Faces without an rvmat (proxy triangles, untextured) are skipped."""
    out, seen = [], set()

    def visual(lods):
        vis = [l for l in lods if l[0] < 1000]                  # resolution LODs, not geometry/memory
        return min(vis, key=lambda l: l[0]) if vis else (lods[0] if lods else None)

    def add(model_path, proxy_name):
        lod = visual(read_lods(model_path))
        if lod is None:
            return []
        for tex, mat, faces in sorted(lod[1], key=lambda e: -e[2]):
            if not mat:
                continue
            rv = _abs(mat, drive)
            key = os.path.normcase(rv)
            if key in seen:
                continue
            seen.add(key)
            texture = tex if tex.startswith("#") else (_abs(tex, drive) if tex else "")   # #(...) = procedural
            out.append({"rvmat": rv, "texture": texture,
                        "faces": faces, "model": model_path, "proxy": proxy_name})
        return lod[2]

    for proxy in add(p3d, None):
        path = _abs(proxy, drive, ".p3d")
        if os.path.isfile(path):
            try:
                add(path, ntpath.basename(proxy))
            except ValueError:
                pass                                            # binarized proxy: not paintable here anyway
    return out


def suggest(materials, texture_set):
    """The entry that most likely belongs to a texture set (same name as the
    rvmat or the _co texture), or None."""
    name = (texture_set or "").strip().lower().replace(" ", "_")
    if not name:
        return None
    for m in materials:
        if ntpath.splitext(ntpath.basename(m["rvmat"]))[0].lower() == name:
            return m
    for m in materials:
        co = ntpath.splitext(ntpath.basename(m["texture"]))[0].lower()
        if co.rsplit("_", 1)[0] == name:
            return m
    for m in materials:
        if name in ntpath.basename(m["rvmat"]).lower():
            return m
    return None
