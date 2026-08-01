# RwG DayZ Texture Exporter — Installation

A self-contained Substance 3D Painter plugin that converts a project's PBR
material into DayZ textures (`_co`, `_nohq`, `_smdi`, `_as`), optional `.paa`,
and a matching `.rvmat`. All the conversion code is bundled in
`RwG_DayZ_Painter/core/`, so the plugin doesn't depend on anything else.

## Contents

```
RwG_DayZ_Painter_Plugin/            (this repo)
   RwG_DayZ_Painter/                (copy this folder into python/plugins)
      __init__.py                   Painter UI + orchestration
      RwG_Logo.ico                  toolbar icon
      README.md                     plugin doc
      core/
         conversion.py              _co / _nohq / _smdi / _as
         rvmat_writer.py            Super-shader .rvmat + material presets
         paa_tools.py               .tga -> .paa, mod paths
         cli.py                     headless entry point
   README.md
   INSTALL.md                       (this file)
```

## Requirements

1. **Substance 3D Painter** (PySide6 on 2024+, PySide2 on older — both handled).
2. A **Python** with `numpy` + `pillow` (used in Built-in mode):
   ```
   python -c "import numpy, PIL; print('OK')"   # otherwise: pip install numpy pillow
   ```
3. **DayZ Tools `ImageToPAA.exe`** — only needed for `.paa` output.

## Install

1. Copy the **`RwG_DayZ_Painter`** folder into Painter's Python plugins folder:
   ```
   Windows:  C:\Users\<you>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
   ```
   Result: `python\plugins\RwG_DayZ_Painter\__init__.py` (with the `core` folder next to it).
2. Restart Painter (or **Python → Reload Plugins**).
3. You get a dock, a toolbar icon (RwG logo) and a **Window** menu entry — all
   three open the panel.

## First run

1. **Settings** (top button): set your Python (there's **Auto-detect**) and,
   for `.paa`, the `ImageToPAA.exe` path.
2. Choose an **Output folder** (ideally inside your `P:\` mod path so the
   `.rvmat` gets game-valid texture paths) and a **Prefix**.
3. Tick the maps you want and click **Export .tga** or **Export .tga + .paa**.
4. In **RVMAT**: pick a preset → **Load preset values**, **Use textures inside**,
   then **Write .rvmat**.

The in-plugin **?** button has a full quick reference (maps, recommended
settings, RVMAT panel, MatEditor sync).
