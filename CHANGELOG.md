# Changelog

## v0.6.0 (2026-10-21)

Model first, a live link to the DayZ Material Viewer, and conversions measured
against the game's own shader. Includes the never-released v0.5.0b work.

### Model first (Setup tab)

- **Model (.p3d)** field: the Object Builder model this project paints. Found by
  itself next to the mesh Painter imported, next to the `.spp` or in/above the
  output folder.
- **Texture set** list: the model's rvmats **and those of its proxies** (stock,
  handguard, magazine … with their own P3D and data folder), read straight from
  the P3D. Choosing one sets Output folder and Prefix; remembered **per texture
  set**, so switching texture sets in Painter switches the paths too. A matching
  name is suggested.
- ✓/✗ check lines: does the export write the `.rvmat` and `_co` where the model
  expects them?
- **Path fix:** paths stay in `P:\` form even when a file dialog returns the real
  folder behind the work drive (`subst` target, mods linked into `P:` by
  junction). Loading a model's rvmat no longer switches to the real folder.

### DayZ Material Viewer link

- **Send after export** — the viewer reloads the written textures and `.rvmat`;
  for a proxy's material it switches that proxy on.
- **Live material values** — the RVMAT values go to the viewer while you edit
  them (no save), applied to every face using `<prefix>.rvmat`.
- **Both ways** — values edited in the viewer's material panel come back into
  the plugin fields (and from there into the viewport shader).
- **Open in viewer** / **Send now**; `DayZViewer.exe` path in Settings.

### DayZ In-Game viewport shader

- **Live to DayZ In-Game shader** and a new **To shader** button send the
  material values to the `dayz-ingame` shader (RwG DayZ SP Shader).
- **One shader instance per texture set.** The values go to the *active*
  texture set only; a texture set sharing its instance with others (or still on
  Painter's default "Main shader") gets its own `DayZ <texture set>` copy first.

### Conversions matched to the game

- **DayZ shader-matched `_smdi` / `_dtsmdi`**, measured against the Super shader
  (RenderDoc captures + a pixel-identical rebuild):
  `G = F0 / F0(fresnel N,K) × B`, `B = (2/roughness⁴ − 2) / specularPower`.
  The older methods wrote F0 into G, which the shader multiplies with the fresnel
  stage again — reflections came out up to ~25× too weak.
- **`_co` = Base Color** only. The shader takes the reflected part off the
  direct light itself and does not darken the ambient light, so the Diffuse /
  glTF spec-gloss / 2D View sources (darkened or black metals) are gone.
- The other `_smdi` methods (glTF, PBR, Met+Rough, Spec+Gloss) and the G/B
  sliders are removed — G/B are fully defined by the material.

### Material presets

- All built-in presets reviewed against the shader: `ambient` / `diffuse` = 1,
  dielectrics with white specular and fresnel `1.5, 0` (wood `1.5, 0.45`),
  metals with a hue-only specular tint and `specularPower` ≤ 400.
- The specular estimate for dielectrics returns white.

### Layout

- **Maps** and **Export** side by side; the export buttons are stacked
  (**Export .tga + .paa**, **Export .tga only**).
- `_co` / `_smdi` show their (single) method as a label instead of a dropdown.

### Removed

- Viewport look buttons (HDRI / DayZ env / tone), the in-Painter map preview
  (eye buttons), **Open in MatEditor** + Auto-sync, **From shader** (the viewer
  link replaces them).

### Performance and fixes

- The numpy/Pillow conversion runs on a **background thread** — export and the
  `.tga → .paa` batch keep Painter responsive; no console window flashes.
- No more "This method is deprecated" spam on Painter 2026 (texture set names
  are read as a property).
- P3D reader: MLOD face data offset fixed (header size includes the signature).

## v0.4.5b — Preview (2026-08-21)

A follow-up to v0.4.3: a detail-strength control, a tidier Maps / Export layout,
a `.tga` default, and a refreshed Help with a GitHub version check.

### Maps

- **`_dtsmdi` detail-strength slider.** A **Detail (R)** slider scales how
  pronounced the `_dtsmdi` detail is. It only changes the amplitude around **0.5**
  — the map stays centred on 0.5 (BI's "average 0.5, fades in the mipmaps" rule),
  so higher just means crisper detail, not a brightness shift. Enabled only when
  `_dtsmdi` is ticked; wired through the CLI (`--dtsmdi-strength`) too.
- **Inline slider layout.** `_dtsmdi` now sits directly under `_smdi`, and each
  map's tuning sliders sit **inline on its own row**, in the gap between the
  source dropdown and the size box — the **G / B** sliders on the `_smdi` row, the
  **Detail (R)** slider on the `_dtsmdi` row.

### RVMAT / UI

- **`.tga` default.** *Texture paths use* now defaults to **.tga** for new
  projects (was `.paa`); existing projects keep their saved choice.
- **Tidier Export section.** The **"Also fill the RVMAT texture fields (NOHQ / AS
  / SMDI / MC)"** option now sits **above** the export buttons (set it before you
  export), and the `.tga → .paa` batch tool is separated as a standalone utility.
- **Refreshed Help + version check.** The **?** help is rewritten for the current
  feature set and links to the **GitHub** repo / releases / wiki. A new **Check
  for updates** button compares the installed version against the latest GitHub
  release (pre-releases included) and points you to it when a newer one exists.

## v0.4.3 — Preview (2026-08-20)

A maps + UI release: a new `_dtsmdi` map for the Multimaterial shader, live
texture-availability lights, clearer wording, and a card-based, red-accented
layout.

### Maps

- **New `_dtsmdi` export (Detail + SMDI)** for the DayZ **Multimaterial** shader.
  `R` = a fine detail map, `G` = specular level, `B` = gloss — G/B built exactly
  like the `_smdi` (same method + the G/B sliders). The **detail (R)** combines
  **height + baked mesh + normal**: Painter's converted normal always, plus the
  raw **Height** channel when the project has one (high-passed, averaged ~0.5 so
  it fades neutrally in the mipmaps). Own map row + resolution; written as
  `<prefix>_dtsmdi`.

### RVMAT / UI

- **paa / tga availability lights.** Each texture row (NOHQ / AS / SMDI / MC) now
  has a small traffic-light: green = the referenced file is on disk, amber = only
  the other extension exists (convert / switch ext), red = nothing found, grey =
  procedural default. Hover for details; updates live.
- **Clearer wording.** *Texture ext* → **Texture paths use** (with a `.paa = game
  · .tga = preview` hint); *Use textures inside* → **Auto-fill from export**, with
  fuller tooltips.
- **Card layout.** Every section is now a titled, bordered card. The RVMAT tab is
  split into **Textures / Material / Write** cards (plus Damage variants) for a
  clearer structure.
- **RwG red accent.** The UI accent switched from green to the RwG red (`#E4141F`,
  matching rwg-addon.com) on headers, cards, active tab, checked boxes, focus and
  sliders; card titles are larger and bold.

