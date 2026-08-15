# RwG DayZ Texture Exporter — Wiki

A **Substance 3D Painter** plugin that turns a normal PBR (metal/rough) project
into game-ready **DayZ / Enfusion** textures (`_co` / `_ca`, `_nohq`, `_smdi`,
`_as`, `_em`, `_mc`), converts them to `.paa`, and writes a complete **Super
shader `.rvmat`** — including the damage / destruct variants — all from a dock
inside Painter.

> This document is written to be dropped straight into a wiki. Each `##` section
> is self-contained and can become its own wiki page; the Table of Contents
> below maps to them.

---

## Table of contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [The panel](#the-panel)
6. [Setup tab](#setup-tab)
7. [Maps tab](#maps-tab)
8. [RVMAT tab](#rvmat-tab)
9. [Damage variants](#damage-variants)
10. [Settings](#settings)
11. [Project vs global settings](#project-vs-global-settings)
12. [How the maps are calculated](#how-the-maps-are-calculated)
13. [Recipes & workflows](#recipes--workflows)
14. [Companion: the RwG DayZ Super viewport shader](#companion-the-rwg-dayz-super-viewport-shader)
15. [Troubleshooting & FAQ](#troubleshooting--faq)
16. [Known limitations](#known-limitations)
17. [Glossary](#glossary)
18. [Changelog](#changelog)
19. [Credits & license](#credits--license)

---

## Overview

DayZ uses the **Enfusion "Super" shader**, which is a *specular / glossiness*
model, not the metal/rough model most artists paint in. This plugin bridges the
two: you keep painting in Painter's usual PBR metal/rough workflow, and the
plugin converts everything into the maps and material definition DayZ expects.

What it produces:

| Output | What it is |
|---|---|
| `_co` | Colour / diffuse (albedo). Assigned on the model, not an rvmat stage. |
| `_ca` | Colour **+ alpha** — the `_co` variant for transparent materials. |
| `_nohq` | Normal map, DirectX convention (normal + height + baked mesh normal). |
| `_smdi` | Specular map: `R = 1`, `G = specular level`, `B = gloss (1 − roughness)`. |
| `_as` | Ambient shadow (DayZ reads only the green = AO). |
| `_em` | Emissive / glow. |
| `_mc` | Macro (detail overlay), RGBA where alpha is the DayZ blend mask. |
| `.rvmat` | The full Super-shader material (7 stages + material colours + fresnel). |
| `.paa` | Any of the above, converted with DayZ Tools' `ImageToPAA`. |

### Super-shader stage layout

The `.rvmat` the plugin writes follows the Bohemia Interactive Super shader:

| Stage | Map | Source |
|---|---|---|
| Stage1 | NOHQ (normal) | `_nohq` |
| Stage2 | DT (detail) | procedural default |
| Stage3 | MC (macro) | `_mc` (or procedural) |
| Stage4 | AS (ambient shadow) | `_as` |
| Stage5 | SMDI (specular) | `_smdi` |
| Stage6 | FRESNEL | procedural `fresnel(N,K)` |
| Stage7 | ENV (environment) | a `dz\data\data` cubemap |

`_co` is **not** an rvmat stage — it is assigned on the model in Object Builder.

---

## Requirements

- **Substance 3D Painter.** PySide6 on 2024+, PySide2 on older versions — both
  are handled automatically.
- A **Python** interpreter with `numpy` + `pillow` (`pip install numpy pillow`).
  This runs the map conversion outside Painter. There is an **Auto-detect** in
  Settings.
- **DayZ Tools `ImageToPAA.exe`** — only needed for `.paa` output.
- Optional: **TexView / TexView2** and a **MatEditor** (Buldozer material editor)
  for the in-plugin *Open* and *Auto-sync* helpers.

The heavy image work (numpy/Pillow) runs in the external Python via a bundled
`core/cli.py`; the pure rvmat/paa helpers run inside Painter. Painter itself only
needs to be able to launch that Python.

---

## Installation

1. Copy the **`RwG_DayZ_Painter`** folder into Painter's Python plugins folder:

   ```
   Windows:  C:\Users\<you>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
   ```

2. Restart Painter, or run **Python → Reload Plugins**.
3. Open the panel. There are three ways in — all open the same dock:
   - the **dock** itself,
   - the **toolbar icon** (RwG logo),
   - the **Window** menu entry.
4. Open **Settings** (top of the panel) and set the **Python** path
   (*Auto-detect* usually finds it) plus, if you want `.paa`, the path to
   **ImageToPAA.exe**.

---

## Quick start

A five-minute first export:

1. Open your textured project in Painter.
2. In **Settings**, set **Python** (Auto-detect) and your **Mod drive** (e.g.
   `P:\`).
3. On the **Setup** tab, set the **Output folder** — ideally inside your `P:\`
   mod path so the `.rvmat` gets game-valid texture paths — and a **Prefix**
   (e.g. `wall`, or hit *Use texture set name*).
4. On the **Maps** tab, tick the maps you want and pick their resolutions.
5. Click **Export .tga** (or **Export .tga + .paa**).
6. On the **RVMAT** tab, pick a **Preset** (e.g. a metal), click **Load**, then
   **Use textures inside** and **Write .rvmat**.

You now have `<prefix>_co.tga`, `_nohq`, `_smdi`, `_as`, and `<prefix>.rvmat` in
your output folder.

---

## The panel

The dock is split into three tabs — **Setup**, **Maps**, **RVMAT** — with
**Settings** and **?** (help) buttons at the top and a status line at the bottom
that reports the result of every action.

You can switch to a single scrolling window in **Settings → Panel layout** if you
prefer everything on one page (useful on tall monitors). The choice is remembered
globally.

---

## Setup tab

- **Output folder** — where the DayZ textures land. Best inside your `P:\` mod
  path so the `.rvmat` receives game-valid texture paths.
- **Prefix** — the file-name base (`wall` → `wall_co.tga`). **Use texture set
  name** fills it from the active texture set.
- **Export mode**:
  - **Built-in maps** — the plugin builds each map from Painter's *converted*
    maps (recommended).
  - **Painter preset** — runs your own saved Painter export preset as-is (no
    external Python needed). Set the **preset name** and its **shelf**.

---

## Maps tab

Each map has its own checkbox and resolution (256–2048). `.tga` is always
written; `.paa` is optional (needs ImageToPAA).

### `_co` (colour / diffuse)

Source dropdown:

- **Diffuse (recommended)** — Painter's converted Diffuse (metal/rough
  converted; metals go black).
- **2D View** — the flattened 2D viewport.
- **Base Color** — the raw albedo channel.
- **Base Color + Specular** — albedo dimmed by the specular reflectance.
- **Spec/Gloss diffuse (glTF)** — the canonical `baseColor × (1 − 0.04) ×
  (1 − metallic)`: metals black, dielectrics keep 96 %.

Tick **alpha (`_ca`)** to add an Opacity alpha and write the file as `_ca`
instead of `_co` — for transparent materials (glass, foliage, decals).

### `_nohq` (normal)

Built from Painter's converted normal (normal channel + height + baked mesh
normal, never flat). DayZ expects **DirectX** normals; the format is switchable
(`opengl` / `directx`) and remembered per project.

### `_smdi` (specular)

`R = white`, `G = specular level`, `B = gloss = 1 − roughness`, with a source
dropdown (see [How the maps are calculated](#how-the-maps-are-calculated) for the
exact formulas):

- **Spec+Gloss (convert maps)** — Painter's converted Specular + Glossiness.
- **Met+Rough (channels)** — straight from metallic + roughness; metals go to a
  flat full specular.
- **Met+Rough+BaseColor (PBR)** — physically based: each metal takes its own
  reflectance from the (linearised) base-colour luminance; dielectrics keep the
  `0.04` floor.
- **Met→Spec/Gloss (glTF)** — the canonical glTF conversion:
  `G = perceivedBrightness(mix(0.04, baseColor, metallic))`.

Two sliders scale the **G** (specular) and **B** (gloss) channels (`1.00 =
unchanged`).

### `_as` (ambient shadow)

DayZ layout: R/B white, G = mixed AO. 512 is usually plenty.

### `_em` (emissive) — optional

The Emissive channel, saved as-is. DayZ multiplies it by the material's
`emmisive[]` value.

### `_mc` (macro) — optional

Built from a Painter **User** channel (or several combined). Source dropdown
picks `User0` / `User1` / `User2` or **Combine (User0-2)** with a **blend mode**
(Lighten / Screen / Add / Overlay / Average / Multiply / Darken). The **alpha**
dropdown sets the DayZ blend mask: **Auto (macro)**, None, a User channel, or
Opacity. The mask controls how the macro blends over the base texture
(`1 = only macro`, `0 = only base`).

> `_em`, `_ca` and `_mc` need extra channels in your project (Emissive, Opacity,
> User0-User2). Add them in one click with **Prepare DayZ channels** in Settings.

### Batch `.paa`

**Convert `.tga → .paa` (folder)** runs ImageToPAA over every `.tga` in a folder
— handy for converting a whole texture set at once.

---

## RVMAT tab

A complete Super-shader `.rvmat` editor.

### Texture extension & "Use textures inside"

Pick the extension (`.paa` / `.tga`) written into the `.rvmat`, then **Use
textures inside** fills the NOHQ / AS / SMDI stages with the real exported paths
(output + prefix, mod-relative).

### Texture stages

`NOHQ`, `AS`, `SMDI`, `MC` — each with **browse** (pick a file, stored
mod-relative), **open** (view in TexView / your default app), and **default**
(reset to the procedural value). The buttons are compact icons with tooltips.

### Preset (built-in + your own)

One grouped dropdown:

- **— Presets —** — the built-in materials: **Default, Rubber, Gold, Iron,
  Plastic, Wood, Cloth, Car Paint New, Car Paint Matte, Aluminum, Copper, Brass,
  Silver, Steel, Titanium, Nickel, Chrome, Glass** (metals carry BI-correct
  fresnel N/K).
- **— My presets —** — presets you saved.

Buttons: **Load** fills all material values from the selection; **Save** stores
the current material values as one of *your* presets (asks for a name); **✕**
deletes one of your presets (built-in presets can't be deleted). Your presets
save only the *values* (ambient / diffuse / forcedDiffuse / emmisive / specular /
specularPower / fresnel N,K / env); loading them resets the texture stages to
their procedural defaults. The presets file lives in a folder you can set in
Settings (empty = next to the plugin; a synced folder shares them across
machines).

### Material colours

`ambient`, `diffuse`, `forcedDiffuse`, `emmisive`, `specular` — each shows a
**coloured button** previewing the RGBA value; click it for an **RGBA editor**
(sliders + live preview + colour picker). Per-row helper icons:

- **tint** (droplet) on ambient/diffuse — average (linearised) base colour.
- **estimate** (spark) on emmisive — from the project's Emissive channel; on
  specularPower — a heuristic from the average roughness.
- **specular estimate** (droplet) — reads the metal tint straight from the base
  colour: glTF `F0 = mix(0.04, baseColor, metallic)` averaged over the metallic
  pixels. One click fills brass / copper / etc.
- **reset** (⟳) — back to the neutral value.

> `specularPower` is always written as an **integer**, and the Default preset's
> specular is white `{1,1,1,1}` — a black specular multiplies the `_smdi`
> specular to zero and the Material Editor then ignores specularPower.

### Fresnel

Editable `N` / `K` → `#(ai,64,64,1)fresnel(N,K)`, or the **Curve** editor: a live
reflectance-vs-angle graph you drag, with an *Estimate from base colour* button.

### material N/K (fresnel library)

A dedicated helper: pick a material and **Apply** to set fresnel `N`/`K` **and**
the specular tint at once. Each entry shows its `F0` (reflectance at normal
incidence). Like the Preset row, the dropdown is grouped into **— Materials —**
(built in) and **— My materials —** (yours), with **Apply / Save / ✕**:

- **Apply** — write the selected material's N, K and specular tint into the
  fields.
- **Save** — store the current fresnel N/K + specular tint as your own material
  (asks for a name). Saved in the same folder as your presets (Settings), so they
  travel/share the same way.
- **✕** — delete one of your materials (built-in materials can't be deleted).

Built-in contents:

- **Metals, BI-correct** (from the presets): Gold, Iron, Aluminum, Copper, Brass,
  Silver, Steel, Titanium, Nickel, Chrome.
- **More metals** (refractiveindex.info, representative): Bronze, Zinc, Tin,
  Lead, Platinum, Cobalt, Tungsten.
- **Dielectrics** (`K = 0`, F0 from N): Glass (1.5), Water (1.33), Ice (1.31),
  MgO (1.74), Sapphire (1.77), Quartz (1.55), Diamond (2.42).

### env (Stage7)

Dropdown of the 23 DayZ `dz\data\data` environment maps (editable if you use a
custom one).

### Write / load / MatEditor

- **Write `.rvmat`** — writes `<prefix>.rvmat` in the output folder.
- **Load existing** — finds `<prefix>.rvmat` and loads its values.
- **Open in MatEditor** — opens the file in the Buldozer material editor, with an
  optional **Auto-sync** that reads changes back into the panel when you save.

---

## Damage variants

DayZ items change material as they take damage (worn / damaged / destroyed). This
section stamps those out for you, ported from the RwG RVMat Speedo tool.

Pick a **material family** and click a variant button. Families: **Generic,
Wood, Food, Weapons Generic, Weapons Metal, Weapons Wood, Plastic, Cloth Tops,
Cloth Vests, Cloth Pants, Cloth Shoes**. Each family offers its variant buttons
(*Worn / Damage / Destruct*, or *Burn / Rotten* for food, …).

It takes the current / loaded base `.rvmat`, swaps **only the MC (Stage3)** to the
family's damage `_mc`, and writes `<prefix><suffix>.rvmat` next to the original —
otherwise identical. Optional checkboxes also reset **NOHQ / AS / SMDI** to their
procedural defaults in the variant.

These damage `_mc` textures are the shared generic BI ones (e.g. under
`dz\characters\data`), so they cost no extra texture memory — hundreds of items
share them.

---

## Settings

Tool paths and machine/UI options live in the **Settings** dialog and are stored
**globally**:

- **Python (numpy+pillow)** — with **Auto-detect**.
- **ImageToPAA.exe** — DayZ Tools, for `.paa`.
- **MatEditor.exe** — Buldozer material editor, for *Open in MatEditor*.
- **TexView.exe** — for the per-stage *Open* buttons.
- **Mod drive** — e.g. `P:\`, used to make `.rvmat` texture paths game-valid and
  to open textures.
- **My presets folder** — where your saved RVMAT presets
  (`rwg_dayz_user_presets.json`) live. Empty = next to the plugin; point it at a
  synced/cloud folder to share presets across machines.
- **Panel layout** — Tabs or Single window.
- **Prepare DayZ channels** — adds **Emissive + Opacity + User0-User2** (colour)
  to the active texture set if they're missing, so `_em` / `_ca` / `_mc` can be
  exported. Best baked into a Painter project template.

---

## Project vs global settings

- **Global** (a JSON file next to the plugin): tool paths, mod drive, panel
  layout, presets folder — everything machine/UI related.
- **Per project** (stored in the Painter project metadata, travels with the
  `.spp`): output folder, prefix, map choices, normal format, and all RVMAT /
  material values.

A brand-new project starts from clean defaults; open an existing one and its
values come back. Save the Painter project to persist the metadata to disk.

---

## How the maps are calculated

DayZ is a **specular / glossiness** engine, so the export is really a metal/rough
→ spec/gloss conversion. The dielectric reflectance constant is `F0 = 0.04`.

### `_co` diffuse

- *Spec/Gloss diffuse (glTF)*: `diffuse = baseColor × (1 − 0.04) × (1 − metallic)`
  — the canonical glTF spec/gloss diffuse. Metals go black; dielectrics keep
  96 % of their albedo (the 4 % that becomes the dielectric specular is removed).

### `_smdi` green (specular level)

The three metal-based methods differ only in where **G** comes from:

```
Spec+Gloss :  G = Specular (Painter converted) × G_slider
Met+Rough  :  G = (0.04 + 0.96 × metallic) × G_slider
PBR        :  G = lerp(0.04, luminance_linear(baseColor), metallic) × G_slider
glTF       :  G = perceivedBrightness( mix(0.04, baseColor_linear, metallic) ) × G_slider
```

`B = (1 − roughness) × B_slider` in every case. `perceivedBrightness(c) =
sqrt(0.299 R² + 0.587 G² + 0.114 B²)` is glTF's canonical brightness metric.

### The `specular[]` tint (rvmat)

DayZ can't store a coloured specular in `_smdi`, so the metal colour lives in the
rvmat `specular[]`. The **specular estimate** computes it as the glTF
`F0 = mix(0.04, baseColor, metallic)`, averaged over the metallic pixels (sRGB) —
which yields the familiar metal colours (copper ≈ `0.95, 0.64, 0.54`, brass ≈
`0.91, 0.74, 0.42`).

### Fresnel N/K → F0

The Stage6 fresnel takes a scalar `N` (index of refraction) and `K` (absorption):

```
F0 = ((N − 1)² + K²) / ((N + 1)² + K²)
```

Dielectric `N = 1.5, K = 0` → `F0 = 0.04`. Conductors go high (copper F0 ≈ 0.86).
The **material N/K** library exposes real values; the metal colour still rides in
the specular tint (DayZ stores one scalar N/K, not one per channel).

---

## Recipes & workflows

### A metal material (brass, copper, steel…)

1. Paint metal/rough as usual.
2. **Maps** → `_smdi` source **Met+Rough+BaseColor (PBR)** (or **glTF**); export.
3. **RVMAT** → pick the metal in **Preset** → **Load** (or use **material N/K** →
   Apply, then the **specular estimate** droplet).
4. Set an **env** map; **Use textures inside**; **Write .rvmat**.

For casings/shells, gloss B around `0.7–0.85` reads as polished; drop it for worn
metal.

### Transparent material (`_ca`)

1. Add an **Opacity** channel (Prepare DayZ channels).
2. **Maps** → tick **alpha (`_ca`)** on `_co`. The colour map is written as `_ca`
   with the Opacity alpha.

### Emissive / glow (`_em`)

1. Add an **Emissive** channel; paint the glow.
2. **Maps** → tick `_em`.
3. **RVMAT** → **emmisive** estimate (spark) reads the average glow colour.

### Macro / detail (`_mc`)

1. Add **User0-User2** channels (Prepare DayZ channels); paint the macro into a
   User channel.
2. **Maps** → `_mc` source = that User channel (or **Combine**), pick a blend and
   an alpha mask.
3. The `_mc` fills Stage3 in the rvmat.

### Two-material item on one UV (e.g. copper bullet + brass case)

DayZ's specular tint is **global per material**, so one rvmat can only show one
metal colour. To get two, use two materials on two face selections — the
DamageSystem swaps both per health level:

1. **Model (Object Builder):** split the mesh into two named selections (e.g.
   `camo` = case, `bullet` = projectile); assign each its own rvmat on the faces.
   On far LODs, keep one material to save the extra draw call.
2. **model.cfg:** list both sections in order, e.g.
   `sections[]={"camo","bullet"};`.
3. **rvmats:** a brass one for the case, a copper one for the bullet — same
   textures, only specular tint + fresnel differ. Save them as **My presets**
   (`Brass Casing`, `Copper Bullet`) so it's one click per cartridge.
4. **config `healthLevels`:** list **two** rvmats per level, in the same order as
   `sections[]` (case first, bullet second). Damage/destruct can reuse one shared
   worn rvmat for both slots.

Cost: one extra draw call in the near LOD only; the textures are shared so there
is no extra VRAM. Damage/destruct variants are *swapped*, not stacked, so they
don't add draw calls.

---

## Companion: the RwG DayZ Super viewport shader

A separate project, **RwG DayZ Super**, is a custom Substance Painter viewport
shader (`dayz-super.glsl`). You keep painting in metal/rough, but the viewport
shades the surface the DayZ way — a Fresnel-N/K driven, tinted specular, gloss
from `1 − roughness` — so the preview matches the in-game look far better than the
default PBR shader. Its parameters mirror this plugin's rvmat editor (ambient /
diffuse / forcedDiffuse / emmisive, fresnel N/K, specular tint, specularPower,
env tint).

Install: drop the `.glsl` into a Painter shelf `shaders` folder and pick it in
**Texture Set Settings → Shader**. It's an approximation (Painter uses an HDRI
IBL, not the DayZ cubemap system) and viewport-only — export is unchanged.

---

## Troubleshooting & FAQ

**"Set Python (numpy + pillow) first."** — Open Settings → set the Python path or
hit Auto-detect. That Python needs `numpy` and `pillow`
(`pip install numpy pillow`).

**`.paa` didn't get written.** — `.paa` needs **ImageToPAA.exe** (DayZ Tools) set
in Settings. `.tga` is always written regardless.

**The Material Editor ignores specularPower.** — specularPower must be an integer
(the plugin writes it as one) and the specular colour must not be black. Use a
metal preset or the specular estimate.

**"Use textures inside" wrote only the file names.** — Set your **Mod drive** in
Settings (e.g. `P:\`) and put the output folder inside that drive, so paths can be
made mod-relative.

**A metal looks flat / dark.** — Make sure an **env** map is set (Stage7) — metal
reflects the environment. Also check the specular isn't black.

**My two-metal cartridge shows one colour.** — One rvmat = one specular tint. You
need two materials on two face selections (see the two-material recipe).

**Nothing exported.** — Tick at least one map on the Maps tab, and make sure a
project is open with an output folder set.

---

## Known limitations

- The *2D View* `_co` source is the flattened base colour — Painter's API has no
  true shaded-viewport export.
- Painter's Python API can't read a project's normal format, so the plugin
  defaults to **DirectX** (switchable, remembered per project).
- Fresnel N/K can't be uniquely recovered from a metalness map — the *Estimate*
  is an F0-matched starting point; named-metal presets and the material N/K
  library are more accurate.
- The extra-metal N/K values (Bronze, Zinc, …) are representative visible-band
  figures; the ten preset metals use the BI reference values.
- Some export details vary by Painter version — if something looks off, open the
  Log and check the message.

---

## Glossary

- **`_co` / `_ca`** — colour (diffuse) / colour+alpha.
- **`_nohq`** — normal map (DayZ, DirectX).
- **`_smdi`** — specular map: R white, G specular level, B gloss.
- **`_as`** — ambient shadow (green = AO).
- **`_em`** — emissive.
- **`_mc`** — macro / detail overlay (alpha = blend mask).
- **`.rvmat`** — the Enfusion material definition (Super shader).
- **`.paa`** — DayZ's compressed texture format.
- **F0** — reflectance at normal incidence (dielectric ≈ 0.04).
- **Gloss** — `1 − roughness`.
- **Super shader** — DayZ/Enfusion's main PBR shader (spec/gloss + fresnel).

---

## Changelog

Full history lives in [`CHANGELOG.md`](CHANGELOG.md); this is the latest release
(everything since the previous upload, **v0.3.0 → v0.4.0**).

### v0.4.0 — Preview (2026-08-15)

A conversion-accuracy + workflow release, focused on the metal/rough → DayZ
spec/gloss pipeline and on taming the growing preset UI.

**Maps**

- New **`_smdi` method — Met→Spec/Gloss (glTF)**: the canonical glTF conversion,
  `G = perceivedBrightness(mix(0.04, baseColor, metallic))`, alongside the
  existing Spec+Gloss / Met+Rough / PBR methods.
- New **`_co` source — Spec/Gloss diffuse (glTF)**: `baseColor × (1 − 0.04) ×
  (1 − metallic)` — metals black, dielectrics keep 96 %.
- **`_mc`** (macro) export from a Painter **User** channel, or several combined
  with a blend mode, with the DayZ alpha **blend mask** (Auto / None / a User
  channel / Opacity).

**RVMAT editor**

- **Fresnel material library** — a `material N/K` picker that sets fresnel N/K
  **and** the specular tint in one click. 24 built-in materials (BI-correct
  metals + more metals + dielectrics), each showing its `F0`.
- **Save your own Fresnel materials** — store the current N/K + specular tint as
  a named material (grouped *— Materials — / — My materials —*, Save / ✕).
- **Specular estimate** — fill `specular[]` from the metal reflectance (glTF
  `F0 = mix(0.04, baseColor, metallic)`, averaged over the metallic pixels).
- **Presets reworked** — built-in + your own saved presets in one grouped
  dropdown (*— Presets — / — My presets —*) with **Load / Save / ✕** and a delete
  confirmation; presets saved to a configurable folder.
- New **Brass** material preset.

**UI & settings**

- **My presets folder** setting (empty = next to the plugin; a synced folder
  shares presets/materials across machines).
- **Prepare DayZ channels** button (Settings) — adds Emissive + Opacity +
  User0–User2 for `_em` / `_ca` / `_mc`.

**Docs**

- Full **`WIKI.md`** (this document).
- Companion project **RwG DayZ Super** — a Substance Painter viewport shader that
  previews the DayZ look while you paint in metal/rough.

### Earlier releases

- **v0.3.0** (2026-08-02) — Tabbed layout, per-project settings, the RVMAT colour
  + fresnel-curve editors, the first extra `_smdi` methods (Met+Rough, PBR), the
  `_ca` / `_em` exports, and the damage-variant generator. See `CHANGELOG.md`.
- **v0.1.0** (2026-08-01) — First public preview.

---

## Credits & license

Built by **RwG** for the DayZ modding community. Fresnel N/K for the metal
presets come from the Bohemia Interactive Super shader documentation; the extra
material N/K values are from refractiveindex.info; the damage `_mc` tables come
from the RwG RVMat Speedo tool; the metal/rough ↔ spec/gloss conversion follows
the glTF reference.

Licensed under the **RwG DayZ Texture Exporter License (Non-Commercial)**: free to
use, share and adapt with credit; **not for sale**, and all intellectual property
stays with RwG. Anything you *make* with it (your textures / `.rvmat` files) is
entirely yours, including commercially. See `LICENSE`.
