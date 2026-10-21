"""
RwG DayZ Texture Exporter - Substance 3D Painter plugin
=======================================================

Exports the current project's PBR channels and converts them to DayZ textures
(_co / _nohq / _smdi / _as), optionally to .paa, and drives a small .rvmat panel
(auto-filled texture paths, presets, open in an external material editor with
auto-sync back).

Self-contained: the conversion code lives in the bundled ``core`` package. The
numpy/Pillow image maths run in an external Python via ``core/cli.py``; the
rvmat + path helpers (pure Python) run directly inside Painter.
"""

import os
import re
import sys
import glob
import json
import math
import shutil
import tempfile
import subprocess

import substance_painter.ui
import substance_painter.export
import substance_painter.project
import substance_painter.logging as splog

try:
    import substance_painter.resource as spresource
except Exception:                                   # pragma: no cover
    spresource = None

try:
    import substance_painter.textureset as sptexset
except Exception:                                   # pragma: no cover
    sptexset = None

try:
    import substance_painter.layerstack as splayer
except Exception:                                   # pragma: no cover
    splayer = None

try:
    import substance_painter.display as spdisplay
except Exception:                                   # pragma: no cover
    spdisplay = None

# Painter 2024+ ships PySide6 (Qt6); older versions ship PySide2 (Qt5).
try:
    from PySide6 import QtWidgets, QtCore, QtGui   # noqa: F401
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui   # noqa: F401
QAction = getattr(QtGui, "QAction", None) or QtWidgets.QAction

# Pure-Python core helpers (no numpy) can run inside Painter.
from .core import rvmat_writer, paa_tools
from . import shader_sync


PLUGIN_TITLE = "RwG DayZ Texture Exporter"
PLUGIN_VERSION = "0.5.0b"
# GitHub project (source, releases, wiki) + the API used for the version check.
GITHUB_REPO_URL = "https://github.com/rv103/RwG_DayZ_Painter_Plugin"
GITHUB_RELEASES_URL = GITHUB_REPO_URL + "/releases"
GITHUB_WIKI_URL = GITHUB_REPO_URL + "/wiki"
# list endpoint (not /releases/latest) so pre-releases are included in the check
GITHUB_API_RELEASES = ("https://api.github.com/repos/rv103/"
                       "RwG_DayZ_Painter_Plugin/releases?per_page=10")
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(PLUGIN_DIR, "rwg_dayz_settings.json")
# user-defined RVMAT material presets (global, shared across all projects)
USER_PRESETS_FILE = os.path.join(PLUGIN_DIR, "rwg_dayz_user_presets.json")
RES_OPTIONS = ["256", "512", "1024", "2048"]
# derived from the shared preset table so new presets appear automatically
PRESETS = list(rvmat_writer.MATERIAL_PRESETS.keys())
META_NS = "RwG_DayZ"
META_NORMAL_KEY = "normal_format"
META_SETTINGS_KEY = "settings"
MINI_BTN = 24          # square size for the small icon helper buttons
# machine / UI settings that stay global (not saved per project)
GLOBAL_KEYS = ("python", "imagetopaa", "mateditor", "texview", "drive", "layout_mode",
               "presets_path", "env_hdri", "env_tone")
USER_PRESETS_NAME = "rwg_dayz_user_presets.json"
USER_FRESNEL_NAME = "rwg_dayz_user_fresnel.json"

HELP_HTML = """
<h3>RwG DayZ Texture Exporter <span style="color:#9aa0a6;">v{version}</span></h3>
<p>Turns your Substance Painter project into DayZ textures
(<b>_co / _ca, _nohq, _smdi, _as, _em, _mc, _dtsmdi</b>), optional <b>.paa</b>, and a
matching Super-shader <b>.rvmat</b> - damage variants included.</p>
<p><b>Project &amp; docs:</b>
<a href="{repo}">GitHub</a> &nbsp;&middot;&nbsp;
<a href="{releases}">Releases / changelog</a> &nbsp;&middot;&nbsp;
<a href="{wiki}">Wiki (full manual)</a><br>
<i>Use <b>Check for updates</b> below to compare this version with the latest
release on GitHub.</i></p>

<b>Setup</b>
<ul>
<li><b>Settings</b> (top button): tool paths (Python with Auto-detect, ImageToPAA,
MatEditor, TexView), the mod <b>Drive</b>, the panel layout, and <b>Prepare DayZ
channels</b> - adds Emissive + Opacity + User0-User2 (colour) to the active texture set
(for _em / _ca / _mc). Best baked into a Painter project template.</li>
<li><b>Output folder</b>: best inside your <b>P:\\</b> mod path so the .rvmat gets game-valid paths.</li>
<li><b>Prefix</b>: file-name base (wall -> wall_co.tga). <b>Use texture set name</b> fills it in.</li>
</ul>

<b>Export mode</b>
<ul>
<li><b>Built-in maps</b> - the plugin builds the maps (per-map size &amp; options).</li>
<li><b>Painter preset</b> - runs your own saved export preset as-is (no external Python needed).</li>
</ul>

<b>Maps</b>
<ul>
<li><b>_co</b>: default <b>Base Color - metals keep color</b> (the DayZ colour map
carries the metal colour; reflectivity rides in the _smdi). Alternatives: <b>Diffuse
(metals black)</b>, 2D View, Base Color + Specular, Spec/Gloss diffuse (glTF). Tick
<b>alpha (_ca)</b> to add an Opacity alpha and write <b>_ca</b> instead (transparent
materials).</li>
<li><b>_nohq</b>: <b>DirectX</b> for DayZ - combines normal + height + baked mesh normal
(never flat). Format is switchable and remembered per project.</li>
<li><b>_smdi</b>: R=white, G=specular, B=gloss. Its <b>G</b> / <b>B</b> sliders sit
inline on the _smdi row (1.00 = unchanged) and also drive the _dtsmdi G/B. Source
dropdown - default <b>Met-&gt;Spec/Gloss (glTF)</b>; also Spec+Gloss (converted maps),
Met+Rough (flat metal spec), Met+Rough+BaseColor (PBR).</li>
<li><b>_dtsmdi</b> (Multimaterial shader): sits right under _smdi. <b>R = a detail
map</b> (height + baked mesh + normal, centred on 0.5 so it fades in the mipmaps),
<b>G/B like the _smdi</b>. Its inline <b>Detail (R)</b> slider scales how pronounced
the detail is - amplitude only, the mid-point stays 0.5. Replaces the _smdi for the
Multimaterial shader.</li>
<li><b>_as</b>: DayZ layout, R/B white, G=mixed AO. 512 is usually enough.</li>
<li><b>_em</b> (optional): emissive / glow, straight from the project's Emissive channel.</li>
<li><b>_mc</b> (optional): macro, from a Painter <b>User channel</b> (User0-2, RGB), or
<b>Combine</b> to stack all three with a blend mode. The <b>alpha</b> is the DayZ blend
mask (1 = only macro, 0 = only base): <b>Auto</b> derives it from the macro's brightness
(applies where you painted), or pick a channel / Opacity, or None for opaque. Use
<b>Settings → Prepare DayZ channels</b> for the User channels.</li>
</ul>
<p>Each map has its own checkbox and size (256-2048). _em / _mc / _dtsmdi are off by
default. _co and _ca are the same map - the <b>alpha (_ca)</b> tick decides which is
written.</p>

<b>Export</b>
<ul>
<li>.tga is always written; .paa needs DayZ Tools <b>ImageToPAA.exe</b>.</li>
<li><b>Also fill the RVMAT texture fields</b> (checkbox above the export buttons, on by
default): after an export, write the produced paths into the RVMAT NOHQ/AS/SMDI/MC
fields. Turn it off to export the maps only and leave the rvmat untouched.</li>
<li><b>Convert .tga -&gt; .paa (folder)</b> is a standalone batch tool, independent of
the project export.</li>
</ul>

<b>RVMAT</b>
<ul>
<li><b>Texture paths use</b>: <b>.tga</b> (raw, for preview - the default) or <b>.paa</b>
(packed, what the game loads) for the texture paths written into the rvmat.</li>
<li>Each texture row has a small <b>availability light</b>: green = the referenced
file is on disk, amber = only the other extension is there (convert it or switch the
extension), red = nothing found, grey = procedural default. Hover it for details.</li>
<li><b>Auto-fill from export</b> fills NOHQ/AS/SMDI with the real exported paths;
<b>default</b> resets a row to its procedural value.</li>
<li>Material values (ambient/diffuse/.../specularPower) are editable fields.
<b>Load preset values</b> fills them from a preset; <b>Write .rvmat</b> saves everything.
Small helpers (hover for tooltips): a <b>droplet</b> = sample the average base colour,
<b>&#8635;</b> = reset to 1,1,1,1, a <b>spark</b> = estimate from the project (emmisive /
specularPower). The colour rows show a <b>coloured button</b> that previews the current
value - click it for an RGBA editor (sliders, live preview and a colour picker).</li>
<li><b>fresnel</b>: edit N/K directly, or click <b>Curve...</b> for a visual editor
with a live reflectance-vs-angle graph. <b>Estimate from base color</b> there
derives a representative N/K from your metal's F0 (metalness workflow).</li>
<li><b>env</b>: dropdown of the DayZ <code>dz\\data\\data</code> environment maps
(Stage7); editable for a custom one. Written into the .rvmat.</li>
<li><b>Open .rvmat in MatEditor</b> + <b>Auto-sync</b>: edits in the editor flow back into the fields.</li>
<li>The panel auto-loads <b>&lt;prefix&gt;.rvmat</b> on startup / when output+prefix change.</li>
<li><b>Damage variants</b>: pick a material family, then a button (Worn/Damage/Destruct,
etc.) writes <b>&lt;prefix&gt;&lt;suffix&gt;.rvmat</b> from the current base - identical
except the MC (Stage3) is swapped to that damage <b>_mc</b>. Same idea as RwG RVMat Speedo.</li>
</ul>

<b>How the _smdi (and _dtsmdi G/B) is calculated</b>
<p>The DayZ _smdi is packed as <b>R = white (1.0)</b>, <b>G = specular level</b>,
<b>B = gloss (= 1 - roughness)</b>. All values run 0..1; the plugin writes
<code>round(value * 255)</code> per channel. The source options only differ
in where G comes from (B is always <code>1 - Roughness</code>) - the <b>G</b> and
<b>B</b> sliders (default 1.0) scale each channel afterwards:</p>
<ul>
<li><b>Met-&gt;Spec/Gloss (glTF)</b> - the recommended default, canonical glTF metric:<br>
<code>G = perceivedBrightness(mix(0.04, baseColor, metallic)) * G-slider</code></li>
<li><b>Spec+Gloss (convert maps)</b> - uses Painter's converted maps directly.
Even a Metallic/Roughness project works because Painter converts them:<br>
<code>G = clamp(Specular * G-slider, 0, 1)</code></li>
<li><b>Met+Rough (channels)</b> - straight from metallic + roughness with a 0.04
dielectric base (F0). Metals go to a flat full specular:<br>
<code>G = clamp((0.04 + 0.96 * Metallic) * G-slider, 0, 1)</code></li>
<li><b>Met+Rough+BaseColor (PBR)</b> - physically based: each metal gets its own
reflectance from the (linearised) base-colour luminance, so dull metal stays
darker than polished. Dielectrics keep the 0.04 floor:<br>
<code>G = clamp(lerp(0.04, luminance(baseColor), Metallic) * G-slider, 0, 1)</code></li>
</ul>
<p>The <b>_dtsmdi</b> uses the same G/B; only its <b>R</b> differs (the detail map).</p>

<p><i>Note: _co is not an rvmat stage in DayZ - it is assigned on the model. The
material references _nohq, _as and _smdi (or _dtsmdi for the Multimaterial shader).</i></p>
""".format(version=PLUGIN_VERSION, repo=GITHUB_REPO_URL,
           releases=GITHUB_RELEASES_URL, wiki=GITHUB_WIKI_URL)

DOCK_QSS = """
QLabel#title { font-weight: bold; font-size: 15px; color: #ff5a62; }
QLabel#sectionHeader {
    font-weight: bold;
    font-size: 13px;
    color: #ff5a62;
    padding: 4px 0 3px 8px;
    border-left: 3px solid #e4141f;
    border-bottom: 1px solid rgba(228,20,31,90);
    margin-bottom: 2px;
}
QLabel#hint { color: #9aa0a6; font-size: 10px; }
QGroupBox#section {
    border: 1px solid rgba(228,20,31,120);
    border-radius: 6px;
    margin-top: 17px;
    padding: 8px 2px 4px 2px;
    background: rgba(255,255,255,8);
}
QGroupBox#section::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 1px 6px;
    color: #ff5a62;
    font-weight: bold;
    font-size: 14px;
}
QGroupBox#subsection {
    border: 1px solid rgba(255,255,255,40);
    border-radius: 5px;
    margin-top: 14px;
    padding: 6px 2px 2px 2px;
    background: rgba(255,255,255,5);
}
QGroupBox#subsection::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 1px 5px;
    color: #ff5a62;
    font-weight: bold;
    font-size: 12px;
}
QPushButton { padding: 3px 8px; border: 1px solid rgba(255,255,255,32); border-radius: 4px; }
QPushButton:hover { border-color: rgba(255,255,255,80); }
QPushButton#mini {
    padding: 0px; font-size: 11px;
    min-width: 24px; max-width: 24px; min-height: 22px; max-height: 24px;
}
QPushButton#primary {
    font-weight: bold;
    border: 1px solid #e4141f;
    background: rgba(228,20,31,70);
}
QPushButton#primary:hover { background: rgba(228,20,31,120); }
QPushButton#help { border-radius: 13px; font-weight: bold; }
QLineEdit, QComboBox, QDoubleSpinBox {
    padding: 3px 5px; border: 1px solid rgba(255,255,255,32); border-radius: 4px;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid #e4141f; }
QPlainTextEdit, QTextEdit { border: 1px solid rgba(255,255,255,32); border-radius: 4px; }
QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #e4141f; }
QCheckBox { spacing: 6px; font-weight: bold; }
QCheckBox::indicator {
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid rgba(255,255,255,70); background: rgba(255,255,255,12);
}
QCheckBox::indicator:checked { background: #e4141f; border: 1px solid #ff5a62; }
QCheckBox::indicator:checked:hover { background: #ff3b45; }
QScrollArea { background: transparent; border: none; }
QTabWidget::pane { border: 1px solid rgba(255,255,255,26); border-radius: 4px; }
QTabBar::tab {
    padding: 4px 14px; margin-right: 2px;
    border: 1px solid rgba(255,255,255,22); border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: rgba(228,20,31,120); font-weight: bold; color: #ffeef0; }
QTabBar::tab:!selected { color: #b7bcc0; }
QSlider::groove:horizontal {
    height: 4px; background: rgba(255,255,255,38); border-radius: 2px;
}
QSlider::sub-page:horizontal { background: rgba(228,20,31,150); border-radius: 2px; }
QSlider::handle:horizontal {
    width: 12px; margin: -6px 0; border-radius: 7px;
    background: #e4141f; border: 1px solid #ff5a62;
}
QSlider::handle:horizontal:hover { background: #ff3b45; }
QLabel#sliderVal { color: #cfd3d6; font-size: 11px; }
"""

_plugin_widgets = []


# --------------------------------------------------------------------------- #
#  settings                                                                    #
# --------------------------------------------------------------------------- #
def load_settings():
    defaults = {
        "python": "", "output": "", "prefix": "",
        "imagetopaa": "", "drive": "P:\\",
        "normal_format": "directx",
        "co_on": True, "nohq_on": True, "smdi_on": True, "as_on": True,
        "em_on": False, "co_alpha": False, "mc_on": False, "mc_source": "User0",
        "mc_blend": "Lighten", "mc_alpha": "Auto (macro)",
        "dtsmdi_on": False,
        "autofill_on_export": True,
        "co_res": "2048", "nohq_res": "2048", "smdi_res": "2048", "as_res": "1024",
        "em_res": "1024", "mc_res": "2048", "dtsmdi_res": "2048",
        "co_source": "base_color",
        "smdi_source": "dayz",
        "smdi_green": 1.0, "smdi_blue": 1.0, "dtsmdi_strength": 1.0,
        "preset": "Default", "mateditor": "", "texview": "", "autosync": True,
        "mode": "builtin", "painter_preset": "DayZ", "preset_shelf": "your_assets",
        "tex_ext": "tga",
        "mat_ambient": "1,1,1,1", "mat_diffuse": "1,1,1,1",
        "mat_forced": "0,0,0,1", "mat_emmisive": "0,0,0,0",
        "mat_specular": "1,1,1,1", "mat_power": "30.0",
        "mat_fresnel_n": "0.4", "mat_fresnel_k": "0.2",
        "fresnel_fmt": "ai", "fresnel_w": "64", "fresnel_h": "64", "fresnel_levels": "1",
        "env": "",
        "env_hdri": "",
        "env_tone": "ACES",
        "layout_mode": "tabs",
        "presets_path": "",
    }
    # global machine/UI keys come from the shared file (tool paths, layout)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                g = json.load(f)
            for k in GLOBAL_KEYS:
                if k in g:
                    defaults[k] = g[k]
    except Exception as e:
        splog.warning(f"[RwG] Could not read settings: {e}")
    # per-project values (a brand-new project has none -> defaults are used)
    proj = load_project_settings()
    if proj:
        defaults.update(proj)
    return defaults


def load_project_settings():
    """Read the per-project settings stored in the open project's metadata."""
    try:
        if substance_painter.project.is_open():
            md = substance_painter.project.Metadata(META_NS)
            raw = md.get(META_SETTINGS_KEY)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return None


def save_project_settings(settings):
    """Store the per-project settings (everything except the global keys) in the
    open project's metadata, so they travel with the .spp file."""
    try:
        if substance_painter.project.is_open():
            md = substance_painter.project.Metadata(META_NS)
            proj = {k: v for k, v in settings.items() if k not in GLOBAL_KEYS}
            md.set(META_SETTINGS_KEY, json.dumps(proj))
    except Exception as e:
        splog.warning(f"[RwG] Could not store settings in project: {e}")


def save_settings(settings):
    # global machine/UI keys -> shared file; per-project keys -> project metadata
    try:
        glob = {k: settings.get(k) for k in GLOBAL_KEYS if k in settings}
        with open(SETTINGS_FILE, "w") as f:
            json.dump(glob, f, indent=2)
    except Exception as e:
        splog.warning(f"[RwG] Could not save settings: {e}")
    save_project_settings(settings)


# --------------------------------------------------------------------------- #
#  user RVMAT presets (material values only, global, save/load by name)        #
# --------------------------------------------------------------------------- #
# Keys stored per user preset - only the material *values*, never texture paths.
USER_PRESET_KEYS = ("mat_ambient", "mat_diffuse", "mat_forced", "mat_emmisive",
                    "mat_specular", "mat_power", "mat_fresnel_n", "mat_fresnel_k",
                    "env")


def user_presets_file(folder=None):
    """Resolve the presets JSON file. ``folder`` (from Settings) overrides the
    default plugin folder; the file name itself is fixed."""
    folder = (folder or "").strip()
    if folder:
        return os.path.join(folder, USER_PRESETS_NAME)
    return USER_PRESETS_FILE


def load_user_presets(folder=None):
    """Return the dict of user-saved material presets ({name: {keys...}})."""
    path = user_presets_file(folder)
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        splog.warning(f"[RwG] Could not read user presets: {e}")
    return {}


def save_user_presets(presets, folder=None):
    """Persist the user preset dict to the configured presets file."""
    path = user_presets_file(folder)
    try:
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        with open(path, "w") as f:
            json.dump(presets, f, indent=2)
    except Exception as e:
        splog.warning(f"[RwG] Could not save user presets: {e}")


def user_fresnel_file(folder=None):
    """Resolve the user Fresnel-materials JSON file (same folder as presets)."""
    folder = (folder or "").strip()
    if folder:
        return os.path.join(folder, USER_FRESNEL_NAME)
    return os.path.join(PLUGIN_DIR, USER_FRESNEL_NAME)


def load_user_fresnel(folder=None):
    """Return the dict of user-saved Fresnel materials ({name: {n,k,specular}})."""
    path = user_fresnel_file(folder)
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        splog.warning(f"[RwG] Could not read user Fresnel materials: {e}")
    return {}


def save_user_fresnel(mats, folder=None):
    """Persist the user Fresnel-materials dict to the configured file."""
    path = user_fresnel_file(folder)
    try:
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        with open(path, "w") as f:
            json.dump(mats, f, indent=2)
    except Exception as e:
        splog.warning(f"[RwG] Could not save user Fresnel materials: {e}")


# --------------------------------------------------------------------------- #
#  project metadata (per-project normal format)                                #
# --------------------------------------------------------------------------- #
def get_project_normal_format(default="opengl"):
    try:
        if substance_painter.project.is_open():
            md = substance_painter.project.Metadata(META_NS)
            v = md.get(META_NORMAL_KEY)
            if v in ("opengl", "directx"):
                return v
    except Exception:
        pass
    return default


def set_project_normal_format(fmt):
    try:
        if substance_painter.project.is_open():
            md = substance_painter.project.Metadata(META_NS)
            md.set(META_NORMAL_KEY, fmt)
    except Exception as e:
        splog.warning(f"[RwG] Could not store normal format in project: {e}")


# --------------------------------------------------------------------------- #
#  CLI execution (external Python)                                             #
# --------------------------------------------------------------------------- #
def _cli_path():
    return os.path.join(PLUGIN_DIR, "core", "cli.py")


# Hide the console window the external Python would flash on Windows.
_NO_WINDOW = {}
if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
    _NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW}


class _BgWorker(QtCore.QThread):
    """Runs a callable off the UI thread and reports (result, error) back on the
    main thread via a queued signal, so the heavy conversion never freezes
    Painter's UI. The callable must NOT touch the Painter API (subprocess / file
    work only) - Painter API calls stay on the main thread."""
    done = QtCore.Signal(object, object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn(), None)
        except Exception as e:                     # pragma: no cover
            self.done.emit(None, e)


def _exec_cli(python, extra_args, log):
    cli = _cli_path()
    if not python or not os.path.exists(python):
        raise RuntimeError("Set 'Python' to a python.exe that has numpy + pillow.")
    if not os.path.exists(cli):
        raise RuntimeError(f"Bundled converter not found: {cli}")
    cmd = [python, cli] + extra_args
    log("[RwG] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=os.path.dirname(cli),
                          capture_output=True, text=True, timeout=900, **_NO_WINDOW)
    if proc.stderr:
        log("[RwG] stderr: " + proc.stderr.strip())
    try:
        start = proc.stdout.index("{")
        return json.loads(proc.stdout[start:])
    except Exception:
        log("[RwG] stdout: " + proc.stdout.strip())
        return None


