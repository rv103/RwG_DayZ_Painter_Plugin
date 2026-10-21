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

# DayZ environment maps shipped under dz\data\data (Stage7 ENV). Ordered so the
# common "Land" default sits near the top; the plugin uses these as a dropdown.
ENV_MAPS = [
    "dz\\data\\data\\env_land_co.paa",
    "dz\\data\\data\\env_co.paa",
    "dz\\data\\data\\env2_co.paa",
    "dz\\data\\data\\env03_co.paa",
    "dz\\data\\data\\env_land_chrome_co.paa",
    "dz\\data\\data\\env_land_eye_co.paa",
    "dz\\data\\data\\env_land_optic_co.paa",
    "dz\\data\\data\\env_land_orange_co.paa",
    "dz\\data\\data\\env_land_plastic_co.paa",
    "dz\\data\\data\\env_land_seattle_co.paa",
    "dz\\data\\data\\env_lake_co.paa",
    "dz\\data\\data\\env_inter_hotel_co.paa",
    "dz\\data\\data\\env_mirror_co.paa",
    "dz\\data\\data\\env_chrome_co.paa",
    "dz\\data\\data\\env_ocean_co.paa",
    "dz\\data\\data\\env_sea_co.paa",
    "dz\\data\\data\\env_roughness_co.paa",
    "dz\\data\\data\\env_skin_co.paa",
    "dz\\data\\data\\env_skin_dark_co.paa",
    "dz\\data\\data\\env_skyline_day_co.paa",
    "dz\\data\\data\\env_bathroom_co.paa",
    "dz\\data\\data\\env_cloth_green_co.paa",
    "dz\\data\\data\\env_cloth_neutral_co.paa",
]


# Damage-variant macro (_mc) textures, ported from the RwG RVMat Speedo tool.
# Each category maps to a list of (label, mc_texture, suffix): generating a
# variant re-uses the base rvmat and only swaps Stage3 (MC) to this texture,
# saved as <prefix><suffix>.rvmat.
DAMAGE_MC = {
    "Generic": [
        ("Worn", "dz\\characters\\data\\generic_worn_mc.paa", "_worn"),
        ("Damage", "dz\\characters\\data\\generic_damage_mc.paa", "_damage"),
        ("Destruct", "dz\\characters\\data\\generic_destruct_mc.paa", "_destruct"),
    ],
    "Wood": [
        ("Worn", "dz\\characters\\data\\generic_wood_worn_mc.paa", "_worn"),
        ("Damage", "dz\\characters\\data\\generic_wood_damage_mc.paa", "_damage"),
        ("Destruct", "dz\\characters\\data\\generic_wood_destruct_mc.paa", "_destruct"),
    ],
    "Food": [
        ("Burn", "dz\\gear\\food\\data\\food_generic_burn_mc.paa", "_burnt"),
        ("Rotten", "dz\\gear\\food\\data\\food_generic_rot_mc.paa", "_rotten"),
        ("Rotten2", "dz\\gear\\food\\data\\food_generic_rot2_mc.paa", "_rotten"),
    ],
    "Weapons Generic": [
        ("Damage", "dz\\weapons\\data\\weapons_damage_generic_mc.paa", "_damage"),
        ("Destruct", "dz\\weapons\\data\\weapons_destruct_generic_mc.paa", "_destruct"),
    ],
    "Weapons Metal": [
        ("Damage", "dz\\weapons\\data\\weapons_damage_metal_mc.paa", "_damage"),
        ("Destruct", "dz\\weapons\\data\\weapons_destruct_metal_mc.paa", "_destruct"),
    ],
    "Weapons Wood": [
        ("Damage", "dz\\weapons\\data\\weapons_damage_wood_mc.paa", "_damage"),
        ("Destruct", "dz\\weapons\\data\\weapons_destruct_wood_mc.paa", "_destruct"),
    ],
    "Plastic": [
        ("Damage", "dz\\characters\\data\\generic_plastic_damage_mc.paa", "_damage"),
    ],
    "Cloth Tops": [
        ("Damage", "dz\\characters\\tops\\data\\tops_damage_mc.paa", "_damage"),
        ("Destruct", "dz\\characters\\tops\\data\\tops_destruct_mc.paa", "_destruct"),
    ],
    "Cloth Vests": [
        ("Damage", "dz\\characters\\vests\\data\\vests_damage_mc.paa", "_damage"),
        ("Destruct", "dz\\characters\\vests\\data\\vests_destruct_mc.paa", "_destruct"),
    ],
    "Cloth Pants": [
        ("Damage", "dz\\characters\\pants\\data\\pants_damage_mc.paa", "_damage"),
        ("Destruct", "dz\\characters\\pants\\data\\pants_destruct_mc.paa", "_destruct"),
    ],
    "Cloth Shoes": [
        ("Damage", "dz\\characters\\shoes\\data\\shoes_damage_mc.paa", "_damage"),
        ("Destruct", "dz\\characters\\shoes\\data\\shoes_destruct_mc.paa", "_destruct"),
    ],
}


