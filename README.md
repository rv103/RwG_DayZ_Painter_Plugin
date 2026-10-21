# RwG DayZ Texture Exporter

A **Substance 3D Painter** plugin that turns your project's PBR material into
game-ready **DayZ** textures — `_co` / `_ca`, `_nohq`, `_smdi`, `_as`, `_em`,
`_mc` and `_dtsmdi` — plus optional `.paa` conversion and a full **`.rvmat`**
editor, all from a dock inside Painter. It even generates the **damage variants**
(`_worn` / `_damage` / `_destruct` …) for you.

> **v0.6.0** — model first, live link to the DayZ Material Viewer, conversions
> matched to the game's shader. Feedback and edge cases welcome!

![RwG DayZ Texture Exporter](docs/preview.png)

## Highlights

- **Model first** — point the plugin at the Object Builder **`.p3d`** and every
  texture set picks its material from the model, **proxies included** (stock,
  handguard, magazine … with their own folders). Output folder and prefix follow
  by themselves, per texture set, always in `P:\` form.
- **Live link to the DayZ Material Viewer** — the viewer shows the real model
  with DayZ's own shading; exported textures and `.rvmat` reload at once, and
  material values go across **while you edit them** — both ways.
- **Matched to the game** — `_co` = Base Color and a **DayZ shader-matched
  `_smdi`**, measured against the game's Super shader (RenderDoc captures and a
  pixel-identical rebuild of it). No guessing between conversion methods.
- **DayZ In-Game viewport shader link** — the RVMAT values drive the
  `dayz-ingame` shader ([RwG DayZ SP Shader](https://github.com/rv103/RwG-DayZ-SP-Shader))
  of the active texture set; every texture set gets its own instance.
- **One-click DayZ export** — `_co` / `_ca`, `_nohq`, `_smdi`, `_as`, `_em`,
  `_mc` and `_dtsmdi`, each with its own toggle and resolution (256–2048), built
  from Painter's *converted* maps so nothing comes out flat.
- **Full `.rvmat` editor** — texture stages with availability lights, material
  colours with RGBA editors, a **visual Fresnel curve editor**, environment map,
  and **material presets checked against the shader** (metals tint the
  specular, dielectrics keep it white).
- **Fresnel material library**, **your own presets**, **damage-variant
  generator**, config snippet and `.rvmat` validator.
- **Per-project settings** — your values travel with the `.spp`.

## Screenshots

| Setup (model, texture set, viewer) | Maps + Export |
|:---:|:---:|
| ![Setup](docs/tab-setup.png) | ![Maps](docs/tab-maps.png) |

| RVMAT | Fresnel curve editor | Settings |
|:---:|:---:|:---:|
| ![RVMAT](docs/tab-rvmat.png) | ![Fresnel curve](docs/fresnel-curve.png) | ![Settings](docs/settings.png) |

| Preset dropdown | material N/K | Colour editor |
|:---:|:---:|:---:|
| ![Presets](docs/preset-dropdown.png) | ![Material N/K](docs/material-nk.png) | ![Colour editor](docs/colour-editor.png) |

## Requirements

- **Substance 3D Painter** (PySide6 on 2024+, PySide2 on older versions — both
  handled automatically).
- A **Python** with `numpy` + `pillow` — used for the built-in map conversion
  (`pip install numpy pillow`). There's an **Auto-detect** in Settings.
- **DayZ Tools `ImageToPAA.exe`** — only for `.paa` output.
- Optional: the **DayZ Material Viewer** for the live preview, the
  **[RwG DayZ SP Shader](https://github.com/rv103/RwG-DayZ-SP-Shader)**
  (`dayz-ingame`) for a DayZ-like viewport, **TexView / TexView2** to open
  textures from the RVMAT panel.

## Install

Copy the **`RwG_DayZ_Painter`** folder into Painter's Python plugins folder:

```
Windows:  C:\Users\<you>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

Restart Painter (or *Python → Reload Plugins*). You get a dock, a toolbar icon
(RwG logo) and a *Window* menu entry — all three open the panel. See
[`INSTALL.md`](INSTALL.md) and the in-plugin **?** help for the full walkthrough.
Updating from an older version: replace the whole folder (your settings and
presets files stay if you keep them).

## The panel

The dock is split into three tabs (switchable to a single scrolling window in
**Settings → Panel layout**). **Settings** and **?** sit at the top; a status
line sits at the bottom.

### Setup

- **Model (.p3d)** — the Object Builder model this project paints. Found by
  itself next to the mesh Painter imported, next to the `.spp` or in/above the
  output folder; pick it with `...` otherwise.
- **Texture set** — which material of the model the *active* texture set
  paints. The list holds the model's rvmats **and those of its proxies**, read
  straight from the P3D (MLOD — binarized models and proxies are not read).
  Choosing one sets **Output folder** (the rvmat's folder) and **Prefix** (its
  name); the choice is remembered per texture set, so switching texture sets in
  Painter switches the paths too. A matching name is suggested.
- Check lines show ✓/✗: does the export write the `.rvmat` and `_co` where the
  model expects them?
