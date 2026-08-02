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
            co_res = _res(args.co_res, args.resolution)
            if args.co_alpha:
                # same colour source as _co, but with an Opacity alpha -> _ca
                result["tga"]["_ca"] = conversion.convert_ca_texture(
                    args.basecolor, args.co_opacity, out("_ca"), co_res)
            else:
                use_spec = args.co_mode == "base_color_specular"
                result["tga"]["_co"] = conversion.convert_co_texture(
                    args.basecolor, args.metallic, out("_co"), use_spec, co_res)
        except Exception as e:
            result["errors"].append(f"_co/_ca: {e}")

    if args.normal:
        try:
            result["tga"]["_nohq"] = conversion.convert_nohq_texture(
                args.normal, out("_nohq"), args.normal_format,
                _res(args.nohq_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_nohq: {e}")

    smdi_mode = args.smdi_mode
    smdi_res = _res(args.smdi_res, args.resolution)
    try:
        if smdi_mode == "pbr":
            if args.metallic and args.roughness and args.smdi_basecolor:
                result["tga"]["_smdi"] = conversion.convert_smdi_pbr(
                    args.metallic, args.roughness, args.smdi_basecolor,
                    out("_smdi"), args.spec, args.gloss, smdi_res)
            else:
                result["errors"].append("_smdi (pbr): needs metallic + roughness "
                                        "+ base colour.")
        elif smdi_mode == "metrough":
            if args.metallic and args.roughness:
                result["tga"]["_smdi"] = conversion.convert_smdi_texture(
                    args.metallic, args.roughness, out("_smdi"),
                    args.spec, args.gloss, smdi_res)
            else:
                result["errors"].append("_smdi (metrough): needs metallic + roughness.")
        elif smdi_mode == "specgloss":
            if args.spec_map and args.gloss_map:
                result["tga"]["_smdi"] = conversion.convert_smdi_direct(
                    args.spec_map, args.gloss_map, out("_smdi"),
                    args.spec, args.gloss, smdi_res)
            else:
                result["errors"].append("_smdi (specgloss): needs spec + gloss maps.")
        else:  # auto - back-compatible inference
            if args.spec_map and args.gloss_map:
                result["tga"]["_smdi"] = conversion.convert_smdi_direct(
                    args.spec_map, args.gloss_map, out("_smdi"),
                    args.spec, args.gloss, smdi_res)
            elif args.metallic and args.roughness:
                result["tga"]["_smdi"] = conversion.convert_smdi_texture(
                    args.metallic, args.roughness, out("_smdi"),
                    args.spec, args.gloss, smdi_res)
            elif args.roughness:
                result["errors"].append("_smdi: roughness given without metallic.")
    except Exception as e:
        result["errors"].append(f"_smdi: {e}")

    if args.ao:
        try:
            result["tga"]["_as"] = conversion.convert_as_texture(
                args.ao, out("_as"), args.invert_ao,
                _res(args.as_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_as: {e}")

    if args.emissive:
        try:
            result["tga"]["_em"] = conversion.convert_em_texture(
                args.emissive, out("_em"), _res(args.em_res, args.resolution))
        except Exception as e:
            result["errors"].append(f"_em: {e}")

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


def run_estimate_fresnel(args):
    """Estimate a representative Fresnel N/K from a metalness/roughness project.

    Reads the base colour + metallic, averages the (linearised) base-colour
    luminance over the metallic texels to get F0, then fixes N = 1.0 and solves
    the conductor Fresnel for K so the curve hits that F0 at normal incidence.
    Falls back to a dielectric (N = 1.5, K = 0) when there is no metal.
    """
    import numpy as np
    from PIL import Image
    res = {"n": 1.5, "k": 0.0, "f0": 0.04, "metal_fraction": 0.0, "errors": []}
    try:
        if not (args.basecolor and args.metallic):
            res["errors"].append("estimate-fresnel needs --basecolor and --metallic.")
            return res
        base = np.asarray(Image.open(args.basecolor).convert("RGB"), np.float32) / 255.0
        base_lin = conversion._srgb_to_linear(base)
        lum = (0.2126 * base_lin[..., 0] + 0.7152 * base_lin[..., 1]
               + 0.0722 * base_lin[..., 2])
        metal = np.asarray(Image.open(args.metallic).convert("L"), np.float32) / 255.0
        mask = metal > 0.5
        frac = float(mask.mean())
        res["metal_fraction"] = round(frac, 4)
        if frac > 0.001:
            f0 = min(0.999, max(0.0, float(lum[mask].mean())))
            n = 1.0
            k = float(np.sqrt(max(0.0, (f0 * (n + 1) ** 2 - (n - 1) ** 2) / (1.0 - f0))))
            res["n"], res["k"], res["f0"] = round(n, 3), round(k, 3), round(f0, 4)
        else:
            s = 0.04 ** 0.5
            res["n"], res["k"], res["f0"] = round((1 + s) / (1 - s), 3), 0.0, 0.04
    except Exception as e:
        res["errors"].append(str(e))
    return res


def run_estimate_material(args):
    """Estimate specularPower (from roughness) and/or emmisive (from an emissive
    channel). specularPower uses a Blinn-Phong-style heuristic mapped into the
    usual DayZ range: power = 2 ** (glossiness * 10), clamped 1..512 (gloss 0.5
    -> ~32, matching the Default preset). It is a starting point, not official.
    """
    import numpy as np
    from PIL import Image
    res = {"specular_power": None, "emmisive": None, "has_emissive": False,
           "avg_roughness": None, "avg_color": None, "errors": []}
    try:
        if args.basecolor:
            base = np.asarray(Image.open(args.basecolor).convert("RGB"), np.float32) / 255.0
            lin = conversion._srgb_to_linear(base)
            res["avg_color"] = [round(float(lin[..., c].mean()), 3) for c in range(3)] + [1.0]
        if args.roughness:
            rough = np.asarray(Image.open(args.roughness).convert("L"), np.float32) / 255.0
            gloss = 1.0 - float(rough.mean())
            res["avg_roughness"] = round(float(rough.mean()), 4)
            power = 2.0 ** (gloss * 10.0)
            res["specular_power"] = float(round(min(512.0, max(1.0, power)), 1))
        if args.emissive:
            em = np.asarray(Image.open(args.emissive).convert("RGB"), np.float32) / 255.0
            lum = 0.2126 * em[..., 0] + 0.7152 * em[..., 1] + 0.0722 * em[..., 2]
            mask = lum > 0.02
            if float(mask.mean()) > 0.0005:
                rgb = [round(float(em[..., c][mask].mean()), 3) for c in range(3)]
                res["emmisive"] = rgb + [1.0]
                res["has_emissive"] = True
            else:
                res["emmisive"] = [0.0, 0.0, 0.0, 0.0]
                res["has_emissive"] = False
    except Exception as e:
        res["errors"].append(str(e))
    return res


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
    p.add_argument("--smdi-mode", dest="smdi_mode", default="auto",
                   choices=["auto", "specgloss", "metrough", "pbr"],
                   help="How to build _smdi. auto = infer from the maps given.")
    p.add_argument("--smdi-basecolor", dest="smdi_basecolor",
                   help="Raw base colour for the 'pbr' _smdi method (metal F0).")
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
    p.add_argument("--estimate-fresnel", dest="estimate_fresnel", action="store_true",
                   help="Estimate Fresnel N/K from --basecolor + --metallic and exit.")
    p.add_argument("--estimate-material", dest="estimate_material", action="store_true",
                   help="Estimate specularPower (--roughness) / emmisive (--emissive) and exit.")
    p.add_argument("--emissive", help="Emissive channel: material estimate, and "
                                      "the source for the _em map export.")
    p.add_argument("--em-res", dest="em_res", type=int)
    p.add_argument("--co-alpha", dest="co_alpha", action="store_true",
                   help="Export the colour map as _ca (colour + alpha) instead of _co.")
    p.add_argument("--co-opacity", dest="co_opacity", help="Opacity channel -> _ca alpha.")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.estimate_fresnel:
        print(json.dumps(run_estimate_fresnel(args), indent=2))
        return 0
    if args.estimate_material:
        print(json.dumps(run_estimate_material(args), indent=2))
        return 0
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
