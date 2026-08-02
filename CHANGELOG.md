# Changelog

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