# --------------------------------------------------------------------------- #
#  python auto-detection                                                       #
# --------------------------------------------------------------------------- #
def _candidate_pythons():
    """Collect plausible python.exe paths (PATH, py launcher, common installs)."""
    cands = []
    for name in ("python", "python3"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    py = shutil.which("py")
    if py:
        try:
            r = subprocess.run([py, "-c", "import sys;print(sys.executable)"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                cands.append(r.stdout.strip())
        except Exception:
            pass
    home = os.path.expanduser("~")
    for pat in (
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python*", "python.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python*", "python3.exe"),
        r"C:\Python*\python.exe",
        os.path.join(home, ".venv", "Scripts", "python.exe"),
    ):
        cands += glob.glob(pat)

    seen, ordered = set(), []
    for c in cands:
        key = os.path.normcase(os.path.abspath(c))
        if key not in seen and os.path.exists(c):
            seen.add(key)
            ordered.append(c)
    return ordered


def _python_has_libs(py):
    try:
        r = subprocess.run([py, "-c", "import numpy, PIL"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def detect_python():
    """Return (path, has_numpy_pillow). Prefers an interpreter that has the libs."""
    cands = _candidate_pythons()
    for c in cands:
        if _python_has_libs(c):
            return c, True
    return (cands[0], False) if cands else (None, False)


# --------------------------------------------------------------------------- #
#  Painter export                                                              #
# --------------------------------------------------------------------------- #
def _texture_set_names():
    names = []
    try:
        if sptexset and hasattr(sptexset, "all_texture_sets"):
            names = [ts.name() for ts in sptexset.all_texture_sets()]
    except Exception as e:
        splog.warning(f"[RwG] Could not list texture sets: {e}")
    return names


def _active_texture_set_name():
    """Name of the CURRENTLY selected texture set (not just the first one)."""
    try:
        if sptexset and hasattr(sptexset, "get_active_stack"):
            stack = sptexset.get_active_stack()
            if stack is not None:
                for getter in ("material", "texture_set"):
                    if hasattr(stack, getter):
                        ts = getattr(stack, getter)()
                        if ts is not None and hasattr(ts, "name"):
                            return ts.name()
                if hasattr(stack, "name"):
                    return stack.name()
    except Exception as e:
        splog.warning(f"[RwG] Could not get active texture set: {e}")
    names = _texture_set_names()
    return names[0] if names else None


def _export_list():
    """Export only the active texture set (so maps match the chosen prefix)."""
    name = _active_texture_set_name()
    if name:
        return [{"rootPath": name}]
    return [{"rootPath": ts} for ts in _texture_set_names()]


def build_export_config(export_path, plan):
    """
    plan: list of dicts {fileName, srcType, srcName, mode}
      srcType: 'documentMap' | 'meshMap' | 'virtualMap'
      mode:    'rgb' | 'gray'

    Painter's converted (virtual) maps do the heavy lifting:
      * Normal_DirectX / Normal_OpenGL - normal channel + height + mesh normal
        combined into the final DayZ-ready normal (no blank normals).
      * AO_Mixed - document AO + baked mesh AO.
      * View_2D  - the flattened 2D View.
    """
    def channels(src_type, src_name, mode):
        comps = ("R", "G", "B") if mode == "rgb" else ("L",)
        return [{"destChannel": c, "srcChannel": c,
                 "srcMapType": src_type, "srcMapName": src_name} for c in comps]

    maps = [{"fileName": o["fileName"],
             "channels": channels(o["srcType"], o["srcName"], o["mode"])}
            for o in plan]
    preset = {"name": "RwG_PBR", "maps": maps}
    params = {"fileFormat": "tga", "bitDepth": "8", "dithering": False,
              "paddingAlgorithm": "infinite"}
    return {
        "exportShaderParams": False,
        "exportPath": export_path,
        "defaultExportPreset": "RwG_PBR",
        "exportPresets": [preset],
        "exportList": _export_list(),
        "exportParameters": [{"parameters": params}],
    }


def export_project_maps(export_path, plan, log):
    os.makedirs(export_path, exist_ok=True)
    config = build_export_config(export_path, plan)
    log("[RwG] Exporting: " + ", ".join(o["srcName"] for o in plan))
    result = substance_painter.export.export_project_textures(config)
    if str(getattr(result, "status", "")).endswith("Error"):
        raise RuntimeError(f"Painter export failed: {getattr(result, 'message', '')}")
    paths = []
    try:
        for _stack, files in result.textures.items():
            paths.extend(files)
    except Exception:
        pass
    return paths


def export_with_preset(export_path, preset_name, shelf, log):
    """Run one of the user's own saved export presets (output templates)."""
    if spresource is None:
        raise RuntimeError("substance_painter.resource not available in this version.")
    os.makedirs(export_path, exist_ok=True)

    contexts = [shelf] if shelf else []
    for c in ("your_assets", "starter_assets", "allegorithmic", "project"):
        if c not in contexts:
            contexts.append(c)

    last_err = None
    for ctx in contexts:
        try:
            rid = spresource.ResourceID(context=ctx, name=preset_name)
            config = {
                "exportShaderParams": False,
                "exportPath": export_path,
                "defaultExportPreset": rid.url(),
                "exportList": _export_list(),
                "exportParameters": [{"parameters": {"fileFormat": "tga", "bitDepth": "8"}}],
            }
            result = substance_painter.export.export_project_textures(config)
            if str(getattr(result, "status", "")).endswith("Error"):
                last_err = getattr(result, "message", "export error")
                continue
            paths = []
            for _stack, files in result.textures.items():
                paths.extend(files)
            if paths:
                log(f"[RwG] Used preset '{preset_name}' from shelf '{ctx}'.")
                return paths
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Could not run preset '{preset_name}': {last_err}")


def maps_from_export_paths(paths):
    found = {}
    # order matters: check 'view2d' before generic tokens
    picks = [("view2d", "view2d"), ("diffuse", "diffuse"), ("basecolor", "basecolor"),
             ("glossiness", "glossiness"), ("specular", "specular"),
             ("normal", "normal"), ("height", "height"),
             ("roughness", "roughness"), ("metallic", "metallic"),
             ("emissive", "emissive"), ("emmisive", "emissive"),
             ("opacity", "opacity"),
             ("user0", "user0"), ("user1", "user1"), ("user2", "user2"),
             ("_ao", "ao"), ("ao", "ao")]
    for p in paths:
        low = os.path.basename(p).lower()
        for token, kind in picks:
            if token in low and kind not in found:
                found[kind] = p
    return found


def _vec_str(vec):
    return ",".join(str(x) for x in vec)


def _parse_vec(text):
    return [x.strip() for x in text.split(",") if x.strip()]


def _parse_fresnel_nk(fresnel_str, default=("0.4", "0.2")):
    """Pull the N and K out of a fresnel(...) string."""
    m = re.search(r"fresnel\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", fresnel_str or "")
    if m:
        return m.group(1), m.group(2)
    return default


def _replace_stage_texture(content, stage, texture):
    """Swap the texture of a given Stage{n} in an .rvmat, leaving everything else
    exactly as-is. Returns (new_content, num_replacements)."""
    pattern = r'(class Stage%d\s*\{[^}]*?\btexture=)"[^"]*";' % stage
    return re.subn(
        pattern,
        lambda m: m.group(1) + '"' + texture + '";',
        content, flags=re.DOTALL)


def _build_fresnel(n, k, fmt="ai", w="64", h="64", levels="1"):
    """Build the Stage6 fresnel string from N and K (+ optional texture header)."""
    n = (n or "").strip() or "0.4"
    k = (k or "").strip() or "0.2"
    fmt = (fmt or "ai").strip() or "ai"
    w = str(w or "64").strip() or "64"
    h = str(h or "64").strip() or "64"
    levels = str(levels or "1").strip() or "1"
    return f"#({fmt},{w},{h},{levels})fresnel({n},{k})"


class FresnelCurve(QtWidgets.QWidget):
    """Live Fresnel reflectance-vs-angle preview (pure Python, no numpy).

    Mirrors the 'Configure Fresnel' plot from the RwG RVMAT Creator: the plotted
    x axis runs 0..90 degrees with grazing on the left and normal incidence on
    the right, reflectance 0..100 % on y.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._n = 1.5
        self._k = 0.01
        self.setMinimumHeight(170)
        self.setMinimumWidth(320)

    def set_nk(self, n, k):
        try:
            self._n = max(0.001, float(n))
            self._k = max(0.0, float(k))
        except (TypeError, ValueError):
            return
        self.update()

    @staticmethod
    def _reflectance(n, k, deg):
        # Exact conductor (complex-IOR) Fresnel from the BI Super shader wiki:
        #   a^2,b^2 from (n,k,theta); FS = s-pol, FP = p-pol; result = (FS+FP)/2.
        # Matches what DayZ's fresnel stage stores, so the curve is game-accurate.
        s = math.radians(deg)
        cs = math.cos(s)
        sn = math.sin(s)
        if cs <= 1e-6:                      # grazing -> total reflection
            return 1.0
        n2k2 = n * n - k * k
        base = n2k2 - sn * sn
        root = math.sqrt(max(0.0, base * base + 4.0 * n * n * k * k))
        a2 = max(0.0, (root + base) / 2.0)
        b2 = max(0.0, (root - base) / 2.0)
        aa = math.sqrt(a2)
        fs_den = a2 + b2 + 2.0 * aa * cs + cs * cs
        fs = (a2 + b2 - 2.0 * aa * cs + cs * cs) / fs_den if fs_den else 0.0
        st = sn * (sn / cs)                 # sin*tan = sin^2/cos
        fp_den = a2 + b2 + 2.0 * aa * st + st * st
        fp = fs * (a2 + b2 - 2.0 * aa * st + st * st) / fp_den if fp_den else 0.0
        return min(1.0, max(0.0, (fs + fp) / 2.0))

    def paintEvent(self, event):
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 42, 12, 10, 22
        gx, gy = ml, mt
        gw, gh = max(1, w - ml - mr), max(1, h - mt - mb)

        qp.fillRect(0, 0, w, h, QtGui.QColor(30, 32, 34))
        qp.fillRect(gx, gy, gw, gh, QtGui.QColor(22, 24, 26))

        grid_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 26))
        grid_pen.setWidth(1)
        qp.setPen(grid_pen)
        for i in range(5):
            y = gy + gh - int(gh * i / 4.0)
            qp.drawLine(gx, y, gx + gw, y)
        for i in range(7):
            x = gx + int(gw * i / 6.0)
            qp.drawLine(x, gy, x, gy + gh)

        qp.setPen(QtGui.QColor(160, 165, 170))
        f = qp.font()
        f.setPointSize(7)
        qp.setFont(f)
        qp.drawText(4, gy + 9, "100%")
        qp.drawText(12, gy + gh, "0%")
        qp.drawText(gx - 3, h - 6, "graz.")
        qp.drawText(gx + gw - 26, h - 6, "normal")

        path = QtGui.QPainterPath()
        steps = 90
        for i in range(steps + 1):
            frac = i / float(steps)
            deg = 90.0 - frac * 90.0          # left = grazing, right = normal
            r = self._reflectance(self._n, self._k, deg)
            px = gx + frac * gw
            py = gy + gh - r * gh
            path.moveTo(px, py) if i == 0 else path.lineTo(px, py)

        fill = QtGui.QPainterPath(path)
        fill.lineTo(gx + gw, gy + gh)
        fill.lineTo(gx, gy + gh)
        fill.closeSubpath()
        qp.fillPath(fill, QtGui.QColor(228, 20, 31, 90))

        pen = QtGui.QPen(QtGui.QColor(255, 90, 98))
        pen.setWidth(2)
        qp.setPen(pen)
        qp.drawPath(path)

        f0 = self._reflectance(self._n, self._k, 0.0)
        qp.setPen(QtGui.QColor(215, 218, 220))
        qp.drawText(gx + 6, gy + 12, f"F0 (normal) = {f0 * 100:.1f}%")
        qp.end()


# --------------------------------------------------------------------------- #
#  UI                                                                          #
# --------------------------------------------------------------------------- #
class RwGDock(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(PLUGIN_TITLE)
        self.s = load_settings()
        self.rvmat_path = None
        self.watcher = QtCore.QFileSystemWatcher()
        self.watcher.fileChanged.connect(self._on_rvmat_changed)
        self._build()
        self._subscribe_project_events()

    def _subscribe_project_events(self):
        """Reload settings from the project (or defaults for a new project) when a
        project is opened or created."""
        self._evt_conns = []
        try:
            import substance_painter.event as spevent
            for name in ("ProjectOpened", "ProjectCreated", "ProjectEditionEntered"):
                evt = getattr(spevent, name, None)
                if evt is not None:
                    spevent.DISPATCHER.connect(evt, self._on_project_event)
                    self._evt_conns.append(evt)
        except Exception as e:
            splog.warning(f"[RwG] Could not subscribe to project events: {e}")

    def _unsubscribe_project_events(self):
        try:
            import substance_painter.event as spevent
            for evt in getattr(self, "_evt_conns", []):
                try:
                    spevent.DISPATCHER.disconnect(evt, self._on_project_event)
                except Exception:
                    pass
            self._evt_conns = []
        except Exception:
            pass

    def _on_project_event(self, *_):
        try:
            self.s = load_settings()          # per-project values, or defaults if none
            self._rebuild_ui(keep_fields=False)
            self.status.setText("Loaded settings for this project.")
        except Exception as e:
            splog.warning(f"[RwG] Project-event refresh failed: {e}")

    # ---------- small builders ----------
    def _path_row(self, layout, label, key, is_dir=False):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit(self.s.get(key, ""))
        row.addWidget(edit)
        btn = QtWidgets.QPushButton("...")
        btn.setFixedWidth(30)

        def browse():
            if is_dir:
                p = QtWidgets.QFileDialog.getExistingDirectory(self, label)
            else:
                p, _ = QtWidgets.QFileDialog.getOpenFileName(self, label)
            if p:
                edit.setText(p)
        btn.clicked.connect(browse)
        row.addWidget(btn)
        layout.addLayout(row)
        return edit

    def _browse(self, edit, is_dir=False):
        if is_dir:
            p = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder")
        else:
            p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")
        if p:
            edit.setText(p)

    def _res_combo(self, key, default):
        c = QtWidgets.QComboBox()
        c.addItems(RES_OPTIONS)
        c.setCurrentText(str(self.s.get(key, default)))
        c.setFixedWidth(70)
        return c

    def _preview_btn(self, kind):
        """Small eye button on a map row: previews that map in Painter."""
        b = QtWidgets.QPushButton()
        b.setObjectName("mini")
        b.setIcon(self._icon("eye"))
        b.setIconSize(QtCore.QSize(14, 14))
        b.setFixedSize(MINI_BTN, MINI_BTN)
        b.setToolTip(f"Preview _{kind} in Painter — builds it from the current "
                     "project and loads it into a spare User channel (pick that "
                     "channel in the 2D view).")
        b.clicked.connect(lambda: self.on_preview_map(kind))
        return b

    def _labeled_slider(self, caption, key, default):
        """0.00-2.00 horizontal slider with a caption and a live value label.

        Returns (caption_label, slider, value_label). The slider stores an int
        0..200; read the float with ``slider.value() / 100.0``.
        """
        cap = QtWidgets.QLabel(caption)
        cap.setFixedWidth(12)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 200)                 # 0.00 .. 2.00 in 0.01 steps
        slider.setSingleStep(5)                 # arrow keys = 0.05
        slider.setPageStep(25)                  # 0.25
        slider.setMinimumWidth(80)
        slider.setValue(int(round(float(self.s.get(key, default)) * 100)))
        val = QtWidgets.QLabel()
        val.setObjectName("sliderVal")
        val.setFixedWidth(30)
        val.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v: val.setText(f"{v / 100.0:.2f}"))
        val.setText(f"{slider.value() / 100.0:.2f}")
        return cap, slider, val

    # ---------- build ----------
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 4)
        outer.setSpacing(4)
        self.setStyleSheet(DOCK_QSS)
        self.setMinimumWidth(320)

        # title + Settings + help (always visible above the tabs)
        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("RwG DayZ Texture Exporter")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch(1)
        settings_btn = QtWidgets.QPushButton("Settings")
        settings_btn.setToolTip("Tool paths: Python, ImageToPAA, MatEditor")
        settings_btn.clicked.connect(self.on_settings)
        top.addWidget(settings_btn)
        help_btn = QtWidgets.QPushButton("?")
        help_btn.setObjectName("help")
        help_btn.setFixedSize(26, 26)
        help_btn.setToolTip("Quick help & recommended settings")
        help_btn.clicked.connect(self.on_help)
        top.addWidget(help_btn)
        outer.addLayout(top)

        def _make_page():
            sc = QtWidgets.QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QtWidgets.QFrame.NoFrame)
            w = QtWidgets.QWidget()
            sc.setWidget(w)
            lay = QtWidgets.QVBoxLayout(w)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(3)
            return sc, lay

        single = self.s.get("layout_mode", "tabs") == "single"
        if single:
            # one scrolling window (like the classic layout)
            page, single_layout = _make_page()
            outer.addWidget(page, 1)
            setup_layout = maps_layout = rvmat_layout = single_layout
        else:
            # three tabs so nothing needs scrolling on a normal monitor
            tabs = QtWidgets.QTabWidget()
            outer.addWidget(tabs, 1)
            setup_page, setup_layout = _make_page()
            maps_page, maps_layout = _make_page()
            rvmat_page, rvmat_layout = _make_page()
            tabs.addTab(setup_page, "Setup")
            tabs.addTab(maps_page, "Maps")
            tabs.addTab(rvmat_page, "RVMAT")

        layout = setup_layout
        page_layout = setup_layout

        def end_page():
            # separate the three tabs; in single-window mode keep sections flowing
            if not single:
                page_layout.addStretch(1)

        def header(txt):
            # each section is a bordered "card" (QGroupBox) with a green title;
            # widgets added afterwards land inside it via the reassigned `layout`.
            nonlocal layout
            box = QtWidgets.QGroupBox(txt)
            box.setObjectName("section")
            inner = QtWidgets.QVBoxLayout(box)
            inner.setContentsMargins(10, 8, 10, 8)
            inner.setSpacing(3)
            page_layout.addWidget(box)
            layout = inner

        def hint(txt):
            lbl = QtWidgets.QLabel(txt)
            lbl.setObjectName("hint")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            return lbl

        # --- Setup tab ---
        header("Setup")
        self.output_edit = self._path_row(layout, "Output folder:", "output", is_dir=True)

        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("Prefix:"))
        self.prefix_edit = QtWidgets.QLineEdit(self.s.get("prefix", ""))
        prow.addWidget(self.prefix_edit)
        btn_ts = QtWidgets.QPushButton("Use texture set name")
        btn_ts.clicked.connect(self.on_use_texset_name)
        prow.addWidget(btn_ts)
        layout.addLayout(prow)

        # re-detect the .rvmat when output/prefix change
        self.output_edit.editingFinished.connect(lambda: self._detect_rvmat())
        self.prefix_edit.editingFinished.connect(lambda: self._detect_rvmat())

        # export mode
        mrow = QtWidgets.QHBoxLayout()
        mrow.addWidget(QtWidgets.QLabel("Export mode:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["Built-in maps", "Painter preset"])
        self.mode_combo.setCurrentText("Painter preset" if self.s.get("mode") == "preset"
                                       else "Built-in maps")
        mrow.addWidget(self.mode_combo)
        mrow.addWidget(QtWidgets.QLabel("Preset:"))
        self.painter_preset_edit = QtWidgets.QLineEdit(self.s.get("painter_preset", "DayZ"))
        self.painter_preset_edit.setFixedWidth(90)
        mrow.addWidget(self.painter_preset_edit)
        mrow.addWidget(QtWidgets.QLabel("Shelf:"))
        self.preset_shelf_edit = QtWidgets.QLineEdit(self.s.get("preset_shelf", "your_assets"))
        self.preset_shelf_edit.setFixedWidth(90)
        mrow.addWidget(self.preset_shelf_edit)
        layout.addLayout(mrow)
        self.mode_combo.currentTextChanged.connect(self._update_mode_fields)
        hint("Built-in = plugin builds the maps.   "
             "Painter preset = run your own DayZ output template as-is.")

        # --- Maps tab ---
        end_page()
        page_layout = maps_layout
        header("Maps  (built-in mode: tick = export, size per map)")

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)      # middle controls take the slack
        grid.addWidget(QtWidgets.QLabel("size"), 0, 2)   # single aligned header

        def middle(*widgets):
            box = QtWidgets.QHBoxLayout()
            for w in widgets:
                box.addWidget(w) if not isinstance(w, str) else box.addWidget(QtWidgets.QLabel(w))
            box.addStretch(1)
            return box

        # _co
        self.co_cb = QtWidgets.QCheckBox("_co")
        self.co_cb.setChecked(self.s.get("co_on", True))
        self.co_source = QtWidgets.QComboBox()
        self.co_source.addItems(["Base Color - metals keep color (recommended)",
                                 "Diffuse (metals black)", "2D View", "Base Color + Specular",
                                 "Spec/Gloss diffuse, glTF (metals black)"])
        self.co_source.setToolTip(
            "How the _co is built. Key question: does the metal colour stay in the _co,\n"
            "or go black (then the metal look rides on specular[] + fresnel + env)?\n"
            "  Diffuse - Painter's metal/rough diffuse: metals go BLACK.\n"
            "  2D View - the flattened 2D viewport.\n"
            "  Base Color - raw albedo: metals KEEP their colour (recommended).\n"
            "  Base Color + Specular - albedo dimmed by specular; metals keep colour.\n"
            "  Spec/Gloss diffuse (glTF) - canonical baseColor*(1-0.04)*(1-metallic): "
            "metals black, dielectrics keep 96%.")
        self.co_source.setCurrentText({"diffuse": "Diffuse (metals black)",
                                       "2d_view": "2D View",
                                       "base_color": "Base Color - metals keep color (recommended)",
                                       "base_color_specular": "Base Color + Specular",
                                       "specgloss": "Spec/Gloss diffuse, glTF (metals black)"}.get(
                                           self.s.get("co_source", "base_color"),
                                           "Base Color - metals keep color (recommended)"))
        # alpha toggle: off = _co, on = _ca (same source, plus an Opacity alpha)
        self.co_alpha_cb = QtWidgets.QCheckBox("alpha (_ca)")
        self.co_alpha_cb.setChecked(self.s.get("co_alpha", False))
        self.co_alpha_cb.setToolTip("Add an alpha channel (from the Opacity channel) and "
                                    "export as _ca instead of _co - for transparent "
                                    "materials (glass, foliage).")
        self.co_res = self._res_combo("co_res", "2048")
        grid.addWidget(self.co_cb, 1, 0)
        grid.addLayout(middle(self.co_source, self.co_alpha_cb), 1, 1)
        grid.addWidget(self.co_res, 1, 2)

        # _nohq
        self.nohq_cb = QtWidgets.QCheckBox("_nohq")
        self.nohq_cb.setChecked(self.s.get("nohq_on", True))
        self.normal_combo = QtWidgets.QComboBox()
        self.normal_combo.addItems(["opengl", "directx"])
        self.normal_combo.setCurrentText(get_project_normal_format(
            self.s.get("normal_format", "directx")))
        self.normal_combo.currentTextChanged.connect(self.on_normal_changed)
        self.nohq_res = self._res_combo("nohq_res", "2048")
        grid.addWidget(self.nohq_cb, 2, 0)
        grid.addLayout(middle("normal:", self.normal_combo), 2, 1)
        grid.addWidget(self.nohq_res, 2, 2)

        # _smdi
        self.smdi_cb = QtWidgets.QCheckBox("_smdi")
        self.smdi_cb.setChecked(self.s.get("smdi_on", True))
        self.smdi_source = QtWidgets.QComboBox()
        self.smdi_source.addItems(["DayZ shader-matched (recommended)",
                                   "Met->Spec/Gloss, glTF",
                                   "Spec+Gloss (converted maps)", "Met+Rough (flat metal spec)",
                                   "Met+Rough+BaseColor, PBR (per-metal spec)"])
        self.smdi_source.setCurrentText(
            {"dayz": "DayZ shader-matched (recommended)",
             "metrough": "Met+Rough (flat metal spec)",
             "pbr": "Met+Rough+BaseColor, PBR (per-metal spec)",
             "gltf": "Met->Spec/Gloss, glTF"}.get(
                self.s.get("smdi_source"), "Spec+Gloss (converted maps)"))
        self.smdi_source.setToolTip(
            "How the _smdi (specular level + gloss) is built:\n"
            "  DayZ shader-matched, recommended - measured against the game's Super shader: "
            "G = the pixel's F0 relative to the rvmat fresnel stage (which already carries "
            "F0), times gloss; B = GGX-equivalent exponent / specularPower. Uses the "
            "specularPower and fresnel N/K from the Material panel - set specularPower with "
            "its estimate button first.\n"
            "  Spec+Gloss (converted maps) - Painter's converted Specular + Glossiness. "
            "Works in a Metallic/Roughness project too (Painter converts them).\n"
            "  Met+Rough (flat metal spec) - built straight from your metallic + roughness "
            "channels; every metal goes to a flat full specular.\n"
            "  Met+Rough+BaseColor, PBR (per-metal spec) - physically-based: each metal gets "
            "its own reflectance from the base-colour luminance (dull metal stays darker than "
            "polished). Dielectrics keep the 0.04 floor.\n"
            "  Met->Spec/Gloss (glTF) - the canonical glTF conversion: G = perceived "
            "brightness of mix(0.04, baseColor, metallic). Like PBR, canonical metric. "
            "(The non-DayZ methods write F0 into G, which the shader multiplies with the "
            "fresnel stage again - reflections come out much weaker than intended.)")
        self.smdi_res = self._res_combo("smdi_res", "2048")
        # _smdi - the G (specular) / B (gloss) sliders sit inline on this row, in
        # the gap between the source dropdown and the size combo. They also scale
        # the _dtsmdi G/B, so they stay always available.
        smdi_mid = QtWidgets.QHBoxLayout()
        smdi_mid.setSpacing(6)
        smdi_mid.addWidget(self.smdi_source)
        smdi_mid.addSpacing(10)
        g_cap, self.smdi_green, g_val = self._labeled_slider("G", "smdi_green", 1.0)
        smdi_mid.addWidget(g_cap)
        smdi_mid.addWidget(self.smdi_green, 1)
        smdi_mid.addWidget(g_val)
        smdi_mid.addSpacing(10)
        b_cap, self.smdi_blue, b_val = self._labeled_slider("B", "smdi_blue", 1.0)
        smdi_mid.addWidget(b_cap)
        smdi_mid.addWidget(self.smdi_blue, 1)
        smdi_mid.addWidget(b_val)
        grid.addWidget(self.smdi_cb, 3, 0)
        grid.addLayout(smdi_mid, 3, 1)
        grid.addWidget(self.smdi_res, 3, 2)

        # _dtsmdi (Detail + SMDI) - directly under _smdi; for the Multimaterial
        # shader. R = detail from the normal, G/B = same as _smdi. The Detail (R)
        # strength slider sits inline on this row, before the size combo.
        self.dtsmdi_cb = QtWidgets.QCheckBox("_dtsmdi")
        self.dtsmdi_cb.setChecked(self.s.get("dtsmdi_on", False))
        self.dtsmdi_cb.setToolTip(
            "Detail + SMDI map for the DayZ Multimaterial shader.\n"
            "  R = a fine detail map from height + baked mesh + normal (avg ~0.5)\n"
            "  G = specular level, B = gloss  - built exactly like the _smdi above\n"
            "     (uses the same _smdi method + the G/B sliders).\n"
            "Needs metallic + roughness (+ base colour for the glTF/PBR method);\n"
            "the normal supplies the detail. Written as <prefix>_dtsmdi.")
        self.dtsmdi_res = self._res_combo("dtsmdi_res", "2048")
        dt_mid = QtWidgets.QHBoxLayout()
        dt_mid.setSpacing(6)
        dt_mid.addWidget(QtWidgets.QLabel("(Multimaterial)"))
        dt_mid.addSpacing(10)
        self.dtsmdi_strength_lbl = QtWidgets.QLabel("Detail")
        self.dtsmdi_strength_lbl.setToolTip(
            "Scales how pronounced the _dtsmdi detail (red channel) is.\n"
            "The map always stays centred on 0.5 (BI's 'average 0.5, fades in\n"
            "the mipmaps' rule) - this only changes the amplitude of the detail,\n"
            "not its mid-point. 1.00 = default; higher = crisper, lower = subtler.")
        dt_mid.addWidget(self.dtsmdi_strength_lbl)
        d_cap, self.dtsmdi_strength, d_val = self._labeled_slider(
            "R", "dtsmdi_strength", 1.0)
        d_cap.setToolTip(self.dtsmdi_strength_lbl.toolTip())
        dt_mid.addWidget(d_cap)
        dt_mid.addWidget(self.dtsmdi_strength, 1)
        dt_mid.addWidget(d_val)
        grid.addWidget(self.dtsmdi_cb, 4, 0)
        grid.addLayout(dt_mid, 4, 1)
        grid.addWidget(self.dtsmdi_res, 4, 2)

        # enable the Detail (R) strength widgets only when _dtsmdi is ticked
        _dt_strength_widgets = (self.dtsmdi_strength_lbl, d_cap,
                                self.dtsmdi_strength, d_val)

        def _sync_dtsmdi_strength(*_):
            on = self.dtsmdi_cb.isChecked()
            for w in _dt_strength_widgets:
                w.setEnabled(on)
        self.dtsmdi_cb.toggled.connect(_sync_dtsmdi_strength)
        _sync_dtsmdi_strength()

        # _as
        self.as_cb = QtWidgets.QCheckBox("_as")
        self.as_cb.setChecked(self.s.get("as_on", True))
        self.as_res = self._res_combo("as_res", "1024")
        grid.addWidget(self.as_cb, 5, 0)
        grid.addLayout(middle("(DayZ standard)"), 5, 1)
        grid.addWidget(self.as_res, 5, 2)

        # _em (emissive) - off by default
        self.em_cb = QtWidgets.QCheckBox("_em")
        self.em_cb.setChecked(self.s.get("em_on", False))
        self.em_res = self._res_combo("em_res", "1024")
        grid.addWidget(self.em_cb, 6, 0)
        grid.addLayout(middle("(Emissive channel)"), 6, 1)
        grid.addWidget(self.em_res, 6, 2)

        # _mc (macro) - off by default; RGB from a Painter User channel
        self.mc_cb = QtWidgets.QCheckBox("_mc")
        self.mc_cb.setChecked(self.s.get("mc_on", False))
        self.mc_source = QtWidgets.QComboBox()
        self.mc_source.addItems(["User0", "User1", "User2", "Combine (User0-2)"])
        self.mc_source.setCurrentText(self.s.get("mc_source", "User0"))
        self.mc_source.setToolTip("Painter User channel to export as the macro (_mc), "
                                  "or Combine to stack User0-2 together.")
        self.mc_blend = QtWidgets.QComboBox()
        self.mc_blend.addItems(["Lighten", "Screen", "Add", "Overlay",
                                "Average", "Multiply", "Darken"])
        self.mc_blend.setCurrentText(self.s.get("mc_blend", "Lighten"))
        self.mc_blend.setToolTip("Blend mode when combining User channels. "
                                 "Lighten / Screen / Add treat black as neutral, so you "
                                 "can paint parts of the macro across different channels.")
        self.mc_alpha = QtWidgets.QComboBox()
        self.mc_alpha.addItems(["Auto (macro)", "None", "User0", "User1", "User2", "Opacity"])
        self.mc_alpha.setCurrentText(self.s.get("mc_alpha", "Auto (macro)"))
        self.mc_alpha.setToolTip("The _mc alpha = DayZ blend mask (1 = only macro, "
                                 "0 = only base). Auto derives it from the macro's "
                                 "brightness (applies where you painted); or pick a "
                                 "channel; None = opaque.")
        self.mc_res = self._res_combo("mc_res", "2048")
        grid.addWidget(self.mc_cb, 7, 0)
        grid.addLayout(middle("from", self.mc_source, self.mc_blend,
                              "a:", self.mc_alpha), 7, 1)
        grid.addWidget(self.mc_res, 7, 2)

        # per-map preview (col 3): an eye button on every map row that loads that
        # map into a spare User channel for inspection in Painter's 2D view, plus
        # a clear button in the header row.
        pv_clear = QtWidgets.QPushButton("✕")
        pv_clear.setObjectName("mini")
        pv_clear.setFixedSize(MINI_BTN, MINI_BTN)
        pv_clear.setToolTip("Remove the map preview layer from Painter.")
        pv_clear.clicked.connect(self.on_clear_preview)
        grid.addWidget(pv_clear, 0, 3, QtCore.Qt.AlignHCenter)
        for _r, _k in ((1, "co"), (2, "nohq"), (3, "smdi"), (4, "dtsmdi"),
                       (5, "as"), (6, "em"), (7, "mc")):
            grid.addWidget(self._preview_btn(_k), _r, 3)

        layout.addLayout(grid)

        hint("SMDI tuning: G scales specular, B scales gloss (1.00 = unchanged); "
             "Detail sets the _dtsmdi detail strength.   The eye button on each map "
             "row previews it in Painter; ✕ removes the preview.")

        # --- paa + export ---
        header("Export  (.tga is always written; .paa optional)")

        # Export option (applies to the buttons below): after an export, also
        # write the produced texture paths into the RVMAT NOHQ/AS/SMDI/MC fields.
        # Off => export textures only, leave the rvmat untouched (you can still
        # fill it later with "Auto-fill from export" on the RVMAT tab).
        self.autofill_cb = QtWidgets.QCheckBox(
            "Also fill the RVMAT texture fields (NOHQ / AS / SMDI / MC)")
        self.autofill_cb.setChecked(self.s.get("autofill_on_export", True))
        self.autofill_cb.setToolTip(
            "On  - after an export, fill the RVMAT texture paths with what was\n"
            "      just exported (the old behaviour).\n"
            "Off - export the textures only and leave the RVMAT fields alone;\n"
            "      use this when you just want the maps, not an rvmat update.\n"
            "The 'Auto-fill from export' button on the RVMAT tab always works\n"
            "regardless of this checkbox.")
        layout.addWidget(self.autofill_cb)

        b1 = QtWidgets.QHBoxLayout()
        for text, fn in (("Export .tga", lambda: self._do_export(False)),
                         ("Export .tga + .paa", lambda: self._do_export(True)),
                         ("Export .paa", lambda: self._do_export(True))):
            btn = QtWidgets.QPushButton(text)
            if text == "Export .tga + .paa":
                btn.setObjectName("primary")
            btn.clicked.connect(fn)
            b1.addWidget(btn)
        layout.addLayout(b1)

        # standalone batch utility - convert an existing folder of .tga to .paa
        conv_hint = QtWidgets.QLabel("Batch tool \u2014 independent of the export above:")
        conv_hint.setStyleSheet("color:#9aa0a6;")
        layout.addWidget(conv_hint)
        folder_btn = QtWidgets.QPushButton("Convert .tga \u2192 .paa (folder)")
        folder_btn.clicked.connect(self.on_convert_folder_paa)
        layout.addWidget(folder_btn)

        # --- RVMAT tab ---
        end_page()
        page_layout = rvmat_layout
        header("RVMAT")

        rext = QtWidgets.QHBoxLayout()
        rext.addWidget(QtWidgets.QLabel("Texture paths use:"))
        self.tex_ext_combo = QtWidgets.QComboBox()
        self.tex_ext_combo.addItems([".paa", ".tga"])
        self.tex_ext_combo.setCurrentText("." + self.s.get("tex_ext", "tga"))
        self.tex_ext_combo.setToolTip(
            "Which file extension the .rvmat points its texture stages at.\n"
            ".paa is the packed texture the game loads; .tga is the raw file,\n"
            "handy while you preview and iterate.")
        self.tex_ext_combo.currentTextChanged.connect(
            lambda _=None: self._update_all_tex_lights())
        rext.addWidget(self.tex_ext_combo)
        ext_hint = QtWidgets.QLabel(".paa = game  ·  .tga = preview")
        ext_hint.setStyleSheet("color:#9aa0a6;")
        rext.addWidget(ext_hint)
        rext.addSpacing(12)
        use_tex_btn = QtWidgets.QPushButton("Auto-fill from export")
        use_tex_btn.setToolTip(
            "Fill the NOHQ / AS / SMDI paths below with the textures this plugin\n"
            "exports (output folder + prefix), stored mod-relative, using the\n"
            "extension chosen on the left. Use it after an export.")
        use_tex_btn.clicked.connect(self.on_use_textures_inside)
        rext.addWidget(use_tex_btn)
        rext.addStretch(1)
        layout.addLayout(rext)

        self.nohq_ref = self._tex_row(layout, "NOHQ:", "NOHQ")
        self.as_ref = self._tex_row(layout, "AS:", "AS")
        self.smdi_ref = self._tex_row(layout, "SMDI:", "SMDI")
        self.mc_ref = self._tex_row(layout, "MC:", "MC")
        self._update_all_tex_lights()

        # the material block (preset -> env) is its own separate card
        header("Material")

        # one preset row: built-in presets + your saved presets in a single
        # grouped dropdown. Load applies the full material values; Save stores
        # the current values as one of your presets; the cross deletes yours.
        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(4)
        prow.addWidget(QtWidgets.QLabel("Preset:"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.setToolTip(
            "Material presets. The '- Presets -' group is built in (metals etc.); "
            "the '- My presets -' group is yours. Load fills all material values; "
            "Save stores the current values as one of your presets.")
        self._populate_preset_combo(select=self.s.get("preset", "Default"))
        prow.addWidget(self.preset_combo, 1)
        load_btn = QtWidgets.QPushButton("Load")
        load_btn.setToolTip("Fill the material value fields below from the selected preset.")
        load_btn.clicked.connect(self.on_load_preset)
        prow.addWidget(load_btn)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setToolTip("Save the current material values (ambient/diffuse/"
                            "forcedDiffuse/emmisive/specular/specularPower/fresnel/env) "
                            "as one of your presets (asks for a name).")
        save_btn.clicked.connect(self.on_save_user_preset)
        prow.addWidget(save_btn)
        del_btn = QtWidgets.QPushButton("✕")
        del_btn.setObjectName("mini")
        del_btn.setFixedSize(MINI_BTN, MINI_BTN)
        del_btn.setToolTip("Delete the selected preset (only your own presets).")
        del_btn.clicked.connect(self.on_delete_user_preset)
        prow.addWidget(del_btn)
        layout.addLayout(prow)

        # material values - each its own editable text field
        tint_tip = ("Estimate: average (linearised) base colour as a tint. Use when _co "
                    "is black/metal and the colour comes from this value (like the metal "
                    "presets). If _co carries the colour, keep 1,1,1,1 instead.")
        reset_tip = "Reset to the neutral multiplier 1,1,1,1."
        self.mat_ambient = self._val_row(
            layout, "ambient", "mat_ambient", "1,1,1,1",
            buttons=[("", self.on_estimate_ambient_tint, tint_tip, 26, "droplet")],
            color_title="ambient")
        self.mat_diffuse = self._val_row(
            layout, "diffuse", "mat_diffuse", "1,1,1,1",
            buttons=[("", self.on_estimate_diffuse_tint, tint_tip, 26, "droplet")],
            color_title="diffuse")
        self.mat_forced = self._val_row(
            layout, "forcedDiffuse", "mat_forced", "0,0,0,1", color_title="forcedDiffuse")
        self.mat_emmisive = self._val_row(
            layout, "emmisive", "mat_emmisive", "0,0,0,0",
            buttons=[("", self.on_estimate_emmisive,
                      "Estimate from the project's Emissive channel (avg glow colour).", 26, "spark")],
            color_title="emmisive")
        self.mat_specular = self._val_row(
            layout, "specular", "mat_specular", "1,1,1,1",
            buttons=[("", self.on_estimate_specular_tint,
                      "Estimate the specular tint from the metal reflectance "
                      "(glTF F0 = mix(0.04, base colour, metallic), averaged over "
                      "the metallic pixels). For brass/copper etc.", 26, "droplet")],
            color_title="specular")
        self.mat_power = self._val_row(
            layout, "specularPower", "mat_power", "30.0",
            buttons=[("", self.on_estimate_specular_power,
                      "Heuristic estimate from the average roughness (smoother = higher). "
                      "A starting point - tune to taste.", 26, "spark")])

        # fresnel as separate N and K fields -> #(ai,64,64,1)fresnel(N,K)
        frow = QtWidgets.QHBoxLayout()
        flbl = QtWidgets.QLabel("fresnel")
        flbl.setFixedWidth(92)
        frow.addWidget(flbl)
        frow.addWidget(QtWidgets.QLabel("N"))
        self.mat_fresnel_n = QtWidgets.QLineEdit(str(self.s.get("mat_fresnel_n", "0.4")))
        frow.addWidget(self.mat_fresnel_n)
        frow.addWidget(QtWidgets.QLabel("K"))
        self.mat_fresnel_k = QtWidgets.QLineEdit(str(self.s.get("mat_fresnel_k", "0.2")))
        frow.addWidget(self.mat_fresnel_k)
        tip = ("Fresnel N/K -> #(ai,64,64,1)fresnel(N,K). "
               "Metals: Gold 0.3/3, Iron 3.12/3.87, Aluminum 1.3/7, Copper 2.08/7.15 ...")
        self.mat_fresnel_n.setToolTip(tip)
        self.mat_fresnel_k.setToolTip(tip)
        fresnel_btn = QtWidgets.QPushButton()
        fresnel_btn.setObjectName("mini")
        fresnel_btn.setIcon(self._icon("curve"))
        fresnel_btn.setIconSize(QtCore.QSize(14, 14))
        fresnel_btn.setFixedSize(MINI_BTN, MINI_BTN)
        fresnel_btn.setToolTip("Curve editor: drag N/K and see the reflectance "
                               "curve update live.")
        fresnel_btn.clicked.connect(self.on_fresnel_editor)
        frow.addWidget(fresnel_btn)
        layout.addLayout(frow)

        # material library: set fresnel N/K + specular tint from a named material
        # (BI-correct metals + refractiveindex.info metals & dielectrics).
        mlrow = QtWidgets.QHBoxLayout()
        mlrow.setSpacing(4)
        mllbl = QtWidgets.QLabel("material N/K")
        mllbl.setFixedWidth(92)
        mlrow.addWidget(mllbl)
        self.fresnel_mat_combo = QtWidgets.QComboBox()
        self.fresnel_mat_combo.setToolTip(
            "Set fresnel N/K + the specular tint from a material. The "
            "'- Materials -' group is built in (BI metals + refractiveindex.info "
            "metals & dielectrics); '- My materials -' is yours. Apply writes N, K "
            "and specular; Save stores the current N/K + specular as a material.")
        self._populate_fresnel_combo()
        mlrow.addWidget(self.fresnel_mat_combo, 1)
        apply_mat_btn = QtWidgets.QPushButton("Apply")
        apply_mat_btn.setToolTip("Write this material's N, K and specular tint "
                                 "into the fields above.")
        apply_mat_btn.clicked.connect(self.on_apply_fresnel_material)
        mlrow.addWidget(apply_mat_btn)
        save_mat_btn = QtWidgets.QPushButton("Save")
        save_mat_btn.setToolTip("Save the current fresnel N/K + specular tint as "
                                "your own material (asks for a name).")
        save_mat_btn.clicked.connect(self.on_save_fresnel_material)
        mlrow.addWidget(save_mat_btn)
        del_mat_btn = QtWidgets.QPushButton("✕")
        del_mat_btn.setObjectName("mini")
        del_mat_btn.setFixedSize(MINI_BTN, MINI_BTN)
        del_mat_btn.setToolTip("Delete the selected material (only your own).")
        del_mat_btn.clicked.connect(self.on_delete_fresnel_material)
        mlrow.addWidget(del_mat_btn)
        layout.addLayout(mlrow)

        # env (Stage7) - dropdown of the dz\data\data environment maps
        erow = QtWidgets.QHBoxLayout()
        elbl = QtWidgets.QLabel("env")
        elbl.setFixedWidth(92)
        erow.addWidget(elbl)
        self.env_combo = QtWidgets.QComboBox()
        self.env_combo.setEditable(True)
        self.env_combo.addItems(rvmat_writer.ENV_MAPS)
        self.env_combo.setCurrentText(self.s.get("env") or rvmat_writer.ENV_MAPS[0])
        self.env_combo.setToolTip("Stage7 environment map written into the .rvmat "
                                  "(the reflection cubemap under dz\\data\\data). "
                                  "Editable if you use a custom one.")
        erow.addWidget(self.env_combo)
        hdri_btn = QtWidgets.QPushButton("HDRI")
        hdri_btn.setToolTip(
            "Load an equirectangular HDRI as Painter's viewport environment, to\n"
            "match the in-game lighting while you paint (separate from the rvmat\n"
            "env above, which is the game's reflection map).\n"
            "Click loads the saved HDRI; Shift-click picks a different one.")
        hdri_btn.clicked.connect(self.on_load_env_hdri)
        erow.addWidget(hdri_btn)
        dayz_env_btn = QtWidgets.QPushButton("DayZ env…")
        dayz_env_btn.setToolTip(
            "Reproject a DayZ env image (hemisphere-in-plane) to an "
            "equirectangular\npanorama and load it as the viewport environment "
            "— pick the projection\nmodel by eye in the dialog.")
        dayz_env_btn.clicked.connect(self.on_dayz_env_dialog)
        erow.addWidget(dayz_env_btn)
        layout.addLayout(erow)

        # viewport look: tone mapping + one-click DayZ env
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(QtWidgets.QLabel("Viewport tone:"))
        self.tone_cb = QtWidgets.QComboBox()
        self.tone_cb.addItems(["ACES", "Linear"])
        self.tone_cb.setCurrentText(self.s.get("env_tone", "ACES"))
        self.tone_cb.setToolTip("Painter viewport tone mapping. ACES = filmic "
                                "(closer to the in-game look); Linear = raw.")
        self.tone_cb.currentTextChanged.connect(self.on_set_tone)   # after setCurrentText
        crow.addWidget(self.tone_cb)
        crow.addSpacing(12)
        dz_look = QtWidgets.QPushButton("DayZ look")
        dz_look.setToolTip(
            "One click: build the saved DayZ env panorama, load it as the "
            "viewport\nenvironment and set ACES tone mapping. (Pick the env once "
            "via 'DayZ env…'.\nThe RwG DayZ Super viewport shader is still "
            "assigned manually in\nTexture Set Settings.)")
        dz_look.clicked.connect(self.on_dayz_look)
        crow.addWidget(dz_look)
        crow.addStretch(1)
        layout.addLayout(crow)

        # link to the DayZ In-Game viewport shader (dayz-ingame.glsl)
        srow = QtWidgets.QHBoxLayout()
        self.shader_link_cb = QtWidgets.QCheckBox("Live to DayZ In-Game shader")
        self.shader_link_cb.setChecked(self.s.get("shader_link", True))
        self.shader_link_cb.setToolTip(
            "Send the material values above (and the _smdi method, G/B sliders and\n"
            "macro source) to every texture set using the 'dayz-ingame' viewport\n"
            "shader, live while you edit - the viewport shows what this .rvmat\n"
            "will look like in game.")
        self.shader_link_cb.toggled.connect(lambda on: on and self._push_shader(announce=True))
        srow.addWidget(self.shader_link_cb)
        pull_btn = QtWidgets.QPushButton("From shader")
        pull_btn.setToolTip("Take the values set in the DayZ In-Game shader's settings "
                            "into the fields above.")
        pull_btn.clicked.connect(self.on_pull_shader)
        srow.addWidget(pull_btn)
        srow.addStretch(1)
        layout.addLayout(srow)

        header("Write")           # write / load / MatEditor buttons in their own card

        wrow = QtWidgets.QHBoxLayout()
        write_btn = QtWidgets.QPushButton("Write .rvmat")
        write_btn.setObjectName("primary")
        write_btn.clicked.connect(self.on_write_rvmat)
        wrow.addWidget(write_btn)
        load_btn = QtWidgets.QPushButton("Load existing")
        load_btn.setToolTip("Find <prefix>.rvmat in the output folder and load its values.")
        load_btn.clicked.connect(lambda: self._detect_rvmat(announce=True))
        wrow.addWidget(load_btn)
        cfg_btn = QtWidgets.QPushButton("Config snippet…")
        cfg_btn.setToolTip("Generate the config.cpp block (hiddenSelectionsMaterials "
                           "+ healthLevels) for your named selections (camo, …) "
                           "and this rvmat's damage variants.")
        cfg_btn.clicked.connect(self.on_config_snippet)
        wrow.addWidget(cfg_btn)
        val_btn = QtWidgets.QPushButton("Validate…")
        val_btn.setToolTip("Lint the loaded / a chosen .rvmat: shader IDs, stages, "
                           "texture paths (extension, slashes, existence on P:), "
                           "and common mistakes.")
        val_btn.clicked.connect(self.on_validate_rvmat)
        wrow.addWidget(val_btn)
        layout.addLayout(wrow)

        m1 = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton("Open .rvmat in MatEditor")
        open_btn.clicked.connect(self.on_open_mateditor)
        m1.addWidget(open_btn)
        self.autosync_cb = QtWidgets.QCheckBox("Auto-sync from MatEditor")
        self.autosync_cb.setChecked(self.s.get("autosync", True))
        m1.addWidget(self.autosync_cb)
        layout.addLayout(m1)

        # --- damage variants (adds an _mc, like RwG RVMat Speedo) ---
        header("Damage variants  (base .rvmat + damage _mc)")
        drow = QtWidgets.QHBoxLayout()
        drow.setSpacing(4)
        drow.addWidget(QtWidgets.QLabel("Material:"))
        self.dmg_combo = QtWidgets.QComboBox()
        self.dmg_combo.addItems(list(rvmat_writer.DAMAGE_MC.keys()))
        self.dmg_combo.setToolTip("Material family - picks which damage _mc textures "
                                  "the buttons use.")
        drow.addWidget(self.dmg_combo, 1)
        self.dmg_btns = []
        for _ in range(3):
            b = QtWidgets.QPushButton()
            b.clicked.connect(lambda _=False, i=len(self.dmg_btns): self._on_damage_variant(i))
            drow.addWidget(b)
            self.dmg_btns.append(b)
        layout.addLayout(drow)
        rrow = QtWidgets.QHBoxLayout()
        rrow.setSpacing(8)
        rrow.addWidget(QtWidgets.QLabel("reset to default:"))
        self.dmg_reset = {}
        for name in ("NOHQ", "AS", "SMDI"):
            cb = QtWidgets.QCheckBox(name)
            cb.setToolTip(f"Also reset {name} to its procedural default in the "
                          "damage variant (optional).")
            rrow.addWidget(cb)
            self.dmg_reset[name] = cb
        rrow.addStretch(1)
        layout.addLayout(rrow)
        hint("Uses the current / loaded .rvmat as base, writes "
             "&lt;prefix&gt;&lt;suffix&gt;.rvmat next to it (only the MC changes; tick "
             "above to also reset NOHQ/AS/SMDI).")
        self.dmg_combo.currentTextChanged.connect(self._update_damage_buttons)
        self._update_damage_buttons()

        # --- inline guidance (hover tooltips) ---
        tips = {
            self.output_edit: "Where the DayZ textures land. Best inside your P:\\ mod path "
                              "so the .rvmat gets game-valid texture paths.",
            self.prefix_edit: "File name prefix, e.g. wall -> wall_co.tga. "
                              "'Use texture set name' fills it from the active set.",
            self.mode_combo: "Built-in = the plugin builds the maps. "
                             "Painter preset = run your own saved output template as-is.",
            self.painter_preset_edit: "Name of your saved Painter export preset (e.g. DayZ).",
            self.preset_shelf_edit: "Shelf that holds the preset (usually your_assets).",
            self.co_cb: "Export the _co (color / diffuse) map.",
            self.co_res: "Output resolution for _co.",
            self.nohq_cb: "Export the _nohq (normal) map.",
            self.normal_combo: "DirectX = DayZ. Painter's converted normal = "
                               "normal channel + height + baked mesh normal.",
            self.nohq_res: "Output resolution for _nohq.",
            self.smdi_cb: "Export the _smdi (specular) map.",
            self.smdi_green: "Scales the _smdi Green (specular level). "
                             "Drag right to boost specular. 1.00 = unchanged.",
            self.smdi_blue: "Scales the _smdi Blue (gloss = 1 - roughness). "
                            "1.00 = unchanged.",
            self.smdi_res: "Output resolution for _smdi.",
            self.dtsmdi_cb: "Export the _dtsmdi (Detail + SMDI) for the "
                            "Multimaterial shader. R = detail, G/B like _smdi.",
            self.dtsmdi_res: "Output resolution for _dtsmdi.",
            self.dtsmdi_strength: "Amplitude of the _dtsmdi detail (R) around 0.5. "
                                  "Higher = crisper detail; the map stays centred "
                                  "on 0.5 so it fades in the mipmaps. 1.00 = default.",
            self.as_cb: "Export the _as (ambient shadow). DayZ layout: R/B white, G = mixed AO.",
            self.as_res: "Output resolution for _as. 512 is usually plenty.",
            self.em_cb: "Export the _em (emissive / glow) from the project's Emissive channel.",
            self.em_res: "Output resolution for _em.",
            self.mc_cb: "Export the _mc (macro) from a Painter User channel (RGB).",
            self.mc_res: "Output resolution for _mc.",
            self.co_alpha_cb: "Export _co with an alpha channel (from Opacity) as _ca "
                              "instead - for transparent materials.",
            self.preset_combo: "Material preset for the .rvmat "
                               "(ambient/diffuse/specular/power + fresnel).",
            self.autosync_cb: "When the material editor saves the .rvmat, read the "
                              "changes back into this panel.",
        }
        for widget, tip in tips.items():
            try:
                widget.setToolTip(tip)
            except Exception:
                pass

        page_layout.addStretch(1)         # end RVMAT tab

        # status bar - always visible under the tabs
        self.status = QtWidgets.QLabel("Ready.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        # initial enabled state for preset/shelf, and load an existing .rvmat
        self._update_mode_fields()
        self._detect_rvmat()
        self._wire_shader_link()

    def _labeled_edit(self, layout, label):
        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(46)
        row.addWidget(lbl)
        edit = QtWidgets.QLineEdit()
        row.addWidget(edit)
        layout.addLayout(row)
        return edit

    def _tex_row(self, layout, label, key):
        """A texture reference field + paa/tga availability light + browse + open
        + a 'default' button."""
        if not hasattr(self, "_tex_dots"):
            self._tex_dots, self._tex_edits = {}, {}
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(88)
        row.addWidget(lbl)
        edit = QtWidgets.QLineEdit()
        row.addWidget(edit)
        # paa/tga availability light: green = referenced file on disk, amber = only
        # the other extension exists, red = nothing found, grey = procedural default.
        dot = QtWidgets.QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet("background:#5a5d63; border-radius:6px;")
        row.addWidget(dot)
        self._tex_dots[key] = dot
        self._tex_edits[key] = edit
        edit.textChanged.connect(lambda _=None, k=key: self._update_tex_light(k))
        browse = QtWidgets.QPushButton()
        browse.setObjectName("mini")
        browse.setIcon(self._icon("folder"))
        browse.setIconSize(QtCore.QSize(14, 14))
        browse.setFixedSize(MINI_BTN, MINI_BTN)
        browse.setToolTip(f"Browse for a {label} texture (.paa/.tga); stored mod-relative.")
        browse.clicked.connect(lambda: self._browse_texture(edit))
        openb = QtWidgets.QPushButton()
        openb.setObjectName("mini")
        openb.setIcon(self._icon("eye"))
        openb.setIconSize(QtCore.QSize(14, 14))
        openb.setFixedSize(MINI_BTN, MINI_BTN)
        openb.setToolTip(f"Open the {label} texture in the viewer (TexView / default app).")
        openb.clicked.connect(lambda: self._open_texture(edit))
        btn = QtWidgets.QPushButton("⟳")
        btn.setObjectName("mini")
        btn.setFixedSize(MINI_BTN, MINI_BTN)
        btn.setToolTip(f"Reset {label} to the procedural default "
                       f"({rvmat_writer.DEFAULT_TEXTURES.get(key, '')}).")
        btn.clicked.connect(lambda: edit.setText(rvmat_writer.DEFAULT_TEXTURES.get(key, "")))
        row.addWidget(browse)
        row.addWidget(openb)
        row.addWidget(btn)
        layout.addLayout(row)
        return edit

    def _open_texture(self, edit):
        """Open the referenced texture in TexView (Settings) or the default app."""
        ref = (edit.text() or "").strip()
        if not ref or ref.startswith("#("):
            self.status.setText("No texture file to open."); return
        has_drive = len(ref) >= 2 and ref[1] == ":"
        drive = self.s.get("drive", "P:\\").strip() or "P:\\"
        path = ref if has_drive else paa_tools.abs_from_rel(ref, drive)
        if not os.path.exists(path):
            self.status.setText(f"Texture not found: {path}"); return
        tv = self.s.get("texview", "").strip()
        try:
            if tv and os.path.exists(tv):
                subprocess.Popen([tv, path])
            elif hasattr(os, "startfile"):
                os.startfile(path)          # Windows default association
            else:
                subprocess.Popen(["xdg-open", path])
            self.status.setText(f"Opening {os.path.basename(path)} ...")
        except Exception as e:
            self.status.setText(f"Could not open texture: {e}")

    def _browse_texture(self, edit):
        """Pick a texture file and store it mod-relative (drive stripped)."""
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select texture", "", "Textures (*.paa *.tga);;All files (*)")
        if not p:
            return
        drive = self.s.get("drive", "P:\\").strip() or "P:\\"
        try:
            rel, _ok = paa_tools.mod_relative_path(p, drive_letter=drive)
        except Exception:
            rel = p
        edit.setText(rel)

    def _abs_tex(self, ref):
        """Resolve a texture reference (mod-relative or absolute) to an abs path."""
        ref = (ref or "").strip()
        has_drive = len(ref) >= 2 and ref[1] == ":"
        drive = self.s.get("drive", "P:\\").strip() or "P:\\"
        return ref if has_drive else paa_tools.abs_from_rel(ref, drive)

    def _update_tex_light(self, key):
        """Colour one row's availability light from what's actually on disk."""
        dot = getattr(self, "_tex_dots", {}).get(key)
        edit = getattr(self, "_tex_edits", {}).get(key)
        if dot is None or edit is None:
            return
        GREY, GREEN, AMBER, RED = "#5a5d63", "#3fb56b", "#e0a92e", "#d05a5a"
        ref = (edit.text() or "").strip()
        if not ref or ref.startswith("#("):
            color, tip = GREY, "Procedural default - no texture file to check."
        else:
            base, ext = os.path.splitext(ref)
            ext = ext.lower()
            try:
                paa = os.path.exists(self._abs_tex(base + ".paa"))
                tga = os.path.exists(self._abs_tex(base + ".tga"))
            except Exception:
                paa = tga = False
            want = ext if ext in (".paa", ".tga") else ".paa"
            have_want = paa if want == ".paa" else tga
            detail = ("  .paa " + ("\u2713" if paa else "\u2717")
                      + "    .tga " + ("\u2713" if tga else "\u2717"))
            if have_want:
                color = GREEN
                tip = "Ready - the referenced " + want + " is on disk.\n" + detail
            elif paa or tga:
                other = ".tga" if want == ".paa" else ".paa"
                color = AMBER
                tip = ("Referenced " + want + " is missing, but " + other + " exists.\n"
                       "Run 'Convert .tga \u2192 .paa' or switch the extension.\n" + detail)
            else:
                color = RED
                tip = "No texture file found at this path.\n" + detail
        dot.setStyleSheet("background:" + color + "; border-radius:6px;")
        dot.setToolTip(tip)

    def _update_all_tex_lights(self):
        """Refresh every texture row's availability light."""
        for k in list(getattr(self, "_tex_dots", {})):
            self._update_tex_light(k)

    def _val_row(self, layout, label, key, default, buttons=None, color_title=None):
        """An editable material-value field (e.g. ambient = 1,1,1,1).

        ``buttons`` is an optional list of (text, callback, tooltip, width) of
        small helper buttons. ``color_title`` adds a colour button that *shows*
        the current RGBA value and opens the colour editor when clicked.
        """
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(88)
        row.addWidget(lbl)
        edit = QtWidgets.QLineEdit(str(self.s.get(key, default)))
        row.addWidget(edit)
        trailing = []
        for spec in (buttons or []):
            text, cb, tip, width = spec[0], spec[1], spec[2], spec[3]
            icon_kind = spec[4] if len(spec) > 4 else None
            b = QtWidgets.QPushButton()
            b.setObjectName("mini")
            if icon_kind:
                b.setIcon(self._icon(icon_kind))
                b.setIconSize(QtCore.QSize(14, 14))
            else:
                b.setText(text)
            b.setFixedSize(MINI_BTN, MINI_BTN)
            b.setToolTip(tip)
            b.clicked.connect(cb)
            trailing.append(b)
        if color_title:
            rb = QtWidgets.QPushButton("⟳")
            rb.setObjectName("mini")
            rb.setFixedSize(MINI_BTN, MINI_BTN)
            rb.setToolTip(f"Reset {color_title} to the default ({default}).")
            rb.clicked.connect(lambda _=False, e=edit, d=default: e.setText(d))
            trailing.append(rb)
            cbtn = QtWidgets.QPushButton()
            cbtn.setFixedSize(42, MINI_BTN)
            cbtn.setToolTip(f"{color_title} colour - click for RGBA sliders, "
                            "preview and a colour picker.")
            cbtn.clicked.connect(lambda _=False, e=edit, t=color_title: self.on_color_editor(e, t))
            edit.textChanged.connect(lambda tx, b=cbtn: self._colorize_button(b, tx))
            self._colorize_button(cbtn, edit.text())
            trailing.append(cbtn)
        for w in trailing:
            row.addWidget(w)
        layout.addLayout(row)
        return edit

    def _icon(self, kind):
        """Draw a small monochrome icon at runtime (no asset files). Light grey
        so it stays visible on the dark panel."""
        pm = QtGui.QPixmap(16, 16)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        col = QtGui.QColor(210, 214, 217)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(col)
        if kind == "droplet":
            path = QtGui.QPainterPath()
            path.moveTo(8, 2.0)
            path.cubicTo(12.8, 8.0, 12.2, 13.2, 8.0, 13.6)
            path.cubicTo(3.8, 13.2, 3.2, 8.0, 8.0, 2.0)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "spark":
            pts = [(8, 1.3), (9.3, 6.7), (14.7, 8), (9.3, 9.3),
                   (8, 14.7), (6.7, 9.3), (1.3, 8), (6.7, 6.7)]
            path = QtGui.QPainterPath()
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "folder":
            tab = QtGui.QPainterPath()
            tab.addRoundedRect(2.0, 3.4, 6.0, 3.2, 1.0, 1.0)
            p.drawPath(tab)
            body = QtGui.QPainterPath()
            body.addRoundedRect(1.6, 5.0, 12.8, 8.4, 1.3, 1.3)
            p.drawPath(body)
        elif kind == "eye":
            pen = QtGui.QPen(col); pen.setWidthF(1.4)
            p.setPen(pen); p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QRectF(1.6, 4.8, 12.8, 6.4))
            p.setPen(QtCore.Qt.NoPen); p.setBrush(col)
            p.drawEllipse(QtCore.QRectF(6.2, 5.6, 3.6, 3.6))
        elif kind == "curve":
            pen = QtGui.QPen(col); pen.setWidthF(1.5)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            p.setPen(pen); p.setBrush(QtCore.Qt.NoBrush)
            path = QtGui.QPainterPath()
            path.moveTo(2.0, 13.0)
            path.cubicTo(7.0, 13.0, 8.0, 3.0, 14.0, 3.0)
            p.drawPath(path)
        p.end()
        return QtGui.QIcon(pm)

    @staticmethod
    def _colorize_button(btn, text):
        """Fill a button with the colour described by an 'r,g,b,a' string (alpha
        mixed over the dark panel background) so the button previews the value."""
        parts = [p.strip() for p in str(text).split(",")]

        def num(i):
            try:
                return max(0.0, min(1.0, float(parts[i])))
            except (IndexError, ValueError):
                return None
        size = "min-width:42px; max-width:42px; min-height:22px; max-height:24px;"
        r, g, b = num(0), num(1), num(2)
        if r is None or g is None or b is None:
            btn.setStyleSheet(f"QPushButton {{ {size} }}")
            return
        a = num(3)
        a = 1.0 if a is None else a
        bg = 46
        mr = int(r * 255 * a + bg * (1 - a))
        mg = int(g * 255 * a + bg * (1 - a))
        mb = int(b * 255 * a + bg * (1 - a))
        # readable border colour depending on brightness
        edge = "rgba(0,0,0,120)" if (mr + mg + mb) / 3 > 128 else "rgba(255,255,255,90)"
        btn.setStyleSheet(f"QPushButton {{ background: rgb({mr},{mg},{mb}); "
                          f"border:1px solid {edge}; border-radius:4px; padding:0; {size} }}")

    # ---------- state ----------
    def _collect(self):
        src_map = {"Diffuse (metals black)": "diffuse", "2D View": "2d_view",
                   "Base Color - metals keep color (recommended)": "base_color",
                   "Base Color + Specular": "base_color_specular",
                   "Spec/Gloss diffuse, glTF (metals black)": "specgloss"}
        # python / imagetopaa / mateditor live in the Settings dialog (self.s)
        self.s.update({
            "output": self.output_edit.text(),
            "prefix": self.prefix_edit.text(),
            "normal_format": self.normal_combo.currentText(),
            "co_on": self.co_cb.isChecked(), "nohq_on": self.nohq_cb.isChecked(),
            "smdi_on": self.smdi_cb.isChecked(), "as_on": self.as_cb.isChecked(),
            "em_on": self.em_cb.isChecked(), "co_alpha": self.co_alpha_cb.isChecked(),
            "mc_on": self.mc_cb.isChecked(), "mc_source": self.mc_source.currentText(),
            "dtsmdi_on": self.dtsmdi_cb.isChecked(),
            "dtsmdi_res": self.dtsmdi_res.currentText(),
            "autofill_on_export": self.autofill_cb.isChecked(),
            "mc_blend": self.mc_blend.currentText(),
            "mc_alpha": self.mc_alpha.currentText(),
            "co_res": self.co_res.currentText(), "nohq_res": self.nohq_res.currentText(),
            "smdi_res": self.smdi_res.currentText(), "as_res": self.as_res.currentText(),
            "em_res": self.em_res.currentText(), "mc_res": self.mc_res.currentText(),
            "co_source": src_map.get(self.co_source.currentText(), "base_color"),
            "smdi_source": ("dayz" if self.smdi_source.currentText().startswith("DayZ")
                            else "gltf" if "glTF" in self.smdi_source.currentText()
                            else "pbr" if "PBR" in self.smdi_source.currentText()
                            else "metrough" if self.smdi_source.currentText().startswith("Met")
                            else "specgloss"),
            "smdi_green": self.smdi_green.value() / 100.0,
            "smdi_blue": self.smdi_blue.value() / 100.0,
            # rvmat values the DayZ _smdi method is relative to (Material panel)
            "dayz_rvmat": self._dayz_rvmat_args(),
            "dtsmdi_strength": self.dtsmdi_strength.value() / 100.0,
            "preset": self._selected_builtin_preset(),
            "autosync": self.autosync_cb.isChecked(),
            "mode": "preset" if self.mode_combo.currentText() == "Painter preset" else "builtin",
            "painter_preset": self.painter_preset_edit.text(),
            "preset_shelf": self.preset_shelf_edit.text(),
            "mateditor": self.s.get("mateditor", ""),
            "tex_ext": self.tex_ext_combo.currentText().lstrip("."),
            "mat_ambient": self.mat_ambient.text(), "mat_diffuse": self.mat_diffuse.text(),
            "mat_forced": self.mat_forced.text(), "mat_emmisive": self.mat_emmisive.text(),
            "mat_specular": self.mat_specular.text(), "mat_power": self.mat_power.text(),
            "mat_fresnel_n": self.mat_fresnel_n.text(),
            "mat_fresnel_k": self.mat_fresnel_k.text(),
            "env": self.env_combo.currentText().strip(),
            "shader_link": self.shader_link_cb.isChecked(),
        })
        save_settings(self.s)
        return self.s

    # ---------- DayZ In-Game shader link ----------
    def _wire_shader_link(self):
        """Push to the viewport shader whenever a linked value changes (debounced)."""
        self._shader_pulling = False
        self._shader_timer = QtCore.QTimer(self)
        self._shader_timer.setSingleShot(True)
        self._shader_timer.setInterval(150)
        self._shader_timer.timeout.connect(self._push_shader)
        kick = lambda *_: (self.shader_link_cb.isChecked() and not self._shader_pulling
                           and self._shader_timer.start())
        for edit in (self.mat_ambient, self.mat_diffuse, self.mat_forced, self.mat_emmisive,
                     self.mat_specular, self.mat_power, self.mat_fresnel_n, self.mat_fresnel_k):
            edit.textChanged.connect(kick)
        self.smdi_source.currentTextChanged.connect(kick)
        self.mc_source.currentTextChanged.connect(kick)
        self.mc_cb.toggled.connect(kick)
        self.smdi_green.valueChanged.connect(kick)
        self.smdi_blue.valueChanged.connect(kick)
        if self.shader_link_cb.isChecked():
            self._shader_timer.start()

    def _shader_values(self):
        src = self.smdi_source.currentText()
        return shader_sync.params_from_settings({
            "mat_ambient": self.mat_ambient.text(), "mat_diffuse": self.mat_diffuse.text(),
            "mat_forced": self.mat_forced.text(), "mat_emmisive": self.mat_emmisive.text(),
            "mat_specular": self.mat_specular.text(), "mat_power": self.mat_power.text(),
            "mat_fresnel_n": self.mat_fresnel_n.text(),
            "mat_fresnel_k": self.mat_fresnel_k.text(),
            "smdi_source": "dayz" if src.startswith("DayZ") else "other",
            "smdi_green": self.smdi_green.value() / 100.0,
            "smdi_blue": self.smdi_blue.value() / 100.0,
            "mc_on": self.mc_cb.isChecked(), "mc_source": self.mc_source.currentText(),
        })

    def _push_shader(self, announce=False):
        try:
            n = shader_sync.push(self._shader_values())
        except Exception as e:
            splog.warning(f"[RwG] DayZ In-Game shader link: {e}")
            return
        if announce:
            self.status.setText(
                f"Material values sent to {n} DayZ In-Game shader instance(s)." if n else
                "No texture set uses the 'dayz-ingame' shader yet (Texture Set Settings -> Shader).")

    def on_pull_shader(self):
        """Fill the material fields from the DayZ In-Game shader's settings."""
        try:
            p = shader_sync.pull()
        except Exception as e:
            self.status.setText(f"Could not read the shader: {e}"); return
        if not p:
            self.status.setText("No texture set uses the 'dayz-ingame' shader."); return

        def vec(edit, key):
            v = p.get(key)
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                old = _parse_vec(edit.text())
                alpha = old[3] if len(old) > 3 else "1"
                edit.setText(_vec_str([f"{float(x):.4g}" for x in v[:3]] + [alpha]))

        self._shader_pulling = True
        try:
            vec(self.mat_ambient, "u_ambient")
            vec(self.mat_diffuse, "u_diffuse")
            vec(self.mat_forced, "u_forced")
            vec(self.mat_emmisive, "u_emmisive")
            vec(self.mat_specular, "u_specular")
            for edit, key in ((self.mat_power, "u_power"), (self.mat_fresnel_n, "u_fresnel_n"),
                              (self.mat_fresnel_k, "u_fresnel_k")):
                if p.get(key) is not None:
                    edit.setText(f"{float(p[key]):.4g}")
            for slider, key in ((self.smdi_green, "u_g_factor"), (self.smdi_blue, "u_b_factor")):
                if p.get(key) is not None:
                    slider.setValue(int(round(float(p[key]) * 100)))
        finally:
            self._shader_pulling = False
        # the shader may hold other values for linked fields (e.g. a macro source) -
        # bring it back in line with the panel
        if self.shader_link_cb.isChecked():
            self._push_shader()
        self.status.setText("Material values taken from the DayZ In-Game shader.")

    def _update_mode_fields(self, *_):
        """Grey out Preset/Shelf when the mode is Built-in maps."""
        preset_mode = self.mode_combo.currentText() == "Painter preset"
        self.painter_preset_edit.setEnabled(preset_mode)
        self.preset_shelf_edit.setEnabled(preset_mode)

    # ---------- handlers ----------
    def on_help(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("RwG DayZ Texture Exporter - Help")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(560, 620)
        v = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QTextBrowser()          # QTextBrowser => clickable links
        view.setOpenExternalLinks(True)
        view.setHtml(HELP_HTML)
        v.addWidget(view)

        # version row: installed version + an online check against GitHub releases
        vrow = QtWidgets.QHBoxLayout()
        vrow.addWidget(QtWidgets.QLabel(f"Installed: v{PLUGIN_VERSION}"))
        self._update_status = QtWidgets.QLabel("")
        self._update_status.setTextFormat(QtCore.Qt.RichText)
        self._update_status.setOpenExternalLinks(True)
        self._update_status.setStyleSheet("color:#9aa0a6;")
        vrow.addWidget(self._update_status, 1)
        chk = QtWidgets.QPushButton("Check for updates")
        chk.setToolTip("Compare this version with the latest release on GitHub "
                       "(includes pre-releases). Needs an internet connection.")
        chk.clicked.connect(lambda: self._check_updates(chk))
        vrow.addWidget(chk)
        gh = QtWidgets.QPushButton("Open GitHub")
        gh.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl(GITHUB_REPO_URL)))
        vrow.addWidget(gh)
        v.addLayout(vrow)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dlg.accept)
        v.addWidget(close)
        run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
        run()

    @staticmethod
    def _version_tuple(s):
        """'v0.4.3' / '0.4.3-preview' -> (0, 4, 3) for a numeric compare."""
        out = []
        for part in str(s).strip().lstrip("vV").split("."):
            num = ""
            for ch in part:
                if ch.isdigit():
                    num += ch
                else:
                    break
            out.append(int(num) if num else 0)
        return tuple(out) or (0,)

    def _fetch_latest_release(self, timeout=6):
        """(tag, html_url) of the newest GitHub release incl. pre-releases; raises
        on any network/parse error."""
        import urllib.request
        import json
        req = urllib.request.Request(
            GITHUB_API_RELEASES,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "RwG-DayZ-Painter-Plugin"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list) or not data:
            raise RuntimeError("no releases found")
        rel = data[0]
        return (rel.get("tag_name") or rel.get("name") or ""), \
               (rel.get("html_url") or GITHUB_RELEASES_URL)

    def _check_updates(self, btn=None):
        if btn is not None:
            btn.setEnabled(False)
        self._update_status.setText("Checking GitHub…")
        app = QtWidgets.QApplication.instance()
        if app:
            app.processEvents()
        try:
            tag, url = self._fetch_latest_release()
        except Exception as e:
            self._update_status.setText(
                "<span style='color:#ff8a8a;'>Couldn't reach GitHub (offline?) - "
                f"check <a href='{GITHUB_RELEASES_URL}'>Releases</a> manually.</span>")
            splog.info(f"[RwG] update check failed: {e}")
            if btn is not None:
                btn.setEnabled(True)
            return
        disp = tag if tag.lower().startswith("v") else "v" + tag
        latest, cur = self._version_tuple(tag), self._version_tuple(PLUGIN_VERSION)
        if latest > cur:
            self._update_status.setText(
                f"<span style='color:#7ec96a;'>Update available: <b>{disp}</b> "
                f"(you have v{PLUGIN_VERSION}) - <a href='{url}'>open release</a>.</span>")
        elif latest == cur:
            self._update_status.setText(
                f"<span style='color:#7ec96a;'>Up to date (v{PLUGIN_VERSION}).</span>")
        else:
            self._update_status.setText(
                f"You're ahead of the latest release ({disp}).")
        if btn is not None:
            btn.setEnabled(True)

    def _pick_fresnel_reference(self, parent):
        """Modal picker over the community N/K reference library. Returns the
        selected row dict {category,name,n,k,description,f0} or None."""
        rows = rvmat_writer.fresnel_reference_flat()
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Fresnel reference library")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(720, 520)
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel(
            "Community reference N/K values (thanks to @|RaG| Tyson). Pick a "
            "material to load its N/K - tuned starting points, not lab-exact. "
            "Colour usually lives in your _co/_smdi maps; specular[] stays neutral."))

        frow = QtWidgets.QHBoxLayout()
        cat = QtWidgets.QComboBox()
        cat.addItem("All categories")
        for c, _ in rvmat_writer.FRESNEL_REFERENCE:
            cat.addItem(c)
        frow.addWidget(cat)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("Search name / look…")
        frow.addWidget(search, 1)
        v.addLayout(frow)

        table = QtWidgets.QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Material", "N", "K", "F0", "Look"])
        table.horizontalHeader().setStretchLastSection(True)
        for col in (1, 2, 3):
            table.horizontalHeader().setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        v.addWidget(table, 1)

        def repop():
            c = cat.currentText()
            q = search.text().strip().lower()
            table.setRowCount(0)
            for r in rows:
                if c != "All categories" and r["category"] != c:
                    continue
                if q and q not in r["name"].lower() and q not in r["description"].lower():
                    continue
                i = table.rowCount()
                table.insertRow(i)
                name_item = QtWidgets.QTableWidgetItem(r["name"])
                name_item.setData(QtCore.Qt.UserRole, r)
                table.setItem(i, 0, name_item)
                table.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{r['n']:g}"))
                table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{r['k']:g}"))
                table.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{r['f0'] * 100:.1f}%"))
                table.setItem(i, 4, QtWidgets.QTableWidgetItem(r["description"]))
            table.resizeRowsToContents()
        cat.currentIndexChanged.connect(lambda *_: repop())
        search.textChanged.connect(lambda *_: repop())
        repop()

        result = {"m": None}

        def accept():
            row = table.currentRow()
            if row < 0:
                self.status.setText("Pick a material row first.")
                return
            result["m"] = table.item(row, 0).data(QtCore.Qt.UserRole)
            dlg.accept()
        table.doubleClicked.connect(lambda *_: accept())

        brow = QtWidgets.QHBoxLayout()
        brow.addStretch(1)
        use = QtWidgets.QPushButton("Use")
        use.setObjectName("primary")
        use.clicked.connect(accept)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        brow.addWidget(use)
        brow.addWidget(cancel)
        v.addLayout(brow)

        (getattr(dlg, "exec", None) or getattr(dlg, "exec_"))()
        return result["m"]

    def on_fresnel_editor(self):
        """Visual Fresnel editor: N/K sliders + live reflectance curve, like the
        RwG RVMAT Creator's 'Configure Fresnel' window."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Configure Fresnel")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(440, 400)
        v = QtWidgets.QVBoxLayout(dlg)

        # texture header: #(format,w,h,levels)
        orow = QtWidgets.QHBoxLayout()
        fmt = QtWidgets.QComboBox(); fmt.addItems(["rgb", "argb", "i", "ai", "a"])
        fmt.setCurrentText(self.s.get("fresnel_fmt", "ai"))
        wcb = QtWidgets.QComboBox()
        hcb = QtWidgets.QComboBox()
        for cb in (wcb, hcb):
            cb.addItems(["1", "2", "4", "8", "16", "32", "64", "128", "256", "512"])
        wcb.setCurrentText(str(self.s.get("fresnel_w", "64")))
        hcb.setCurrentText(str(self.s.get("fresnel_h", "64")))
        lcb = QtWidgets.QComboBox(); lcb.addItems([str(i) for i in range(1, 10)])
        lcb.setCurrentText(str(self.s.get("fresnel_levels", "1")))
        for lab, wdg in (("Format", fmt), ("W", wcb), ("H", hcb), ("Levels", lcb)):
            orow.addWidget(QtWidgets.QLabel(lab)); orow.addWidget(wdg)
        orow.addStretch(1)
        v.addLayout(orow)

        curve = FresnelCurve()
        v.addWidget(curve)

        def _num(text, fallback):
            try:
                return float(text)
            except (TypeError, ValueError):
                return fallback

        def slider_row(caption, init):
            row = QtWidgets.QHBoxLayout()
            cap = QtWidgets.QLabel(caption); cap.setFixedWidth(140)
            sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sld.setRange(1, 1000)                     # 0.01 .. 10.00
            sld.setValue(int(round(max(0.01, min(10.0, init)) * 100)))
            val = QtWidgets.QLabel(); val.setObjectName("sliderVal"); val.setFixedWidth(38)
            val.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            row.addWidget(cap); row.addWidget(sld, 1); row.addWidget(val)
            return row, sld, val

        nrow, ns, nval = slider_row("N (Refractive Index)", _num(self.mat_fresnel_n.text(), 1.5))
        krow, ks, kval = slider_row("K (Absorption)", _num(self.mat_fresnel_k.text(), 0.01))
        v.addLayout(nrow); v.addLayout(krow)

        def refresh(*_):
            n, k = ns.value() / 100.0, ks.value() / 100.0
            nval.setText(f"{n:.2f}"); kval.setText(f"{k:.2f}")
            curve.set_nk(n, k)
        ns.valueChanged.connect(refresh); ks.valueChanged.connect(refresh)
        refresh()

        # reference library: pick -> load exact N/K (+ suggested specular on OK).
        # sliderMoved fires only on user drag, so nudging a slider drops the pick
        # and we fall back to the slider values.
        picked = {"m": None}
        lib_row = QtWidgets.QHBoxLayout()
        lib_btn = QtWidgets.QPushButton("Reference library…")
        lib_btn.setToolTip("Browse 130 community N/K values (metals, terrain, "
                           "organics, plastics, gems…) with a look note for each.")
        lib_info = QtWidgets.QLabel(""); lib_info.setObjectName("hint")

        def do_pick_reference():
            m = self._pick_fresnel_reference(dlg)
            if not m:
                return
            picked["m"] = m
            ns.setValue(int(round(max(0.01, min(10.0, m["n"])) * 100)))
            ks.setValue(int(round(max(0.0, min(10.0, m["k"])) * 100)))
            refresh()
            nval.setText(f"{m['n']:g}"); kval.setText(f"{m['k']:g}")
            lib_info.setText(f"{m['name']} - {m['description']}")
        lib_btn.clicked.connect(do_pick_reference)
        ns.sliderMoved.connect(lambda *_: (picked.update(m=None), lib_info.setText("")))
        ks.sliderMoved.connect(lambda *_: (picked.update(m=None), lib_info.setText("")))
        lib_row.addWidget(lib_btn); lib_row.addWidget(lib_info, 1)
        v.addLayout(lib_row)

        est_row = QtWidgets.QHBoxLayout()
        est_btn = QtWidgets.QPushButton("Estimate from base color")
        est_btn.setToolTip("Export the project's base colour + metallic and derive a "
                           "representative N/K (F0 of the metal, N fixed at 1.0).")
        est_info = QtWidgets.QLabel(""); est_info.setObjectName("hint")

        def do_estimate():
            est_btn.setEnabled(False)
            old = est_btn.text(); est_btn.setText("Estimating...")
            QtWidgets.QApplication.processEvents()
            try:
                n, k, summary = self._estimate_fresnel_nk()
                picked["m"] = None; lib_info.setText("")
                ns.setValue(int(round(max(0.01, min(10.0, n)) * 100)))
                ks.setValue(int(round(max(0.01, min(10.0, k)) * 100)))
                refresh()
                est_info.setText(f"metal {summary.get('metal_fraction', 0) * 100:.0f}%  "
                                 f"F0={summary.get('f0', 0):.3f}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(dlg, "Estimate Fresnel", str(e))
            finally:
                est_btn.setEnabled(True); est_btn.setText(old)

        est_btn.clicked.connect(do_estimate)
        est_row.addWidget(est_btn); est_row.addWidget(est_info); est_row.addStretch(1)
        v.addLayout(est_row)

        brow = QtWidgets.QHBoxLayout(); brow.addStretch(1)
        ok = QtWidgets.QPushButton("OK"); ok.setObjectName("primary")
        cancel = QtWidgets.QPushButton("Cancel")
        ok.clicked.connect(dlg.accept); cancel.clicked.connect(dlg.reject)
        brow.addWidget(ok); brow.addWidget(cancel)
        v.addLayout(brow)

        run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
        if run():
            m = picked["m"]
            if m:
                # keep the library's exact precision (e.g. 1.333, 2.417)
                self.mat_fresnel_n.setText(f"{m['n']:g}")
                self.mat_fresnel_k.setText(f"{m['k']:g}")
                spec = rvmat_writer.suggested_specular(m["n"], m["k"])
                self.mat_specular.setText(",".join(str(x) for x in spec))
                self.status.setText(
                    f"{m['name']}: fresnel({m['n']:g},{m['k']:g})  F0 {m['f0'] * 100:.1f}%"
                    f"  specular {self.mat_specular.text()}")
            else:
                self.mat_fresnel_n.setText(f"{ns.value() / 100.0:.2f}")
                self.mat_fresnel_k.setText(f"{ks.value() / 100.0:.2f}")
            self.s["fresnel_fmt"] = fmt.currentText()
            self.s["fresnel_w"] = wcb.currentText()
            self.s["fresnel_h"] = hcb.currentText()
            self.s["fresnel_levels"] = lcb.currentText()
            save_settings(self.s)

    def _export_estimate_maps(self, plan, subdir):
        """Export `plan` to a temp folder and return (maps, export_dir). Caller
        is responsible for removing export_dir."""
        if not substance_painter.project.is_open():
            raise RuntimeError("Open a project first.")
        s = self._collect()
        py = s.get("python") or detect_python()[0]
        if not py:
            raise RuntimeError("Set 'Python' (numpy + pillow) in Settings first.")
        base_out = s["output"].strip() or PLUGIN_DIR
        export_dir = os.path.join(base_out, subdir)
        paths = export_project_maps(export_dir, plan, splog.info)
        return maps_from_export_paths(paths), export_dir, py

    def _dayz_rvmat_args(self):
        """CLI args for the DayZ _smdi method: the specularPower and fresnel N/K the
        rvmat will carry (the _smdi G and B are relative to them)."""
        def num(widget_name, default):
            w = getattr(self, widget_name, None)
            try:
                return str(float(w.text().strip())) if w is not None else default
            except ValueError:
                return default
        return ["--specular-power", num("mat_power", "100.0"),
                "--fresnel-n", num("mat_fresnel_n", "1.5"),
                "--fresnel-k", num("mat_fresnel_k", "0.0")]

    def on_estimate_specular_power(self):
        """Heuristic specularPower from the project's roughness (classic: average;
        DayZ _smdi method: sized for the smoothest part so the gloss never clips)."""
        export_dir = None
        try:
            plan = [{"fileName": "$textureSet_roughness", "srcType": "documentMap",
                     "srcName": "roughness", "mode": "gray"}]
            maps, export_dir, py = self._export_estimate_maps(plan, "_mat_src")
            if not maps.get("roughness"):
                raise RuntimeError("No roughness channel to sample.")
            mode = "dayz" if self.smdi_source.currentText().startswith("DayZ") else "classic"
            summary = _exec_cli(py, ["--estimate-material", "--estimate-mode", mode,
                                     "--roughness", maps["roughness"]], splog.info)
            if not summary or summary.get("specular_power") is None:
                raise RuntimeError("Estimate failed: "
                                   + ("; ".join((summary or {}).get("errors", [])) or "no result"))
            self.mat_power.setText(str(summary["specular_power"]))
            self.status.setText(f"specularPower ~{summary['specular_power']} "
                                f"(avg roughness {summary.get('avg_roughness')}). Tune to taste.")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")
        finally:
            if export_dir and os.path.isdir(export_dir):
                shutil.rmtree(export_dir, ignore_errors=True)

    def on_estimate_emmisive(self):
        """Estimate emmisive[] from the project's Emissive channel (if any)."""
        export_dir = None
        try:
            plan = [{"fileName": "$textureSet_emissive", "srcType": "documentMap",
                     "srcName": "emissive", "mode": "rgb"}]
            try:
                maps, export_dir, py = self._export_estimate_maps(plan, "_mat_src")
            except Exception:
                self.status.setText("No Emissive channel in this project - "
                                    "emmisive stays 0,0,0,0.")
                return
            if not maps.get("emissive"):
                self.status.setText("No Emissive channel in this project - "
                                    "emmisive stays 0,0,0,0.")
                return
            summary = _exec_cli(py, ["--estimate-material",
                                     "--emissive", maps["emissive"]], splog.info)
            if not summary or summary.get("emmisive") is None:
                raise RuntimeError("Estimate failed: "
                                   + ("; ".join((summary or {}).get("errors", [])) or "no result"))
            em = summary["emmisive"]
            self.mat_emmisive.setText(",".join(str(x) for x in em))
            if summary.get("has_emissive"):
                self.status.setText(f"emmisive set from Emissive channel: {self.mat_emmisive.text()}")
            else:
                self.status.setText("Emissive channel is black - emmisive set to 0,0,0,0.")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")
        finally:
            if export_dir and os.path.isdir(export_dir):
                shutil.rmtree(export_dir, ignore_errors=True)

    def _estimate_albedo_tint(self):
        """Export the base colour, return its average linear colour as 'r,g,b,1'."""
        export_dir = None
        try:
            plan = [{"fileName": "$textureSet_baseColor", "srcType": "documentMap",
                     "srcName": "baseColor", "mode": "rgb"}]
            maps, export_dir, py = self._export_estimate_maps(plan, "_mat_src")
            if not maps.get("basecolor"):
                raise RuntimeError("No base colour channel to sample.")
            summary = _exec_cli(py, ["--estimate-material",
                                     "--basecolor", maps["basecolor"]], splog.info)
            if not summary or not summary.get("avg_color"):
                raise RuntimeError("Estimate failed: "
                                   + ("; ".join((summary or {}).get("errors", [])) or "no result"))
            return ",".join(str(x) for x in summary["avg_color"])
        finally:
            if export_dir and os.path.isdir(export_dir):
                shutil.rmtree(export_dir, ignore_errors=True)

    def on_color_editor(self, field, title):
        """RGBA colour editor (R/G/B/A sliders + live preview + colour picker),
        writing 'r,g,b,a' back into `field`. Mirrors the RVMAT Creator."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"Colour - {title}")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(360, 300)
        v = QtWidgets.QVBoxLayout(dlg)

        parts = [p.strip() for p in field.text().split(",")]

        def fnum(i, d):
            try:
                return max(0.0, min(1.0, float(parts[i])))
            except (IndexError, ValueError):
                return d

        swatch = QtWidgets.QLabel()
        swatch.setFixedHeight(46)
        swatch.setAutoFillBackground(True)
        v.addWidget(swatch)

        def add_slider(name, init):
            row = QtWidgets.QHBoxLayout()
            cap = QtWidgets.QLabel(name); cap.setFixedWidth(14)
            sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sld.setRange(0, 1000)
            sld.setValue(int(round(init * 1000)))
            val = QtWidgets.QLabel(); val.setObjectName("sliderVal"); val.setFixedWidth(42)
            val.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            row.addWidget(cap); row.addWidget(sld, 1); row.addWidget(val)
            v.addLayout(row)
            return sld, val

        sr, vr = add_slider("R", fnum(0, 1.0))
        sg, vg = add_slider("G", fnum(1, 1.0))
        sb, vb = add_slider("B", fnum(2, 1.0))
        sa, va = add_slider("A", fnum(3, 1.0))

        def refresh(*_):
            r, g, b, a = (x.value() / 1000.0 for x in (sr, sg, sb, sa))
            vr.setText(f"{r:.3f}"); vg.setText(f"{g:.3f}")
            vb.setText(f"{b:.3f}"); va.setText(f"{a:.3f}")
            # preview: colour over a light-grey background, mixed by alpha
            mr = int(r * 255 * a + 240 * (1 - a))
            mg = int(g * 255 * a + 240 * (1 - a))
            mb = int(b * 255 * a + 240 * (1 - a))
            swatch.setStyleSheet(f"background-color: rgb({mr},{mg},{mb}); "
                                 "border:1px solid rgba(255,255,255,50);")
        for s in (sr, sg, sb, sa):
            s.valueChanged.connect(refresh)
        refresh()

        prow = QtWidgets.QHBoxLayout()
        pick = QtWidgets.QPushButton("Pick colour...")

        def do_pick():
            c0 = QtGui.QColor(int(sr.value() / 1000 * 255),
                              int(sg.value() / 1000 * 255),
                              int(sb.value() / 1000 * 255))
            c = QtWidgets.QColorDialog.getColor(c0, dlg, "Pick colour")
            if c.isValid():
                sr.setValue(int(round(c.red() / 255 * 1000)))
                sg.setValue(int(round(c.green() / 255 * 1000)))
                sb.setValue(int(round(c.blue() / 255 * 1000)))
        pick.clicked.connect(do_pick)
        prow.addWidget(pick); prow.addStretch(1)
        v.addLayout(prow)

        brow = QtWidgets.QHBoxLayout(); brow.addStretch(1)
        ok = QtWidgets.QPushButton("OK"); ok.setObjectName("primary")
        cancel = QtWidgets.QPushButton("Cancel")
        ok.clicked.connect(dlg.accept); cancel.clicked.connect(dlg.reject)
        brow.addWidget(ok); brow.addWidget(cancel)
        v.addLayout(brow)

        run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
        if run():
            r, g, b, a = (round(x.value() / 1000.0, 3) for x in (sr, sg, sb, sa))
            field.setText(f"{r},{g},{b},{a}")

    def on_estimate_diffuse_tint(self):
        try:
            self.mat_diffuse.setText(self._estimate_albedo_tint())
            self.status.setText(f"diffuse tint from avg base colour: {self.mat_diffuse.text()}")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    def on_estimate_specular_tint(self):
        """Fill specular[] from the metal reflectance: the glTF F0 = mix(0.04,
        base colour, metallic), averaged over the metallic pixels (sRGB)."""
        export_dir = None
        try:
            plan = [{"fileName": "$textureSet_baseColor", "srcType": "documentMap",
                     "srcName": "baseColor", "mode": "rgb"},
                    {"fileName": "$textureSet_metallic", "srcType": "documentMap",
                     "srcName": "metallic", "mode": "gray"}]
            maps, export_dir, py = self._export_estimate_maps(plan, "_mat_src")
            if not (maps.get("basecolor") and maps.get("metallic")):
                raise RuntimeError("Needs base colour + metallic channels.")
            summary = _exec_cli(py, ["--estimate-material",
                                     "--basecolor", maps["basecolor"],
                                     "--metallic", maps["metallic"]], splog.info)
            tint = (summary or {}).get("specular_tint")
            if not tint:
                raise RuntimeError("Estimate failed: "
                                   + ("; ".join((summary or {}).get("errors", [])) or "no result"))
            self.mat_specular.setText(",".join(str(x) for x in tint))
            frac = (summary or {}).get("metal_fraction")
            if frac is not None and frac < 0.001:
                self.status.setText("No metal in this project - specular kept white "
                                    "(1,1,1,1).")
            else:
                self.status.setText(f"specular tint from metal reflectance: "
                                    f"{self.mat_specular.text()} "
                                    f"(metal {round((frac or 0)*100)}%).")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")
        finally:
            if export_dir and os.path.isdir(export_dir):
                shutil.rmtree(export_dir, ignore_errors=True)

    def on_estimate_ambient_tint(self):
        try:
            self.mat_ambient.setText(self._estimate_albedo_tint())
            self.status.setText(f"ambient tint from avg base colour: {self.mat_ambient.text()}")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    def _estimate_fresnel_nk(self):
        """Export base colour + metallic, run the CLI estimate, return (n, k, summary)."""
        if not substance_painter.project.is_open():
            raise RuntimeError("Open a project first.")
        s = self._collect()
        py = s.get("python") or detect_python()[0]
        if not py:
            raise RuntimeError("Set 'Python' (numpy + pillow) in Settings first.")
        base_out = s["output"].strip() or PLUGIN_DIR
        export_dir = os.path.join(base_out, "_fresnel_src")
        plan = [
            {"fileName": "$textureSet_baseColor", "srcType": "documentMap",
             "srcName": "baseColor", "mode": "rgb"},
            {"fileName": "$textureSet_metallic", "srcType": "documentMap",
             "srcName": "metallic", "mode": "gray"},
        ]
        try:
            paths = export_project_maps(export_dir, plan, splog.info)
            maps = maps_from_export_paths(paths)
            if not (maps.get("basecolor") and maps.get("metallic")):
                raise RuntimeError("Could not export base colour + metallic "
                                   "(does the project have those channels?).")
            summary = _exec_cli(py, ["--estimate-fresnel",
                                     "--basecolor", maps["basecolor"],
                                     "--metallic", maps["metallic"]], splog.info)
            if not summary or summary.get("n") is None or summary.get("k") is None:
                errs = "; ".join((summary or {}).get("errors", [])) or "no result"
                raise RuntimeError(f"Estimate failed: {errs}")
            return float(summary["n"]), float(summary["k"]), summary
        finally:
            try:
                if os.path.isdir(export_dir):
                    shutil.rmtree(export_dir, ignore_errors=True)
            except Exception:
                pass

    def _rebuild_ui(self, keep_fields=True):
        """Rebuild the whole panel in place (layout switch / project change), so
        it updates immediately without reloading the plugin. keep_fields=False
        discards the current widgets' values and uses self.s as-is (project load)."""
        try:
            if keep_fields:
                try:
                    self._collect()      # keep current field values across the rebuild
                except Exception:
                    pass
            old = self.layout()
            if old is not None:
                # re-parent the old layout (and its widgets) onto a throwaway
                # widget so Qt frees them and `self` can take a fresh layout
                tmp = QtWidgets.QWidget()
                tmp.setLayout(old)
                tmp.deleteLater()
            self._build()
            return True
        except Exception as e:
            splog.warning(f"[RwG] Could not rebuild UI live: {e}")
            return False

    def on_settings(self):
        """Dialog holding the tool paths: Python, ImageToPAA, MatEditor."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("RwG DayZ Exporter - Settings")
        dlg.resize(580, 260)
        v = QtWidgets.QVBoxLayout(dlg)

        def path_row(label, key):
            row = QtWidgets.QHBoxLayout()
            lab = QtWidgets.QLabel(label)
            lab.setFixedWidth(150)
            row.addWidget(lab)
            edit = QtWidgets.QLineEdit(self.s.get(key, ""))
            row.addWidget(edit)
            b = QtWidgets.QPushButton("...")
            b.setFixedWidth(30)
            b.clicked.connect(lambda: self._browse(edit, False))
            row.addWidget(b)
            v.addLayout(row)
            return row, edit

        prow, py_edit = path_row("Python (numpy+pillow):", "python")
        auto = QtWidgets.QPushButton("Auto-detect")
        auto.clicked.connect(lambda: self.on_detect_python(py_edit))
        prow.addWidget(auto)
        _, ip_edit = path_row("ImageToPAA.exe:", "imagetopaa")
        _, me_edit = path_row("MatEditor.exe:", "mateditor")
        _, tv_edit = path_row("TexView.exe:", "texview")

        drow = QtWidgets.QHBoxLayout()
        dlab = QtWidgets.QLabel("Mod drive:")
        dlab.setFixedWidth(150)
        drow.addWidget(dlab)
        drive_field = QtWidgets.QLineEdit(self.s.get("drive", "P:\\"))
        drive_field.setToolTip("The mounted mod drive, e.g. P:\\ - used to make the "
                               ".rvmat texture paths game-valid and to open textures.")
        drow.addWidget(drive_field)
        v.addLayout(drow)

        pprow = QtWidgets.QHBoxLayout()
        pplab = QtWidgets.QLabel("My presets folder:")
        pplab.setFixedWidth(150)
        pprow.addWidget(pplab)
        presets_field = QtWidgets.QLineEdit(self.s.get("presets_path", ""))
        presets_field.setToolTip("Folder where your saved RVMAT material presets "
                                 f"({USER_PRESETS_NAME}) are stored. Leave empty to keep "
                                 "them next to the plugin. Put it in a synced/cloud "
                                 "folder to share presets across machines.")
        pprow.addWidget(presets_field)
        ppb = QtWidgets.QPushButton("...")
        ppb.setFixedWidth(30)
        ppb.clicked.connect(lambda: self._browse(presets_field, True))
        pprow.addWidget(ppb)
        v.addLayout(pprow)

        lrow = QtWidgets.QHBoxLayout()
        llab = QtWidgets.QLabel("Panel layout:")
        llab.setFixedWidth(150)
        lrow.addWidget(llab)
        layout_combo = QtWidgets.QComboBox()
        layout_combo.addItems(["Tabs (Setup / Maps / RVMAT)", "Single window (scroll)"])
        layout_combo.setCurrentText("Single window (scroll)"
                                    if self.s.get("layout_mode", "tabs") == "single"
                                    else "Tabs (Setup / Maps / RVMAT)")
        lrow.addWidget(layout_combo)
        lrow.addStretch(1)
        v.addLayout(lrow)

        crow = QtWidgets.QHBoxLayout()
        prep_btn = QtWidgets.QPushButton("Prepare DayZ channels")
        prep_btn.setToolTip("Add Emissive, Opacity and User0-User2 (colour) to the "
                            "active texture set if missing - for _em / _ca / _mc.")
        prep_btn.clicked.connect(self.on_prepare_channels)
        crow.addWidget(prep_btn)
        crow.addWidget(QtWidgets.QLabel("adds Emissive + Opacity + User0-2 to the "
                                        "active texture set"))
        crow.addStretch(1)
        v.addLayout(crow)

        v.addStretch(1)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        ok = QtWidgets.QPushButton("Save")
        cancel = QtWidgets.QPushButton("Cancel")
        btns.addWidget(ok); btns.addWidget(cancel)
        v.addLayout(btns)
        ok.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)

        run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
        if run():
            self.s["python"] = py_edit.text()
            self.s["imagetopaa"] = ip_edit.text()
            self.s["mateditor"] = me_edit.text()
            self.s["texview"] = tv_edit.text()
            self.s["drive"] = drive_field.text().strip() or "P:\\"
            self.s["presets_path"] = presets_field.text().strip()
            new_mode = "single" if layout_combo.currentText().startswith("Single") else "tabs"
            mode_changed = new_mode != self.s.get("layout_mode", "tabs")
            self.s["layout_mode"] = new_mode
            save_settings(self.s)
            try:
                self._refresh_user_presets()
                self._populate_fresnel_combo()
            except Exception:
                pass
            if mode_changed and not self._rebuild_ui():
                self.status.setText("Settings saved. Reload Plugins to apply the "
                                    "new panel layout.")
            else:
                self.status.setText("Settings saved.")

    def on_detect_python(self, edit):
        self.status.setText("Searching for Python..."); QtWidgets.QApplication.processEvents()
        try:
            py, ok = detect_python()
        except Exception as e:
            self.status.setText(f"Auto-detect failed: {e}"); return
        if not py:
            self.status.setText("No python.exe found on PATH. Enter it manually.")
            return
        edit.setText(py)
        if ok:
            self.status.setText(f"Found Python with numpy+pillow: {py}")
        else:
            self.status.setText("Found Python, but numpy/pillow missing - run: "
                                f"pip install numpy pillow  ({py})")

    def on_normal_changed(self, fmt):
        set_project_normal_format(fmt)

    def _has_channel(self, *names):
        """True if the active texture set has one of the named document channels
        (e.g. 'Height'). Used to fold the raw Height into the _dtsmdi detail only
        when it actually exists, so the export never breaks on a missing channel."""
        try:
            stack = sptexset.get_active_stack()
            CT = getattr(sptexset, "ChannelType", None)
            existing = set(stack.all_channels().keys())
            for n in names:
                ct = getattr(CT, n, None) or getattr(CT, n.lower(), None)
                if ct is not None and ct in existing:
                    return True
        except Exception:
            pass
        return False

    def on_prepare_channels(self):
        """Add the Emissive + Opacity channels to the active texture set if they
        are missing (so _em / _ca can be exported)."""
        if not substance_painter.project.is_open():
            self.status.setText("Open a project first."); return
        if sptexset is None or not hasattr(sptexset, "get_active_stack"):
            self.status.setText("Channel API not available in this Painter version.")
            return
        try:
            stack = sptexset.get_active_stack()
            CT = getattr(sptexset, "ChannelType", None)
            CF = getattr(sptexset, "ChannelFormat", None)
            if stack is None or CT is None or CF is None:
                self.status.setText("Channel API not available in this Painter version.")
                return

            def enum(mod, *names):
                for n in names:
                    v = getattr(mod, n, None)
                    if v is not None:
                        return v
                return None

            emissive = enum(CT, "Emissive", "emissive")
            opacity = enum(CT, "Opacity", "opacity")
            col_fmt = enum(CF, "sRGB8", "RGB8", "sRGB16F")
            gray_fmt = enum(CF, "L8", "L16", "L16F")
            wanted = [("Emissive", emissive, col_fmt), ("Opacity", opacity, gray_fmt)]
            # User0-User2 as colour channels (for the _mc macro)
            for uname in ("User0", "User1", "User2"):
                uch = enum(CT, uname, uname.lower())
                if uch is not None:
                    wanted.append((uname, uch, col_fmt))

            try:
                existing = set(stack.all_channels().keys())
            except Exception:
                existing = set()

            added, present, failed = [], [], []
            for name, ctype, cfmt in wanted:
                if ctype is None or cfmt is None:
                    failed.append(name); continue
                if ctype in existing:
                    present.append(name); continue
                try:
                    stack.add_channel(ctype, cfmt)
                    added.append(name)
                except Exception as e:
                    splog.warning(f"[RwG] Could not add {name} channel: {e}")
                    failed.append(name)

            parts = []
            if added:
                parts.append("added " + ", ".join(added))
            if present:
                parts.append("already had " + ", ".join(present))
            if failed:
                parts.append("failed " + ", ".join(failed))
            self.status.setText("DayZ channels: " + "; ".join(parts) + "."
                                if parts else "Nothing to do.")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error preparing channels: {e}")

    def on_use_texset_name(self):
        name = _active_texture_set_name()
        if name:
            self.prefix_edit.setText(re.sub(r"\s+", "_", name))
            self.status.setText(f"Prefix set to active texture set: {name}")
        else:
            self.status.setText("No texture set found (open a project first).")

    def _prefix(self, s):
        p = s["prefix"].strip()
        if p:
            return p
        name = _active_texture_set_name()
        return re.sub(r"\s+", "_", name) if name else "material"

    # ------------------------------------------------------------------ #
    #  background execution (keeps Painter's UI responsive)               #
    # ------------------------------------------------------------------ #
    def _run_bg(self, work_fn, done_fn):
        """Run work_fn() on a worker thread; call done_fn(result, error) back on
        the main thread. work_fn must not call the Painter API."""
        worker = _BgWorker(work_fn)
        self._bg_workers = getattr(self, "_bg_workers", [])
        self._bg_workers.append(worker)

        def _on_done(result, error):
            try:
                done_fn(result, error)
            finally:
                try:
                    self._bg_workers.remove(worker)
                except ValueError:
                    pass
                worker.deleteLater()
        worker.done.connect(_on_done)
        worker.start()

    def _set_busy(self, busy):
        self._busy = busy

    def _do_export(self, make_paa):
        if getattr(self, "_busy", False):
            self.status.setText("Busy - please wait for the current job to finish.")
            return
        s = self._collect()
        if s["mode"] == "preset":
            return self._do_export_preset(make_paa, s)
        try:
            if not substance_painter.project.is_open():
                self.status.setText("No project open."); return
            if not s["output"].strip():
                self.status.setText("Choose an output folder first."); return

            prefix = self._prefix(s)
            self.prefix_edit.setText(prefix)

            # Build the export plan from Painter's converted (virtual) maps so
            # the normal takes normal+height+mesh normal, AO is mixed, etc.
            plan = []

            def add(fn, st, sn, mode):
                if not any(o["fileName"] == fn for o in plan):
                    plan.append({"fileName": fn, "srcType": st, "srcName": sn, "mode": mode})

            if s["co_on"]:
                if s["co_source"] == "diffuse":
                    add("$textureSet_diffuse", "virtualMap", "Diffuse", "rgb")
                elif s["co_source"] == "2d_view":
                    add("$textureSet_view2d", "virtualMap", "View_2D", "rgb")
                else:
                    add("$textureSet_baseColor", "documentMap", "baseColor", "rgb")
                    if s["co_source"] in ("base_color_specular", "specgloss"):
                        add("$textureSet_metallic", "documentMap", "metallic", "gray")
                if s["co_alpha"]:                     # _ca variant needs opacity
                    add("$textureSet_opacity", "documentMap", "opacity", "gray")
            if s["nohq_on"]:
                vname = "Normal_OpenGL" if s["normal_format"] == "opengl" else "Normal_DirectX"
                add("$textureSet_normal", "virtualMap", vname, "rgb")
            if s["smdi_on"]:
                if s["smdi_source"] == "specgloss":
                    add("$textureSet_specular", "virtualMap", "Specular", "rgb")
                    add("$textureSet_glossiness", "virtualMap", "Glossiness", "rgb")
                else:
                    add("$textureSet_metallic", "documentMap", "metallic", "gray")
                    add("$textureSet_roughness", "documentMap", "roughness", "gray")
                    if s["smdi_source"] in ("pbr", "gltf", "dayz"):
                        # raw albedo carries each metal's F0 for PBR / glTF / DayZ methods
                        add("$textureSet_baseColor", "documentMap", "baseColor", "rgb")
            if s["as_on"]:
                add("$textureSet_ao", "virtualMap", "AO_Mixed", "gray")
            if s["em_on"]:
                add("$textureSet_emissive", "documentMap", "emissive", "rgb")
            if s["mc_on"]:
                if s["mc_source"].startswith("Combine"):
                    for u in ("user0", "user1", "user2"):
                        add(f"$textureSet_{u}", "documentMap", u, "rgb")
                else:
                    uch = s["mc_source"].lower()      # user0 / user1 / user2
                    add(f"$textureSet_{uch}", "documentMap", uch, "rgb")
                a = s["mc_alpha"]                     # export the mask channel if needed
                if a == "Opacity":
                    add("$textureSet_opacity", "documentMap", "opacity", "gray")
                elif a.startswith("User"):
                    add(f"$textureSet_{a.lower()}", "documentMap", a.lower(), "gray")
            if s.get("dtsmdi_on"):
                m = s["smdi_source"]
                if m == "specgloss":
                    add("$textureSet_specular", "virtualMap", "Specular", "rgb")
                    add("$textureSet_glossiness", "virtualMap", "Glossiness", "rgb")
                else:
                    add("$textureSet_metallic", "documentMap", "metallic", "gray")
                    add("$textureSet_roughness", "documentMap", "roughness", "gray")
                    if m in ("pbr", "gltf", "dayz"):
                        add("$textureSet_baseColor", "documentMap", "baseColor", "rgb")
                # the _dtsmdi R (detail) combines height + mesh + normal: the
                # converted normal (normal + baked mesh + height) always, plus the
                # raw Height channel when the project has one.
                vname = "Normal_OpenGL" if s["normal_format"] == "opengl" else "Normal_DirectX"
                add("$textureSet_normal", "virtualMap", vname, "rgb")
                if self._has_channel("Height"):
                    add("$textureSet_height", "documentMap", "height", "gray")
            if not plan:
                self.status.setText("Tick at least one map to export."); return

            export_dir = os.path.join(s["output"].strip(), "_pbr_src")
            paths = export_project_maps(export_dir, plan, splog.info)
            maps = maps_from_export_paths(paths)
            if not maps:
                self.status.setText("Export produced no recognizable maps - see Log."); return

            args = ["--output", s["output"].strip(), "--prefix", prefix,
                    "--drive", s["drive"].strip() or "P:\\"]
            co_mode = ("base_color_specular" if s["co_source"] == "base_color_specular"
                       else "specgloss" if s["co_source"] == "specgloss"
                       else "base_color")
            # Painter's virtual maps are already in their final format, so the CLI
            # must NOT flip the normal - pass 'directx' to disable flipping.
            args += ["--co-mode", co_mode, "--normal-format", "directx",
                     "--spec", str(s["smdi_green"]), "--gloss", str(s["smdi_blue"])]

            co_input = {"diffuse": maps.get("diffuse"),
                        "2d_view": maps.get("view2d")}.get(s["co_source"], maps.get("basecolor"))
            if s["co_on"] and co_input:
                args += ["--basecolor", co_input, "--co-res", s["co_res"]]
                if co_mode in ("base_color_specular", "specgloss") and maps.get("metallic"):
                    args += ["--metallic", maps["metallic"]]
                if s["co_alpha"]:                     # export as _ca (colour + alpha)
                    args += ["--co-alpha"]
                    if maps.get("opacity"):
                        args += ["--co-opacity", maps["opacity"]]
            if s["nohq_on"] and maps.get("normal"):
                args += ["--normal", maps["normal"], "--nohq-res", s["nohq_res"]]
            if s["smdi_on"]:
                args += ["--smdi"]          # explicitly request the _smdi map
                if s["smdi_source"] == "specgloss" and maps.get("specular") and maps.get("glossiness"):
                    args += ["--smdi-mode", "specgloss",
                             "--spec-map", maps["specular"], "--gloss-map", maps["glossiness"],
                             "--smdi-res", s["smdi_res"]]
                elif s["smdi_source"] == "dayz" and maps.get("metallic") and maps.get("roughness"):
                    args += ["--smdi-mode", "dayz",
                             "--metallic", maps["metallic"], "--roughness", maps["roughness"],
                             "--smdi-res", s["smdi_res"]] + s["dayz_rvmat"]
                    if maps.get("basecolor"):
                        args += ["--smdi-basecolor", maps["basecolor"]]
                elif s["smdi_source"] in ("pbr", "gltf") and maps.get("metallic") and \
                        maps.get("roughness") and maps.get("basecolor"):
                    args += ["--smdi-mode", s["smdi_source"],
                             "--metallic", maps["metallic"], "--roughness", maps["roughness"],
                             "--smdi-basecolor", maps["basecolor"], "--smdi-res", s["smdi_res"]]
                elif maps.get("metallic") and maps.get("roughness"):
                    args += ["--smdi-mode", "metrough",
                             "--metallic", maps["metallic"], "--roughness", maps["roughness"],
                             "--smdi-res", s["smdi_res"]]
            if s.get("dtsmdi_on"):
                m = s["smdi_source"]
                dt = None
                if m == "specgloss" and maps.get("specular") and maps.get("glossiness"):
                    dt = ["--dtsmdi-mode", "specgloss",
                          "--spec-map", maps["specular"], "--gloss-map", maps["glossiness"]]
                elif m == "dayz" and maps.get("metallic") and maps.get("roughness"):
                    dt = ["--dtsmdi-mode", "dayz",
                          "--metallic", maps["metallic"], "--roughness", maps["roughness"]] \
                         + s["dayz_rvmat"]
                    if maps.get("basecolor"):
                        dt += ["--smdi-basecolor", maps["basecolor"]]
                elif m in ("pbr", "gltf") and maps.get("metallic") and \
                        maps.get("roughness") and maps.get("basecolor"):
                    dt = ["--dtsmdi-mode", m,
                          "--metallic", maps["metallic"], "--roughness", maps["roughness"],
                          "--smdi-basecolor", maps["basecolor"]]
                elif maps.get("metallic") and maps.get("roughness"):
                    dt = ["--dtsmdi-mode", "metrough",
                          "--metallic", maps["metallic"], "--roughness", maps["roughness"]]
                if dt is not None:
                    args += ["--dtsmdi", "--dtsmdi-res", s["dtsmdi_res"],
                             "--dtsmdi-strength", str(s["dtsmdi_strength"])] + dt
                    det = [maps[k] for k in ("normal", "height") if maps.get(k)]
                    if det:
                        args += ["--dtsmdi-detail"] + det
            if s["as_on"] and maps.get("ao"):
                args += ["--ao", maps["ao"], "--as-res", s["as_res"]]
            if s["em_on"] and maps.get("emissive"):
                args += ["--emissive", maps["emissive"], "--em-res", s["em_res"]]
            if s["mc_on"]:
                if s["mc_source"].startswith("Combine"):
                    mc_paths = [maps.get(u) for u in ("user0", "user1", "user2")]
                    mc_paths = [p for p in mc_paths if p]
                    if mc_paths:
                        args += ["--mc"] + mc_paths + \
                                ["--mc-blend", s["mc_blend"].lower(), "--mc-res", s["mc_res"]]
                else:
                    mc_src = maps.get(s["mc_source"].lower())
                    if mc_src:
                        args += ["--mc", mc_src, "--mc-res", s["mc_res"]]
                # blend mask (alpha) for the _mc
                a = s["mc_alpha"]
                if "--mc" in args:
                    if a == "Auto (macro)":
                        args += ["--mc-alpha", "auto"]
                    elif a == "Opacity" and maps.get("opacity"):
                        args += ["--mc-alpha", maps["opacity"]]
                    elif a.startswith("User") and maps.get(a.lower()):
                        args += ["--mc-alpha", maps[a.lower()]]
            if make_paa:
                args += ["--paa"]
                if s["imagetopaa"].strip():
                    args += ["--imagetopaa", s["imagetopaa"].strip()]

            # The heavy numpy/Pillow conversion runs in a worker thread so the
            # Painter UI stays responsive (the Painter export above is done).
            self.status.setText("Converting… (working in the background)")
            py = s["python"]
            self._set_busy(True)

            def work():
                return _exec_cli(py, args, splog.info)

            def done(summary, error):
                try:
                    if error is not None:
                        splog.error(f"[RwG] {error}")
                        self.status.setText(f"Error: {error}")
                    else:
                        self._finish(summary, s)
                finally:
                    try:
                        if os.path.isdir(export_dir):
                            shutil.rmtree(export_dir, ignore_errors=True)
                    except Exception as ce:
                        splog.warning(f"[RwG] Could not remove {export_dir}: {ce}")
                    self._set_busy(False)

            self._run_bg(work, done)
        except Exception as e:
            self._set_busy(False)
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    # ------------------------------------------------------------------ #
    #  In-Painter map preview (window + spare-channel)                    #
    # ------------------------------------------------------------------ #
    def _preview_prepare(self, kind):
        """(main thread) Export the source channels and build the CLI args for a
        single DayZ map preview. Returns a context dict; the caller runs the
        conversion on a worker thread. Raises on any setup error."""
        if not substance_painter.project.is_open():
            raise RuntimeError("Open a project first.")
        s = self._collect()
        py = s.get("python") or detect_python()[0]
        if not py:
            raise RuntimeError("Set 'Python' (numpy + pillow) in Settings first.")

        plan = []

        def add(fn, st, sn, mode):
            if not any(o["fileName"] == fn for o in plan):
                plan.append({"fileName": fn, "srcType": st, "srcName": sn, "mode": mode})

        nfmt = "opengl" if s["normal_format"] == "opengl" else "directx"
        vnorm = "Normal_OpenGL" if nfmt == "opengl" else "Normal_DirectX"

        if kind == "co":
            if s["co_source"] == "diffuse":
                add("$textureSet_diffuse", "virtualMap", "Diffuse", "rgb")
            elif s["co_source"] == "2d_view":
                add("$textureSet_view2d", "virtualMap", "View_2D", "rgb")
            else:
                add("$textureSet_baseColor", "documentMap", "baseColor", "rgb")
                if s["co_source"] in ("base_color_specular", "specgloss"):
                    add("$textureSet_metallic", "documentMap", "metallic", "gray")
        elif kind == "nohq":
            add("$textureSet_normal", "virtualMap", vnorm, "rgb")
        elif kind == "as":
            add("$textureSet_ao", "virtualMap", "AO_Mixed", "gray")
        elif kind in ("smdi", "dtsmdi"):
            m = s["smdi_source"]
            if m == "specgloss":
                add("$textureSet_specular", "virtualMap", "Specular", "rgb")
                add("$textureSet_glossiness", "virtualMap", "Glossiness", "rgb")
            else:
                add("$textureSet_metallic", "documentMap", "metallic", "gray")
                add("$textureSet_roughness", "documentMap", "roughness", "gray")
                if m in ("pbr", "gltf", "dayz"):
                    add("$textureSet_baseColor", "documentMap", "baseColor", "rgb")
            if kind == "dtsmdi":
                add("$textureSet_normal", "virtualMap", vnorm, "rgb")
                if self._has_channel("Height"):
                    add("$textureSet_height", "documentMap", "height", "gray")
        elif kind == "em":
            add("$textureSet_emissive", "documentMap", "emissive", "rgb")
        elif kind == "mc":
            if s["mc_source"].startswith("Combine"):
                for u in ("user0", "user1", "user2"):
                    add(f"$textureSet_{u}", "documentMap", u, "rgb")
            else:
                uch = s["mc_source"].lower()
                add(f"$textureSet_{uch}", "documentMap", uch, "rgb")
            a = s["mc_alpha"]
            if a == "Opacity":
                add("$textureSet_opacity", "documentMap", "opacity", "gray")
            elif a.startswith("User"):
                add(f"$textureSet_{a.lower()}", "documentMap", a.lower(), "gray")
        else:
            raise RuntimeError(f"Unknown preview map '{kind}'.")

        if not plan:
            raise RuntimeError("Nothing to preview for this map.")

        tmp = os.path.join(tempfile.gettempdir(), "rwg_preview")
        src_dir = os.path.join(tmp, "_src")
        shutil.rmtree(src_dir, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        paths = export_project_maps(src_dir, plan, splog.info)
        maps = maps_from_export_paths(paths)
        if not maps:
            raise RuntimeError("Preview export produced no recognizable maps - see Log.")

        prefix = "rwgpreview"
        co_mode = ("base_color_specular" if s["co_source"] == "base_color_specular"
                   else "specgloss" if s["co_source"] == "specgloss" else "base_color")
        args = ["--output", tmp, "--prefix", prefix,
                "--drive", s["drive"].strip() or "P:\\",
                "--co-mode", co_mode, "--normal-format", "directx",
                "--spec", str(s["smdi_green"]), "--gloss", str(s["smdi_blue"])]

        if kind == "co":
            co_input = {"diffuse": maps.get("diffuse"),
                        "2d_view": maps.get("view2d")}.get(s["co_source"],
                                                           maps.get("basecolor"))
            if not co_input:
                raise RuntimeError("No base colour to build _co from.")
            args += ["--basecolor", co_input, "--co-res", s["co_res"]]
            if s["co_source"] in ("base_color_specular", "specgloss") and maps.get("metallic"):
                args += ["--metallic", maps["metallic"]]
        elif kind == "nohq":
            if not maps.get("normal"):
                raise RuntimeError("No normal channel to build _nohq from.")
            args += ["--normal", maps["normal"], "--nohq-res", s["nohq_res"]]
        elif kind == "as":
            if not maps.get("ao"):
                raise RuntimeError("No AO channel to build _as from.")
            args += ["--ao", maps["ao"], "--as-res", s["as_res"]]
        elif kind == "smdi":
            args += ["--smdi", "--smdi-res", s["smdi_res"]]
            m = s["smdi_source"]
            if m == "specgloss" and maps.get("specular") and maps.get("glossiness"):
                args += ["--smdi-mode", "specgloss", "--spec-map", maps["specular"],
                         "--gloss-map", maps["glossiness"]]
            elif m == "dayz" and maps.get("metallic") and maps.get("roughness"):
                args += ["--smdi-mode", "dayz", "--metallic", maps["metallic"],
                         "--roughness", maps["roughness"]] + s["dayz_rvmat"]
                if maps.get("basecolor"):
                    args += ["--smdi-basecolor", maps["basecolor"]]
            elif m in ("pbr", "gltf") and maps.get("metallic") and \
                    maps.get("roughness") and maps.get("basecolor"):
                args += ["--smdi-mode", m, "--metallic", maps["metallic"],
                         "--roughness", maps["roughness"], "--smdi-basecolor", maps["basecolor"]]
            elif maps.get("metallic") and maps.get("roughness"):
                args += ["--smdi-mode", "metrough", "--metallic", maps["metallic"],
                         "--roughness", maps["roughness"]]
            else:
                raise RuntimeError("Missing metallic/roughness (or spec/gloss) for _smdi.")
        elif kind == "dtsmdi":
            m = s["smdi_source"]
            if m == "specgloss" and maps.get("specular") and maps.get("glossiness"):
                dt = ["--dtsmdi-mode", "specgloss", "--spec-map", maps["specular"],
                      "--gloss-map", maps["glossiness"]]
            elif m == "dayz" and maps.get("metallic") and maps.get("roughness"):
                dt = ["--dtsmdi-mode", "dayz", "--metallic", maps["metallic"],
                      "--roughness", maps["roughness"]] + s["dayz_rvmat"]
                if maps.get("basecolor"):
                    dt += ["--smdi-basecolor", maps["basecolor"]]
            elif m in ("pbr", "gltf") and maps.get("metallic") and \
                    maps.get("roughness") and maps.get("basecolor"):
                dt = ["--dtsmdi-mode", m, "--metallic", maps["metallic"],
                      "--roughness", maps["roughness"], "--smdi-basecolor", maps["basecolor"]]
            elif maps.get("metallic") and maps.get("roughness"):
                dt = ["--dtsmdi-mode", "metrough", "--metallic", maps["metallic"],
                      "--roughness", maps["roughness"]]
            else:
                raise RuntimeError("Missing metallic/roughness (or spec/gloss) for _dtsmdi.")
            args += ["--dtsmdi", "--dtsmdi-res", s["dtsmdi_res"],
                     "--dtsmdi-strength", str(s["dtsmdi_strength"])] + dt
            det = [maps[k] for k in ("normal", "height") if maps.get(k)]
            if det:
                args += ["--dtsmdi-detail"] + det
        elif kind == "em":
            if not maps.get("emissive"):
                raise RuntimeError("No Emissive channel to build _em from.")
            args += ["--emissive", maps["emissive"], "--em-res", s["em_res"]]
        elif kind == "mc":
            if s["mc_source"].startswith("Combine"):
                mc_paths = [maps.get(u) for u in ("user0", "user1", "user2") if maps.get(u)]
                if not mc_paths:
                    raise RuntimeError("No User channels to build _mc from.")
                args += ["--mc"] + mc_paths + \
                        ["--mc-blend", s["mc_blend"].lower(), "--mc-res", s["mc_res"]]
            else:
                mc_src = maps.get(s["mc_source"].lower())
                if not mc_src:
                    raise RuntimeError("No User channel to build _mc from.")
                args += ["--mc", mc_src, "--mc-res", s["mc_res"]]
            a = s["mc_alpha"]
            if a == "Auto (macro)":
                args += ["--mc-alpha", "auto"]
            elif a == "Opacity" and maps.get("opacity"):
                args += ["--mc-alpha", maps["opacity"]]
            elif a.startswith("User") and maps.get(a.lower()):
                args += ["--mc-alpha", maps[a.lower()]]

        return {"py": py, "args": args, "tmp": tmp,
                "prefix": prefix, "suffix": "_" + kind, "kind": kind}

    def _preview_resolve(self, res, tmp, prefix, suffix):
        tga = None
        if isinstance(res, dict):
            tga = (res.get("tga") or {}).get(suffix)
        if not tga or not os.path.exists(tga):
            cand = os.path.join(tmp, prefix + suffix + ".tga")
            tga = cand if os.path.exists(cand) else None
        if not tga:
            raise RuntimeError(f"Converter did not produce {suffix} - see Log.")
        return tga

    def _remove_preview_layers(self, stack):
        """Delete any fill layers this plugin added for a channel preview."""
        if splayer is None:
            return
        try:
            nodes = splayer.get_root_layer_nodes(stack)
        except Exception:
            nodes = []
        for n in list(nodes):
            try:
                nm = n.get_name()
            except Exception:
                nm = ""
            if isinstance(nm, str) and nm.startswith("RwG preview"):
                done = False
                for meth in ("delete", "remove"):
                    try:
                        getattr(n, meth)()
                        done = True
                        break
                    except Exception:
                        pass
                if not done:
                    try:
                        splayer.delete_node(n)
                    except Exception as e:
                        splog.warning(f"[RwG] could not delete preview layer: {e}")

    def _push_preview_channel(self, kind, tga):
        """Load the computed map into a spare User channel via a top fill layer,
        so it can be inspected in Painter's 2D view. Best-effort / experimental."""
        if sptexset is None or splayer is None or spresource is None:
            raise RuntimeError("Layer/channel API not available in this Painter version.")
        stack = sptexset.get_active_stack()
        CT = getattr(sptexset, "ChannelType", None)
        CF = getattr(sptexset, "ChannelFormat", None)
        if stack is None or CT is None:
            raise RuntimeError("Channel API not available in this Painter version.")

        try:
            existing = set(stack.all_channels().keys())
        except Exception:
            existing = set()
        col_fmt = None
        for fn in ("sRGB8", "RGB8", "sRGB16F", "RGB16F"):
            col_fmt = getattr(CF, fn, None)
            if col_fmt is not None:
                break

        ch = None
        ch_name = None
        for uname in ("User7", "User6", "User5", "User4", "User3"):
            ct = getattr(CT, uname, None)
            if ct is None:
                continue
            if ct not in existing and col_fmt is not None:
                try:
                    stack.add_channel(ct, col_fmt)
                except Exception as e:
                    splog.warning(f"[RwG] add preview channel {uname}: {e}")
                    continue
            ch, ch_name = ct, uname
            break
        if ch is None:
            raise RuntimeError("No spare User channel available for the preview.")

        rid = spresource.import_session_resource(
            tga, spresource.Usage.TEXTURE).identifier()

        self._remove_preview_layers(stack)
        pos = splayer.InsertPosition.from_textureset_stack(stack)
        layer = splayer.insert_fill(pos)
        try:
            layer.set_name(f"RwG preview _{kind}")
        except Exception:
            pass
        # restrict the fill to the preview channel only, so it doesn't grey out
        # the real material channels
        for attr, val in (("active_channels", {ch}),):
            try:
                setattr(layer, attr, val)
            except Exception as e:
                splog.warning(f"[RwG] set {attr}: {e}")
        layer.set_source(ch, rid)
        return ch_name

    def on_preview_map(self, kind):
        if getattr(self, "_busy", False):
            self.status.setText("Busy - please wait for the current job to finish.")
            return
        kind = str(kind).lstrip("_")
        try:
            ctx = self._preview_prepare(kind)          # main: Painter export
        except Exception as e:
            splog.error(f"[RwG] preview: {e}")
            self.status.setText(f"Preview error: {e}")
            return

        self.status.setText(f"Building _{kind} preview\u2026 (background)")
        self._set_busy(True)

        def work():
            return _exec_cli(ctx["py"], ctx["args"], splog.info)

        def done(res, error):
            try:
                if error is not None:
                    splog.error(f"[RwG] preview: {error}")
                    self.status.setText(f"Preview error: {error}")
                    return
                tga = self._preview_resolve(res, ctx["tmp"], ctx["prefix"], ctx["suffix"])
                ch_name = self._push_preview_channel(kind, tga)   # main: layerstack
                self.status.setText(
                    f"_{kind} loaded into the '{ch_name}' channel - "
                    "select it in the 2D view.")
            except Exception as e:
                splog.error(f"[RwG] preview: {e}")
                self.status.setText(f"Preview error: {e}")
            finally:
                self._set_busy(False)

        self._run_bg(work, done)

    def on_clear_preview(self):
        if sptexset is None or splayer is None:
            self.status.setText("Layer API not available in this Painter version.")
            return
        try:
            stack = sptexset.get_active_stack()
            self._remove_preview_layers(stack)
            self.status.setText("Removed preview layer(s).")
        except Exception as e:
            splog.error(f"[RwG] clear preview: {e}")
            self.status.setText(f"Clear error: {e}")

    def on_load_env_hdri(self):
        """Import an equirectangular HDRI and set it as Painter's viewport
        environment (Display Settings) to match the in-game lighting while you
        paint. Unrelated to the rvmat 'env' (that's the game's reflection
        cubemap). Click loads the saved HDRI; Shift-click picks a different one."""
        if spdisplay is None or spresource is None:
            self.status.setText("Display API not available in this Painter version.")
            return
        if not substance_painter.project.is_open():
            self.status.setText("Open a project first.")
            return
        usage = getattr(spresource.Usage, "ENVIRONMENT", None)
        if usage is None:
            self.status.setText("This Painter version has no ENVIRONMENT resource usage.")
            return

        path = self.s.get("env_hdri", "")
        force_pick = bool(QtWidgets.QApplication.keyboardModifiers()
                          & QtCore.Qt.ShiftModifier)
        if force_pick or not path or not os.path.exists(path):
            start = os.path.dirname(path) if path else ""
            picked, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose a viewport HDRI (equirectangular)", start,
                "Environment images (*.hdr *.exr *.hdri *.tif *.tiff *.png *.jpg *.jpeg)")
            if not picked:
                return
            path = picked
            self.s["env_hdri"] = path
            save_settings(self.s)

        try:
            rid = spresource.import_session_resource(path, usage).identifier()
            spdisplay.set_environment_resource(rid)
            self.status.setText(
                f"Viewport environment set from {os.path.basename(path)}.")
        except Exception as e:
            splog.error(f"[RwG] env HDRI: {e}")
            self.status.setText(f"Env HDRI error: {e}")

    def on_dayz_env_dialog(self):
        """Reproject a DayZ 'hemisphere-in-plane' env image to an equirectangular
        panorama (pick the projection model by eye) and load it as Painter's
        viewport environment."""
        if spdisplay is None or spresource is None:
            self.status.setText("Display API not available in this Painter version.")
            return
        if not substance_painter.project.is_open():
            self.status.setText("Open a project first.")
            return
        usage = getattr(spresource.Usage, "ENVIRONMENT", None)
        if usage is None:
            self.status.setText("This Painter version has no ENVIRONMENT resource usage.")
            return

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("DayZ env → viewport (reproject)")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(560, 560)
        v = QtWidgets.QVBoxLayout(dlg)

        frow = QtWidgets.QHBoxLayout()
        frow.addWidget(QtWidgets.QLabel("DayZ env:"))
        src_edit = QtWidgets.QLineEdit(self.s.get("env_dayz_src", ""))
        src_edit.setToolTip("A DayZ env image (the hemisphere-in-plane texture), "
                            "e.g. a .tga export of env_land_co.")
        frow.addWidget(src_edit, 1)
        br = QtWidgets.QPushButton("…")
        br.setFixedWidth(30)

        def do_browse():
            start = os.path.dirname(src_edit.text()) if src_edit.text() else ""
            p, _ = QtWidgets.QFileDialog.getOpenFileName(
                dlg, "DayZ env map", start,
                "Env image (*.tga *.png *.tif *.tiff *.jpg *.jpeg)")
            if p:
                src_edit.setText(p)
        br.clicked.connect(do_browse)
        frow.addWidget(br)
        v.addLayout(frow)

        orow = QtWidgets.QHBoxLayout()
        orow.addWidget(QtWidgets.QLabel("Tiles:"))
        tiles_cb = QtWidgets.QComboBox()
        tiles_cb.addItems(["2", "3", "4", "5", "6"])
        tiles_cb.setCurrentText(str(self.s.get("env_dayz_tiles", "3")))
        tiles_cb.setToolTip("How many times the landscape plate repeats around "
                            "360°. 3 usually looks natural.")
        orow.addWidget(tiles_cb)
        mirror_cb = QtWidgets.QCheckBox("mirror")
        mirror_cb.setChecked(bool(self.s.get("env_dayz_mirror", True)))
        mirror_cb.setToolTip("Mirror alternate copies so the tile seams vanish.")
        orow.addWidget(mirror_cb)
        orow.addSpacing(10)
        orow.addWidget(QtWidgets.QLabel("Exp:"))
        gain_cb = QtWidgets.QComboBox()
        gain_cb.addItems(["1.0", "1.5", "2.0", "3.0", "4.0"])
        gain_cb.setCurrentText(str(self.s.get("env_dayz_gain", "2.0")))
        gain_cb.setToolTip("Brightness/exposure of the env. The DayZ plate is a "
                           "dim LDR image, so 2–3 usually lights the model well "
                           "(written as a real .hdr).")
        orow.addWidget(gain_cb)
        orow.addSpacing(10)
        orow.addWidget(QtWidgets.QLabel("Rotate:"))
        rot_cb = QtWidgets.QComboBox()
        rot_cb.addItems(["0°", "90°", "180°", "270°"])
        rot_cb.setCurrentText(str(self.s.get("env_dayz_rot", "0")).rstrip("°") + "°")
        rot_cb.setToolTip("Rotate the panorama horizontally (which way faces front).")
        orow.addWidget(rot_cb)
        orow.addStretch(1)
        v.addLayout(orow)

        img = QtWidgets.QLabel("Preview the reprojection, then load it into the viewport.")
        img.setAlignment(QtCore.Qt.AlignCenter)
        img.setMinimumSize(512, 256)
        v.addWidget(img, 1)
        info = QtWidgets.QLabel("")
        info.setStyleSheet("color:#9aa0a6;")
        v.addWidget(info)

        prow = QtWidgets.QHBoxLayout()
        pv = QtWidgets.QPushButton("Preview")
        load = QtWidgets.QPushButton("Load into viewport")
        load.setObjectName("primary")
        close = QtWidgets.QPushButton("Close")

        def reproject(then):
            src = src_edit.text().strip()
            if not src or not os.path.exists(src):
                info.setText("Pick a valid DayZ env image.")
                return
            py = self.s.get("python") or detect_python()[0]
            if not py:
                info.setText("Set 'Python' (numpy + pillow) in Settings first.")
                return
            rot = rot_cb.currentText().rstrip("°") or "0"
            tiles = tiles_cb.currentText()
            gain = gain_cb.currentText()
            self.s["env_dayz_src"] = src
            self.s["env_dayz_tiles"] = tiles
            self.s["env_dayz_mirror"] = mirror_cb.isChecked()
            self.s["env_dayz_rot"] = rot
            self.s["env_dayz_gain"] = gain
            save_settings(self.s)
            out = os.path.join(tempfile.gettempdir(), "rwg_preview",
                               "dayz_env_equirect.png")
            args = ["--reproject-env", src, "--reproject-out", out,
                    "--reproject-tiles", tiles, "--reproject-rot", rot,
                    "--reproject-gain", gain]
            if not mirror_cb.isChecked():
                args += ["--reproject-no-mirror"]
            for b in (pv, load):
                b.setEnabled(False)
            info.setText("Reprojecting…")

            def work():
                return _exec_cli(py, args, splog.info)

            def done(res, err):
                try:
                    if err is not None:
                        info.setText(f"Error: {err}")
                        return
                    res = res if isinstance(res, dict) else {}
                    env = res.get("env")                      # .hdr for loading
                    preview = res.get("env_preview") or env   # .png for display
                    if not env or not os.path.exists(env):
                        info.setText("Reproject produced nothing - see Log.")
                        return
                    pm = QtGui.QPixmap(preview)
                    if not pm.isNull():
                        img.setPixmap(pm.scaled(512, 256, QtCore.Qt.KeepAspectRatio,
                                                QtCore.Qt.SmoothTransformation))
                    info.setText(os.path.basename(env))
                    if then:
                        then(env)
                finally:
                    for b in (pv, load):
                        b.setEnabled(True)

            self._run_bg(work, done)

        def do_load(path):
            try:
                rid = spresource.import_session_resource(path, usage).identifier()
                spdisplay.set_environment_resource(rid)
                info.setText(f"Viewport environment set from {os.path.basename(path)}.")
                self.status.setText("DayZ env loaded into the viewport.")
            except Exception as e:
                splog.error(f"[RwG] dayz env load: {e}")
                info.setText(f"Load error: {e}")

        pv.clicked.connect(lambda: reproject(None))
        load.clicked.connect(lambda: reproject(do_load))
        close.clicked.connect(dlg.accept)
        prow.addWidget(pv)
        prow.addStretch(1)
        prow.addWidget(load)
        prow.addWidget(close)
        v.addLayout(prow)
        (getattr(dlg, "exec", None) or getattr(dlg, "exec_"))()

    def on_set_tone(self, name):
        """Set Painter's viewport tone mapping (ACES / Linear)."""
        if spdisplay is None:
            self.status.setText("Display API not available in this Painter version.")
            return
        tmf = getattr(spdisplay, "ToneMappingFunction", None)
        val = getattr(tmf, name, None) if tmf is not None else None
        if val is None:
            self.status.setText(f"Tone mapping '{name}' not available.")
            return
        try:
            spdisplay.set_tone_mapping(val)
            self.s["env_tone"] = name
            save_settings(self.s)
            self.status.setText(f"Viewport tone mapping: {name}.")
        except Exception as e:
            splog.error(f"[RwG] tone: {e}")
            self.status.setText(f"Tone error: {e}")

    def _reproject_and_load_env(self, src, tiles, mirror, rot, gain="2.0", tone=None):
        """Wrap the DayZ env plate to an equirect (background) and load it as the
        viewport environment; optionally also set the tone mapping."""
        if spdisplay is None or spresource is None:
            self.status.setText("Display API not available in this Painter version.")
            return
        if not (src and os.path.exists(src)):
            self.status.setText("Pick a DayZ env first via 'DayZ env…'.")
            return
        py = self.s.get("python") or detect_python()[0]
        if not py:
            self.status.setText("Set 'Python' (numpy + pillow) in Settings first.")
            return
        out = os.path.join(tempfile.gettempdir(), "rwg_preview",
                           "dayz_env_equirect.png")
        args = ["--reproject-env", src, "--reproject-out", out,
                "--reproject-tiles", str(tiles), "--reproject-rot", str(rot),
                "--reproject-gain", str(gain)]
        if not mirror:
            args += ["--reproject-no-mirror"]
        self.status.setText("Building DayZ env… (background)")

        def work():
            return _exec_cli(py, args, splog.info)

        def done(res, err):
            if err is not None:
                splog.error(f"[RwG] {err}")
                self.status.setText(f"Error: {err}")
                return
            path = (res or {}).get("env") if isinstance(res, dict) else None
            if not path or not os.path.exists(path):
                self.status.setText("Reproject produced nothing - see Log.")
                return
            try:
                usage = getattr(spresource.Usage, "ENVIRONMENT", None)
                rid = spresource.import_session_resource(path, usage).identifier()
                spdisplay.set_environment_resource(rid)
                if tone:
                    self.on_set_tone(tone)
                self.status.setText(
                    "DayZ look applied (viewport env"
                    + (f" + {tone} tone" if tone else "") + ").")
            except Exception as e:
                splog.error(f"[RwG] env load: {e}")
                self.status.setText(f"Load error: {e}")

        self._run_bg(work, done)

    def on_dayz_look(self):
        """One click: build the saved DayZ env (bright HDR), load it as the
        viewport environment and apply the chosen tone mapping. (The RwG DayZ
        Super shader stays a manual assignment.)"""
        if not substance_painter.project.is_open():
            self.status.setText("Open a project first.")
            return
        tone = self.tone_cb.currentText() if hasattr(self, "tone_cb") else "ACES"
        self._reproject_and_load_env(
            self.s.get("env_dayz_src", ""),
            self.s.get("env_dayz_tiles", "3"),
            bool(self.s.get("env_dayz_mirror", True)),
            self.s.get("env_dayz_rot", "0"),
            gain=self.s.get("env_dayz_gain", "2.0"),
            tone=tone)

    # ------------------------------------------------------------------ #
    #  config.cpp snippet (hiddenSelectionsMaterials + healthLevels)      #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _rvmat_with_suffix(path, suffix):
        if not suffix:
            return path
        root, ext = os.path.splitext(path)
        return root + suffix + (ext or ".rvmat")

    @staticmethod
    def _fmt_threshold(t):
        return str(int(t)) if float(t).is_integer() else f"{t:g}"

    def _build_config_snippet(self, selections, hitpoints="100",
                              include_damage=True, worn=False, include_hidden=True):
        """selections: list of (name, co_paa, rvmat), all mod-relative. Returns a
        copy-paste config.cpp block."""
        names = [n for n, _, _ in selections]
        cos = [c for _, c, _ in selections]
        rv = [r for _, _, r in selections]
        out = ["// --- RwG DayZ Texture Exporter: paste into your item's class ---"]
        if include_hidden:
            out.append("hiddenSelections[] = {"
                       + ", ".join(f'"{n}"' for n in names) + "};")
        out.append("hiddenSelectionsTextures[] = {"
                   + ", ".join(f'"{c}"' for c in cos) + "};")
        out.append("hiddenSelectionsMaterials[] = {"
                   + ", ".join(f'"{r}"' for r in rv) + "};")
        if include_damage:
            # 1.0 pristine .. 0.0 ruined. Weapons/most items reuse the base at 0.7
            # (no _worn); tick 'worn' for families that have a _worn variant.
            if worn:
                levels = [(1.0, ""), (0.7, "_worn"), (0.5, "_damage"),
                          (0.3, "_damage"), (0.0, "_destruct")]
            else:
                levels = [(1.0, ""), (0.7, ""), (0.5, "_damage"),
                          (0.3, "_damage"), (0.0, "_destruct")]
            rows = []
            for thr, suf in levels:
                mats = ", ".join(f'"{self._rvmat_with_suffix(r, suf)}"' for r in rv)
                rows.append(f"                {{{self._fmt_threshold(thr)}, {{{mats}}}}}")
            out.append("")
            out.append("class DamageSystem")
            out.append("{")
            out.append("    class GlobalHealth")
            out.append("    {")
            out.append("        class Health")
            out.append("        {")
            out.append(f"            hitpoints = {hitpoints};")
            out.append("            healthLevels[] =")
            out.append("            {")
            out.append(",\n".join(rows))
            out.append("            };")
            out.append("        };")
            out.append("    };")
            out.append("};")
            out.append("// Note: make sure the referenced _damage/_destruct "
                       ".rvmats exist")
            out.append("// (generate them with the Damage variants buttons).")
        return "\n".join(out)

    def on_config_snippet(self):
        s = self._collect()
        drive = s["drive"].strip() or "P:\\"
        out_dir = s["output"].strip()
        prefix = self._prefix(s)
        base_rvmat = self.rvmat_path or (
            os.path.join(out_dir, prefix + ".rvmat") if out_dir else "")

        def modrel(path):
            if not path:
                return ""
            try:
                rel, _ = paa_tools.mod_relative_path(path, drive_letter=drive)
                return rel
            except Exception:
                return path

        default_rvmat = modrel(base_rvmat)
        default_co = modrel(os.path.join(out_dir, prefix + "_co.paa")) if out_dir else \
            (self._rvmat_with_suffix(default_rvmat, "").replace(".rvmat", "_co.paa")
             if default_rvmat else "")

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Config snippet (config.cpp)")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(760, 580)
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel(
            "One row per named selection (e.g. camo, bullet): its _co texture and "
            "base .rvmat, mod-relative to your P: drive."))

        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Selection", "_co (.paa)", "rvmat"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        v.addWidget(table, 1)

        def add_row(name="camo", co=default_co, rvmat=default_rvmat):
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            table.setItem(r, 1, QtWidgets.QTableWidgetItem(co))
            table.setItem(r, 2, QtWidgets.QTableWidgetItem(rvmat))
        add_row()

        rowbtns = QtWidgets.QHBoxLayout()
        add_b = QtWidgets.QPushButton("+ selection")
        add_b.clicked.connect(lambda: add_row("", "", ""))
        rem_b = QtWidgets.QPushButton("− remove")
        rem_b.clicked.connect(lambda: table.removeRow(table.currentRow())
                              if table.currentRow() >= 0 else None)
        rowbtns.addWidget(add_b)
        rowbtns.addWidget(rem_b)
        rowbtns.addStretch(1)
        v.addLayout(rowbtns)

        orow = QtWidgets.QHBoxLayout()
        orow.addWidget(QtWidgets.QLabel("hitpoints:"))
        hp_edit = QtWidgets.QLineEdit("100")
        hp_edit.setFixedWidth(70)
        orow.addWidget(hp_edit)
        orow.addSpacing(12)
        inc_dmg = QtWidgets.QCheckBox("damage states")
        inc_dmg.setChecked(True)
        inc_dmg.setToolTip("Add the DamageSystem healthLevels block "
                           "(base .. _damage .. _destruct).")
        orow.addWidget(inc_dmg)
        worn_cb = QtWidgets.QCheckBox("use _worn @ 0.7")
        worn_cb.setToolTip("For families that have a _worn variant (e.g. Generic). "
                           "Off = reuse the base at 0.7 (like weapons).")
        orow.addWidget(worn_cb)
        hid_cb = QtWidgets.QCheckBox("include hiddenSelections[]")
        hid_cb.setChecked(True)
        hid_cb.setToolTip("Untick if your base class already defines hiddenSelections[].")
        orow.addWidget(hid_cb)
        orow.addStretch(1)
        v.addLayout(orow)

        out_edit = QtWidgets.QPlainTextEdit()   # editable, so you can tweak before copy
        out_edit.setMinimumHeight(200)
        v.addWidget(out_edit, 1)

        def generate():
            sels = []
            for r in range(table.rowCount()):
                n = table.item(r, 0).text().strip() if table.item(r, 0) else ""
                co = table.item(r, 1).text().strip() if table.item(r, 1) else ""
                rv = table.item(r, 2).text().strip() if table.item(r, 2) else ""
                if n and rv:
                    sels.append((n, co, rv))
            if not sels:
                out_edit.setPlainText("Add at least one selection with a rvmat path.")
                return
            out_edit.setPlainText(self._build_config_snippet(
                sels, hitpoints=hp_edit.text().strip() or "100",
                include_damage=inc_dmg.isChecked(), worn=worn_cb.isChecked(),
                include_hidden=hid_cb.isChecked()))

        brow = QtWidgets.QHBoxLayout()
        gen = QtWidgets.QPushButton("Generate")
        gen.setObjectName("primary")
        gen.clicked.connect(generate)
        brow.addWidget(gen)
        copy = QtWidgets.QPushButton("Copy")

        def do_copy():
            app = QtWidgets.QApplication.instance()
            if app and out_edit.toPlainText().strip():
                app.clipboard().setText(out_edit.toPlainText())
                self.status.setText("Config snippet copied to clipboard.")
        copy.clicked.connect(do_copy)
        brow.addWidget(copy)
        save = QtWidgets.QPushButton("Save .txt")

        def do_save():
            if not out_edit.toPlainText().strip():
                return
            start = s["output"].strip() or ""
            p, _ = QtWidgets.QFileDialog.getSaveFileName(
                dlg, "Save config snippet", os.path.join(start, "config_snippet.txt"),
                "Text (*.txt)")
            if p:
                try:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(out_edit.toPlainText())
                    self.status.setText(f"Config snippet saved: {os.path.basename(p)}")
                except Exception as e:
                    splog.error(f"[RwG] config snippet: {e}")
        save.clicked.connect(do_save)
        brow.addWidget(save)
        brow.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dlg.accept)
        brow.addWidget(close)
        v.addLayout(brow)

        generate()
        (getattr(dlg, "exec", None) or getattr(dlg, "exec_"))()

    # ------------------------------------------------------------------ #
    #  RVMAT validator / linter                                           #
    # ------------------------------------------------------------------ #
    _SEV_STYLE = {
        rvmat_writer.SEV_ERROR: ("ERROR", QtGui.QColor(255, 90, 98)),
        rvmat_writer.SEV_WARN:  ("WARN",  QtGui.QColor(240, 190, 90)),
        rvmat_writer.SEV_INFO:  ("INFO",  QtGui.QColor(140, 180, 240)),
        rvmat_writer.SEV_OK:    ("OK",    QtGui.QColor(120, 210, 130)),
    }

    def on_validate_rvmat(self):
        s = self._collect()
        drive = s["drive"].strip() or "P:\\"
        out_dir = s["output"].strip()
        prefix = self._prefix(s)
        default_path = self.rvmat_path or (
            os.path.join(out_dir, prefix + ".rvmat") if out_dir else "")

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Validate .rvmat")
        dlg.setStyleSheet(DOCK_QSS)
        dlg.resize(760, 560)
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel(
            "Lints a DayZ Super-shader .rvmat: shader IDs, the 7 stages, and each "
            "texture path (extension, slashes, mod-relative, exists on your drive)."))

        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel(".rvmat:"))
        path_edit = QtWidgets.QLineEdit(default_path)
        prow.addWidget(path_edit, 1)
        browse = QtWidgets.QPushButton("Browse…")

        def do_browse():
            start = out_dir or os.path.dirname(default_path) or ""
            p, _ = QtWidgets.QFileDialog.getOpenFileName(
                dlg, "Choose .rvmat", start, "RVMAT (*.rvmat);;All files (*)")
            if p:
                path_edit.setText(p)
        browse.clicked.connect(do_browse)
        prow.addWidget(browse)
        v.addLayout(prow)

        summary = QtWidgets.QLabel("")
        v.addWidget(summary)

        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Severity", "Where", "Finding"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        v.addWidget(table, 1)

        def run():
            path = path_edit.text().strip()
            table.setRowCount(0)
            if not path or not os.path.isfile(path):
                summary.setText("File not found - pick an existing .rvmat.")
                return
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception as e:
                summary.setText("Could not read the file: %s" % e)
                return
            findings = rvmat_writer.validate_rvmat(text, drive=drive, check_files=True)
            counts = {rvmat_writer.SEV_ERROR: 0, rvmat_writer.SEV_WARN: 0,
                      rvmat_writer.SEV_INFO: 0, rvmat_writer.SEV_OK: 0}
            for sev, area, msg in findings:
                counts[sev] = counts.get(sev, 0) + 1
                r = table.rowCount()
                table.insertRow(r)
                label, color = self._SEV_STYLE.get(sev, (sev.upper(), None))
                sev_item = QtWidgets.QTableWidgetItem(label)
                if color is not None:
                    sev_item.setForeground(color)
                    f = sev_item.font(); f.setBold(True); sev_item.setFont(f)
                table.setItem(r, 0, sev_item)
                table.setItem(r, 1, QtWidgets.QTableWidgetItem(area))
                table.setItem(r, 2, QtWidgets.QTableWidgetItem(msg))
            table.resizeRowsToContents()
            if counts[rvmat_writer.SEV_ERROR]:
                verdict = "%d error(s)" % counts[rvmat_writer.SEV_ERROR]
            elif counts[rvmat_writer.SEV_WARN]:
                verdict = "no errors, %d warning(s)" % counts[rvmat_writer.SEV_WARN]
            else:
                verdict = "looks good"
            summary.setText("%s  -  %s   (%d errors, %d warnings, %d info)" % (
                os.path.basename(path), verdict,
                counts[rvmat_writer.SEV_ERROR], counts[rvmat_writer.SEV_WARN],
                counts[rvmat_writer.SEV_INFO]))

        brow = QtWidgets.QHBoxLayout()
        run_btn = QtWidgets.QPushButton("Validate")
        run_btn.setObjectName("primary")
        run_btn.clicked.connect(run)
        brow.addWidget(run_btn)
        copy = QtWidgets.QPushButton("Copy report")

        def do_copy():
            lines = []
            for r in range(table.rowCount()):
                lines.append("[%s] %s: %s" % (
                    table.item(r, 0).text(), table.item(r, 1).text(),
                    table.item(r, 2).text()))
            app = QtWidgets.QApplication.instance()
            if app and lines:
                app.clipboard().setText("\n".join(lines))
                self.status.setText("Validation report copied to clipboard.")
        copy.clicked.connect(do_copy)
        brow.addWidget(copy)
        brow.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dlg.accept)
        brow.addWidget(close)
        v.addLayout(brow)

        run()
        (getattr(dlg, "exec", None) or getattr(dlg, "exec_"))()

    def _do_export_preset(self, make_paa, s):
        """Run the user's own Painter export preset, then optional .paa + rvmat
        auto-fill. Everything here runs inside Painter (no external Python)."""
        try:
            if not substance_painter.project.is_open():
                self.status.setText("No project open."); return
            if not s["output"].strip():
                self.status.setText("Choose an output folder first."); return
            out = s["output"].strip()
            self.status.setText("Running Painter preset..."); QtWidgets.QApplication.processEvents()
            paths = export_with_preset(out, s["painter_preset"].strip() or "DayZ",
                                       s["preset_shelf"].strip() or "your_assets", splog.info)
            if not paths:
                self.status.setText("Preset export produced nothing - see Log."); return

            paa_files = []
            if make_paa:
                exe = s["imagetopaa"].strip() or None
                if not exe:
                    splog.warning("[RwG] .paa requested but ImageToPAA.exe is not set.")
                for p in paths:
                    if p.lower().endswith(".tga"):
                        try:
                            paa_files.append(paa_tools.tga_to_paa(p, imagetopaa_exe=exe))
                        except Exception as e:
                            splog.warning(f"[RwG] .paa {os.path.basename(p)}: {e}")

            if s.get("autofill_on_export", True):
                self._autofill_rvmat_from_files(paa_files + paths, s)
            msg = f"Preset '{s['painter_preset']}' exported {len(paths)} map(s)"
            if paa_files:
                msg += f", {len(paa_files)} .paa"
            self.status.setText(msg)
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    def _autofill_rvmat_from_files(self, files, s):
        """Fill NOHQ/AS/SMDI rvmat fields from produced files (with the chosen
        extension)."""
        drive = s["drive"].strip() or "P:\\"
        ext = s["tex_ext"]

        def find(suffix):
            cands = [f for f in files if suffix in os.path.basename(f).lower()]
            if not cands:
                return None
            src = os.path.splitext(cands[0])[0] + "." + ext
            rel, _ok = paa_tools.mod_relative_path(src, drive_letter=drive)
            return rel

        n, a, sm = find("_nohq"), find("_as"), find("_smdi")
        if n:
            self.nohq_ref.setText(n)
        if a:
            self.as_ref.setText(a)
        if sm:
            self.smdi_ref.setText(sm)

    def on_convert_folder_paa(self):
        if getattr(self, "_busy", False):
            self.status.setText("Busy - please wait for the current job to finish.")
            return
        s = self._collect()
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder with .tga files")
        if not folder:
            return
        args = ["--paa-folder", folder]
        if s["imagetopaa"].strip():
            args += ["--imagetopaa", s["imagetopaa"].strip()]
        py = s["python"]
        self.status.setText("Converting to .paa… (background)")
        self._set_busy(True)

        def work():
            return _exec_cli(py, args, splog.info)

        def done(summary, error):
            try:
                if error is not None:
                    splog.error(f"[RwG] {error}")
                    self.status.setText(f"Error: {error}")
                elif summary:
                    n = len(summary.get("paa", {}))
                    self.status.setText(
                        f".paa written: {n} file(s)"
                        + (f", {len(summary['errors'])} error(s)"
                           if summary.get("errors") else ""))
                    for e in summary.get("errors", []):
                        splog.warning(f"[RwG] {e}")
                else:
                    self.status.setText("Done - see Log.")
            finally:
                self._set_busy(False)

        self._run_bg(work, done)

    def _finish(self, summary, s):
        if not summary:
            self.status.setText("Done, but no summary - see Log."); return
        made = list(summary.get("tga", {}).keys())
        paa = summary.get("paa", {})
        msg = "Created: " + (", ".join(made) or "nothing")
        if paa:
            msg += " | .paa: " + ", ".join(paa.keys())
        for e in summary.get("errors", []):
            splog.warning(f"[RwG] {e}")
        for n in summary.get("notes", []):
            splog.info(f"[RwG] {n}")
        if summary.get("errors"):
            msg += f"  ({len(summary['errors'])} issue(s) - see Log)"
        self.status.setText(msg)
        if s.get("autofill_on_export", True):
            self._autofill_rvmat(summary, s)

    def _autofill_rvmat(self, summary, s):
        """Fill the rvmat texture fields from the produced maps (mod-relative,
        with the extension chosen in the RVMAT section)."""
        drive = s["drive"].strip() or "P:\\"
        ext = s["tex_ext"]
        tga, paa = summary.get("tga", {}), summary.get("paa", {})

        def ref(suffix):
            src = paa.get(suffix) or tga.get(suffix)
            if not src:
                return None
            src = os.path.splitext(src)[0] + "." + ext   # reference the chosen ext
            rel, _ok = paa_tools.mod_relative_path(src, drive_letter=drive)
            return rel
        for suffix, edit in (("_nohq", self.nohq_ref), ("_as", self.as_ref),
                             ("_smdi", self.smdi_ref), ("_mc", self.mc_ref)):
            r = ref(suffix)
            if r:
                edit.setText(r)

    # ---------- rvmat presets (built-in + user, one grouped dropdown) ----------
    def _populate_preset_combo(self, select=None):
        """Fill the preset dropdown: a '- Presets -' group (built in) then a
        '- My presets -' group (yours). Item data = ('builtin'|'user', name);
        the group headers are disabled non-selectable rows."""
        combo = getattr(self, "preset_combo", None)
        if combo is None:
            return

        def header(text):
            combo.addItem(text, None)
            try:
                combo.model().item(combo.count() - 1).setEnabled(False)
            except Exception:
                pass

        combo.blockSignals(True)
        combo.clear()
        header("─ Presets ─")
        for name in PRESETS:
            combo.addItem(f"   {name}", ("builtin", name))
        header("─ My presets ─")
        users = sorted(load_user_presets(self._presets_folder()).keys(), key=str.lower)
        if users:
            for name in users:
                combo.addItem(f"   {name}", ("user", name))
        else:
            combo.addItem("   (none saved)", None)
            try:
                combo.model().item(combo.count() - 1).setEnabled(False)
            except Exception:
                pass
        # restore selection (by name), else first selectable item
        target = None
        if select:
            for i in range(combo.count()):
                d = combo.itemData(i)
                if d and d[1] == select:
                    target = i
                    break
        if target is None:
            for i in range(combo.count()):
                if combo.itemData(i):
                    target = i
                    break
        if target is not None:
            combo.setCurrentIndex(target)
        combo.blockSignals(False)

    def _selected_builtin_preset(self):
        """The currently selected built-in preset name (falls back to the last
        one) - kept valid for the .rvmat export path that needs a real preset."""
        d = self.preset_combo.currentData() if hasattr(self, "preset_combo") else None
        if d and d[0] == "builtin":
            return d[1]
        return self.s.get("preset", "Default")

    def on_load_preset(self):
        """Load the selected preset - built-in or one of yours - into the fields."""
        d = self.preset_combo.currentData()
        if not d:
            self.status.setText("Pick a preset from the list first."); return
        kind, name = d
        if kind == "builtin":
            self._apply_builtin_preset(name)
        else:
            self.on_load_user_preset(name)

    def _apply_builtin_preset(self, name):
        """Fill the material value fields from a built-in preset (textures kept)."""
        p = rvmat_writer.MATERIAL_PRESETS.get(name, rvmat_writer.MATERIAL_PRESETS["Default"])
        self.mat_ambient.setText(_vec_str(p["ambient"]))
        self.mat_diffuse.setText(_vec_str(p["diffuse"]))
        self.mat_forced.setText(_vec_str(p["forcedDiffuse"]))
        self.mat_emmisive.setText(_vec_str(p["emmisive"]))
        self.mat_specular.setText(_vec_str(p["specular"]))
        self.mat_power.setText(str(p["specularPower"]))
        n, k = _parse_fresnel_nk(p["fresnel"])
        self.mat_fresnel_n.setText(n)
        self.mat_fresnel_k.setText(k)
        if p.get("env"):
            self.env_combo.setCurrentText(p["env"])
        self.status.setText(f"Loaded preset '{name}' values into the fields.")

    # ---------- fresnel material library (built-in + user) ----------
    def _populate_fresnel_combo(self, select=None):
        """Fill the material N/K dropdown: a '- Materials -' group (built in) then
        a '- My materials -' group (yours). Item data = ('builtin'|'user', name)."""
        combo = getattr(self, "fresnel_mat_combo", None)
        if combo is None:
            return

        def header(text):
            combo.addItem(text, None)
            try:
                combo.model().item(combo.count() - 1).setEnabled(False)
            except Exception:
                pass

        self._fresnel_lib = rvmat_writer.fresnel_materials()
        self._fresnel_user = load_user_fresnel(self._presets_folder())
        combo.blockSignals(True)
        combo.clear()
        header("─ Materials ─")
        for name, m in self._fresnel_lib.items():
            f0 = rvmat_writer.fresnel_f0(m["n"], m["k"])
            combo.addItem(f"   {name}   (F0 {f0:.3f})", ("builtin", name))
        header("─ My materials ─")
        if self._fresnel_user:
            for name in sorted(self._fresnel_user.keys(), key=str.lower):
                m = self._fresnel_user[name]
                f0 = rvmat_writer.fresnel_f0(m.get("n", 1.5), m.get("k", 0.0))
                combo.addItem(f"   {name}   (F0 {f0:.3f})", ("user", name))
        else:
            combo.addItem("   (none saved)", None)
            try:
                combo.model().item(combo.count() - 1).setEnabled(False)
            except Exception:
                pass
        target = None
        if select:
            for i in range(combo.count()):
                d = combo.itemData(i)
                if d and d[1] == select:
                    target = i
                    break
        if target is None:
            for i in range(combo.count()):
                if combo.itemData(i):
                    target = i
                    break
        if target is not None:
            combo.setCurrentIndex(target)
        combo.blockSignals(False)

    def _selected_fresnel_material(self):
        """Return the (name, {n,k,specular}) for the current dropdown selection."""
        d = self.fresnel_mat_combo.currentData()
        if not d:
            return None, None
        kind, name = d
        if kind == "builtin":
            return name, (getattr(self, "_fresnel_lib", None)
                          or rvmat_writer.fresnel_materials()).get(name)
        return name, (getattr(self, "_fresnel_user", None) or {}).get(name)

    def on_apply_fresnel_material(self):
        """Set fresnel N/K + specular tint from the selected library material."""
        name, m = self._selected_fresnel_material()
        if not m:
            self.status.setText("Pick a material from the list first."); return
        self.mat_fresnel_n.setText(str(m["n"]))
        self.mat_fresnel_k.setText(str(m["k"]))
        self.mat_specular.setText(",".join(str(x) for x in m["specular"]))
        f0 = rvmat_writer.fresnel_f0(m["n"], m["k"])
        self.status.setText(f"{name}: fresnel({m['n']},{m['k']})  F0 {f0:.3f}  "
                            f"specular {self.mat_specular.text()}")

    def _parse_specular_field(self):
        """Read the specular field as a 4-float list (padded/clamped to RGBA)."""
        parts = [p.strip() for p in self.mat_specular.text().split(",")]
        vals = []
        for p in parts[:4]:
            try:
                vals.append(round(float(p), 4))
            except ValueError:
                vals.append(1.0)
        while len(vals) < 4:
            vals.append(1.0)
        return vals

    def on_save_fresnel_material(self):
        """Save the current fresnel N/K + specular tint as a user material."""
        d = self.fresnel_mat_combo.currentData()
        suggested = d[1] if (d and d[0] == "user") else ""
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save material", "Material name:",
            QtWidgets.QLineEdit.Normal, suggested)
        if not ok:
            return
        name = name.strip()
        if not name:
            self.status.setText("Enter a name to save the material."); return
        try:
            n = float(self.mat_fresnel_n.text())
            k = float(self.mat_fresnel_k.text())
        except ValueError:
            self.status.setText("Fresnel N/K must be numbers."); return
        folder = self._presets_folder()
        mats = load_user_fresnel(folder)
        mats[name] = {"n": n, "k": k, "specular": self._parse_specular_field()}
        save_user_fresnel(mats, folder)
        self._populate_fresnel_combo(select=name)
        f0 = rvmat_writer.fresnel_f0(n, k)
        self.status.setText(f"Saved material '{name}': fresnel({n},{k})  F0 {f0:.3f}")

    def on_delete_fresnel_material(self):
        """Delete the selected user material (built-in materials can't be deleted)."""
        d = self.fresnel_mat_combo.currentData()
        if not d or d[0] != "user":
            self.status.setText("Select one of your materials to delete "
                                "(built-in materials can't be deleted)."); return
        name = d[1]
        folder = self._presets_folder()
        mats = load_user_fresnel(folder)
        if name not in mats:
            self.status.setText(f"No saved material named '{name}'."); return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete material")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText(f"Delete your material '{name}'?")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        run = getattr(box, "exec", None) or getattr(box, "exec_")
        if run() != QtWidgets.QMessageBox.Yes:
            self.status.setText("Delete cancelled."); return
        del mats[name]
        save_user_fresnel(mats, folder)
        self._populate_fresnel_combo(select="")
        self.status.setText(f"Deleted material '{name}'.")

    # ---------- user (custom) material presets ----------
    def _presets_folder(self):
        return (self.s.get("presets_path") or "").strip()

    def _refresh_user_presets(self, select=None):
        """Repopulate the merged preset dropdown (built-in + user) from disk."""
        try:
            self._populate_preset_combo(select=select or self._selected_builtin_preset())
        except Exception as e:
            splog.warning(f"[RwG] user preset refresh: {e}")

    def on_save_user_preset(self):
        """Save the current material VALUES as one of your presets (asks a name)."""
        d = self.preset_combo.currentData()
        suggested = d[1] if (d and d[0] == "user") else ""
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save preset", "Preset name:", QtWidgets.QLineEdit.Normal, suggested)
        if not ok:
            return
        name = name.strip()
        if not name:
            self.status.setText("Enter a name to save the preset."); return
        s = self._collect()
        folder = self._presets_folder()
        presets = load_user_presets(folder)
        presets[name] = {k: s.get(k) for k in USER_PRESET_KEYS}
        save_user_presets(presets, folder)
        self._populate_preset_combo(select=name)
        self.status.setText(f"Saved preset '{name}' -> {user_presets_file(folder)}")

    def on_load_user_preset(self, name=None):
        """Load one of your presets' material values; reset texture stages to
        their procedural defaults (only numbers + default textures load)."""
        if not name:
            d = self.preset_combo.currentData()
            name = d[1] if (d and d[0] == "user") else None
        if not name:
            self.status.setText("Pick one of your presets to load."); return
        presets = load_user_presets(self._presets_folder())
        p = presets.get(name)
        if not p:
            self.status.setText(f"No saved preset named '{name}'."); return
        setters = {
            "mat_ambient": self.mat_ambient, "mat_diffuse": self.mat_diffuse,
            "mat_forced": self.mat_forced, "mat_emmisive": self.mat_emmisive,
            "mat_specular": self.mat_specular, "mat_power": self.mat_power,
            "mat_fresnel_n": self.mat_fresnel_n, "mat_fresnel_k": self.mat_fresnel_k,
        }
        for key, widget in setters.items():
            if p.get(key) is not None:
                widget.setText(str(p[key]))
        if p.get("env"):
            self.env_combo.setCurrentText(p["env"])
        # reset texture stages to their procedural defaults
        dflt = rvmat_writer.DEFAULT_TEXTURES
        for edit, tkey in ((self.nohq_ref, "NOHQ"), (self.as_ref, "AS"),
                           (self.smdi_ref, "SMDI"), (self.mc_ref, "MC")):
            edit.setText(dflt[tkey])
        self.status.setText(f"Loaded your preset '{name}' (textures reset to default).")

    def on_delete_user_preset(self):
        """Remove the selected user preset (built-in presets can't be deleted)."""
        d = self.preset_combo.currentData()
        if not d or d[0] != "user":
            self.status.setText("Select one of your presets to delete "
                                "(built-in presets can't be deleted)."); return
        name = d[1]
        folder = self._presets_folder()
        presets = load_user_presets(folder)
        if name not in presets:
            self.status.setText(f"No saved preset named '{name}'."); return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete preset")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText(f"Delete your preset '{name}'?")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        run = getattr(box, "exec", None) or getattr(box, "exec_")
        if run() != QtWidgets.QMessageBox.Yes:
            self.status.setText("Delete cancelled."); return
        del presets[name]
        save_user_presets(presets, folder)
        self._populate_preset_combo(select="")
        self.status.setText(f"Deleted preset '{name}'.")

    def on_use_textures_inside(self):
        """Fill NOHQ/AS/SMDI with the real exported texture paths (mod-relative,
        using the chosen extension)."""
        s = self._collect()
        out = s["output"].strip()
        if not out:
            self.status.setText("Choose an output folder first."); return
        prefix = self._prefix(s)
        drive = s["drive"].strip() or "P:\\"
        ext = s["tex_ext"]
        for edit, suffix in ((self.nohq_ref, "nohq"), (self.as_ref, "as"),
                             (self.smdi_ref, "smdi")):
            p = os.path.join(out, f"{prefix}_{suffix}.{ext}")
            rel, _ok = paa_tools.mod_relative_path(p, drive_letter=drive)
            edit.setText(rel)
        self.status.setText(f"Texture paths set (.{ext}).")

    def _fill_fields_from_rvmat(self, content):
        """Load an .rvmat's texture paths + material values into the fields."""
        d = rvmat_writer.parse_rvmat(content)
        tex = d.get("textures", {})
        if tex.get("NOHQ"):
            self.nohq_ref.setText(tex["NOHQ"])
        if tex.get("AS"):
            self.as_ref.setText(tex["AS"])
        if tex.get("SMDI"):
            self.smdi_ref.setText(tex["SMDI"])
        if tex.get("MC"):
            self.mc_ref.setText(tex["MC"])
        for key, edit in (("ambient", self.mat_ambient), ("diffuse", self.mat_diffuse),
                          ("forcedDiffuse", self.mat_forced), ("emmisive", self.mat_emmisive),
                          ("specular", self.mat_specular), ("specularPower", self.mat_power)):
            if d.get(key):
                edit.setText(d[key])
        if tex.get("FRESNEL"):
            n, k = _parse_fresnel_nk(tex["FRESNEL"])
            self.mat_fresnel_n.setText(n)
            self.mat_fresnel_k.setText(k)
        if tex.get("ENV"):
            self.env_combo.setCurrentText(tex["ENV"])

    def _rvmat_out_path(self, s):
        return os.path.join(s["output"].strip(), f"{self._prefix(s)}.rvmat")

    def _detect_rvmat(self, announce=False):
        """Find <prefix>.rvmat in the output folder and load it, so reopening a
        project (or restarting Painter) restores the RVMAT panel."""
        out = self.output_edit.text().strip()
        prefix = self.prefix_edit.text().strip()
        if not out or not prefix:
            return
        path = os.path.join(out, f"{prefix}.rvmat")
        if not os.path.exists(path):
            if announce:
                self.status.setText(f"No {prefix}.rvmat found in the output folder.")
            return
        try:
            with open(path) as f:
                content = f.read()
            self.rvmat_path = path
            self._fill_fields_from_rvmat(content)
            if path not in self.watcher.files():
                self.watcher.addPath(path)
            if announce:
                self.status.setText(f"Loaded {os.path.basename(path)}.")
        except Exception as e:
            splog.warning(f"[RwG] Could not load rvmat: {e}")

    def _current_rvmat_content(self, s, mc_override=None):
        """Build the .rvmat text from the current fields (mc_override swaps the
        MC/Stage3 texture, used for the damage variants)."""
        p = rvmat_writer.MATERIAL_PRESETS.get(s["preset"],
                                              rvmat_writer.MATERIAL_PRESETS["Default"])
        mc = mc_override if mc_override else (self.mc_ref.text().strip() or None)
        return rvmat_writer.build_rvmat(
            nohq=self.nohq_ref.text().strip() or None,
            as_map=self.as_ref.text().strip() or None,
            smdi=self.smdi_ref.text().strip() or None,
            mc=mc,
            fresnel=_build_fresnel(self.mat_fresnel_n.text(), self.mat_fresnel_k.text(),
                                   s.get("fresnel_fmt", "ai"), s.get("fresnel_w", "64"),
                                   s.get("fresnel_h", "64"), s.get("fresnel_levels", "1")),
            env=(self.env_combo.currentText().strip() or p["env"]),
            ambient=_parse_vec(self.mat_ambient.text()),
            diffuse=_parse_vec(self.mat_diffuse.text()),
            forced_diffuse=_parse_vec(self.mat_forced.text()),
            emmisive=_parse_vec(self.mat_emmisive.text()),
            specular=_parse_vec(self.mat_specular.text()),
            specular_power=self.mat_power.text().strip() or "30.0")

    def on_write_rvmat(self):
        s = self._collect()
        try:
            if not s["output"].strip():
                self.status.setText("Choose an output folder first."); return
            content = self._current_rvmat_content(s)
            path = self._rvmat_out_path(s)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            self.rvmat_path = path
            if path not in self.watcher.files():
                self.watcher.addPath(path)
            self.status.setText(f".rvmat written: {os.path.basename(path)}")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    def _update_damage_buttons(self, *_):
        """Relabel the three variant buttons for the selected material family."""
        variants = rvmat_writer.DAMAGE_MC.get(self.dmg_combo.currentText(), [])
        self._dmg_variants = variants
        for i, b in enumerate(self.dmg_btns):
            if i < len(variants):
                label, mc, suffix = variants[i]
                b.setText(label)
                b.setToolTip(f"Write <prefix>{suffix}.rvmat with MC = {mc}")
                b.setVisible(True)
            else:
                b.setVisible(False)

    def _on_damage_variant(self, i):
        variants = getattr(self, "_dmg_variants", [])
        if 0 <= i < len(variants):
            _label, mc, suffix = variants[i]
            self._write_damage_variant(mc, suffix)

    def _write_damage_variant(self, mc_texture, suffix):
        """Write a damage-variant .rvmat: the base material with only the MC
        (Stage3) swapped to `mc_texture`, saved as <base><suffix>.rvmat. Prefers
        editing the existing base file verbatim (so it matches the original)."""
        s = self._collect()
        try:
            base = None
            if self.rvmat_path and os.path.exists(self.rvmat_path):
                base = self.rvmat_path
            elif s["output"].strip():
                cand = self._rvmat_out_path(s)
                base = cand if os.path.exists(cand) else None

            # which stages to reset to their procedural default (Speedo option)
            resets = {stage: name for name, stage in (("NOHQ", 1), ("AS", 4), ("SMDI", 5))
                      if self.dmg_reset[name].isChecked()}

            if base:
                with open(base, "r", encoding="utf-8") as f:
                    content = f.read()
                content, n = _replace_stage_texture(content, 3, mc_texture)
                if not n:
                    self.status.setText("No Stage3 (MC) found in the base .rvmat."); return
                for stage, name in resets.items():
                    content, _ = _replace_stage_texture(
                        content, stage, rvmat_writer.DEFAULT_TEXTURES[name])
                out_path = os.path.splitext(base)[0] + suffix + ".rvmat"
            else:
                if not s["output"].strip():
                    self.status.setText("Choose an output folder / write the base .rvmat first.")
                    return
                content = self._current_rvmat_content(s, mc_override=mc_texture)
                for stage, name in resets.items():
                    content, _ = _replace_stage_texture(
                        content, stage, rvmat_writer.DEFAULT_TEXTURES[name])
                out_path = os.path.join(s["output"].strip(),
                                        f"{self._prefix(s)}{suffix}.rvmat")

            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.status.setText(f"Damage variant written: {os.path.basename(out_path)}")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    def on_open_mateditor(self):
        s = self._collect()
        exe = s["mateditor"].strip()
        if not exe or not os.path.exists(exe):
            self.status.setText("Set the MatEditor.exe path first."); return
        # make sure a .rvmat exists to open
        if not self.rvmat_path or not os.path.exists(self.rvmat_path):
            self.on_write_rvmat()
        if not self.rvmat_path or not os.path.exists(self.rvmat_path):
            return
        try:
            subprocess.Popen([exe, self.rvmat_path])
            # watch the file so edits flow back in
            if self.rvmat_path not in self.watcher.files():
                self.watcher.addPath(self.rvmat_path)
            self.status.setText("Opened in MatEditor - watching for changes.")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

    def _on_rvmat_changed(self, path):
        # editors often replace the file; re-add the watch.
        if os.path.exists(path) and path not in self.watcher.files():
            self.watcher.addPath(path)
        if not self.autosync_cb.isChecked():
            return
        try:
            with open(path) as f:
                content = f.read()
            self._fill_fields_from_rvmat(content)
            self.status.setText("Synced changes from MatEditor.")
        except Exception as e:
            splog.warning(f"[RwG] sync failed: {e}")


