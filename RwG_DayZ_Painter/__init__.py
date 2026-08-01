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
import shutil
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

# Painter 2024+ ships PySide6 (Qt6); older versions ship PySide2 (Qt5).
try:
    from PySide6 import QtWidgets, QtCore, QtGui   # noqa: F401
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui   # noqa: F401
QAction = getattr(QtGui, "QAction", None) or QtWidgets.QAction

# Pure-Python core helpers (no numpy) can run inside Painter.
from .core import rvmat_writer, paa_tools


PLUGIN_TITLE = "RwG DayZ Texture Exporter"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(PLUGIN_DIR, "rwg_dayz_settings.json")
RES_OPTIONS = ["256", "512", "1024", "2048"]
# derived from the shared preset table so new presets appear automatically
PRESETS = list(rvmat_writer.MATERIAL_PRESETS.keys())
META_NS = "RwG_DayZ"
META_NORMAL_KEY = "normal_format"

HELP_HTML = """
<h3>RwG DayZ Texture Exporter</h3>
<p>Turns your Substance Painter project into DayZ textures
(<b>_co, _nohq, _smdi, _as</b>), optional <b>.paa</b>, and a matching <b>.rvmat</b>.</p>

<b>Setup</b>
<ul>
<li><b>Settings</b> (top button): the tool paths - Python (numpy+pillow, with Auto-detect),
ImageToPAA.exe, MatEditor.exe.</li>
<li><b>Output folder</b>: best inside your <b>P:\\</b> mod path so the .rvmat gets game-valid paths.</li>
<li><b>Prefix</b>: file-name base (wall -> wall_co.tga). <b>Use texture set name</b> fills it in.</li>
</ul>

<b>Export mode</b>
<ul>
<li><b>Built-in maps</b> - the plugin builds the maps (per-map size &amp; options).</li>
<li><b>Painter preset</b> - runs your own saved export preset as-is (no external Python needed).</li>
</ul>

<b>Maps (recommended)</b>
<ul>
<li><b>_co</b>: use <b>Diffuse</b> (metal/rough converted; metals go black). 2D View / Base Color are alternatives.</li>
<li><b>_nohq</b>: <b>DirectX</b> for DayZ - combines normal + height + baked mesh normal (never flat).</li>
<li><b>_smdi</b>: R=white, G=specular, B=gloss. Source: <b>Spec+Gloss</b> (Painter's converted maps, recommended) or Met+Rough (computed). G/B sliders default 1.0.</li>
<li><b>_as</b>: DayZ layout, R/B white, G=mixed AO. 512 is usually enough.</li>
</ul>
<p>Each map has its own checkbox and size (256-2048).</p>

<b>Export</b>
<ul>
<li>.tga is always written; .paa needs DayZ Tools <b>ImageToPAA.exe</b>.</li>
<li><b>Convert .tga -&gt; .paa (folder)</b> batch-converts an existing folder.</li>
</ul>

<b>RVMAT</b>
<ul>
<li><b>Texture ext</b>: .paa or .tga for the texture paths written into the rvmat.</li>
<li>NOHQ/AS/SMDI auto-fill after an export. <b>default</b> sets the procedural value;
<b>Use textures inside</b> fills the real exported paths.</li>
<li>Material values (ambient/diffuse/.../specularPower) are editable fields.
<b>Load preset values</b> fills them from a preset; <b>Write .rvmat</b> saves everything.</li>
<li><b>Open .rvmat in MatEditor</b> + <b>Auto-sync</b>: edits in the editor flow back into the fields.</li>
<li>The panel auto-loads <b>&lt;prefix&gt;.rvmat</b> on startup / when output+prefix change.</li>
</ul>

<p><i>Note: _co is not an rvmat stage in DayZ - it is assigned on the model. The
material references _nohq, _as and _smdi.</i></p>
"""