- Paths are always kept in `P:\` form — also when a file dialog returns the
  real folder behind the work drive (subst target, mods linked into `P:`).
- **Export mode** — *Built-in maps* (the plugin builds them) or *Painter
  preset* (runs your own saved export template as-is).

### DayZ Material Viewer (live preview)

- **Send after export** — after every export the viewer reloads the written
  textures and `.rvmat`; for a proxy's material it switches that proxy on.
- **Live material values** — ambient, diffuse, forcedDiffuse, emmisive,
  specular, specularPower and fresnel go to the viewer while you edit them, no
  save needed. Values edited in the viewer's material panel come back into the
  plugin (and from there into the viewport shader).
- **Open in viewer** starts the viewer with the model; **Send now** sends model,
  current textures and values without exporting.

### Maps + Export

Each map has its own checkbox and resolution.

- **`_co`** — the **Base Color**, unchanged; metals keep their colour. The
  Super shader takes the reflected part off the direct light itself
  (`1 − Fresnel × G`) and does not darken the ambient light, so a darkened `_co`
  would be wrong twice. Tick **alpha (`_ca`)** to add an Opacity alpha and write
  `_ca` instead.
- **`_nohq`** — **Normal DirectX** for DayZ (normal channel + height + baked
  mesh normal). OpenGL is switchable and remembered per project.
- **`_smdi`** — **DayZ shader-matched** (see below). R = white, G = specular,
  B = gloss.
- **`_dtsmdi`** — for the Multimaterial shader: G/B like the `_smdi`, R = a
  detail map (height + mesh + normal, centred on 0.5) with a **Detail** slider.
- **`_as`** — DayZ layout (R/B white, G = mixed AO).
- **`_em`** / **`_mc`** *(optional)* — emissive, and macro from a User channel
  (with blend mask).

**Export .tga + .paa** / **Export .tga only**; *Fill RVMAT texture fields*
writes the exported paths into the RVMAT tab. A **Convert `.tga → .paa`
(folder)** batch tool is included.

### RVMAT

- **Texture stages** — `NOHQ`, `AS`, `SMDI`, `MC` with browse / open / default
  and an **availability light** (is the file on disk?). **Auto-fill from
  export** fills the real paths.
- **Preset** — built-in materials and *My presets* in one dropdown (Load /
  Save / ✕).
- **Material colours** — coloured buttons open an RGBA editor; helpers sample
  the base colour or estimate from the project.
- **Fresnel** — `N` / `K` or the **Curve** editor; **material N/K** applies a
  named material's N/K + specular tint.
- **env** — the Stage7 environment map.
- **Live to DayZ In-Game shader** / **To shader** — send the values to the
  `dayz-ingame` viewport shader of the active texture set.
- **Write `.rvmat`**, **Load existing**, **Config snippet…**, **Validate…**
- **Damage variants** — pick a material family and a variant
  (*Worn / Damage / Destruct* …); writes `<prefix><suffix>.rvmat` with the damage
  `_mc` swapped in.

## How the `_smdi` is calculated

Measured against the game's Super shader: the reflection is
`G × Fresnel(angle)` from the rvmat's `fresnel(N,K)` stage, the highlight
exponent is `B × specularPower`. So the plugin writes:

```
F0 = perceivedBrightness(mix(0.04, linear baseColor, metallic))
G  = F0 / F0(fresnel N,K) × B
B  = (2 / roughness⁴ − 2) / specularPower
```

The fresnel stage already carries F0, so G is the fraction of it; `× B` keeps
rough areas from a full-strength highlight. Set **specularPower** and
**fresnel N/K** (RVMAT tab) before exporting — choose the fresnel of the most
reflective material in the texture set (usually the metal).

## Material presets

The built-in presets follow what the shader does with each value:

- `ambient` / `diffuse` = 1 — the colour comes from `_co`.
- **Dielectrics** (plastic, rubber, wood, cloth …): white `specular[]` and a
  dielectric fresnel (`1.5, 0`; wood `1.5, 0.45`).
- **Metals** (gold, iron, copper, brass, steel …): the specular carries the
  metal's hue, the fresnel N/K the reflectance; `specularPower` ≤ 400 (the
  `_smdi` is BC1 in game, a larger value crushes the rough range).

## Known limitations

- Binarized (ODOL) models and proxies are not read — use the MLOD `.p3d` from
  Object Builder.
- Painter's Python API can't read a project's normal format, so the plugin
  defaults to **DirectX** (switchable, remembered per project).
- Fresnel N/K can't be uniquely recovered from a metalness map — the
  *Estimate* is an F0-matched starting point; named materials are more accurate.
- Some export details vary by Painter version — if something looks off, open an
  issue with the plugin log.

## Credits

Built by **RwG** for the DayZ modding community. Fresnel N/K values are taken
from the Bohemia Interactive *Super shader* documentation; the damage `_mc`
tables come from the RwG RVMat Speedo tool.

## License

Free for the community, but **not for sale** — see [LICENSE](LICENSE)
(*RwG DayZ Texture Exporter License, non-commercial*). You may use, share and
adapt it for free with credit; you may not sell it or put it behind a paywall,
and all intellectual property stays with RwG. Anything you **make** with it
(your textures / `.rvmat` files) is yours to use freely, including commercially.
