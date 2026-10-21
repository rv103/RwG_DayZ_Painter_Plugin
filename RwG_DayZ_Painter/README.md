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
   viewer_link.py     (live link to the DayZ Material Viewer)
   shader_sync.py     (values -> dayz-ingame viewport shader)
   core/
      conversion.py    (_co / _nohq / _smdi / _as)
      rvmat_writer.py  (Super-shader .rvmat)
      paa_tools.py     (.tga -> .paa, mod paths)
      p3d_reader.py    (materials of a P3D and its proxies)
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
| **DayZViewer.exe** | DayZ Material Viewer for the live preview (optional) |

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

Only conversions that match the game's Super shader (checked against RenderDoc
captures and a pixel-identical rebuild of it, DayZ Shader project) are offered:

* **_co** — the **Base Color**, unchanged; metals keep their colour. The shader
  takes the reflected part off the direct light itself (`1 - Fresnel × G`) and
  does not reduce the ambient light, so a darkened `_co` (Diffuse, glTF
  spec/gloss, Base Color + Specular) or one with baked light (2D View) would be
  wrong twice; metals would go black in shade.
* **_nohq** — uses Painter's `Normal_DirectX` converted map, which merges the
  **normal channel + height + baked mesh normal** into the final DayZ (DirectX)
  normal. The dropdown switches DirectX/OpenGL; DirectX is the DayZ default.
* **_smdi** — **DayZ shader-matched** from metallic + roughness + base colour:
  `G = F0 / F0(rvmat fresnel N,K) × B`, `B = (2/roughness⁴ − 2) / specularPower`
  (the shader reflects `G × Fresnel` and uses `B × specularPower` as exponent).
  Set specularPower and fresnel N/K in the RVMAT tab first; R is always white.
* **_as** — uses `AO_Mixed` (document AO + baked mesh AO) and writes the DayZ
  layout (R/B white, G = AO). No options.

## Export buttons

* **Export .tga + .paa** — export + convert, then run ImageToPAA.
* **Export .tga only** — export + convert, TGA only.
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

**Live to DayZ In-Game shader** / **To shader** send the material values to the
`dayz-ingame` viewport shader of the active texture set; a texture set sharing
one shader instance with others first gets its own (`DayZ <texture set>`).

## Model first (Setup tab)

* **Model (.p3d)** — the Object Builder model this project paints. Found by
  itself next to the mesh Painter imported, next to the `.spp` or in/above the
  output folder; pick it with `...` otherwise.
* **Texture set** — which material of the model the *active* texture set paints.
  The list holds the model's rvmats **and those of its proxies** (stock,
  handguard, magazine ... with their own P3D and data folder), read straight
  from the P3D. Choosing one sets **Output folder** (the rvmat's folder) and
  **Prefix** (its name); the choice is remembered per texture set, so switching
  texture sets in Painter switches the paths too. A matching name is suggested.
* The lines below show ✓/✗: does the export write the `.rvmat` and `_co` where
  the model expects them?
* Paths are always kept in `P:\` form, also when a file dialog returns the real
  folder behind the work drive (subst target, mods linked into P:).

## DayZ Material Viewer link

Setup tab → **DayZ Material Viewer (live preview)**. The DayZ Material Viewer
shows the real Object Builder model with DayZ's own shading:

* The viewer shows the **Model** from the Setup tab; for a proxy's material it
  switches that proxy on by itself.
* **Send after export** — after every export the viewer reloads the written
  textures and `.rvmat` at once.
* **Live material values** — the RVMAT tab's values (ambient, diffuse,
  forcedDiffuse, emmisive, specular, power, fresnel) go to the viewer while
  you edit them, applied to every face using `<prefix>.rvmat`; no save needed.
  Both ways: values edited in the viewer's material panel come back into these
  fields (and from there into the DayZ In-Game viewport shader). **Write
  .rvmat** saves them. (Viewer → plugin: `painterlink.json` next to
  `livelink.json`.)
* **Open in viewer** starts `DayZViewer.exe` (path in Settings) with the model;
  **Send now** sends model, current textures and values without exporting.

The export has to land where the P3D's faces point to (the model's `data`
folder). Messages go through `%LOCALAPPDATA%\DayZViewer\livelink.json`.

## Notes

* The `.tga` files are always kept (for previewing); `.paa` is written
  alongside when requested.
* For game-valid `.rvmat` paths, export into your mod's `P:\` path.
* `_co` is not a `.rvmat` stage in DayZ (it is assigned on the model); the
  material references `_nohq`, `_as` and `_smdi`.
