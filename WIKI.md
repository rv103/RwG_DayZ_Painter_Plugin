# RwG DayZ Texture Exporter — Complete Guide

A **Substance 3D Painter** plugin that turns a normal PBR (metal/rough) project
into game-ready **DayZ / Enfusion** textures (`_co` / `_ca`, `_nohq`, `_smdi`,
`_as`, `_em`, `_mc`, `_dtsmdi`), converts them to `.paa`, and writes a complete **Super
shader `.rvmat`** — damage / destruct variants included — all from a dock inside
Painter.

> This document is a full manual. Each `##` section is self-contained and can
> become its own wiki page; the Table of Contents maps to them. Look for the
> **Tip** call-outs.

---

## Table of contents

1. [How DayZ shading works (read this first)](#how-dayz-shading-works-read-this-first)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [First export in 5 minutes](#first-export-in-5-minutes)
5. [The panel & layout](#the-panel--layout)
6. [Setup tab](#setup-tab)
7. [Maps tab — the `_co` converters](#maps-tab--the-_co-converters)
8. [Maps tab — the `_smdi` converters](#maps-tab--the-_smdi-converters)
9. [Maps tab — `_nohq`, `_as`, `_em`, `_mc`](#maps-tab--_nohq-_as-_em-_mc)
10. [Export & `.paa`](#export--paa)
11. [RVMAT tab — texture stages](#rvmat-tab--texture-stages)
12. [RVMAT tab — presets](#rvmat-tab--presets)
13. [RVMAT tab — material colours & estimates](#rvmat-tab--material-colours--estimates)
14. [RVMAT tab — fresnel & the material N/K library](#rvmat-tab--fresnel--the-material-nk-library)
15. [RVMAT tab — env, write, load, MatEditor](#rvmat-tab--env-write-load-mateditor)
16. [Damage variants](#damage-variants)
17. [Settings & Prepare DayZ channels](#settings--prepare-dayz-channels)
18. [Project vs global settings](#project-vs-global-settings)
19. [Recipes & workflows](#recipes--workflows)
20. [Walkthrough: a material accent with `_mc`](#walkthrough-a-material-accent-with-_mc)
21. [The RwG DayZ Super viewport shader](#the-rwg-dayz-super-viewport-shader)
22. [Troubleshooting & FAQ](#troubleshooting--faq)
23. [Known limitations](#known-limitations)
24. [Reference tables](#reference-tables)
25. [Changelog](#changelog)
26. [Credits & license](#credits--license)

---

## How DayZ shading works (read this first)

Understanding this one thing makes every option in the plugin obvious.

Most artists paint in the **metal/rough** model: a `baseColor`, a `metallic`
mask, and a `roughness` map. DayZ's **Enfusion "Super" shader** does **not** use
that model. It uses **specular / glossiness**:

- **Colour lives in the `_co`.** The `_co` (albedo) carries the surface colour —
  for dielectrics *and*, by default, for metals. DayZ's `_co` is "colour only, no
  reflection info", so as long as the `_smdi` is right you can simply let a metal
  keep its colour in the `_co`. *(This is v0.4.2's default; the classic
  "metals-black" route is still supported — see the note below.)*
- **`_smdi` is grayscale.** It stores a specular *level* (how reflective, `G`) and
  a *gloss* (`B = 1 − roughness`). It decides how *shiny* the surface is, **not**
  what *colour* it is.
- **`fresnel(N,K)`** shapes how reflectance rises toward grazing angles.
- **`env`** (Stage7) is the reflection cubemap — without it, metal looks flat.

So the plugin's job is a **metal/rough → spec/gloss conversion**, split across
the maps:

| Metal/rough input | Goes to |
|---|---|
| baseColor (colour — dielectric *and* metal) | `_co` |
| metallic + roughness + baseColor | `_smdi` (G = specular level, B = gloss) |
| normal + height | `_nohq` |
| AO | `_as` |
| emissive | `_em`, `emmisive[]` |

> **Tip — the classic alternative.** BI's older Super-shader approach keeps a metal
> **black** in the `_co` and puts its colour in the rvmat **`specular[]` tint**
> instead. Both work; the plugin still supports it — pick the *Diffuse (metals
> black)* or *Spec/Gloss diffuse* `_co` source and set the specular tint (the
> estimate / material library). v0.4.2 just defaults to the simpler "colour stays
> in the `_co`" route.

> **Tip:** If a metal looks flat/greyish in-game, it's usually the **`_smdi`
> specular level** or a missing **env** map — not the colour. Check those first.

The dielectric reflectance constant used everywhere is **F0 = 0.04** (4 %), the
standard non-metal reflectance.

---

## Requirements

- **Substance 3D Painter** — PySide6 (2024+) or PySide2 (older); both handled.
- A **Python** with `numpy` + `pillow` (`pip install numpy pillow`) — runs the
  image conversion outside Painter. **Auto-detect** is in Settings.
- **DayZ Tools `ImageToPAA.exe`** — only for `.paa` output.
- Optional: **TexView / TexView2** and a **MatEditor** (Buldozer) for the
  in-plugin *Open* / *Auto-sync* helpers.

---

## Installation

1. Copy the **`RwG_DayZ_Painter`** folder into
   `…\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\`.
2. Restart Painter, or **Python → Reload Plugins**.
3. Open the panel via the dock, the toolbar icon, or the **Window** menu.
4. In **Settings**, set **Python** (Auto-detect) and, for `.paa`, **ImageToPAA**.

---

## First export in 5 minutes

1. Open your textured project.
2. **Settings** → set **Python** and your **Mod drive** (e.g. `P:\`).
3. **Setup** → **Output folder** (put it inside your `P:\` mod path) and a
   **Prefix** (or *Use texture set name*).
4. **Maps** → tick the maps, pick resolutions.
5. **Export .tga** (or **Export .tga + .paa**).
6. **RVMAT** → pick a **Preset** → **Load** → **Auto-fill from export** →
   **Write .rvmat**.

---

## The panel & layout

Three tabs — **Setup**, **Maps**, **RVMAT** — with **Settings** and **?** at the
top and a **status line** at the bottom that reports the result of every action.
Prefer one page? **Settings → Panel layout → Single window**. The choice is
global.

> **Tip:** When something doesn't work, read the status line first — it names the
> exact reason (missing channel, no output folder, no Python, …).

---

## Setup tab

- **Output folder** — where the textures land. Put it inside your `P:\` mod path
  so the `.rvmat` gets game-valid, mod-relative texture paths.
- **Prefix** — the file-name base (`wall` → `wall_co.tga`). **Use texture set
  name** fills it from the active set.
- **Export mode**:
  - **Built-in maps** — the plugin builds each map (recommended; gives you the
    converters below).
  - **Painter preset** — runs your *own* saved Painter export preset as-is (no
    external Python needed). Set the **preset name** + **shelf**.

> **Tip:** One output folder per texture set / item keeps prefixes from colliding.
> The plugin finds `<prefix>_*.tga` by folder + prefix, so keep them tidy.

---

## Maps tab — the `_co` converters

`_co` is the colour/diffuse map (assigned on the model, not an rvmat stage). The
**source** dropdown decides how it's built. This is where "metals go black" is
controlled.

| Source | What it does | Use it when |
|---|---|---|
| **Base Color — metals keep color (recommended)** | The raw albedo channel, untouched — metals keep their colour, so the DayZ colour map carries the metal colour. | **The default.** The simplest route: colour in `_co`, reflectivity in `_smdi`. |
| **Diffuse (metals black)** | Painter's *converted* Diffuse — the classic metal/rough→diffuse; metals go black and their colour must come from the rvmat specular tint. | The classic BI approach, or when you deliberately want metals black in `_co`. |
| **2D View** | The flattened 2D viewport, exactly as shown. | You want the painted look incl. effects that don't map to a channel. |
| **Base Color + Specular** | Albedo dimmed by the specular reflectance peak: `diffuse = base × (1 − specLevel)`. | You want the diffuse to lose exactly the energy that becomes specular (energy-ish conservation). |
| **Spec/Gloss diffuse (glTF)** | The canonical spec/gloss diffuse: `base × (1 − 0.04) × (1 − metallic)`. Metals fully black, dielectrics keep 96 %. | A physically-correct "metals-black" diffuse; companion to the glTF/PBR `_smdi`. |

Tick **alpha (`_ca`)** to add an **Opacity** alpha and write the file as `_ca`
instead of `_co` — for transparent materials (glass, foliage, decals).

> **Tip — which to pick:** Default to **Base Color** — metals keep their colour in
> the `_co` and the `_smdi` handles the shine. Switch to **Diffuse (metals black)**
> or **Spec/Gloss diffuse (glTF)** only if you want the classic black-metal `_co`
> with the colour in the rvmat specular tint. **2D View** is a fallback when you
> rely on 2D-only effects.

> **Tip — metals in `_co`:** With the default **Base Color**, metals *keep* their
> colour in `_co` — that's intended, not a bug. If you instead pick a "metals-
> black" source and a metal then looks grey in-game, its colour has to come from
> the rvmat `specular[]` (see the material colours / N/K library sections).

---

## Maps tab — the `_smdi` converters

`_smdi` packs `R = white`, **`G = specular level`** (how reflective), **`B =
gloss = 1 − roughness`** (how sharp/polished). The two sliders **G** and **B**
scale each channel (`1.00 = unchanged`). Only the **method** changes where `G`
comes from — `B` is always `(1 − roughness) × B_slider`.

| Method | Green (specular level) formula | Character | Use it when |
|---|---|---|---|
| **Met→Spec/Gloss (glTF) — recommended** | `G = perceivedBrightness(mix(0.04, baseColor, metallic))` | The canonical glTF metric (sqrt-weighted brightness): each metal takes its **own** reflectance from its base-colour brightness — dull/oxidised stays darker than polished. | **The default** — accurate, varied metals straight from a metal/rough project. |
| **Spec+Gloss (convert maps)** | `G = luminance(Painter's converted Specular)` | Respects a hand-authored specular; works even in a metal/rough project (Painter converts internally). | You painted a specular/gloss set, or want Painter's own conversion. |
| **Met+Rough (channels)** | `G = 0.04 + 0.96 × metallic` | Punchy: every metal jumps to a flat, near-full specular; dielectrics sit at 0.04. Ignores each metal's own reflectance. | You want a strong, uniform metallic look, or the base colour isn't reliable. |
| **Met+Rough+BaseColor (PBR)** | `G = lerp(0.04, luminance_linear(baseColor), metallic)` | Physically based; practically identical to glTF, just plain linear luminance instead of the glTF weighting. | An alternative reflectance-accurate method. |

`perceivedBrightness(c) = sqrt(0.299 R² + 0.587 G² + 0.114 B²)`.

> **Tip — which to pick:** Default to **glTF** (or the near-identical **PBR**) for
> realistic metals; use **Met+Rough** when you want every metal maximally shiny
> regardless of its colour; use **Spec+Gloss** when you have a real specular/gloss
> set to honour.

> **Tip — gloss (B):** `B = 1 − roughness`. A fresh brass casing is smooth →
> gloss ≈ **0.7–0.85**; worn/blasted metal → lower. Use the **B slider** to nudge
> the whole map without repainting roughness.

> **Tip — the colour still isn't here.** `_smdi` is grayscale on purpose. Set the
> metal's colour in the rvmat `specular[]` (one click: the **specular estimate**
> droplet, or the **material N/K** library). See below.

---

## Maps tab — `_nohq`, `_as`, `_em`, `_mc`

### `_nohq` (normal)

Built from Painter's converted normal (normal channel **+ height + baked mesh
normal**, never flat). DayZ expects **DirectX** normals; the format
(`opengl`/`directx`) is switchable and **remembered per project**.

> **Tip:** If a surface looks "inverted" / lit from the wrong side in-game, flip
> the normal format here.

### `_as` (ambient shadow)

DayZ layout: R/B white, **G = mixed AO**. 512 is usually plenty.

### `_em` (emissive) — optional

The Emissive channel saved as-is. DayZ multiplies it by the material's
`emmisive[]`. Needs an **Emissive** channel (see *Prepare DayZ channels*).

### `_mc` (macro) — optional

A detail/macro overlay from a Painter **User** channel — or several combined:

- **Source**: `User0` / `User1` / `User2`, or **Combine (User0-2)** with a
  **blend mode** (Lighten / Screen / Add / Overlay / Average / Multiply / Darken).
- **Alpha (blend mask)**: **Auto (macro)**, None, a User channel, or Opacity.
  DayZ uses this alpha to blend macro over the base (`1 = only macro`,
  `0 = only base`).

> **Tip:** Needs the **User0-User2** channels. Add them (plus Emissive + Opacity)
> in one click with **Prepare DayZ channels** in Settings — best baked into a
> project template.

### `_dtsmdi` (Detail + SMDI) — optional

The **Multimaterial** shader replaces the normal `_smdi` with a `_dtsmdi`, which
packs a fine **detail map** into the red channel while keeping the same specular /
gloss in green / blue:

- **`R` = detail** — a high-frequency detail map combined from **height + baked
  mesh + normal**. Painter's converted normal is always used; the raw **Height**
  channel is added when the project has one. Each source is high-passed (its
  low-frequency shape removed) and the deltas are summed around a neutral **0.5**,
  so the map fades out in the mip-chain instead of darkening the surface.
- **`G` = specular level, `B` = gloss** — built exactly like the `_smdi`: same
  source dropdown (Spec+Gloss / Met+Rough / PBR / glTF) and the same **G / B**
  sliders.

Tick **`_dtsmdi`** on the Maps tab and give it its own resolution; it's written as
`<prefix>_dtsmdi`. In the `.rvmat` this is the map the Multimaterial shader reads
in place of the Super shader's `_smdi`.

> **Tip:** `_dtsmdi` and `_smdi` are alternatives — the Super shader uses `_smdi`,
> the Multimaterial shader uses `_dtsmdi`. You don't normally need both for the
> same material.

---

## Export & `.paa`

- **Export .tga** — writes the ticked maps as `.tga` (always available).
- **Export .tga + .paa** / **Export .paa** — also runs **ImageToPAA**.
- **Convert `.tga → .paa` (folder)** — batch-convert every `.tga` in a folder.

After an export the plugin can auto-fill the RVMAT texture fields with the paths
it just wrote.

> **Tip:** `.tga` is your editable/previewable copy; `.paa` is what the game
> packs. Keep both — the rvmat can reference either (set the **Texture paths use** on
> the RVMAT tab).

---

## RVMAT tab — texture stages

The Super-shader stage layout the plugin writes:

| Stage | Map | Field |
|---|---|---|
| 1 | NOHQ (normal) | **NOHQ** |
| 2 | DT (detail) | procedural default |
| 3 | MC (macro) | **MC** |
| 4 | AS (ambient shadow) | **AS** |
| 5 | SMDI (specular) | **SMDI** |
| 6 | FRESNEL | `fresnel(N,K)` |
| 7 | ENV | **env** |

`_co` is **not** a stage — it's assigned on the model.

Each texture field (**NOHQ / AS / SMDI / MC**) has three icon buttons: **browse**
(pick a file, stored mod-relative), **open** (view in TexView / default app), and
**default** (reset to the procedural value). **Texture paths use** picks `.paa`/`.tga`,
and **Auto-fill from export** fills NOHQ/AS/SMDI with the real exported paths.

Behind each field is a small **availability light** that checks the disk live:
**green** = the referenced file exists, **amber** = only the *other* extension is
there (so convert it, or switch **Texture paths use**), **red** = nothing found,
**grey** = a procedural default (nothing to check). Hover it for the resolved
path. It's a quick way to catch a typo'd path or a `.paa` you forgot to convert
before the material ever reaches the game.

> **Tip:** Store paths **mod-relative** — set your **Mod drive** (`P:\`) in
> Settings and keep the output inside it, or "Auto-fill from export" will fall back
> to a folder-relative path.

---

## RVMAT tab — presets

One grouped **Preset** dropdown holds two groups:

- **— Presets —** — built-in materials: **Default, Rubber, Gold, Iron, Plastic,
  Wood, Cloth, Car Paint New, Car Paint Matte, Aluminum, Copper, Brass, Silver,
  Steel, Titanium, Nickel, Chrome, Glass** (metals carry BI-correct fresnel N/K).
- **— My presets —** — presets you saved.

Buttons: **Load** fills *all* material values from the selection; **Save** stores
the current values as one of *your* presets (asks a name); **✕** deletes one of
yours (built-in presets can't be deleted).

Your presets save only the **values** (ambient / diffuse / forcedDiffuse /
emmisive / specular / specularPower / fresnel N,K / env). Loading one **resets the
texture stages to their procedural defaults** — so a preset is a portable
*material look*, not tied to any texture paths. The presets file lives in a
folder you can set in **Settings** (empty = next to the plugin; a synced folder
shares them across machines).

> **Tip:** Build once, reuse forever. Tune a material, hit **Save** as e.g.
> `Brass Casing`, and every future item is one **Load** away.

---

## RVMAT tab — material colours & estimates

`ambient`, `diffuse`, `forcedDiffuse`, `emmisive`, `specular` — each shows a
**coloured button** previewing its RGBA value; click it for an **RGBA editor**
(sliders + live preview + colour picker). Per-row icons:

- **tint** (droplet) on ambient/diffuse — average (linearised) base colour.
- **estimate** (spark) on emmisive — from the Emissive channel; on specularPower
  — a heuristic from the average roughness.
- **specular estimate** (droplet) — reads the metal tint from the base colour:
  glTF `F0 = mix(0.04, baseColor, metallic)` averaged over the metallic pixels.
  One click fills brass / copper / etc.
- **reset** (⟳) — back to the neutral value.

What each field means in DayZ:

| Field | Effect |
|---|---|
| `ambient` | Tints the ambient (environment) light response. |
| `diffuse` | Tints the diffuse/base-colour response. |
| `forcedDiffuse` | An **unlit** constant colour added on top (always visible). |
| `emmisive` | Glow colour/strength (multiplies the `_em`). |
| `specular` | **The metal colour** + level of the specular reflection. |
| `specularPower` | Highlight tightness — higher = sharper/shinier. Written as an **integer**. |

> **Tip — never a black specular.** A black `specular[]` multiplies the `_smdi`
> specular to **zero** and the Material Editor then ignores `specularPower`.
> Keep it white for dielectrics, or the metal colour for metals.

> **Tip — the fastest metal setup:** paint metal/rough → export `_smdi` (PBR) →
> click the **specular estimate** droplet → done. The estimate pulls the exact
> brass/copper/steel tint straight from your base colour.

---

## RVMAT tab — fresnel & the material N/K library

### Fresnel N/K

Editable `N` (index of refraction) and `K` (absorption) → `#(ai,64,64,1)
fresnel(N,K)`. They set **F0**, the reflectance at head-on angle:

```
F0 = ((N − 1)² + K²) / ((N + 1)² + K²)
```

Dielectric `N = 1.5, K = 0` → F0 = 0.04. Conductors go high (copper ≈ 0.86). The
**Curve** editor shows the reflectance-vs-angle graph live and has an *Estimate
from base colour* button.

### material N/K library

A dedicated helper row. Pick a material and **Apply** to set fresnel `N`/`K`
**and** the specular tint at once — each entry shows its `F0`. The dropdown is
grouped like the presets:

- **— Materials —** (built in):
  - *Metals, BI-correct:* Gold, Iron, Aluminum, Copper, Brass, Silver, Steel,
    Titanium, Nickel, Chrome.
  - *More metals* (refractiveindex.info, representative): Bronze, Zinc, Tin,
    Lead, Platinum, Cobalt, Tungsten.
  - *Dielectrics* (`K = 0`, F0 from N): Glass (1.5), Water (1.33), Ice (1.31),
    MgO (1.74), Sapphire (1.77), Quartz (1.55), Diamond (2.42).
- **— My materials —** — yours.

Buttons: **Apply** (write N/K + specular), **Save** (store the current N/K +
specular tint as your own material, asks a name), **✕** (delete one of yours).

> **Tip:** DayZ stores a **single scalar** N/K, not one per colour channel — so
> the metal's *colour* rides in the **specular tint**, and N/K sets the
> *strength/curve*. That's why Apply sets both together.

> **Tip:** Need exact physics for an unusual material? Look it up on
> refractiveindex.info, take `n`/`k` around ~550 nm (green), compute F0 with the
> formula above, and **Save** it as your own material.

---

## RVMAT tab — env, write, load, MatEditor

- **env** — dropdown of the 23 DayZ `dz\data\data` environment cubemaps (Stage7),
  editable for a custom one. **A metal needs an env map or it looks flat.**
- **Write `.rvmat`** — writes `<prefix>.rvmat` in the output folder.
- **Load existing** — finds `<prefix>.rvmat` and loads its values back.
- **Open in MatEditor** — opens it in Buldozer's material editor, with optional
  **Auto-sync** that reads your edits back into the panel when you save.

> **Tip:** Set the env before writing. `env_land_co.paa` is the safe outdoor
> default; the reflective/chrome variants suit polished metal.

---

## Damage variants

DayZ items change material as they take damage. This section stamps those out,
ported from the RwG RVMat Speedo tool.

Pick a **material family** — Generic, Wood, Food, Weapons Generic, Weapons Metal,
Weapons Wood, Plastic, Cloth Tops, Cloth Vests, Cloth Pants, Cloth Shoes — and
click a variant button (*Worn / Damage / Destruct*, or *Burn / Rotten* for food).
It takes the current/loaded base `.rvmat`, swaps **only the MC (Stage3)** to the
family's damage `_mc`, and writes `<prefix><suffix>.rvmat` next to the original —
otherwise identical. Optional checkboxes also reset **NOHQ / AS / SMDI** to their
defaults in the variant.

> **Tip:** These damage `_mc` textures are the shared generic BI ones (under
> `dz\characters\data`, etc.), so they cost **no** extra texture memory — hundreds
> of items reuse them. And in the config they are *swapped* per health level, not
> stacked, so they don't add draw calls.

---

## Settings & Prepare DayZ channels

Global (machine/UI) settings:

- **Python (numpy+pillow)** — with **Auto-detect**.
- **ImageToPAA.exe** — for `.paa`.
- **MatEditor.exe** / **TexView.exe** — for the Open / Auto-sync helpers.
- **Mod drive** — e.g. `P:\`; makes texture paths game-valid.
- **My presets folder** — where your saved presets **and** materials live (empty
  = next to the plugin; a synced/cloud folder shares them across machines).
- **Panel layout** — Tabs / Single window.
- **Prepare DayZ channels** — adds **Emissive + Opacity + User0–User2** to the
  active texture set if missing, so `_em` / `_ca` / `_mc` can be exported.

> **Tip:** Run **Prepare DayZ channels** once and save it into a Painter
> **project template** — then every new DayZ item starts with the right channels.

---

## Project vs global settings

- **Global** (a JSON next to the plugin): tool paths, mod drive, panel layout,
  presets folder.
- **Per project** (Painter project metadata, travels with the `.spp`): output
  folder, prefix, map choices, normal format, and all RVMAT / material values.

A new project starts from clean defaults; reopen an old one and its values come
back. **Save the Painter project** to persist the metadata to disk.

---

## Recipes & workflows

### A metal material (brass, copper, steel…)

1. Paint metal/rough as usual.
2. **Maps** → `_co` source **Base Color** (metals keep colour — the default), or
   **Diffuse (metals black)** for the classic route; `_smdi` source
   **Met→Spec/Gloss (glTF)** (the default). Export.
3. **RVMAT** → pick the metal in **Preset → Load** *or* **material N/K → Apply**;
   then the **specular estimate** droplet to pull the exact tint from your art.
4. Set an **env** map; **Auto-fill from export**; **Write .rvmat**.

> **Tip:** Casings/shells: gloss **B ≈ 0.7–0.85** for polished, lower for worn.

### Transparent material (`_ca`)

1. Add an **Opacity** channel (Prepare DayZ channels); paint opacity.
2. **Maps** → tick **alpha (`_ca`)** on `_co`. The colour map is written as `_ca`
   with the Opacity alpha.

### Emissive / glow (`_em`)

1. Add an **Emissive** channel; paint the glow.
2. **Maps** → tick `_em`. **RVMAT** → **emmisive** estimate reads the glow colour.

### Macro / detail (`_mc`)

1. Add **User0-User2** (Prepare DayZ channels); paint the macro into a User
   channel.
2. **Maps** → `_mc` source = that channel (or **Combine**), pick a blend + alpha.

### Two metals on one UV (e.g. copper bullet + brass case)

DayZ's specular tint is **global per material**, so one rvmat = one metal colour.
For two, use two materials on two face selections; the DamageSystem swaps both
per health level:

1. **Object Builder:** split the mesh into two named selections (e.g. `camo` =
   case, `bullet` = projectile); assign each its own rvmat on the faces. Merge
   back to one material on far LODs to save the extra draw call.
2. **model.cfg:** `sections[]={"camo","bullet"};` (order matters).
3. **rvmats:** a brass one + a copper one — same textures, only specular tint +
   fresnel differ. Save them as **My presets** (`Brass Casing`, `Copper Bullet`).
4. **config `healthLevels`:** list **two** rvmats per level, same order as
   `sections[]` (case first, bullet second). Damage/destruct can reuse one shared
   worn rvmat for both slots.

> **Tip — performance:** two materials = one extra draw call in the near LOD only;
> textures are shared so no extra VRAM. Damage variants are swapped, not stacked.

---

## Walkthrough: a material accent with `_mc`

This is the trick for adding a small second (or third) material to an object
**without** a second rvmat — for example two **brass rivets** on a steel-and-wood
knife, a painted logo, a bit of rust, a coloured stripe. The `_mc` (macro) lays a
colour over the whole UV, and its **alpha channel is the blend mask** that decides
*where* that colour actually shows.

### The one rule that trips everyone up

**Black = transparent, white = opaque — not the other way round.**

The `_mc` alpha is a blend mask: `alpha = 1` shows the macro colour, `alpha = 0`
lets the base `_co` show through. When you use the plugin's **Auto (macro)** alpha,
the mask is taken from the macro's own brightness (`max(R, G, B)` per pixel). So:

- A **white** background → `max = 1` → **opaque everywhere** → the macro (white
  included) is drawn over the *whole* object. This is the "my background came out
  white instead of transparent" problem.
- A **black** background → `max = 0` → **transparent** → only your painted marks
  show, the base texture stays everywhere else.

> Paint the macro on **black**, not white.

### Step by step

1. **Add the User channels.** Settings → **Prepare DayZ channels** (adds
   User0–User2, Emissive, Opacity). Do this once and save it into your project
   template.
2. **Fill User0 with black.** In the layer stack, add a fill layer that writes
   **black** into User0 — this is your transparent background.
3. **Paint the accent.** On top, paint the accent colour where it belongs — e.g.
   the brass colour (`~0.91, 0.74, 0.42`) on the two rivets. Everything you *don't*
   paint stays black = transparent.
4. **Export the `_mc`.** Maps tab → tick **`_mc`**:
   - **Source:** `User0`
   - **alpha:** **Auto (macro)**
   - **size:** for a couple of small marks, **512** is plenty (see the note).
   Export.
5. **Wire it into the rvmat.** RVMAT tab → the **MC** stage → **Use textures
   inside** (or browse to `<prefix>_mc`). Write the `.rvmat`.
6. **Check in-game / Buldozer.** The rivets show brass; the rest of the knife is
   untouched.

### If you can't repaint User0 on black

Keep the RGB you have and drive the mask from a **separate channel** instead:

1. Paint the accent locations **white on black** into another channel — e.g.
   **User1** or **Opacity**.
2. Maps → `_mc` **Source** = your colour channel, **alpha** = that mask channel
   (User1 / Opacity) instead of *Auto (macro)*.

Now the RGB can be anything; only the masked spots are drawn.

### Combining several accents

If the accents live in different User channels (say brass in User0, a painted
number in User1), set the `_mc` **Source** to **Combine (User0-2)** and pick a
blend mode (**Lighten** keeps black neutral, so unpainted areas of each channel
don't fight). The alpha still follows the same black-is-transparent rule.

> **Is it worth it?** An `_mc` is a full extra texture over the object. For four
> tiny brass dots, use a **small** map (256–512) and remember the alternative:
> if the accent is a *big* part of the object (a whole metal fitting on a wooden
> handle), a **second rvmat** on its own face selection is often cleaner than a
> macro. Use `_mc` for the small stuff, a second material for the big stuff.

---

## The RwG DayZ Super viewport shader

A separate companion project, **RwG DayZ Super** (`dayz-super.glsl`), is a custom
Painter viewport shader. You keep painting in metal/rough, but the viewport shades
the surface the DayZ way — a Fresnel-N/K driven, tinted specular, gloss from
`1 − roughness` — so the preview matches the in-game look far better than the
default PBR shader. Its parameters mirror this plugin's rvmat editor (ambient /
diffuse / forcedDiffuse / emmisive, fresnel N/K, specular tint, specularPower, env
tint).

Install: drop the `.glsl` into a Painter shelf `shaders` folder and pick it in
**Texture Set Settings → Shader**.

> **Tip:** Load a DayZ-ish outdoor **HDRI** in Painter's Display Settings so the
> reflections read close to the game. It's an approximation and viewport-only —
> export is unchanged.

---

## Troubleshooting & FAQ

**"Set Python (numpy + pillow) first."** — Settings → set Python or Auto-detect;
that Python needs `numpy` + `pillow`.

**No `.paa` written.** — `.paa` needs **ImageToPAA.exe** in Settings. `.tga` is
always written.

**Metal is grey / colourless in-game.** — Set the `specular[]` tint (specular
estimate or material N/K) **and** an **env** map. `_smdi` only makes it shiny.

**The Material Editor ignores specularPower.** — It must be an integer (the plugin
writes it as one) and the specular must not be black.

**"Auto-fill from export" wrote only file names.** — Set the **Mod drive** and put
the output inside it so paths can be made mod-relative.

**Surface lit from the wrong side.** — Flip the **normal format** (opengl/directx)
on the `_nohq` row.

**My two-metal item shows one colour.** — One rvmat = one specular tint; use two
materials on two face selections (see the recipe).

**Nothing exported.** — Tick at least one map, a project open, an output folder
set.

**`_em` / `_ca` / `_mc` do nothing.** — Those need the Emissive / Opacity /
User0-2 channels — run **Prepare DayZ channels**.

**My `_mc` came out opaque / white over the whole object.** — The `_mc` alpha is a
blend mask where **black = transparent, white = opaque**. Paint the macro on a
**black** background (not white); with *Auto (macro)* alpha, black areas become
transparent and only your marks show. See the `_mc` walkthrough.

---

## Known limitations

- **2D View** `_co` is a flattened base colour — no true shaded-viewport export.
- Painter's API can't read a project's normal format, so the plugin defaults to
  **DirectX** (switchable, remembered per project).
- Fresnel N/K can't be uniquely recovered from a metalness map — the *Estimate* is
  an F0-matched starting point; the presets / material library are more accurate.
- The extra-metal N/K (Bronze, Zinc, …) are representative visible-band figures;
  the ten preset metals use the BI reference values.
- Some export details vary by Painter version — check the Log if something's off.

---

## Reference tables

### `_smdi` methods at a glance

| Method | G (specular level) | Best for |
|---|---|---|
| glTF *(default)* | `perceivedBrightness(mix(0.04, base, metallic))` | Accurate varied metals (canonical glTF) |
| Spec+Gloss | `luminance(Painter specular)` | Hand-authored spec/gloss |
| Met+Rough | `0.04 + 0.96·metallic` | Strong, uniform metals |
| PBR | `lerp(0.04, luminance_lin(base), metallic)` | Alternative accurate metals |

### `_co` sources at a glance

| Source | Metals | Dielectrics |
|---|---|---|
| Base Color *(default)* | keep colour | keep colour |
| Diffuse (metals black) | black | painted colour |
| 2D View | as shown | as shown |
| Base Color + Specular | dimmed by spec | slightly dimmed |
| Spec/Gloss glTF | black | ×0.96 |

### F0 of common materials

| Material | N | K | F0 |
|---|---|---|---|
| Glass | 1.5 | 0 | 0.040 |
| MgO | 1.74 | 0 | 0.073 |
| Diamond | 2.42 | 0 | 0.172 |
| Iron | 3.12 | 3.87 | ~0.56 |
| Brass | 0.44 | 3.0 | ~0.84 |
| Copper | 2.08 | 7.15 | ~0.86 |
| Gold | 0.3 | 3.0 | ~0.89 |

---

## Changelog

Latest releases; full history in `CHANGELOG.md`.

### v0.4.3 — Preview (2026-08-20)

**Maps** — new **`_dtsmdi` (Detail + SMDI)** export for the **Multimaterial**
shader: `R` = a fine detail map combined from **height + baked mesh + normal**,
with `G` / `B` built exactly like the `_smdi`. Own map row + resolution.
**RVMAT / UI** — live **paa / tga availability lights** behind every texture row
(green = on disk, amber = only the other extension, red = missing, grey =
procedural); clearer wording (*Texture ext* → **Texture paths use**, *Use textures
inside* → **Auto-fill from export**); a **card-based layout** (RVMAT split into
Textures / Material / Write cards); and the RwG **red** accent (`#E4141F`) with
larger, bold card titles.

### v0.4.2 — Preview (2026-08-20)

Clarity + defaults for the map export. The `_co` and `_smdi` source dropdowns now
spell out what each option does, and ship with sensible defaults: `_co` →
**Base Color (metals keep color)** so the colour map carries the metal colour, and
`_smdi` → **Met→Spec/Gloss (glTF)**. The recommended option now sits at the top of
each dropdown, marked *(recommended)*. Internal source keys are unchanged, so
existing projects keep their saved choice.

### v0.4.0 — Preview (2026-08-15)

**Maps** — new `_smdi` method *Met→Spec/Gloss (glTF)*; new `_co` source *Spec/Gloss
diffuse (glTF)*; `_mc` macro export (single or combined User channels + DayZ blend
mask). **RVMAT** — the Fresnel **material N/K library** (Apply N/K + specular tint;
save your own); the **specular tint estimate**; presets reworked into one grouped
built-in + user dropdown (Load / Save / delete); new **Brass** preset. **Settings**
— *My presets folder*; *Prepare DayZ channels*. **Docs** — this full guide; the
companion **RwG DayZ Super** viewport shader.

### Earlier

- **v0.3.0** (2026-08-02) — Tabs, per-project settings, colour + fresnel-curve
  editors, first extra `_smdi` methods, `_ca` / `_em`, damage-variant generator.
- **v0.1.0** (2026-08-01) — First public preview.

---

## Credits & license

Built by **RwG** for the DayZ modding community. Fresnel N/K for the preset metals
come from the Bohemia Interactive Super shader docs; the extra material N/K from
refractiveindex.info; the damage `_mc` tables from RwG RVMat Speedo; the metal/rough
↔ spec/gloss conversion follows the glTF reference.

Licensed under the **RwG DayZ Texture Exporter License (Non-Commercial)**: free to
use, share and adapt with credit; **not for sale**; all IP stays with RwG. Anything
you *make* with it (your textures / `.rvmat`) is entirely yours. See `LICENSE`.
