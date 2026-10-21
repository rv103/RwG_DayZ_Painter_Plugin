# RwG DayZ Texture Exporter — Installation

A self-contained Substance 3D Painter plugin that converts a project's PBR
material into DayZ textures (`_co`/`_ca`, `_nohq`, `_smdi`, `_as`, `_em`),
optional `.paa`, and a matching `.rvmat` (including damage variants). All the
conversion code is bundled in `RwG_DayZ_Painter/core/`, so the plugin doesn't
depend on anything else.

## Contents

```
RwG_DayZ_Painter_Plugin/            (this repo)
   RwG_DayZ_Painter/                (copy this folder into python/plugins)
      __init__.py                   Painter UI + orchestration
      RwG_Logo.ico                  toolbar icon
      viewer_link.py                live link to the DayZ Material Viewer
      shader_sync.py                values -> dayz-ingame viewport shader
      core/
         conversion.py              _co / _ca / _nohq / _smdi / _as / _em
         rvmat_writer.py            Super-shader .rvmat + presets + damage table
         paa_tools.py               .tga -> .paa, mod paths
         p3d_reader.py              materials of a P3D and its proxies
         cli.py                     headless entry point
   README.md
   INSTALL.md                       (this file)
   CHANGELOG.md
   LICENSE
```

## 1. Requirements

1. **Substance 3D Painter** — PySide6 on 2024+, PySide2 on older versions
   (both handled automatically).
2. A **Python** with `numpy` + `pillow` (used in Built-in mode). Check it:
   ```
   python -c "import numpy, PIL; print('OK')"      # otherwise:
   pip install numpy pillow
   ```
3. **DayZ Tools `ImageToPAA.exe`** — only needed for `.paa` output.
4. Optional: the **DayZ Material Viewer** (live preview of the model with
   DayZ's shading), the **RwG DayZ SP Shader** (`dayz-ingame` viewport shader)
   and **TexView / TexView2** (to open textures from the RVMAT panel).

## 2. Install the plugin

1. Copy the **`RwG_DayZ_Painter`** folder into Painter's Python plugins folder:
   ```
   Windows:  C:\Users\<you>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
   ```
   Result: `python\plugins\RwG_DayZ_Painter\__init__.py` (with the `core`
   folder next to it).
2. Restart Painter, or use **Python → Reload Plugins**.
3. You now have three ways to open the panel: a **dock**, a **toolbar icon**
   (RwG logo) and a **Window** menu entry.

**Updating:** close Painter, replace the `RwG_DayZ_Painter` folder, keep your
`rwg_dayz_settings.json` (tool paths) if you like. Your own presets live in the
*My presets folder* from Settings and are not touched.

## 3. First-run setup (Settings)

Open the panel and click **Settings** (top of the panel). Set:

- **Python (numpy+pillow)** — click **Auto-detect**, or point it at a
  `python.exe` that has the libraries.
- **ImageToPAA.exe** — for `.paa` output (DayZ Tools).
- **TexView.exe** — optional, for the *open* button next to each texture.
- **DayZViewer.exe** — optional, the DayZ Material Viewer for *Open in viewer*.
- **Mod drive** — the mounted DayZ work drive, usually `P:\`. This is used to
  turn absolute texture paths into game-valid, mod-relative paths.
- **Panel layout** — *Tabs* (Setup / Maps / RVMAT) or *Single window*.

These settings are global (per machine). Everything else is saved per project.

## 4. Export a texture set

1. In **Setup**, set the **Model (.p3d)** (usually found by itself) and pick
   the **Texture set** material — the model's rvmats and those of its proxies.
   That fills **Output folder** and **Prefix**; the ✓/✗ lines confirm the
   export lands where the model expects it. Without a model, set Output folder
   (inside your `P:\` mod path) and Prefix by hand.
2. In **RVMAT**, set **specularPower** and **fresnel N/K** (or load a preset) —
   the `_smdi` is calculated relative to them.
3. In **Maps**, tick the maps you want and set their resolutions (optionally
   the `_co` alpha → `_ca`).
4. Click **Export .tga + .paa** or **Export .tga only**.

The plugin exports Painter's converted maps to a temporary `_pbr_src` folder,
runs the bundled converter with your external Python, writes the DayZ textures,
and cleans up.

## 5. Build the `.rvmat`

1. In **RVMAT**, choose a **Preset** and click **Load**.
2. Set the texture stages: **Auto-fill from export** fills the exported paths,
   or use the **browse** button per stage. **Texture paths use** picks `.paa` /
   `.tga`.
3. Tune the material colours (colour buttons open an RGBA editor), the
   **Fresnel** (N/K or the **Curve** editor) and the **env** map.
4. Click **Write .rvmat**.

## 6. Live preview (optional)

- **DayZ Material Viewer:** set *DayZViewer.exe* in Settings, then in Setup
  tick **Send after export** and **Live material values** and click **Open in
  viewer**. Exports reload in the viewer; RVMAT values go across while you edit
  them, and edits made in the viewer come back.
- **DayZ In-Game viewport shader:** load `dayz-ingame` (RwG DayZ SP Shader) as
  the texture set's shader, then tick **Live to DayZ In-Game shader** or click
  **To shader** in the RVMAT tab. Each texture set gets its own shader
  instance (`DayZ <texture set>`).

## 7. Damage variants (optional)

In **RVMAT → Damage variants**, pick a material family and click a variant
(*Worn / Damage / Destruct*, …). It writes `<prefix><suffix>.rvmat` next to the
base, identical except the MC (damage `_mc`) is swapped in.

## Troubleshooting

- **"Set 'Python' …"** — the external Python isn't set or lacks numpy/pillow.
  Use **Settings → Auto-detect**, or `pip install numpy pillow`.
- **`.paa` not produced** — set **ImageToPAA.exe** in Settings.
- **`.rvmat` paths show only a file name / a non-`P:` path** — your output
  folder isn't on the **Mod drive**. Set the drive in Settings to match, or put
  the output inside your `P:\` mount.
- **specularPower / material value not picked up in MatEditor** — DayZ Tools
  wants an integer `specularPower` and a non-black `specular[]`; the plugin
  already writes those. Reload the `.rvmat` in the editor.
- **Texture set list is empty / model not found** — pick the MLOD `.p3d` with
  `...`; binarized models and proxies can't be read.
- **Viewer doesn't update** — check *DayZViewer.exe* in Settings and that the
  export lands in the model's data folder (✓ lines in Setup).
- **Panel looks off after an update** — fully restart Painter (layout/stylesheet
  changes don't always survive a plain reload).

The in-plugin **?** button has a full quick reference (model, maps, viewer and
shader link, RVMAT panel, damage variants).
