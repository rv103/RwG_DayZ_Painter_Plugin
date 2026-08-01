# RwG DayZ Texture Exporter — Substance 3D Painter Plugin

Turns the current Painter project's PBR channels into DayZ textures
(`_co / _nohq / _smdi / _as`) and, optionally, `.paa` files and a `.rvmat`.

**Self-contained:** all conversion code is bundled in the `core/` folder next
to this file — the plugin does not depend on any other repo.

```
RwG_DayZ_Painter/
   __init__.py        (Painter UI + orchestration)
   RwG_Logo.ico       (toolbar icon)
   README.md
   core/
      conversion.py    (_co / _nohq / _smdi / _as)
      rvmat_writer.py  (Super-shader .rvmat)
      paa_tools.py     (.tga -> .paa, mod paths)
      cli.py           (headless entry point)
```

## How it works

Painter's embedded Python only runs the UI. The image maths run in a **normal
Python** (with `numpy` + `pillow`) via the bundled `core/cli.py`. So you do not
have to install anything inside Painter — you only point the plugin at that
Python.

## Requirements

1. A Python with the image libraries:
   ```
   pip install numpy pillow
   ```
2. For `.paa`: DayZ Tools `ImageToPAA.exe`.

## Install

Copy the whole **`RwG_DayZ_Painter`** folder into Painter's Python plugins
folder:

```
Windows:  C:\Users\<you>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

Restart Painter (or Python > Reload Plugins). You get a dock, a toolbar icon
(RwG logo) and a `Window` menu entry — all three open the panel.

## Configure (once)

| Field | Value |
|-------|-------|
| **Python** | the `python.exe` that has numpy + pillow (hit **Auto-detect** to find and verify it) |
| **Output folder** | where the DayZ textures should land (ideally on your `P:\` mod drive) |
| **ImageToPAA.exe** | only needed for `.paa` |
| **Drive** | mod drive for the `.rvmat` paths (default `P:\`) |
| **MatEditor.exe** | external material editor to open the `.rvmat` (optional) |

Settings are saved to `rwg_dayz_settings.json` next to the plugin.

## Export mode

* **Built-in maps** — the plugin builds `_co/_nohq/_smdi/_as` itself (per-map
  toggles, sizes and the options below). Needs the external Python.
* **Painter preset** — runs one of *your own* saved export presets (output
  templates) as-is; set the preset name (e.g. `DayZ`) and its shelf
  (`your_assets`). `.paa` and `.rvmat` still run afterwards. This mode works
  entirely inside Painter (no external Python needed).

## Maps

Each map (`_co / _nohq / _smdi / _as`) has its own checkbox (export or not) and
its own size dropdown (256/512/1024/2048) — you rarely need a 2048 `_as`.

The export pulls from Painter's **converted (virtual) maps**, so nothing comes
out blank and the normal carries all detail:

* **_co** — a dropdown picks the source:
  * **Diffuse** *(default, recommended)* — Painter's `Diffuse` converted map
    (metal/rough → diffuse; metals go black). This is the proper `_co` for a
    spec/gloss engine like DayZ.
  * **2D View** — Painter's `View_2D` converted map (the flattened 2D View).
  * **Base Color** — the raw flattened base-color channel.
  * **Base Color + Specular** — base color with a specular-based dim.
* **_nohq** — uses Painter's `Normal_DirectX` converted map, which merges the
  **normal channel + height + baked mesh normal** into the final DayZ (DirectX)
  normal. The dropdown switches DirectX/OpenGL; DirectX is the DayZ default.
* **_smdi** — a source dropdown: **Spec+Gloss** (Painter's converted Specular +
  Glossiness — the proper PBR conversion, default) or **Met+Rough** (computed
  from the metallic + roughness channels). Two spin boxes tune the Green
  (specular) and Blue (gloss) channels; R is always white.
* **_as** — uses `AO_Mixed` (document AO + baked mesh AO) and writes the DayZ
  layout (R/B white, G = AO). No options.

## Export buttons

* **Export .tga** — export + convert, TGA only.
* **Export .tga + .paa** / **Export .paa** — also run ImageToPAA.
* **Convert .tga → .paa (folder)** — batch-convert an existing folder of `.tga`.

The `.tga` files are always kept for previewing.

## RVMAT panel

After an export the NOHQ / AS / SMDI paths are auto-filled (mod-relative).
Pick a material **Preset** and **Write .rvmat** (writes `<prefix>.rvmat` into
the output folder). **Apply preset (values only)** changes just the material
values + fresnel and keeps the texture paths.

The panel **auto-loads** `<prefix>.rvmat` from the output folder on startup and
when you change the output/prefix — so reopening a project restores it. **Load
existing** re-loads it on demand.

**Open .rvmat in MatEditor** launches your external editor on the file. With
**Auto-sync** on, any change saved there is read back into the panel
automatically (texture paths + material values).

## Notes

* The `.tga` files are always kept (for previewing); `.paa` is written
  alongside when requested.
* For game-valid `.rvmat` paths, export into your mod's `P:\` path.
* `_co` is not a `.rvmat` stage in DayZ (it is assigned on the model); the
  material references `_nohq`, `_as` and `_smdi`.