# Material presets: ambient, diffuse, forcedDiffuse, emmisive, specular (RGBA),
# specularPower, fresnel and env.
#
# Checked against the Super shader (RenderDoc-verified rebuild, DayZ Shader project)
# and the vanilla rvmats (~3400 Super rvmats in weapons/gear/characters):
#   * ambient[] x sky is the whole ambient light and diffuse[] scales the direct
#     light of the entire material - both stay 1 (vanilla: ~80 % use 1,1,1,1).
#     The colour lives in _co; 0 would leave the material black in shade.
#   * reflection = _smdi G x fresnel(N,K) x specular[]. The plugin's _smdi sets G so
#     that G x fresnel already gives the pixel's F0 - specular[] must therefore not
#     carry F0 again: white for non-metals, only the HUE (brightest channel 1) for
#     coloured metals.
#   * specularPower <= 400: the highlight stops getting brighter at ~219, and _smdi
#     B (= exponent / specularPower) is 5-bit in game - higher values crush rough
#     areas to B = 0. Use the estimate button to fit it to the roughness.
#   * fresnel: metals = complex-IOR N/K (F0 = their reflectance); non-metals N 1.5,
#     K 0 (F0 0.04, the physical curve) - also the best _smdi G precision.
_ENV = "dz\\data\\data\\env_land_co.paa"


def _preset(specular, power, n, k):
    return {"ambient": (1, 1, 1, 1), "diffuse": (1, 1, 1, 1),
            "forcedDiffuse": (0, 0, 0, 1), "emmisive": (0, 0, 0, 0),
            "specular": specular, "specularPower": float(power),
            "fresnel": f"#(ai,64,64,1)fresnel({n},{k})", "env": _ENV}


_WHITE = (1, 1, 1, 1)

MATERIAL_PRESETS = {
    # BI's default fresnel (F0 0.2): fits mixed texture sets up to F0 0.2.
    "Default":         _preset(_WHITE, 30, 0.4, 0.2),
    # ----- non-metals: specular white, fresnel N 1.5 / K 0 (F0 0.04) ----- #
    "Rubber":          _preset(_WHITE, 8, 1.5, 0),
    "Plastic":         _preset(_WHITE, 35, 1.5, 0),
    "Wood":            _preset(_WHITE, 45, 1.5, 0.45),          # F0 0.07, slightly flatter curve
    "Cloth":           _preset(_WHITE, 4, 1.5, 0),
    "Car Paint New":   _preset(_WHITE, 172, 1.5, 0),            # clear coat
    "Car Paint Matte": _preset(_WHITE, 32, 1.5, 0),
    "Glass":           _preset(_WHITE, 400, 1.5, 0),
    # ----- metals: N/K from the BI Super shader table, specular = hue only ----- #
    "Gold":            _preset((1.0, 0.78, 0.34, 1), 400, 0.3, 3),
    "Iron":            _preset((0.97, 0.98, 1.0, 1), 60, 3.12, 3.87),
    "Aluminum":        _preset((0.99, 1.0, 1.0, 1), 220, 1.3, 7),
    "Copper":          _preset((1.0, 0.67, 0.57, 1), 200, 2.08, 7.15),
    # copper-zinc alloy, between copper (redder) and gold; good for cartridge cases
    "Brass":           _preset((1.0, 0.81, 0.46, 1), 200, 0.44, 3.0),
    "Silver":          _preset((1.0, 0.99, 0.94, 1), 300, 0.2, 3),
    "Steel":           _preset((0.97, 0.98, 1.0, 1), 180, 3.12, 3.87),
    "Titanium":        _preset((1.0, 0.96, 0.91, 1), 250, 3.21, 4.01),
    "Nickel":          _preset((1.0, 0.96, 0.90, 1), 260, 2.59, 4.55),
    # chromium is not in the BI table; N/K approximated (~3.0 / 3.3)
    "Chrome":          _preset((0.98, 0.99, 1.0, 1), 400, 3.0, 3.3),
}


