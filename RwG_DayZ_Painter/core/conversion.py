"""
PBR -> DayZ texture conversion (pure, numpy based).

Produces the DayZ / Enfusion texture maps:

    _co    - color / diffuse (albedo, optionally specular-corrected)
    _nohq  - normal map (DirectX convention, as DayZ expects)
    _smdi  - specular map   (R = white, G = specular level, B = gloss)
    _as    - ambient shadow  (only the G channel is used by the engine)

Channel layouts follow the Bohemia Interactive "Super shader" / "Texture Map
Types" documentation:

    _smdi : R = 1.0 (white)                       -> always white
            G = specular level from metallic        -> whiter = more metallic
            B = gloss (specular power) = 1 - rough  -> white = smooth / shiny
    _as   : R = white, G = ambient occlusion,       -> white = full ambient
            B = white                                  (only G is read by engine)
    _nohq : DayZ uses DirectX-style normals. If the source normal map is
            OpenGL (Y+), the green channel is flipped to DirectX (Y-).

These functions are shared, unchanged, with the standalone RwG Texture Converter.
"""

import os

import numpy as np
from PIL import Image


# Dielectric base reflectance (F0) used by the metallic/roughness workflow.
DIELECTRIC_F0 = 0.04


def _load_gray(path):
    """Load an image as a float32 grayscale array in the range [0, 1]."""
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def _load_rgb(path):
    """Load an image as a float32 RGB array in the range [0, 1]."""
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _save(arr01, output_path, resolution=None):
    """Clamp a [0, 1] array, optionally resize, and write it as a TGA file."""
    arr = np.clip(arr01 * 255.0, 0, 255).astype(np.uint8)
    mode = "RGB" if arr.ndim == 3 else "L"
    img = Image.fromarray(arr, mode)
    if resolution:
        img = img.resize((int(resolution), int(resolution)), Image.LANCZOS)
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    img.save(output_path, format="TGA")
    return output_path


def convert_co_texture(base_color_path, metal_path, output_path,
                       use_specular_conversion=False, resolution=1024):
    """
    _co (diffuse / albedo).

    In 'Base Color + Specular' mode the diffuse is dimmed by the specular
    reflectance so that the energy that ends up in the specular response
    (driven by the metallic map) is removed from the diffuse term.
    """
    try:
        base = _load_rgb(base_color_path)

        if use_specular_conversion and metal_path:
            metal = _load_gray(metal_path)[..., None]           # H x W x 1
            # Specular colour: metals reflect their base colour, dielectrics 0.04.
            specular = base * metal + (1.0 - metal) * DIELECTRIC_F0
            spec_level = specular.max(axis=2, keepdims=True)
            diffuse = base * (1.0 - spec_level)
            _save(diffuse, output_path, resolution)
            print(f"_co saved (specular-corrected): {output_path}")
        else:
            _save(base, output_path, resolution)
            print(f"_co saved (base colour only): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _co texture: {e}")
        raise


def convert_nohq_texture(normal_path, output_path,
                         input_format="opengl", resolution=1024):
    """
    _nohq (normal map).

    DayZ / Enfusion expects DirectX-style normals (green = Y-). If the source
    is OpenGL (green = Y+) we flip the green channel; if the source is already
    DirectX we leave it untouched.
    """
    try:
        n = _load_rgb(normal_path)
        if input_format == "opengl":
            n[..., 1] = 1.0 - n[..., 1]     # OpenGL (Y+) -> DirectX (Y-)
        _save(n, output_path, resolution)
        print(f"_nohq saved (source={input_format} -> DirectX): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _nohq texture: {e}")
        raise


def convert_smdi_texture(metal_path, roughness_path, output_path,
                         specular_factor=1.0, glossiness_factor=1.0,
                         resolution=1024):
    """
    _smdi (specular map).

        R = 1.0                              always white
        G = specular level (from metallic)   whiter = more metallic
        B = gloss = 1 - roughness            white = smooth / shiny

    The green channel keeps a dielectric floor of 0.04 so non-metal surfaces
    still receive a physically plausible specular response instead of going
    completely matte. Both channels are tunable via the two factors.
    """
    try:
        if not (metal_path and roughness_path):
            raise ValueError("Both metallic and roughness maps are required for _smdi.")

        metal = _load_gray(metal_path)
        rough = _load_gray(roughness_path)

        red = np.ones_like(metal)                                    # always white
        green = np.clip((DIELECTRIC_F0 + (1.0 - DIELECTRIC_F0) * metal)
                        * specular_factor, 0.0, 1.0)                 # specular level
        blue = np.clip((1.0 - rough) * glossiness_factor, 0.0, 1.0)  # gloss

        smdi = np.stack([red, green, blue], axis=2)
        _save(smdi, output_path, resolution)
        print(f"_smdi saved: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _smdi texture: {e}")
        raise


def convert_smdi_direct(spec_path, gloss_path, output_path,
                        specular_factor=1.0, glossiness_factor=1.0, resolution=1024):
    """
    _smdi packed directly from Painter's converted Specular + Glossiness maps
    (the physically-based PBR -> spec/gloss conversion). Both inputs are read as
    grayscale; metal specular colour collapses to its luminance for the single
    SMDI specular-level channel.

        R = 1.0 (white)
        G = Specular   * specular_factor
        B = Glossiness * glossiness_factor
    """
    try:
        spec = _load_gray(spec_path)
        gloss = _load_gray(gloss_path)
        red = np.ones_like(spec)
        green = np.clip(spec * specular_factor, 0.0, 1.0)
        blue = np.clip(gloss * glossiness_factor, 0.0, 1.0)
        smdi = np.stack([red, green, blue], axis=2)
        _save(smdi, output_path, resolution)
        print(f"_smdi saved (from Specular+Glossiness): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _smdi texture: {e}")
        raise


def convert_as_texture(ao_path, output_path, invert_ao=False, resolution=1024):
    """
    _as (ambient shadow).

    Only the green channel is read by the engine: white = full ambient light,
    black = fully occluded. A standard AO map (white = unoccluded) maps
    directly, so no inversion is applied by default. R and B are filled white
    to match the documented layout.
    """
    try:
        ao = _load_gray(ao_path)
        if invert_ao:
            ao = 1.0 - ao
        white = np.ones_like(ao)
        as_map = np.stack([white, ao, white], axis=2)   # R=white, G=AO, B=white
        _save(as_map, output_path, resolution)
        print(f"_as saved: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _as texture: {e}")
        raise
