"""
Shared RVMAT writer for the RwG toolchain.

This module is the single source of truth for the DayZ / Enfusion "Super"
shader .rvmat format. Both the RwG Texture Converter and the RwG RVMAT Creator
import it, so the material format only ever lives in one place.

Stage layout (Super shader):

    Stage1 = NOHQ    (normal map)          <- Texture Converter _nohq
    Stage2 = DT      (detail)
    Stage3 = MC      (macro)
    Stage4 = AS      (ambient shadow)       <- Texture Converter _as
    Stage5 = SMDI    (specular map)         <- Texture Converter _smdi
    Stage6 = FRESNEL (procedural)
    Stage7 = ENV     (environment map)

Note: _co (color) is intentionally NOT a stage - it is assigned on the model,
not inside the material.
"""

import os
import re


# Default procedural textures used when no real map is supplied. These match
# the values the RVMAT Creator has always written, so output stays identical.
DEFAULT_TEXTURES = {
    "NOHQ": "#(argb,8,8,3)color(0.5,0.5,1,1,NOHQ)",
    "DT": "#(argb,8,8,3)color(0.5,0.5,0.5,1,DT)",
    "MC": "#(argb,8,8,3)color(0,0,0,0,MC)",
    "AS": "#(argb,8,8,3)color(1,1,1,1,AS)",
    "SMDI": "#(argb,8,8,3)color(1,1,1,1,SMDI)",
    "FRESNEL": "#(ai,64,64,1)fresnel(0.4,0.2)",
    "ENV": "dz\\data\\data\\env_land_co.paa",
}

STAGE_ORDER = ["NOHQ", "DT", "MC", "AS", "SMDI", "FRESNEL", "ENV"]


# Material presets: ambient, diffuse, forcedDiffuse, emmisive, specular (RGBA),
# specularPower, fresnel and env. Ported verbatim from the RVMAT Creator so the
# two tools share one preset table.
MATERIAL_PRESETS = {
    "Default": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0, 0, 0, 1), "specularPower": 30.0,
        "fresnel": "#(ai,64,64,1)fresnel(0.4,0.2)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Rubber": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 0), "emmisive": (0, 0, 0, 0),
        "specular": (0.05, 0.05, 0.05, 1), "specularPower": 8.0,
        "fresnel": "#(ai,64,64,1)fresnel(3.48,0.03)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Gold": {
        # fresnel N/K corrected to the BI Super shader reference (Gold: 0.3, 3)
        "ambient": (0, 0, 0, 0), "diffuse": (0.20784314, 0.17254902, 0.050980393, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.83529413, 0.81568629, 0.18431373, 1), "specularPower": 800.0,
        "fresnel": "#(ai,64,64,1)fresnel(0.3,3)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Iron": {
        # fresnel N/K corrected to the BI Super shader reference (Iron: 3.12, 3.87)
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 0), "emmisive": (0, 0, 0, 0),
        "specular": (0.4, 0.38, 0.36, 1), "specularPower": 60.0,
        "fresnel": "#(ai,64,64,1)fresnel(3.12,3.87)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Plastic": {
        "ambient": (0, 0, 0, 0), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 0), "emmisive": (0, 0, 0, 0),
        "specular": (0.09, 0.09, 0.09, 1), "specularPower": 35.0,
        "fresnel": "#(ai,64,64,1)fresnel(1.5,1.22)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Wood": {
        "ambient": (0, 0, 0, 0), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 0), "emmisive": (0, 0, 0, 0),
        "specular": (0.16, 0.16, 0.16, 1), "specularPower": 45.0,
        "fresnel": "#(ai,64,64,1)fresnel(1.5,0.45)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Cloth": {
        "ambient": (0, 0, 0, 0), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 0), "emmisive": (0, 0, 0, 0),
        "specular": (0.01, 0.01, 0.01, 1), "specularPower": 2.0,
        "fresnel": "#(ai,64,64,1)fresnel(3.7,2.2)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Car Paint New": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 1),
        "specular": (0.7, 0.7, 0.7, 1), "specularPower": 172.0,
        "fresnel": "#(ai,64,64,1)fresnel(1.1,0.3)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Car Paint Matte": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 1),
        "specular": (0.3, 0.3, 0.3, 1), "specularPower": 32.0,
        "fresnel": "#(ai,64,64,1)fresnel(1.1,0.3)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    # ----- metals, fresnel N/K from the BI Super shader reference table ----- #
    "Aluminum": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.91, 0.92, 0.92, 1), "specularPower": 220.0,
        "fresnel": "#(ai,64,64,1)fresnel(1.3,7)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Copper": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.95, 0.64, 0.54, 1), "specularPower": 200.0,
        "fresnel": "#(ai,64,64,1)fresnel(2.08,7.15)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Silver": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.97, 0.96, 0.91, 1), "specularPower": 300.0,
        "fresnel": "#(ai,64,64,1)fresnel(0.2,3)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Steel": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.56, 0.57, 0.58, 1), "specularPower": 180.0,
        "fresnel": "#(ai,64,64,1)fresnel(3.12,3.87)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Titanium": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.76, 0.73, 0.69, 1), "specularPower": 250.0,
        "fresnel": "#(ai,64,64,1)fresnel(3.21,4.01)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Nickel": {
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.83, 0.80, 0.75, 1), "specularPower": 260.0,
        "fresnel": "#(ai,64,64,1)fresnel(2.59,4.55)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Chrome": {
        # chromium is not in the BI table; N/K approximated (~3.0 / 3.3)
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.90, 0.91, 0.92, 1), "specularPower": 600.0,
        "fresnel": "#(ai,64,64,1)fresnel(3.0,3.3)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
    "Glass": {
        # dielectric: N ~ 1.5, K ~ 0
        "ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
        "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
        "specular": (0.25, 0.25, 0.25, 1), "specularPower": 400.0,
        "fresnel": "#(ai,64,64,1)fresnel(1.5,0.0)",
        "env": "dz\\data\\data\\env_land_co.paa",
    },
}