# --------------------------------------------------------------------------- #
#  Fresnel material library (N/K + specular tint)                              #
# --------------------------------------------------------------------------- #
def fresnel_f0(n, k=0.0):
    """Reflectance at normal incidence from a complex index of refraction.
    Dielectric (k=0): ((n-1)/(n+1))^2. Metals include the absorption k."""
    try:
        n = float(n); k = float(k)
    except (TypeError, ValueError):
        return 0.04
    num = (n - 1.0) ** 2 + k * k
    den = (n + 1.0) ** 2 + k * k
    return num / den if den else 0.0


def _fresnel_nk_from_texture(fresnel_texture):
    """Pull the scalar (N, K) out of a '#(ai,..)fresnel(N,K)' texture string."""
    m = re.search(r"fresnel\(([^,]+),([^)]+)\)", fresnel_texture or "")
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    return 1.5, 0.0


# Metals whose DayZ-correct (BI Super shader) N/K + specular already live in the
# preset table - reused here so the library stays consistent with the presets.
_PRESET_FRESNEL_NAMES = ("Gold", "Iron", "Aluminum", "Copper", "Brass", "Silver",
                         "Steel", "Titanium", "Nickel", "Chrome")

# Extra materials NOT in the preset table. N/K are representative visible-band
# values from refractiveindex.info (single scalar for the DayZ fresnel stage).
# specular[] is only the HUE of a coloured metal (brightest channel 1) and white
# otherwise: the fresnel stage and the _smdi G already carry the reflectance, so a
# grey F0 in specular[] would apply it twice. Dielectrics have K = 0, so their look
# rides on N -> a low F0 (glass 0.04, MgO ~0.073, diamond ~0.17).
FRESNEL_EXTRA = {
    # --- additional metals / alloys ---
    "Bronze":          {"n": 1.18, "k": 3.5, "specular": (1.0, 0.71, 0.46, 1)},
    "Zinc":            {"n": 1.0,  "k": 5.0, "specular": (0.94, 0.98, 1.0, 1)},
    "Tin":             {"n": 1.5,  "k": 5.0, "specular": (1.0, 0.99, 0.94, 1)},
    "Lead":            {"n": 2.0,  "k": 3.4, "specular": (0.95, 0.95, 1.0, 1)},
    "Platinum":        {"n": 2.33, "k": 4.0, "specular": (1.0, 0.96, 0.87, 1)},
    "Cobalt":          {"n": 2.2,  "k": 4.0, "specular": (1.0, 1.0, 0.97, 1)},
    "Tungsten":        {"n": 3.6,  "k": 2.8, "specular": _WHITE},
    # --- dielectrics (K = 0; F0 comes from N) ---
    "Glass (n1.5)":    {"n": 1.5,  "k": 0.0, "specular": _WHITE},
    "Water (n1.33)":   {"n": 1.33, "k": 0.0, "specular": _WHITE},
    "Ice (n1.31)":     {"n": 1.31, "k": 0.0, "specular": _WHITE},
    "MgO (n1.74)":     {"n": 1.74, "k": 0.0, "specular": _WHITE},
    "Sapphire (n1.77)": {"n": 1.77, "k": 0.0, "specular": _WHITE},
    "Quartz (n1.55)":  {"n": 1.55, "k": 0.0, "specular": _WHITE},
    "Diamond (n2.42)": {"n": 2.42, "k": 0.0, "specular": _WHITE},
}


def fresnel_materials():
    """Ordered {name: {n, k, specular}} library for the plugin's N/K picker:
    the preset metals (BI-correct) first, then the extra metals + dielectrics."""
    out = {}
    for name in _PRESET_FRESNEL_NAMES:
        p = MATERIAL_PRESETS.get(name)
        if not p:
            continue
        n, k = _fresnel_nk_from_texture(p.get("fresnel"))
        out[name] = {"n": n, "k": k, "specular": p.get("specular", (1, 1, 1, 1))}
    out.update(FRESNEL_EXTRA)
    return out