### Fixes

- **`_dtsmdi` no longer drags a `_smdi` along.** Exporting with only `_co` /
  `_nohq` / `_dtsmdi` ticked used to also write a `_smdi`, because `_dtsmdi`
  supplies the same metallic/roughness inputs the CLI would infer a `_smdi` from.
  The `_smdi` is now built only when its own checkbox is ticked.
- **Optional RVMAT auto-fill.** New checkbox **"Also fill the RVMAT texture
  fields (NOHQ / AS / SMDI / MC)"** in the Export card (on by default). Turn it off
  to export the maps only and leave the RVMAT fields untouched; the **Auto-fill
  from export** button still works on demand.

## v0.4.2 — Preview (2026-08-20)

A small clarity + defaults release for the map export, based on how the DayZ
Super shader actually works (colour lives in the `_co`, the `_smdi` drives the
specular).

### Export

- **Clearer method names.** The `_co` and `_smdi` source dropdowns now spell out
  what each option does — for `_co` whether metals **keep their colour** or **go
  black**, for `_smdi` how the specular level is derived (flat metal spec /
  per-metal spec / glTF).
- **New sensible defaults.** `_co` defaults to **Base Color (metals keep color)**
  so the DayZ colour map carries the metal colour, and `_smdi` to
  **Met→Spec/Gloss (glTF)** — per-metal reflectance from
  `mix(0.04, baseColor, metallic)`.
- The recommended default now sits at the **top of each dropdown**, marked
  **(recommended)**; tooltips updated to match.

Internal source keys are unchanged, so existing projects keep their saved choice.

## v0.4.0 — Preview (2026-08-15)

A conversion-accuracy + workflow release, focused on the metal/rough → DayZ
spec/gloss pipeline and on taming the growing preset UI.

### Maps

- New **`_smdi` method — Met→Spec/Gloss (glTF)**: the canonical glTF conversion,
  `G = perceivedBrightness(mix(0.04, baseColor, metallic))`, alongside the
  existing Spec+Gloss / Met+Rough / PBR methods.
- New **`_co` source — Spec/Gloss diffuse (glTF)**: `baseColor × (1 − 0.04) ×
  (1 − metallic)` — metals black, dielectrics keep 96 %.
- **`_mc`** (macro) export from a Painter **User** channel, or several combined
  with a blend mode (Lighten / Screen / Add / Overlay / Average / Multiply /
  Darken), with the DayZ alpha **blend mask** (Auto / None / a User channel /
  Opacity).

### RVMAT editor

- **Fresnel material library** — a `material N/K` picker that sets fresnel N/K
  **and** the specular tint in one click. 24 built-in materials: the BI-correct
  metals plus more metals and dielectrics (Bronze, Zinc, Tin, Lead, Platinum,
  Cobalt, Tungsten, Glass, Water, Ice, MgO, Sapphire, Quartz, Diamond), each
  showing its `F0`.
- **Save your own Fresnel materials** — store the current N/K + specular tint as
  a named material (grouped `— Materials — / — My materials —`, with Save / ✕).