def _fmt_vec(vec):
    """Format an RGBA sequence the way the original tool did (bare Python str)."""
    return ",".join(str(v) for v in vec)


def _stage_block(stage_number, texture_value):
    """One Stage{n} block. Byte-identical to the RVMAT Creator's output."""
    return (
        f"\nclass Stage{stage_number}\n"
        "{\n"
        f'    texture="{texture_value}";\n'
        '    uvSource="tex";\n'
        "    class uvTransform\n"
        "    {\n"
        "        aside[]={1,0,0};\n"
        "        up[]={0,1,0};\n"
        "        dir[]={0,0,0};\n"
        "        pos[]={0,0,0};\n"
        "    };\n"
        "};\n"
    )


def build_rvmat(nohq=None, dt=None, mc=None, as_map=None, smdi=None,
                fresnel=None, env=None,
                ambient=(1, 1, 1, 1), diffuse=(1, 1, 1, 1),
                forced_diffuse=(0, 0, 0, 1), emmisive=(0, 0, 0, 0),
                specular=(0, 0, 0, 1), specular_power=30.0):
    """
    Build the full .rvmat text. Any texture argument left as None falls back to
    the documented default procedural texture for that stage.
    """
    textures = {
        "NOHQ": nohq if nohq else DEFAULT_TEXTURES["NOHQ"],
        "DT": dt if dt else DEFAULT_TEXTURES["DT"],
        "MC": mc if mc else DEFAULT_TEXTURES["MC"],
        "AS": as_map if as_map else DEFAULT_TEXTURES["AS"],
        "SMDI": smdi if smdi else DEFAULT_TEXTURES["SMDI"],
        "FRESNEL": fresnel if fresnel else DEFAULT_TEXTURES["FRESNEL"],
        "ENV": env if env else DEFAULT_TEXTURES["ENV"],
    }

    content = (
        f"\nambient[]={{{_fmt_vec(ambient)}}};\n"
        f"diffuse[]={{{_fmt_vec(diffuse)}}};\n"
        f"forcedDiffuse[]={{{_fmt_vec(forced_diffuse)}}};\n"
        f"emmisive[]={{{_fmt_vec(emmisive)}}};\n"
        f"specular[]={{{_fmt_vec(specular)}}};\n"
        f"specularPower={specular_power};\n"
        'PixelShaderID="Super";\n'
        'VertexShaderID="Super";\n'
    )

    for i, key in enumerate(STAGE_ORDER, start=1):
        content += _stage_block(i, textures[key])

    return content


