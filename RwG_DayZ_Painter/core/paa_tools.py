"""
Shared helpers for config reading, .tga -> .paa conversion and mod-relative
path handling. Used by the RwG Texture Converter (and available to the RVMAT
Creator, which already reads the same config.cfg).

config.cfg format (as used by the RVMAT Creator):

    drive_letter=P:\
    textview_path=E:\...\DayZ Tools\Bin\ImageToPAA\TextView.exe

The DayZ Tools ship both TextView.exe (GUI viewer) and ImageToPAA.exe (CLI
converter) in the same folder. We derive the CLI converter from textview_path.
"""

import os
import ntpath
import subprocess


DEFAULT_DRIVE = "P:\\"


def read_config(config_path="config.cfg"):
    """Return {'drive_letter':..., 'textview_path':...} from config.cfg."""
    cfg = {"drive_letter": DEFAULT_DRIVE, "textview_path": ""}
    if not os.path.exists(config_path):
        return cfg
    with open(config_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def get_imagetopaa_exe(config_path="config.cfg"):
    """
    Locate ImageToPAA.exe. Preference:
      1. an explicit 'imagetopaa_path' entry in config.cfg (if present)
      2. ImageToPAA.exe next to the configured textview_path
    Returns the path or None if it cannot be found.
    """
    cfg = read_config(config_path)

    explicit = cfg.get("imagetopaa_path", "").strip()
    if explicit and os.path.exists(explicit):
        return explicit

    tv = cfg.get("textview_path", "").strip()
    if tv:
        candidate = os.path.join(os.path.dirname(tv), "ImageToPAA.exe")
        if os.path.exists(candidate):
            return candidate
        # Fall back to the configured path itself if it already points at the exe.
        if tv.lower().endswith("imagetopaa.exe") and os.path.exists(tv):
            return tv
    return None


def tga_to_paa(tga_path, paa_path=None, imagetopaa_exe=None,
               config_path="config.cfg", timeout=120):
    """
    Convert a single .tga to .paa using ImageToPAA.exe. The source .tga is kept.

    Returns the output .paa path on success. Raises FileNotFoundError if the
    converter or the source cannot be found, and RuntimeError if the conversion
    process fails.
    """
    if not os.path.exists(tga_path):
        raise FileNotFoundError(f"Source texture not found: {tga_path}")

    if imagetopaa_exe is None:
        imagetopaa_exe = get_imagetopaa_exe(config_path)
    if not imagetopaa_exe or not os.path.exists(imagetopaa_exe):
        raise FileNotFoundError(
            "ImageToPAA.exe not found. Set 'textview_path' (DayZ Tools "
            "ImageToPAA folder) or 'imagetopaa_path' in config.cfg."
        )

    if paa_path is None:
        paa_path = os.path.splitext(tga_path)[0] + ".paa"

    result = subprocess.run(
        [imagetopaa_exe, tga_path, paa_path],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0 or not os.path.exists(paa_path):
        raise RuntimeError(
            f"ImageToPAA failed for {tga_path}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return paa_path


def mod_relative_path(abs_path, drive_letter=None, config_path="config.cfg"):
    """
    Turn an absolute texture path into the mod-relative path a .rvmat should
    reference (backslash separated, no drive letter), e.g.

        P:\\MyMod\\data\\wall_smdi.paa  ->  MyMod\\data\\wall_smdi.paa

    If the path is not on the configured mod drive we can only fall back to the
    file name; the returned 'on_drive' flag tells the caller whether the path is
    game-valid so it can warn the user.
    """
    if drive_letter is None:
        drive_letter = read_config(config_path).get("drive_letter", DEFAULT_DRIVE)

    # Use ntpath so Windows-style DayZ paths resolve correctly on any host OS.
    abs_norm = ntpath.normpath(abs_path)
    drive_norm = ntpath.splitdrive(ntpath.normpath(drive_letter))[0]  # e.g. 'P:'
    path_drive, path_rest = ntpath.splitdrive(abs_norm)

    if drive_norm and path_drive.upper() == drive_norm.upper():
        rel = path_rest.lstrip("\\/").replace("/", "\\")
        return rel, True

    # Not on the mod drive: keep the folder structure (drive stripped) so the
    # path doesn't collapse to just a file name.
    return path_rest.lstrip("\\/").replace("/", "\\") or ntpath.basename(abs_norm), False


def abs_from_rel(rel, drive_letter):
    """Join a mod-relative texture path with the mod drive -> absolute path."""
    d = ntpath.splitdrive(ntpath.normpath(drive_letter))[0] or "P:"
    return ntpath.normpath(d + "\\" + str(rel).lstrip("\\/"))