DOCK_QSS = """
QLabel#title { font-weight: bold; font-size: 14px; }
QLabel#sectionHeader {
    font-weight: bold;
    font-size: 12px;
    padding: 9px 0 3px 0;
    border-bottom: 1px solid rgba(255,255,255,38);
    margin-bottom: 3px;
}
QLabel#hint { color: #9aa0a6; font-size: 11px; }
QPushButton { padding: 4px 10px; border: 1px solid rgba(255,255,255,32); border-radius: 4px; }
QPushButton:hover { border-color: rgba(255,255,255,80); }
QPushButton#primary {
    font-weight: bold;
    border: 1px solid #59946f;
    background: rgba(89,148,111,70);
}
QPushButton#primary:hover { background: rgba(89,148,111,120); }
QPushButton#help { border-radius: 13px; font-weight: bold; }
QLineEdit, QComboBox, QDoubleSpinBox {
    padding: 3px 5px; border: 1px solid rgba(255,255,255,32); border-radius: 4px;
}
QPlainTextEdit, QTextEdit { border: 1px solid rgba(255,255,255,32); border-radius: 4px; }
QCheckBox { spacing: 6px; font-weight: bold; }
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
        "co_res": "2048", "nohq_res": "2048", "smdi_res": "2048", "as_res": "1024",
        "co_source": "diffuse",
        "smdi_source": "specgloss",
        "smdi_green": 1.0, "smdi_blue": 1.0,
        "preset": "Default", "mateditor": "", "autosync": True,
        "mode": "builtin", "painter_preset": "DayZ", "preset_shelf": "your_assets",
        "tex_ext": "paa",
        "mat_ambient": "1,1,1,1", "mat_diffuse": "1,1,1,1",
        "mat_forced": "0,0,0,1", "mat_emmisive": "0,0,0,0",
        "mat_specular": "0,0,0,1", "mat_power": "30.0",
        "mat_fresnel_n": "0.4", "mat_fresnel_k": "0.2",
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                defaults.update(json.load(f))
    except Exception as e:
        splog.warning(f"[RwG] Could not read settings: {e}")
    return defaults


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        splog.warning(f"[RwG] Could not save settings: {e}")


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


def _exec_cli(python, extra_args, log):
    cli = _cli_path()
    if not python or not os.path.exists(python):
        raise RuntimeError("Set 'Python' to a python.exe that has numpy + pillow.")
    if not os.path.exists(cli):
        raise RuntimeError(f"Bundled converter not found: {cli}")
    cmd = [python, cli] + extra_args
    log("[RwG] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=os.path.dirname(cli),
                          capture_output=True, text=True, timeout=900)
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
        "exportList": [{"rootPath": ts} for ts in _texture_set_names()],
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
                "exportList": [{"rootPath": ts} for ts in _texture_set_names()],
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
             ("normal", "normal"), ("roughness", "roughness"), ("metallic", "metallic"),
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


def _build_fresnel(n, k):
    """Build the standard Stage6 fresnel string from N and K."""
    n = (n or "").strip() or "0.4"
    k = (k or "").strip() or "0.2"
    return f"#(ai,64,64,1)fresnel({n},{k})"


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

    def _spin(self, key, default):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(0.0, 2.0)
        s.setSingleStep(0.05)
        s.setValue(float(self.s.get(key, default)))
        s.setFixedWidth(60)
        return s

    # ---------- build ----------
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QtWidgets.QWidget()
        scroll.setWidget(content)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        self.setStyleSheet(DOCK_QSS)
        self.setMinimumWidth(320)

        def header(txt):
            lbl = QtWidgets.QLabel(txt)
            lbl.setObjectName("sectionHeader")
            layout.addWidget(lbl)

        def hint(txt):
            lbl = QtWidgets.QLabel(txt)
            lbl.setObjectName("hint")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            return lbl

        # title + help button (top)
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
        layout.addLayout(top)

        # --- paths ---
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

        # --- maps (grid so the 'size' column lines up across all rows) ---
        header("Maps  (built-in mode: tick = export, size per map)")

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
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
        self.co_source.addItems(["Diffuse (recommended)", "2D View", "Base Color",
                                 "Base Color + Specular"])
        self.co_source.setToolTip(
            "Diffuse - proper DayZ diffuse (metal/rough converted; metals go black).\n"
            "2D View - the flattened 2D viewport.\n"
            "Base Color - the raw albedo channel.\n"
            "Base Color + Specular - albedo dimmed by specular.")
        self.co_source.setCurrentText({"diffuse": "Diffuse (recommended)",
                                       "2d_view": "2D View",
                                       "base_color": "Base Color",
                                       "base_color_specular": "Base Color + Specular"}.get(
                                           self.s.get("co_source", "diffuse"),
                                           "Diffuse (recommended)"))
        self.co_res = self._res_combo("co_res", "2048")
        grid.addWidget(self.co_cb, 1, 0)
        grid.addLayout(middle(self.co_source), 1, 1)
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
        self.smdi_source.addItems(["Spec+Gloss", "Met+Rough"])
        self.smdi_source.setCurrentText(
            "Met+Rough" if self.s.get("smdi_source") == "metrough" else "Spec+Gloss")
        self.smdi_source.setToolTip(
            "Spec+Gloss - Painter's converted Specular + Glossiness (proper PBR "
            "conversion, recommended).\n"
            "Met+Rough - computed from the metallic + roughness channels.")
        self.smdi_green = self._spin("smdi_green", 1.0)
        self.smdi_blue = self._spin("smdi_blue", 1.0)
        self.smdi_res = self._res_combo("smdi_res", "2048")
        grid.addWidget(self.smdi_cb, 3, 0)
        grid.addLayout(middle(self.smdi_source, "G", self.smdi_green,
                              "B", self.smdi_blue), 3, 1)
        grid.addWidget(self.smdi_res, 3, 2)

        # _as
        self.as_cb = QtWidgets.QCheckBox("_as")
        self.as_cb.setChecked(self.s.get("as_on", True))
        self.as_res = self._res_combo("as_res", "1024")
        grid.addWidget(self.as_cb, 4, 0)
        grid.addLayout(middle("(DayZ standard)"), 4, 1)
        grid.addWidget(self.as_res, 4, 2)

        layout.addLayout(grid)
        hint("Per-map details &amp; recommendations are in the  ?  help.")

        # --- paa + export ---
        header("Export  (.tga is always written; .paa optional)")

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
        folder_btn = QtWidgets.QPushButton("Convert .tga \u2192 .paa (folder)")
        folder_btn.clicked.connect(self.on_convert_folder_paa)
        layout.addWidget(folder_btn)

        # --- rvmat ---
        header("RVMAT")

        rext = QtWidgets.QHBoxLayout()
        rext.addWidget(QtWidgets.QLabel("Texture ext:"))
        self.tex_ext_combo = QtWidgets.QComboBox()
        self.tex_ext_combo.addItems([".paa", ".tga"])
        self.tex_ext_combo.setCurrentText("." + self.s.get("tex_ext", "paa"))
        self.tex_ext_combo.setToolTip("Extension used for the texture paths written into the .rvmat.")
        rext.addWidget(self.tex_ext_combo)
        use_tex_btn = QtWidgets.QPushButton("Use textures inside")
        use_tex_btn.setToolTip("Fill NOHQ/AS/SMDI with the exported texture paths "
                               "(output + prefix, mod-relative, with the chosen extension).")
        use_tex_btn.clicked.connect(self.on_use_textures_inside)
        rext.addWidget(use_tex_btn)
        rext.addStretch(1)
        layout.addLayout(rext)

        self.nohq_ref = self._tex_row(layout, "NOHQ:", "NOHQ")
        self.as_ref = self._tex_row(layout, "AS:", "AS")
        self.smdi_ref = self._tex_row(layout, "SMDI:", "SMDI")

        r1 = QtWidgets.QHBoxLayout()
        r1.addWidget(QtWidgets.QLabel("Preset:"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.addItems(PRESETS)
        self.preset_combo.setCurrentText(self.s.get("preset", "Default"))
        r1.addWidget(self.preset_combo)
        load_vals_btn = QtWidgets.QPushButton("Load preset values")
        load_vals_btn.setToolTip("Fill the material value fields below from the selected preset.")
        load_vals_btn.clicked.connect(self.on_load_preset_values)
        r1.addWidget(load_vals_btn)
        r1.addWidget(QtWidgets.QLabel("Drive:"))
        self.drive_edit = QtWidgets.QLineEdit(self.s.get("drive", "P:\\"))
        self.drive_edit.setFixedWidth(50)
        r1.addWidget(self.drive_edit)
        layout.addLayout(r1)

        # material values - each its own editable text field
        self.mat_ambient = self._val_row(layout, "ambient", "mat_ambient", "1,1,1,1")
        self.mat_diffuse = self._val_row(layout, "diffuse", "mat_diffuse", "1,1,1,1")
        self.mat_forced = self._val_row(layout, "forcedDiffuse", "mat_forced", "0,0,0,1")
        self.mat_emmisive = self._val_row(layout, "emmisive", "mat_emmisive", "0,0,0,0")
        self.mat_specular = self._val_row(layout, "specular", "mat_specular", "0,0,0,1")
        self.mat_power = self._val_row(layout, "specularPower", "mat_power", "30.0")

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
        layout.addLayout(frow)

        wrow = QtWidgets.QHBoxLayout()
        write_btn = QtWidgets.QPushButton("Write .rvmat")
        write_btn.setObjectName("primary")
        write_btn.clicked.connect(self.on_write_rvmat)
        wrow.addWidget(write_btn)
        load_btn = QtWidgets.QPushButton("Load existing")
        load_btn.setToolTip("Find <prefix>.rvmat in the output folder and load its values.")
        load_btn.clicked.connect(lambda: self._detect_rvmat(announce=True))
        wrow.addWidget(load_btn)
        layout.addLayout(wrow)

        m1 = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton("Open .rvmat in MatEditor")
        open_btn.clicked.connect(self.on_open_mateditor)
        m1.addWidget(open_btn)
        self.autosync_cb = QtWidgets.QCheckBox("Auto-sync from MatEditor")
        self.autosync_cb.setChecked(self.s.get("autosync", True))
        m1.addWidget(self.autosync_cb)
        layout.addLayout(m1)

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
            self.smdi_green: "SMDI Green = specular level (from metallic). 1.0 = standard.",
            self.smdi_blue: "SMDI Blue = gloss = 1 - roughness. 1.0 = standard.",
            self.smdi_res: "Output resolution for _smdi.",
            self.as_cb: "Export the _as (ambient shadow). DayZ layout: R/B white, G = mixed AO.",
            self.as_res: "Output resolution for _as. 512 is usually plenty.",
            self.preset_combo: "Material preset for the .rvmat "
                               "(ambient/diffuse/specular/power + fresnel).",
            self.drive_edit: "Mod drive used for the .rvmat texture paths, e.g. P:\\.",
            self.autosync_cb: "When the material editor saves the .rvmat, read the "
                              "changes back into this panel.",
        }
        for widget, tip in tips.items():
            try:
                widget.setToolTip(tip)
            except Exception:
                pass

        self.status = QtWidgets.QLabel("Ready.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

        # initial enabled state for preset/shelf, and load an existing .rvmat
        self._update_mode_fields()
        self._detect_rvmat()

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
        """A texture reference field + a 'default' button (procedural value)."""
        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(46)
        row.addWidget(lbl)
        edit = QtWidgets.QLineEdit()
        row.addWidget(edit)
        btn = QtWidgets.QPushButton("default")
        btn.setFixedWidth(64)
        btn.setToolTip(f"Set {label} to the procedural default "
                       f"({rvmat_writer.DEFAULT_TEXTURES.get(key, '')}).")
        btn.clicked.connect(lambda: edit.setText(rvmat_writer.DEFAULT_TEXTURES.get(key, "")))
        row.addWidget(btn)
        layout.addLayout(row)
        return edit

    def _val_row(self, layout, label, key, default):
        """An editable material-value field (e.g. ambient = 1,1,1,1)."""
        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(92)
        row.addWidget(lbl)
        edit = QtWidgets.QLineEdit(str(self.s.get(key, default)))
        row.addWidget(edit)
        layout.addLayout(row)
        return edit

    # ---------- state ----------
    def _collect(self):
        src_map = {"Diffuse (recommended)": "diffuse", "2D View": "2d_view",
                   "Base Color": "base_color", "Base Color + Specular": "base_color_specular"}
        # python / imagetopaa / mateditor live in the Settings dialog (self.s)
        self.s.update({
            "output": self.output_edit.text(),
            "prefix": self.prefix_edit.text(),
            "drive": self.drive_edit.text(),
            "normal_format": self.normal_combo.currentText(),
            "co_on": self.co_cb.isChecked(), "nohq_on": self.nohq_cb.isChecked(),
            "smdi_on": self.smdi_cb.isChecked(), "as_on": self.as_cb.isChecked(),
            "co_res": self.co_res.currentText(), "nohq_res": self.nohq_res.currentText(),
            "smdi_res": self.smdi_res.currentText(), "as_res": self.as_res.currentText(),
            "co_source": src_map.get(self.co_source.currentText(), "base_color"),
            "smdi_source": "metrough" if self.smdi_source.currentText() == "Met+Rough" else "specgloss",
            "smdi_green": self.smdi_green.value(), "smdi_blue": self.smdi_blue.value(),
            "preset": self.preset_combo.currentText(),
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
        })
        save_settings(self.s)
        return self.s

    def _update_mode_fields(self, *_):
        """Grey out Preset/Shelf when the mode is Built-in maps."""
        preset_mode = self.mode_combo.currentText() == "Painter preset"
        self.painter_preset_edit.setEnabled(preset_mode)
        self.preset_shelf_edit.setEnabled(preset_mode)

    # ---------- handlers ----------
    def on_help(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("RwG DayZ Texture Exporter - Help")
        dlg.resize(540, 580)
        v = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QTextEdit()
        view.setReadOnly(True)
        view.setHtml(HELP_HTML)
        v.addWidget(view)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dlg.accept)
        v.addWidget(close)
        run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
        run()

    def on_settings(self):
        """Dialog holding the tool paths: Python, ImageToPAA, MatEditor."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("RwG DayZ Exporter - Settings")
        dlg.resize(580, 190)
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
            save_settings(self.s)
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

    def on_use_texset_name(self):
        names = _texture_set_names()
        if names:
            self.prefix_edit.setText(re.sub(r"\s+", "_", names[0]))
        else:
            self.status.setText("No texture set found (open a project first).")

    def _prefix(self, s):
        p = s["prefix"].strip()
        if p:
            return p
        names = _texture_set_names()
        return re.sub(r"\s+", "_", names[0]) if names else "material"

    def _do_export(self, make_paa):
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
                    if s["co_source"] == "base_color_specular":
                        add("$textureSet_metallic", "documentMap", "metallic", "gray")
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
            if s["as_on"]:
                add("$textureSet_ao", "virtualMap", "AO_Mixed", "gray")
            if not plan:
                self.status.setText("Tick at least one map to export."); return

            export_dir = os.path.join(s["output"].strip(), "_pbr_src")
            paths = export_project_maps(export_dir, plan, splog.info)
            maps = maps_from_export_paths(paths)
            if not maps:
                self.status.setText("Export produced no recognizable maps - see Log."); return

            args = ["--output", s["output"].strip(), "--prefix", prefix,
                    "--drive", s["drive"].strip() or "P:\\"]
            co_mode = "base_color_specular" if s["co_source"] == "base_color_specular" else "base_color"
            # Painter's virtual maps are already in their final format, so the CLI
            # must NOT flip the normal - pass 'directx' to disable flipping.
            args += ["--co-mode", co_mode, "--normal-format", "directx",
                     "--spec", str(s["smdi_green"]), "--gloss", str(s["smdi_blue"])]

            co_input = {"diffuse": maps.get("diffuse"),
                        "2d_view": maps.get("view2d")}.get(s["co_source"], maps.get("basecolor"))
            if s["co_on"] and co_input:
                args += ["--basecolor", co_input, "--co-res", s["co_res"]]
                if co_mode == "base_color_specular" and maps.get("metallic"):
                    args += ["--metallic", maps["metallic"]]
            if s["nohq_on"] and maps.get("normal"):
                args += ["--normal", maps["normal"], "--nohq-res", s["nohq_res"]]
            if s["smdi_on"]:
                if s["smdi_source"] == "specgloss" and maps.get("specular") and maps.get("glossiness"):
                    args += ["--spec-map", maps["specular"], "--gloss-map", maps["glossiness"],
                             "--smdi-res", s["smdi_res"]]
                elif maps.get("metallic") and maps.get("roughness"):
                    args += ["--metallic", maps["metallic"], "--roughness", maps["roughness"],
                             "--smdi-res", s["smdi_res"]]
            if s["as_on"] and maps.get("ao"):
                args += ["--ao", maps["ao"], "--as-res", s["as_res"]]
            if make_paa:
                args += ["--paa"]
                if s["imagetopaa"].strip():
                    args += ["--imagetopaa", s["imagetopaa"].strip()]

            self.status.setText("Converting..."); QtWidgets.QApplication.processEvents()
            summary = _exec_cli(s["python"], args, splog.info)
            self._finish(summary, s)

            # remove the intermediate PBR export folder
            try:
                if os.path.isdir(export_dir):
                    shutil.rmtree(export_dir, ignore_errors=True)
                    splog.info(f"[RwG] Removed intermediate folder {export_dir}")
            except Exception as ce:
                splog.warning(f"[RwG] Could not remove {export_dir}: {ce}")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

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
        s = self._collect()
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder with .tga files")
        if not folder:
            return
        try:
            args = ["--paa-folder", folder]
            if s["imagetopaa"].strip():
                args += ["--imagetopaa", s["imagetopaa"].strip()]
            self.status.setText("Converting to .paa..."); QtWidgets.QApplication.processEvents()
            summary = _exec_cli(s["python"], args, splog.info)
            if summary:
                n = len(summary.get("paa", {}))
                self.status.setText(f".paa written: {n} file(s)"
                                    + (f", {len(summary['errors'])} error(s)" if summary.get("errors") else ""))
                for e in summary.get("errors", []):
                    splog.warning(f"[RwG] {e}")
            else:
                self.status.setText("Done - see Log.")
        except Exception as e:
            splog.error(f"[RwG] {e}")
            self.status.setText(f"Error: {e}")

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
                             ("_smdi", self.smdi_ref)):
            r = ref(suffix)
            if r:
                edit.setText(r)

    # ---------- rvmat ----------
    def on_load_preset_values(self):
        """Fill the material value fields from the selected preset (texture
        paths are untouched)."""
        s = self._collect()
        p = rvmat_writer.MATERIAL_PRESETS.get(s["preset"], rvmat_writer.MATERIAL_PRESETS["Default"])
        self.mat_ambient.setText(_vec_str(p["ambient"]))
        self.mat_diffuse.setText(_vec_str(p["diffuse"]))
        self.mat_forced.setText(_vec_str(p["forcedDiffuse"]))
        self.mat_emmisive.setText(_vec_str(p["emmisive"]))
        self.mat_specular.setText(_vec_str(p["specular"]))
        self.mat_power.setText(str(p["specularPower"]))
        n, k = _parse_fresnel_nk(p["fresnel"])
        self.mat_fresnel_n.setText(n)
        self.mat_fresnel_k.setText(k)
        self.status.setText(f"Loaded '{s['preset']}' values into the fields.")

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
        for key, edit in (("ambient", self.mat_ambient), ("diffuse", self.mat_diffuse),
                          ("forcedDiffuse", self.mat_forced), ("emmisive", self.mat_emmisive),
                          ("specular", self.mat_specular), ("specularPower", self.mat_power)):
            if d.get(key):
                edit.setText(d[key])
        if tex.get("FRESNEL"):
            n, k = _parse_fresnel_nk(tex["FRESNEL"])
            self.mat_fresnel_n.setText(n)
            self.mat_fresnel_k.setText(k)

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

    def on_write_rvmat(self):
        s = self._collect()
        try:
            if not s["output"].strip():
                self.status.setText("Choose an output folder first."); return
            # fresnel + env come from the selected preset; DT/MC keep defaults.
            p = rvmat_writer.MATERIAL_PRESETS.get(s["preset"],
                                                  rvmat_writer.MATERIAL_PRESETS["Default"])
            content = rvmat_writer.build_rvmat(
                nohq=self.nohq_ref.text().strip() or None,
                as_map=self.as_ref.text().strip() or None,
                smdi=self.smdi_ref.text().strip() or None,
                fresnel=_build_fresnel(self.mat_fresnel_n.text(), self.mat_fresnel_k.text()),
                env=p["env"],
                ambient=_parse_vec(self.mat_ambient.text()),
                diffuse=_parse_vec(self.mat_diffuse.text()),
                forced_diffuse=_parse_vec(self.mat_forced.text()),
                emmisive=_parse_vec(self.mat_emmisive.text()),
                specular=_parse_vec(self.mat_specular.text()),
                specular_power=self.mat_power.text().strip() or "30.0")
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

    splog.info(f"[RwG] {PLUGIN_TITLE} loaded (dock shown).")


def close_plugin():
    for w in _plugin_widgets:
        try:
            substance_painter.ui.delete_ui_element(w)
        except Exception:
            pass
    _plugin_widgets.clear()


if __name__ == "__main__":
    start_plugin()