# --------------------------------------------------------------------------- #
#  plugin entry points                                                         #
# --------------------------------------------------------------------------- #
def _show_widget(widget):
    for target in (widget, getattr(widget, "parent", lambda: None)()):
        if target is None:
            continue
        try:
            target.setVisible(True); target.show(); target.raise_()
        except Exception:
            pass


def start_plugin():
    dock = RwGDock()
    widget = substance_painter.ui.add_dock_widget(dock)
    _plugin_widgets.append(dock)
    _plugin_widgets.append(widget)
    _show_widget(widget)

    def _show_dock():
        _show_widget(widget)

    # toolbar icon
    try:
        button = QtWidgets.QToolButton()
        button.setToolTip(PLUGIN_TITLE)
        icon_path = os.path.join(PLUGIN_DIR, "RwG_Logo.ico")
        if os.path.exists(icon_path):
            button.setIcon(QtGui.QIcon(icon_path))
        else:
            button.setText("RwG")
        button.clicked.connect(_show_dock)
        if hasattr(substance_painter.ui, "add_plugins_toolbar_widget"):
            substance_painter.ui.add_plugins_toolbar_widget(button)
            _plugin_widgets.append(button)
            splog.info("[RwG] Toolbar icon added.")
    except Exception as e:
        splog.warning(f"[RwG] Could not add toolbar icon: {e}")

    # window menu entry
    try:
        action = QAction(PLUGIN_TITLE)
        action.triggered.connect(_show_dock)
        menu = substance_painter.ui.ApplicationMenu
        for name in ("Window", "View", "File", "Edit"):
            if hasattr(menu, name):
                substance_painter.ui.add_action(getattr(menu, name), action)
                _plugin_widgets.append(action)
                splog.info(f"[RwG] Menu entry added under '{name}'.")
                break
    except Exception as e:
        splog.warning(f"[RwG] Could not add menu entry: {e}")

    splog.info(f"[RwG] {PLUGIN_TITLE} v{PLUGIN_VERSION} loaded (dock shown).")


def close_plugin():
    for w in _plugin_widgets:
        try:
            if isinstance(w, RwGDock):
                w._unsubscribe_project_events()
        except Exception:
            pass
        try:
            substance_painter.ui.delete_ui_element(w)
        except Exception:
            pass
    _plugin_widgets.clear()


if __name__ == "__main__":
    start_plugin()