def write_rvmat(output_path, **kwargs):
    """Build and write an .rvmat file. kwargs are forwarded to build_rvmat()."""
    content = build_rvmat(**kwargs)
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(content)
    return output_path


_STAGE_NAMES = {"1": "NOHQ", "2": "DT", "3": "MC", "4": "AS",
                "5": "SMDI", "6": "FRESNEL", "7": "ENV"}


def parse_rvmat(text):
    """
    Read an .rvmat back into a summary dict (used to sync changes made in an
    external editor back into the plugin). Returns material vectors, specular
    power and the per-stage texture strings.
    """
    def vec(name):
        m = re.search(name + r"\[\]=\{([^}]+)\};", text)
        return m.group(1).strip() if m else None

    sp = re.search(r"specularPower\s*=\s*([\d.]+);", text)
    stages = dict(re.findall(r'class Stage(\d+)\s*\{\s*texture="([^"]+)"', text))
    textures = {_STAGE_NAMES.get(k, k): v for k, v in stages.items()}
    return {
        "ambient": vec("ambient"),
        "diffuse": vec("diffuse"),
        "forcedDiffuse": vec("forcedDiffuse"),
        "emmisive": vec("emmisive"),
        "specular": vec("specular"),
        "specularPower": sp.group(1) if sp else None,
        "textures": textures,
    }


def apply_preset_to_rvmat(text, preset_name):
    """
    Apply a material preset to an EXISTING .rvmat, changing ONLY the material
    values (ambient / diffuse / forcedDiffuse / emmisive / specular /
    specularPower) and the Stage6 fresnel texture. All texture stages
    (NOHQ / DT / MC / AS / SMDI / ENV) and their paths are left untouched.
    """
    p = MATERIAL_PRESETS.get(preset_name, MATERIAL_PRESETS["Default"])

    for name, key in (("ambient", "ambient"), ("diffuse", "diffuse"),
                      ("forcedDiffuse", "forcedDiffuse"), ("emmisive", "emmisive"),
                      ("specular", "specular")):
        text = re.sub(r"(?m)^" + name + r"\[\]=\{[^}]*\};",
                      name + "[]={" + _fmt_vec(p[key]) + "};", text, count=1)

    text = re.sub(r"(?m)^specularPower\s*=\s*[\d.]+;",
                  "specularPower=" + str(p["specularPower"]) + ";", text, count=1)

    # Stage6 = fresnel. Replace only its texture value.
    text = re.sub(r'(class Stage6\s*\{\s*texture=")[^"]*(")',
                  lambda m: m.group(1) + p["fresnel"] + m.group(2), text, count=1)
    return text


def build_rvmat_from_preset(preset_name="Default", nohq=None, dt=None, mc=None,
                            as_map=None, smdi=None):
    """
    Convenience wrapper: take the material values from a named preset and
    combine them with the given texture maps (typically the ones the Texture
    Converter just produced).
    """
    p = MATERIAL_PRESETS.get(preset_name, MATERIAL_PRESETS["Default"])
    return build_rvmat(
        nohq=nohq, dt=dt, mc=mc, as_map=as_map, smdi=smdi,
        fresnel=p["fresnel"], env=p["env"],
        ambient=p["ambient"], diffuse=p["diffuse"],
        forced_diffuse=p["forcedDiffuse"], emmisive=p["emmisive"],
        specular=p["specular"], specular_power=p["specularPower"],
    )