# --------------------------------------------------------------------------- #
#  Fresnel reference library (community N/K table)                             #
# --------------------------------------------------------------------------- #
# A broad reference of commonly-used refractive values (N) and absorption (K)
# for DayZ rvmat fresnel stages, grouped by category, each with a short look
# note so you can match your texture maps. This is a *reference* table shown in
# its own picker - it does NOT replace the curated BI-correct preset metals
# above (their N/K come from the BI Super shader reference and can differ).
#
# Credit: shared by the community (thanks to @|RaG| Tyson for highlighting how
# much the fresnel value matters). N/K are representative, not lab-exact -
# treat them as tuned starting points. BI reference:
#   https://community.bistudio.com/wiki/Super_shader
#
# Structure: [(category, [(name, n, k, description), ...]), ...]
FRESNEL_REFERENCE = [
    ("Construction & Terrain", [
        ("Concrete (dry)", 1.52, 0.07, "Matte, light gray; slightly porous, low reflection"),
        ("Concrete (wet)", 1.55, 0.09, "Darker, glossy patches; moist, shallow reflection"),
        ("Cement Paste (fresh)", 1.53, 0.06, "Damp, smooth, slightly reflective"),
        ("Asphalt (dry)", 1.60, 0.10, "Rough, dark gray; moderate reflection on flat angles"),
        ("Asphalt (wet)", 1.65, 0.13, "Shiny, dark, strong specular spots"),
        ("Brick (old)", 1.58, 0.07, "Matte, dusty; low reflectivity"),
        ("Brick (new)", 1.60, 0.05, "Slightly smoother, semi-matte surface"),
        ("Terracotta", 1.56, 0.05, "Warm red-orange, matte, porous texture"),
        ("Clay (dry)", 1.54, 0.05, "Light tan, powdery matte finish"),
        ("Clay (wet)", 1.57, 0.08, "Darker brown, glossy and sticky appearance"),
        ("Mud (wet)", 1.60, 0.09, "Wet, reflective, soft surface with depth"),
        ("Soil (dry)", 1.52, 0.06, "Matte, granular, earthy tone"),
        ("Soil (moist)", 1.55, 0.09, "Slightly glossy, darkened color"),
        ("Gravel", 1.58, 0.06, "Mixed reflection, semi-matte"),
        ("Rock (granite)", 1.60, 0.02, "Hard, slightly speckled, low gloss"),
        ("Rock (limestone)", 1.63, 0.00, "Light surface, minimal absorption, matte"),
        ("Slate", 1.61, 0.05, "Smooth, gray-black, subtle sheen"),
        ("Moss-covered stone", 1.50, 0.10, "Dull, uneven gloss, soft diffuse reflection"),
        ("Wet road (asphalt)", 1.66, 0.13, "Glossy wet specular; mirror-like patches"),
        ("Puddle water (on asphalt)", 1.333, 0.00, "Transparent thin layer; strong reflections"),
    ]),
    ("Organic & Natural", [
        ("Wood (dry pine)", 1.53, 0.03, "Light, fibrous, matte"),
        ("Wood (wet oak)", 1.56, 0.08, "Glossy, darker wood grain visible"),
        ("Bark (dry)", 1.54, 0.04, "Rough, fibrous, matte"),
        ("Bark (wet)", 1.57, 0.08, "Damp, darker color, increased gloss"),
        ("Leaf (fresh)", 1.42, 0.03, "Semi-gloss green, translucent"),
        ("Leaf (dry)", 1.45, 0.06, "Brittle, matte brown surface"),
        ("Grass (fresh)", 1.44, 0.02, "Smooth sheen; bright green"),
        ("Grass (wet)", 1.47, 0.05, "Glossy; darker saturation"),
        ("Bone", 1.56, 0.01, "Hard, pale surface, slight sheen"),
        ("Skin (dry)", 1.42, 0.02, "Soft, diffuse reflection"),
        ("Skin (moist)", 1.45, 0.05, "Subtle gloss, smooth highlights"),
        ("Skin (oily/wet)", 1.47, 0.08, "Stronger specular shine; reflective patches"),
        ("Muscle tissue", 1.40, 0.05, "Deep red, semi-gloss, subsurface scattering"),
        ("Fat tissue", 1.46, 0.01, "Pale, translucent, slightly glossy"),
        ("Blood (fresh)", 1.39, 0.09, "Deep red, shiny, wet surface"),
        ("Blood (dried)", 1.45, 0.15, "Brown-red, matte, low reflection"),
        ("Flesh wound (moist)", 1.47, 0.08, "Glossy, dark red, wet sheen"),
        ("Leather (dry)", 1.55, 0.06, "Matte, textured surface"),
        ("Leather (oiled)", 1.58, 0.09, "Glossy, darkened color"),
        ("Leather (worn)", 1.56, 0.07, "Semi-gloss, aged patches"),
        ("Hair (dark)", 1.55, 0.02, "Slight sheen, soft reflections"),
        ("Hair (light/blonde)", 1.53, 0.01, "Diffuse reflection, low gloss"),
        ("Paper (white)", 1.48, 0.00, "Matte, diffuse"),
        ("Paper (aged)", 1.50, 0.02, "Yellow tint, softer reflection"),
    ]),
    ("Metals", [
        ("Iron", 2.91, 3.36, "Metallic gray, strong reflection"),
        ("Steel (polished)", 2.50, 3.10, "Bright silver, mirror finish"),
        ("Steel (brushed)", 2.40, 3.00, "Semi-gloss, linear highlights"),
        ("Steel (rusted)", 2.20, 2.10, "Matte, reddish-brown oxide layer"),
        ("Aluminum", 1.44, 7.38, "Silvery-white, strong reflectivity"),
        ("Copper", 0.64, 2.62, "Reddish metallic, moderate gloss"),
        ("Brass", 0.40, 2.90, "Yellow metallic, strong reflection"),
        ("Gold", 0.47, 2.41, "Warm metallic yellow, high reflectivity"),
        ("Silver", 0.14, 4.02, "Bright, mirror-like"),
        ("Titanium", 2.49, 3.09, "Dark gray, high reflectivity"),
        ("Zinc", 0.27, 3.67, "Dull gray metallic"),
        ("Lead", 1.92, 3.31, "Dark gray, low gloss"),
        ("Nickel", 1.92, 3.37, "Slightly yellow-silver, moderate gloss"),
        ("Chromium", 3.17, 3.32, "Hard, shiny silver"),
        ("Platinum", 2.30, 4.10, "Bright white metallic, mirror-like"),
    ]),
    ("Plastics & Synthetics", [
        ("PVC (rigid)", 1.54, 0.00, "Smooth, matte white"),
        ("ABS plastic", 1.55, 0.02, "Semi-gloss, colored surface"),
        ("Nylon", 1.53, 0.02, "Slight gloss, flexible"),
        ("Polyethylene (PE)", 1.51, 0.00, "Matte, low absorption"),
        ("Polypropylene (PP)", 1.49, 0.00, "Translucent white, soft sheen"),
        ("Polystyrene (PS)", 1.59, 0.00, "Clear, glossy plastic"),
        ("Polycarbonate (PC)", 1.586, 0.00, "Transparent, slightly glossy"),
        ("Acrylic (PMMA)", 1.490, 0.00, "Clear, glass-like transparency"),
        ("Epoxy resin (cured)", 1.55, 0.01, "Transparent, glossy"),
        ("Rubber (natural)", 1.52, 0.10, "Dull black, flexible"),
        ("Rubber (synthetic)", 1.54, 0.13, "Slight gloss, dark gray"),
        ("Carbon fiber composite", 1.90, 0.10, "Dark, semi-gloss pattern"),
        ("Fiberglass", 1.49, 0.00, "Translucent, low gloss"),
        ("Kevlar", 1.60, 0.05, "Woven texture, matte yellow"),
    ]),
    ("Industrial & Misc", [
        ("Paint (matte)", 1.50, 0.05, "Diffuse, flat finish"),
        ("Paint (glossy)", 1.55, 0.07, "Glossy, reflective"),
        ("Oily metal", 1.46, 0.10, "Reflective with smooth sheen"),
        ("Grease-coated surface", 1.47, 0.08, "Dark, oily reflection"),
        ("Rust (iron oxide)", 2.42, 2.70, "Dull red-brown metallic, low gloss"),
        ("Burnt wood (charcoal)", 1.85, 0.30, "Matte black, high absorption"),
        ("Plastic burn residue", 1.70, 0.40, "Dark glossy, irregular surface"),
        ("Glass (clear)", 1.52, 0.00, "Transparent, bright reflections"),
        ("Glass (frosted)", 1.52, 0.00, "Matte diffuse scattering"),
        ("Cracked glass", 1.52, 0.00, "Fragmented reflections"),
        ("Oil film (thin)", 1.45, 0.05, "Iridescent color shift, reflective"),
        ("Wet mud-metal mix", 1.60, 0.12, "Dark, semi-gloss, complex specular"),
    ]),
    ("Environmental", [
        ("Water (clean)", 1.333, 0.00, "Transparent, clear reflections"),
        ("Water (murky)", 1.34, 0.02, "Slight absorption, low transparency"),
        ("Snow (clean)", 1.31, 0.00, "White, diffuse scattering"),
        ("Snow (dirty)", 1.33, 0.02, "Dull brown tint, low reflectance"),
        ("Ice (clear)", 1.309, 0.00, "Transparent, smooth reflection"),
        ("Ash", 1.54, 0.10, "Gray, powdery matte"),
        ("Soot", 1.75, 0.44, "Black, strong light absorption"),
        ("Blood splatter (fresh)", 1.41, 0.07, "Glossy, deep red"),
        ("Blood splatter (dried)", 1.46, 0.15, "Matte, brown-red"),
        ("Slime / mucus", 1.40, 0.05, "Glossy, translucent wet film"),
        ("Moss (moist)", 1.45, 0.05, "Soft, green semi-gloss"),
        ("Algae (wet)", 1.42, 0.03, "Green, glossy surface"),
        ("Burnt soil", 1.58, 0.12, "Dark brown-black, low reflectance"),
    ]),
    ("Stones & Gemstones", [
        ("Diamond", 2.417, 0.00, "Colorless, very high brilliance; strong dispersion"),
        ("Cubic Zirconia", 2.17, 0.00, "Colorless, glassy; diamond simulant, high sparkle"),
        ("Sapphire (Al2O3)", 1.77, 0.00, "Transparent, hard; blue varieties common"),
        ("Ruby (Cr:Al2O3)", 1.77, 0.005, "Transparent red, slight absorption"),
        ("Emerald (beryl)", 1.58, 0.010, "Rich green, moderate absorption"),
        ("Beryl (aquamarine)", 1.57, 0.001, "Pale blue-green, very low absorption"),
        ("Topaz", 1.61, 0.002, "Transparent, various colors, low absorption"),
        ("Spinel", 1.72, 0.003, "Transparent, bright; various colors"),
        ("Tourmaline (avg)", 1.64, 0.015, "Strongly colored, dichroic; moderate absorption"),
        ("Zircon (natural)", 1.92, 0.005, "Bright, high refractive index; various colors"),
        ("Garnet (almandine)", 1.79, 0.020, "Deep red, noticeable absorption"),
        ("Garnet (pyrope)", 1.74, 0.010, "Red to pink, moderate absorption"),
        ("Peridot (olivine)", 1.65, 0.010, "Yellow-green, moderate absorption"),
        ("Jadeite (jade)", 1.66, 0.010, "Translucent green, waxy luster"),
        ("Nephrite (jade)", 1.61, 0.010, "Cream to green, fibrous; waxy luster"),
        ("Jade (generic)", 1.63, 0.010, "Translucent green, waxy luster"),
        ("Opal (precious)", 1.44, 0.000, "Translucent; play-of-color, minimal absorption"),
        ("Quartz (amethyst)", 1.55, 0.003, "Purple quartz; very low absorption"),
        ("Quartz (smoky)", 1.55, 0.005, "Brown/gray quartz; slight absorption"),
        ("Fluorite", 1.434, 0.000, "Transparent; low dispersion, soft"),
        ("Calcite", 1.49, 0.000, "Transparent; birefringent (double refraction)"),
        ("Turquoise", 1.61, 0.020, "Opaque blue-green, matte to waxy"),
        ("Obsidian (volcanic glass)", 1.50, 0.020, "Dark glass, semi-transparent edges"),
        ("Obsidian (mahogany)", 1.50, 0.025, "Dark reddish-brown glass; slight absorption"),
        ("Amber", 1.54, 0.000, "Translucent resin, warm yellow; low absorption"),
        ("Lapis Lazuli", 1.61, 0.020, "Opaque deep blue; matte to slight sheen"),
        ("Malachite", 1.66, 0.030, "Opaque green banding; strong absorption"),
        ("Agate (banded chalcedony)", 1.54, 0.002, "Translucent, waxy; banded patterns"),
        ("Onyx (black chalcedony)", 1.54, 0.010, "Opaque to translucent black; low gloss"),
        ("Jasper", 1.54, 0.015, "Opaque chalcedony; earthy colors, matte"),
        ("Moonstone (feldspar)", 1.52, 0.002, "Translucent, adularescence (sheen)"),
        ("Labradorite (feldspar)", 1.56, 0.010, "Iridescent labradorescence; semi-translucent"),
    ]),
]