- **Specular estimate** — fill `specular[]` from the metal reflectance
  (glTF `F0 = mix(0.04, baseColor, metallic)`, averaged over the metallic
  pixels); fills brass / copper in a click.
- **Presets reworked** — built-in presets and **your own saved presets** now
  live in one grouped dropdown (`— Presets — / — My presets —`) with **Load /
  Save / ✕**; a delete confirmation dialog; your presets are saved to a
  configurable folder.
- New **Brass** material preset.

### UI & settings

- **My presets folder** setting — where your saved presets / materials live
  (empty = next to the plugin; a synced folder shares them across machines).
- **Prepare DayZ channels** button (Settings) — adds Emissive + Opacity +
  User0–User2 to the active texture set for `_em` / `_ca` / `_mc`.

### Docs

- Full **`WIKI.md`** — a complete, wiki-ready manual (install, every tab, the
  map formulas, recipes incl. the two-material cartridge, troubleshooting).
- Companion project **RwG DayZ Super** — a Substance Painter viewport shader that
  previews the DayZ look while you paint in metal/rough.

## v0.3.0 — Preview (2026-08-02)

A big feature + workflow release.

### Maps

- New **`_smdi` methods**: *Met+Rough (channels)* and a physically-based
  *Met+Rough+BaseColor (PBR)* that derives each metal's specular level from the
  linearised base-colour luminance (`lerp(0.04, luminance, metallic)`), on top
  of the existing *Spec+Gloss (convert maps)*. G/B sliders scale the channels.
- **`_co` → `_ca`** alpha toggle: export the colour map with an Opacity alpha as
  `_ca` for transparent materials.
- New **`_em`** (emissive / glow) export.

### RVMAT editor

- **Texture stages** gained a **browse** (file → mod-relative), **open** (view
  in TexView / default app) and icon **default/reset** button; added an **MC**
  (Stage3) stage.
- **Material colour editor** — every colour field shows a live colour-preview
  button that opens an **RGBA editor** (sliders + preview + colour picker).
  Helpers: **tint** (average base colour), **estimate** (specularPower from
  roughness, emmisive from the Emissive channel), and **reset to default**.
- **Fresnel curve editor** — a live reflectance-vs-angle graph with N/K sliders,
  the texture header (format/size), and an **Estimate from base colour** button.
- **env** dropdown of the DayZ `dz\data\data` environment maps (Stage7).
- Expanded, corrected material presets (metals with BI fresnel N/K).

### Damage variants

- Integrated **RwG RVMat Speedo**: pick a material family (Generic, Wood, Food,
  Weapons Generic/Metal/Wood, Plastic, Cloth Tops/Vests/Pants/Shoes) and stamp
  out `_worn` / `_damage` / `_destruct` (and `_burnt` / `_rotten`) rvmats — the
  base material with only the MC (Stage3) swapped to a damage `_mc`. Optional
  NOHQ / AS / SMDI reset checkboxes.

### UI & settings

- **Tabbed layout** (Setup / Maps / RVMAT) with a **Settings toggle** back to a
  single scrolling window.
- **Per-project settings** stored in the Painter project metadata — values
  travel with the `.spp`; a new project starts from clean defaults. Tool paths,
  mod drive and layout stay global.
- **Settings** gained **TexView.exe** and the **Mod drive** field.
- Compact, icon-based helper buttons.

### Fixes

- `specularPower` is written as an integer, and the Default preset's `specular`
  is now white `{1,1,1,1}` (black would zero out the `_smdi` specular and keep
  the MatEditor from picking up specularPower).
- `Use textures inside` / mod-relative paths no longer collapse to a bare file
  name when the output folder isn't on the mod drive — the folder path is kept.
- Correct active-texture-set export, non-blank `_nohq`, and various layout fixes.

## v0.1.0 — Preview (2026-08-01)

First public preview.

- Export DayZ textures from the active Substance 3D Painter project:
  `_co`, `_nohq`, `_smdi`, `_as`, each with its own toggle and resolution.
- Uses Painter's converted maps: `Normal_DirectX` (normal + height + mesh
  normal), `Diffuse` for `_co`, `Specular` + `Glossiness` for `_smdi`,
  `AO_Mixed` for `_as`.
- Optional `.paa` conversion via DayZ Tools ImageToPAA, plus a batch
  `.tga → .paa` folder tool.
- RVMAT panel: `.paa`/`.tga` extension choice, auto-filled texture paths,
  per-texture "default" buttons, "Use textures inside", editable material
  value fields, editable fresnel, material presets (metals with BI-correct
  fresnel N/K), Write/Load, and live auto-sync with an external MatEditor.
- "Painter preset" mode to run your own saved export template.
- Dock toolbar icon, Window menu entry, in-plugin `?` help and Settings dialog.

Known limitations:
- The "2D View" `_co` source is the flattened base color (Painter's API has no
  true shaded-viewport export).
- Painter's Python API cannot read a project's normal format, so DirectX is the
  default (switchable).
