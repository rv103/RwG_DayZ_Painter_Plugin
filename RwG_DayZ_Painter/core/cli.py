"""
Headless PBR -> DayZ converter (bundled with the Painter plugin).

Self-contained inside the plugin's `core` package. The plugin calls this with
an external Python that has numpy + pillow installed; it prints a JSON summary.

Two modes:
  * conversion mode (default): PBR maps -> _co/_nohq/_smdi/_as, optional .paa/.rvmat
  * folder mode (--paa-folder DIR): convert every .tga in DIR to .paa

Per-map resolution: --co-res/--nohq-res/--smdi-res/--as-res override --resolution.
Only the maps whose inputs are supplied are produced (the plugin passes just the
checked ones).
"""

import os
import sys
import glob
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conversion          # noqa: E402
import rvmat_writer        # noqa: E402
import paa_tools           # noqa: E402


def _res(specific, default):
    return specific if specific else default


def run(args):
    os.makedirs(args.output, exist_ok=True)
    result = {"tga": {}, "paa": {}, "rvmat": None, "errors": [], "notes": []}

    def out(suffix):
        return os.path.join(args.output, f"{args.prefix}{suffix}.tga")

    if args.basecolor:
        try:
            use_spec = args.co_mode == "base_color_specular"
            result["tga"]["_co"] = conversion.convert_co_texture(
                args.basecolor, args.metallic, out("_co"), use_spec,
                _res(args.co_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_co: {e}")

    if args.normal:
        try:
            result["tga"]["_nohq"] = conversion.convert_nohq_texture(
                args.normal, out("_nohq"), args.normal_format,
                _res(args.nohq_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_nohq: {e}")

    if args.spec_map and args.gloss_map:
        try:
            result["tga"]["_smdi"] = conversion.convert_smdi_direct(
                args.spec_map, args.gloss_map, out("_smdi"),
                args.spec, args.gloss, _res(args.smdi_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_smdi: {e}")
    elif args.metallic and args.roughness:
        try:
            result["tga"]["_smdi"] = conversion.convert_smdi_texture(
                args.metallic, args.roughness, out("_smdi"),
                args.spec, args.gloss, _res(args.smdi_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_smdi: {e}")
    elif args.roughness:
        result["errors"].append("_smdi: roughness given without metallic.")

    if args.ao:
        try:
            result["tga"]["_as"] = conversion.convert_as_texture(
                args.ao, out("_as"), args.invert_ao,
                _res(args.as_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_as: {e}")

    # optional TGA -> PAA (TGA kept for previewing)
    make_paa = args.paa or args.rvmat
    if make_paa and result["tga"]:
        for suffix, tga_path in result["tga"].items():
            try:
                result["paa"][suffix] = paa_tools.tga_to_paa(
                    tga_path, imagetopaa_exe=(args.imagetopaa or None),
                    config_path=args.config)
            except Exception as e:
                result["errors"].append(f"{suffix} .paa: {e}")

    # optional RVMAT
    if args.rvmat:
        try:
            def ref(suffix):
                src = result["paa"].get(suffix) or result["tga"].get(suffix)
                if not src:
                    return None, True
                return paa_tools.mod_relative_path(src, drive_letter=args.drive)

            nohq_ref, nohq_ok = ref("_nohq")
            as_ref, as_ok = ref("_as")
            smdi_ref, smdi_ok = ref("_smdi")

            content = rvmat_writer.build_rvmat_from_preset(
                args.preset, nohq=nohq_ref, as_map=as_ref, smdi=smdi_ref)
            rvmat_path = os.path.join(args.output, f"{args.prefix}.rvmat")
            with open(rvmat_path, "w") as f:
                f.write(content)
            result["rvmat"] = rvmat_path

            off_drive = [s for s, ok in
                         (("_nohq", nohq_ok), ("_as", as_ok), ("_smdi", smdi_ok))
                         if not ok]
            if off_drive:
                result["notes"].append(
                    f"Output folder not on mod drive {args.drive}; rvmat uses bare "
                    f"file names for {', '.join(off_drive)}.")
        except Exception as e:
            result["errors"].append(f".rvmat: {e}")

    return result


def run_folder_to_paa(args):
    """Convert every .tga in a folder to .paa (keeps the .tga)."""
    result = {"paa": {}, "errors": [], "notes": []}
    tgas = sorted(glob.glob(os.path.join(args.paa_folder, "*.tga")))
    if not tgas:
        result["errors"].append(f"No .tga files in {args.paa_folder}")
        return result
    for tga in tgas:
        try:
            result["paa"][os.path.basename(tga)] = paa_tools.tga_to_paa(
                tga, imagetopaa_exe=(args.imagetopaa or None), config_path=args.config)
        except Exception as e:
            result["errors"].append(f"{os.path.basename(tga)}: {e}")
    return result


def build_parser():
    p = argparse.ArgumentParser(description="RwG PBR -> DayZ texture converter (headless).")
    p.add_argument("--basecolor")
    p.add_argument("--normal")
    p.add_argument("--roughness")
    p.add_argument("--metallic")
    p.add_argument("--ao")
    p.add_argument("--spec-map", dest="spec_map",
                   help="Painter Specular map for _smdi green (spec/gloss mode).")
    p.add_argument("--gloss-map", dest="gloss_map",
                   help="Painter Glossiness map for _smdi blue (spec/gloss mode).")
    p.add_argument("--output")
    p.add_argument("--prefix")
    p.add_argument("--co-mode", default="base_color",
                   choices=["base_color", "base_color_specular"])
    p.add_argument("--normal-format", default="opengl", choices=["opengl", "directx"])
    p.add_argument("--invert-ao", action="store_true")
    p.add_argument("--spec", type=float, default=1.0)
    p.add_argument("--gloss", type=float, default=1.0)
    p.add_argument("--resolution", type=int, default=1024)
    p.add_argument("--co-res", type=int)
    p.add_argument("--nohq-res", type=int)
    p.add_argument("--smdi-res", type=int)
    p.add_argument("--as-res", type=int)
    p.add_argument("--paa", action="store_true")
    p.add_argument("--imagetopaa", default="")
    p.add_argument("--rvmat", action="store_true")
    p.add_argument("--preset", default="Default")
    p.add_argument("--drive", default="P:\\")
    p.add_argument("--config", default="config.cfg")
    p.add_argument("--paa-folder", help="Convert every .tga in this folder to .paa "
                                        "and exit (ignores the PBR inputs).")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.paa_folder:
        result = run_folder_to_paa(args)
    else:
        if not args.output or not args.prefix:
            print(json.dumps({"errors": ["--output and --prefix are required."]}))
            return 1
        result = run(args)
    print(json.dumps(result, indent=2))
    ok = result.get("tga") or result.get("paa")
    return 0 if ok else (1 if result.get("errors") else 0)


if __name__ == "__main__":
    sys.exit(main())