def suggested_specular(n, k):
    """specular[] for a fresnel(N,K) picked from the reference table: white. The
    stage and the _smdi G already carry the reflectance (F0), so specular[] only
    tints - give a coloured metal its hue yourself (brightest channel 1)."""
    return _WHITE


def fresnel_reference_flat():
    """Flatten FRESNEL_REFERENCE to an ordered list of dicts for pickers:
    {category, name, n, k, description, f0}."""
    rows = []
    for category, items in FRESNEL_REFERENCE:
        for name, n, k, desc in items:
            rows.append({"category": category, "name": name, "n": n, "k": k,
                         "description": desc, "f0": fresnel_f0(n, k)})
    return rows


def _fmt_vec(vec):
    """Format an RGBA sequence the way the original tool did (bare Python str)."""
    return ",".join(str(v) for v in vec)


def _fmt_power(v):
    """specularPower the way DayZ Tools expects it: a whole number is written as
    an integer (15, not 15.0) so the Material Editor picks it up; genuine
    fractional values keep their decimals."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(round(f))) if abs(f - round(f)) < 1e-9 else repr(f)


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
                specular=(1, 1, 1, 1), specular_power=30.0):
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
        f"specularPower={_fmt_power(specular_power)};\n"
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


# --------------------------------------------------------------------------- #
#  RVMAT validator / linter                                                    #
# --------------------------------------------------------------------------- #
# Severities, ordered worst -> best. The UI colours by these.
SEV_ERROR = "error"   # will not work / will not load in-game
SEV_WARN = "warn"     # loads, but probably not what you want
SEV_INFO = "info"     # heads-up, usually fine
SEV_OK = "ok"         # explicit pass note

VALID_TEXTURE_EXT = (".paa", ".tga")

# Stages that normally carry a real bitmap. Stage6 (FRESNEL) is procedural by
# design, so it is not file-checked.
_REAL_STAGE_KEYS = ("NOHQ", "DT", "MC", "AS", "SMDI", "ENV")
# Which of those the game shades from a real map often enough that an all-white /
# procedural default is worth a heads-up rather than silent.
_EXPECTED_REAL_MAPS = ("NOHQ", "SMDI")


def _is_procedural_texture(tex):
    """True for inline '#(argb,..)color(..)' / '#(ai,..)fresnel(..)' textures."""
    return bool(tex) and tex.strip().startswith("#(")


def _looks_absolute_path(path):
    """DayZ texture paths must be mod-relative (no drive letter / UNC / POSIX
    root). Returns True if the path is absolute in any of those senses."""
    p = (path or "").strip()
    if not p:
        return False
    return (bool(re.match(r"^[A-Za-z]:[\\/]", p))   # P:\... , C:/...
            or p.startswith("\\\\")                  # UNC \\server\share
            or p.startswith("/"))                    # POSIX /...


def _abs_from_modrel(relpath, drive):
    """Join a mod-relative texture path onto the work drive, normalising the
    backslashes DayZ uses to this OS's separator so os.path.exists works on both
    Windows (inside Painter) and POSIX (unit tests)."""
    norm = (relpath or "").replace("\\", os.sep).replace("/", os.sep).lstrip(os.sep)
    drv = (drive or "").rstrip("\\/")
    return os.path.join(drv, norm) if drv else norm


def _sibling_with_ext(abs_path, ext):
    root, _ = os.path.splitext(abs_path)
    return root + ext


def validate_rvmat(text, drive="P:\\", check_files=True):
    """
    Lint the text of a DayZ Super-shader .rvmat and return a list of
    (severity, area, message) findings. Pure text + filesystem checks - no
    Substance Painter or paa_tools dependency, so it is unit-testable.

    drive        : the work drive texture paths are relative to (e.g. 'P:\\').
    check_files  : resolve each real texture path against the drive and report
                   missing files. Silently downgraded to a note if the drive
                   folder is not present on this machine.
    """
    findings = []

    def add(sev, area, msg):
        findings.append((sev, area, msg))

    if not (text or "").strip():
        add(SEV_ERROR, "file", "The .rvmat is empty or could not be read.")
        return findings

    # -- shader IDs ------------------------------------------------------- #
    px = re.search(r'PixelShaderID\s*=\s*"([^"]*)"', text)
    vx = re.search(r'VertexShaderID\s*=\s*"([^"]*)"', text)
    if not px:
        add(SEV_ERROR, "shader", 'No PixelShaderID - DayZ will not load this material.')
    elif px.group(1) != "Super":
        add(SEV_INFO, "shader",
            'PixelShaderID="%s" (this tool targets "Super").' % px.group(1))
    if not vx:
        add(SEV_ERROR, "shader", "No VertexShaderID - DayZ will not load this material.")
    elif vx.group(1) != "Super":
        add(SEV_INFO, "shader",
            'VertexShaderID="%s" (this tool targets "Super").' % vx.group(1))

    # -- specularPower ---------------------------------------------------- #
    if not re.search(r"specularPower\s*=\s*[\d.]+\s*;", text):
        add(SEV_WARN, "material", "specularPower is missing or non-numeric.")

    # -- stages ----------------------------------------------------------- #
    stages = dict(re.findall(r'class Stage(\d+)\s*\{\s*texture="([^"]*)"', text))
    present = set(stages.keys())
    for num, key in sorted(_STAGE_NAMES.items()):
        if num not in present:
            sev = SEV_WARN if key in _EXPECTED_REAL_MAPS else SEV_INFO
            add(sev, "Stage%s/%s" % (num, key),
                "Stage%s (%s) is missing - the shader falls back to its default."
                % (num, key))
    extra = sorted(n for n in present if n not in _STAGE_NAMES)
    for n in extra:
        add(SEV_INFO, "Stage%s" % n,
            "Stage%s is beyond the 7 Super-shader stages - ignored in-game." % n)

    # -- per-stage texture paths ----------------------------------------- #
    drive_ok = bool(drive) and (not check_files or os.path.isdir(drive.rstrip("\\/")))
    if check_files and not drive_ok:
        add(SEV_INFO, "files",
            "Work drive '%s' not found here - skipped the file-exists checks." % drive)

    for num, tex in sorted(stages.items()):
        key = _STAGE_NAMES.get(num, num)
        area = "Stage%s/%s" % (num, key)
        if _is_procedural_texture(tex):
            if key in _EXPECTED_REAL_MAPS:
                add(SEV_INFO, area,
                    "%s still uses a procedural default (no real %s map)."
                    % (key, key))
            continue
        if not tex.strip():
            add(SEV_WARN, area, "Empty texture path.")
            continue

        # colour map wrongly placed in a stage (ENV maps legitimately end _co)
        if key != "ENV" and re.search(r"_co\b", tex, re.IGNORECASE):
            add(SEV_WARN, area,
                "References a _co (colour) map - colour is assigned on the model, "
                "not in the .rvmat.")

        if "/" in tex:
            add(SEV_WARN, area, "Uses forward slashes - DayZ expects backslashes.")

        if _looks_absolute_path(tex):
            add(SEV_ERROR, area,
                "Absolute path - must be mod-relative (e.g. MyMod\\data\\x_nohq.paa), "
                "no drive letter.")

        ext = os.path.splitext(tex)[1].lower()
        if ext == ".tga":
            add(SEV_WARN, area,
                "Points at .tga - DayZ loads .paa in-game. Fine for local editing; "
                "switch to .paa before packing.")
        elif ext and ext not in VALID_TEXTURE_EXT:
            add(SEV_ERROR, area, "Unsupported texture extension '%s'." % ext)
        elif not ext:
            add(SEV_WARN, area, "Texture path has no file extension.")

        # existence
        if check_files and drive_ok and not _looks_absolute_path(tex):
            abs_path = _abs_from_modrel(tex, drive)
            if os.path.exists(abs_path):
                continue
            other = ".tga" if ext == ".paa" else (".paa" if ext == ".tga" else None)
            if other and os.path.exists(_sibling_with_ext(abs_path, other)):
                add(SEV_WARN, area,
                    "Referenced %s not found, but the %s source exists - "
                    "convert/pack it before use." % (ext, other))
            elif re.match(r"(?i)^dz[\\/]", tex.strip()):
                # base-game content - only present if the game is unpacked to the
                # work drive, so a miss here is expected, not a mod error.
                add(SEV_INFO, area,
                    "Base-game texture (dz\\...) not on this drive - fine, the "
                    "game provides it; unpack DayZ to P: only if you want a preview.")
            else:
                add(SEV_ERROR, area, "Texture not found on the work drive: %s" % abs_path)

    if not findings:
        add(SEV_OK, "file", "No problems found.")
    return findings


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
