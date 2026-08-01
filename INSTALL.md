# RwG DayZ Painter Plugin — Projekt

Eigenständiges Substance-3D-Painter-Plugin, das PBR-Texturen aus dem aktiven
Projekt in DayZ-Texturen (`_co/_nohq/_smdi/_as`), optional `.paa` und eine
`.rvmat` umwandelt. Der gesamte Konvertierungs-Code ist im Plugin gebündelt
(`RwG_DayZ_Painter/core/`), das Projekt hängt an keinem anderen Repo.

## Struktur

```
RwG_DayZ_Painter_Plugin/            (dieses Repo)
   RwG_DayZ_Painter/                (-> nach python\plugins kopieren)
      __init__.py                   Painter-UI + Steuerung
      RwG_Logo.ico                  Toolbar-Icon
      README.md                     Plugin-Doku
      core/
         conversion.py              _co/_nohq/_smdi/_as
         rvmat_writer.py            Super-Shader-.rvmat
         paa_tools.py               .tga -> .paa, Mod-Pfade
         cli.py                     headless Einstieg
   INSTALL.md                       (diese Datei)
```

## Installation (Kurzfassung)

1. Python mit Bildbibliotheken bereitstellen:
   ```
   python -c "import numpy, PIL; print('OK')"   # sonst: pip install numpy pillow
   ```
2. Den Ordner `RwG_DayZ_Painter` nach
   `C:\Users\canex\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\`
   kopieren.
3. Painter neu starten → Menü **Python → RwG DayZ Texture Exporter** (oder das
   RwG-Icon in der Plugin-Leiste / den Window-Menüeintrag).
4. Im Dock einmal **Python** (numpy+pillow) und **Output-Ordner** setzen, dann
   **Export project + Convert**.

Details siehe `RwG_DayZ_Painter/README.md`.

## Verhältnis zu den anderen Tools

Der Kern-Code (`conversion`, `rvmat_writer`, `paa_tools`) ist identisch mit dem
im Texture-Converter-Repo — hier bewusst als eigenständige Kopie mitgeliefert,
damit das Plugin ohne externe Pfade läuft. Änderungen am Konvertierungs-Format
müssen bei Bedarf in beiden Repos nachgezogen werden.
