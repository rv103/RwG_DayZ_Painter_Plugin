"""Live link to the DayZ Material Viewer (E:\\Git\\DayZ Shader, DayZViewer.exe).

The viewer watches %LOCALAPPDATA%\\DayZViewer\\livelink.json (the same file the
Blender add-on writes). A message names the P3D to show, the files an export
just wrote (so the viewer reloads them at once) and, optionally, the current
material values of the .rvmat, which the viewer applies live without a save.
Every field is optional; a new ``seq`` marks a new message.
"""

import glob
import json
import os
import subprocess
import time

LINK_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                         "DayZViewer", "livelink.json")
VIEWER_EXE_NAME = "DayZViewer.exe"
# the other direction: values edited in the viewer's material panel
FROM_VIEWER_FILE = os.path.join(os.path.dirname(LINK_FILE), "painterlink.json")


def _floats(text, count, default):
    vals = []
    for part in str(text).split(","):
        try:
            vals.append(float(part.strip()))
        except ValueError:
            pass
    vals = vals[:count]
    return vals + list(default)[len(vals):count]


def _num(text, default):
    try:
        return float(str(text).strip())
    except ValueError:
        return default


def material_from_settings(s):
    """rvmat values from the plugin's settings dict (same keys as the Material panel)."""
    return {
        "ambient": _floats(s.get("mat_ambient", ""), 4, (1, 1, 1, 1)),
        "diffuse": _floats(s.get("mat_diffuse", ""), 4, (1, 1, 1, 1)),
        "forcedDiffuse": _floats(s.get("mat_forced", ""), 4, (0, 0, 0, 1)),
        "emmisive": _floats(s.get("mat_emmisive", ""), 4, (0, 0, 0, 0)),
        "specular": _floats(s.get("mat_specular", ""), 4, (1, 1, 1, 1)),
        "specularPower": max(1.0, _num(s.get("mat_power", ""), 30.0)),
        "fresnel": [_num(s.get("mat_fresnel_n", ""), 0.4), _num(s.get("mat_fresnel_k", ""), 0.2)],
    }


# map types the export writes (prefix + "_" + type); "ca" is the colour map with alpha
MAP_TYPES = ("co", "ca", "nohq", "smdi", "dtsmdi", "as", "mc", "em")
MAP_EXTENSIONS = (".tga", ".png", ".paa")


def export_maps(output_folder, prefix):
    """The exported files of a texture set by map type: {"co": [..._co.tga, ..._co.paa], "nohq": [...], ...}.
    The viewer puts exactly these on the stages of the set's rvmat (no guessing by name or P: path)."""
    maps = {}
    if not output_folder or not prefix or not os.path.isdir(output_folder):
        return maps
    for kind in MAP_TYPES:
        found = [f for f in glob.glob(os.path.join(output_folder, f"{prefix}_{kind}.*"))
                 if f.lower().endswith(MAP_EXTENSIONS)]
        if found:
            maps["co" if kind == "ca" and "co" not in maps else kind] = sorted(found)
    return maps


def send(model=None, files=None, rvmat=None, material=None, texture_set=None, proxy=None, maps=None, engine=None):
    """Write one message for the viewer (atomically). Returns the file path.
    ``proxy``: the proxy model (.p3d) the rvmat belongs to - the viewer switches it on.
    ``maps``: the texture set's exported files by map type (export_maps) - the viewer binds them to the rvmat.
    ``engine``: "direct" (Buldozer) or "world" (RwG Viewer World) - the viewer opens it, live."""
    msg = {"seq": int(time.time() * 1000), "source": "painter"}
    if model:
        msg["model"] = os.path.abspath(model)
    if proxy:
        msg["proxy"] = os.path.abspath(proxy)
    if files:
        msg["files"] = [os.path.abspath(f) for f in files]
    if rvmat:
        msg["rvmat"] = os.path.abspath(rvmat)
    if material:
        msg["material"] = material
    if texture_set:
        msg["textureSet"] = texture_set
    if maps:
        msg["maps"] = {kind: [os.path.abspath(f) for f in files_] for kind, files_ in maps.items()}
    if engine:
        msg["engine"] = engine
    os.makedirs(os.path.dirname(LINK_FILE), exist_ok=True)
    tmp = LINK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(msg, f)
    os.replace(tmp, LINK_FILE)
    return LINK_FILE


def read_from_viewer(last_mtime):
    """A new message from the viewer, if the file changed since ``last_mtime``.
    Returns (message or None, mtime)."""
    try:
        mtime = os.path.getmtime(FROM_VIEWER_FILE)
    except OSError:
        return None, last_mtime
    if mtime == last_mtime:
        return None, last_mtime
    try:
        with open(FROM_VIEWER_FILE, encoding="utf-8") as f:
            return json.load(f), mtime
    except (OSError, ValueError):
        return None, last_mtime          # being replaced right now: try again on the next poll


def fields_from_material(material):
    """Plugin field texts (mat_* keys) from a viewer material message."""
    def vec(key):
        v = material.get(key)
        return ",".join(f"{float(x):.4g}" for x in v) if isinstance(v, list) and v else None
    out = {"mat_ambient": vec("ambient"), "mat_diffuse": vec("diffuse"),
           "mat_forced": vec("forcedDiffuse"), "mat_emmisive": vec("emmisive"),
           "mat_specular": vec("specular")}
    if material.get("specularPower") is not None:
        out["mat_power"] = f"{float(material['specularPower']):.4g}"
    fr = material.get("fresnel")
    if isinstance(fr, list) and len(fr) >= 2:
        out["mat_fresnel_n"], out["mat_fresnel_k"] = f"{float(fr[0]):.4g}", f"{float(fr[1]):.4g}"
    return {k: v for k, v in out.items() if v is not None}


def guess_p3d(output_folder):
    """The model for an export folder: a .p3d in the folder itself, else one level up
    (DayZ layout: <item>\\<item>.p3d next to <item>\\data\\). None if not unique."""
    if not output_folder or not os.path.isdir(output_folder):
        return None
    for folder in (output_folder, os.path.dirname(os.path.normpath(output_folder))):
        found = glob.glob(os.path.join(folder, "*.p3d"))
        if len(found) == 1:
            return found[0]
    return None


def viewer_running():
    """True if a DayZViewer.exe process is running."""
    try:
        # bytes: tasklist prints in the console code page (umlauts in German Windows)
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {VIEWER_EXE_NAME}", "/NH"],
                             capture_output=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return VIEWER_EXE_NAME.lower().encode() in out.lower()
    except Exception:
        return False


def start_viewer(exe, model=None):
    """Start the viewer, optionally with a model."""
    if not exe or not os.path.isfile(exe):
        raise FileNotFoundError("DayZViewer.exe not set or not found (Settings).")
    args = [exe] + ([os.path.abspath(model)] if model else [])
    subprocess.Popen(args, cwd=os.path.dirname(exe))
