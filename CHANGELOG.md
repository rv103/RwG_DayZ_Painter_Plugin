# Changelog

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
