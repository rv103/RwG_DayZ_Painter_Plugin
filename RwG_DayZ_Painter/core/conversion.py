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
    if arr.ndim == 3:
        mode = {3: "RGB", 4: "RGBA"}.get(arr.shape[2], "RGB")
    else:
        mode = "L"
    img = Image.fromarray(arr, mode)
    if resolution:
        img = img.resize((int(resolution), int(resolution)), Image.LANCZOS)
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    img.save(output_path, format="TGA")
    return output_path


def _save_hdr(rgb, path):
    """Write a linear float RGB image (values may exceed 1) as a Radiance .hdr
    (uncompressed RGBE) so it works as a real IBL environment."""
    rgb = np.asarray(rgb, dtype=np.float32)
    rgb = np.maximum(rgb, 0.0)
    bright = rgb.max(axis=2)
    mant, expo = np.frexp(bright)                    # bright = mant * 2**expo
    scale = np.where(bright > 1e-32, mant * 256.0 / bright, 0.0)
    rgbe = np.zeros(rgb.shape[:2] + (4,), dtype=np.uint8)
    rgbe[..., 0:3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.clip(expo + 128, 0, 255).astype(np.uint8)
    rgbe[bright <= 1e-32] = 0
    h, w = rgb.shape[:2]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {h} +X {w}\n".encode("ascii"))
        rgbe.tofile(f)
    return path


def wrap_plate_array(src_path, tiles=3, mirror=True, rotation_deg=0.0,
                     out_w=1024, out_h=512, gain=1.0):
    """Wrap a DayZ landscape env plate into an equirectangular float panorama.

    DayZ ``env_*_co`` maps are not fisheye or panoramic - they're a flat
    landscape plate (sky on top, horizon in the middle, ground at the bottom).
    We tile the plate horizontally ``tiles`` times (``mirror`` flips alternate
    copies so the seams vanish) and map the plate's vertical straight onto the
    equirect vertical (top = sky, bottom = ground). ``rotation_deg`` shifts it
    horizontally; ``gain`` scales brightness (for IBL energy). Returns a float
    HxWx3 array (values may exceed 1 when gain > 1).
    """
    plate = _load_rgb(src_path)                     # H,W,3 in 0..1
    sh, sw = plate.shape[:2]
    ow, oh = int(out_w), int(out_h)
    tiles = max(1, int(tiles))

    xs = np.arange(ow, dtype=np.float64)
    ys = np.arange(oh, dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)

    shift = (float(rotation_deg) / 360.0) * ow
    xr = np.mod(X + shift, ow)
    p = (xr / ow) * tiles
    k = np.floor(p).astype(np.int64)
    f = p - k
    if mirror:
        f = np.where(k % 2 == 1, 1.0 - f, f)
    sx = f * (sw - 1)
    sy = (Y / oh) * (sh - 1)

    x0 = np.clip(np.floor(sx).astype(np.int64), 0, sw - 1)
    x1 = np.clip(x0 + 1, 0, sw - 1)
    y0 = np.clip(np.floor(sy).astype(np.int64), 0, sh - 1)
    y1 = np.clip(y0 + 1, 0, sh - 1)
    wx = (sx - x0)[..., None]
    wy = (sy - y0)[..., None]
    top = plate[y0, x0] * (1 - wx) + plate[y0, x1] * wx
    bot = plate[y1, x0] * (1 - wx) + plate[y1, x1] * wx
    out = top * (1 - wy) + bot * wy                 # H,W,3
    return out.astype(np.float32) * float(gain)


def wrap_plate_to_equirect(src_path, output_path, tiles=3, mirror=True,
                           rotation_deg=0.0, out_w=1024, out_h=512, gain=1.0):
    """Wrap the plate and save it. A `.hdr` output keeps the (gained) float values
    for proper IBL brightness; any other extension is written as a clamped PNG."""
    out = wrap_plate_array(src_path, tiles, mirror, rotation_deg, out_w, out_h, gain)
    if str(output_path).lower().endswith(".hdr"):
        return _save_hdr(out, output_path)
    out8 = np.clip(out * 255.0, 0, 255).astype(np.uint8)
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(out8, "RGB").save(output_path)
    return output_path


def convert_co_texture(base_color_path, metal_path, output_path,
                       use_specular_conversion=False, resolution=1024,
                       spec_gloss=False):
    """
    _co (diffuse / albedo).

    Three modes:
      * default            - the base colour, untouched.
      * spec_gloss=True     - the canonical glTF metal/rough -> spec/gloss diffuse:
                              diffuse = baseColor * (1 - 0.04) * (1 - metallic).
                              Metals go black, dielectrics keep 96% of their
                              albedo (the 4% that becomes the dielectric specular
                              is removed). Needs the metallic map.
      * use_specular_conversion=True - older 'Base Color + Specular' mode: the
                              diffuse is dimmed by the specular reflectance's peak
                              channel. Kept for back-compatibility.
    """
    try:
        base = _load_rgb(base_color_path)

        if spec_gloss and metal_path:
            metal = _load_gray(metal_path)[..., None]           # H x W x 1
            # Canonical glTF spec/gloss diffuse.
            diffuse = base * (1.0 - DIELECTRIC_F0) * (1.0 - metal)
            _save(diffuse, output_path, resolution)
            print(f"_co saved (spec/gloss diffuse): {output_path}")
        elif use_specular_conversion and metal_path:
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


def convert_ca_texture(color_path, opacity_path, output_path, resolution=1024):
    """
    _ca (colour + alpha) - the same colour as _co but with a transparency
    channel: RGB from the colour map, A from the Opacity channel. Used for
    materials that need alpha (glass, foliage, decals).
    """
    try:
        rgb = _load_rgb(color_path)
        if opacity_path and os.path.exists(opacity_path):
            alpha = _load_gray(opacity_path)
        else:
            alpha = np.ones(rgb.shape[:2], dtype=np.float32)
        rgba = np.dstack([rgb, alpha])
        _save(rgba, output_path, resolution)
        print(f"_ca saved (colour + opacity alpha): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _ca texture: {e}")
        raise


def convert_em_texture(emissive_path, output_path, resolution=1024):
    """
    _em (emissive / glow) - the emissive colour saved as-is (metals/dielectrics
    alike). DayZ multiplies this by the material's emmisive[] value.
    """
    try:
        em = _load_rgb(emissive_path)
        _save(em, output_path, resolution)
        print(f"_em saved (emissive): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _em texture: {e}")
        raise


def _apply_mc_alpha(rgb, alpha):
    """Attach the macro blend mask as the _mc alpha channel.

    DayZ blends base<->macro by the macro's alpha (1 = only macro, 0 = only base).
    `alpha` is None (no alpha, opaque), the string "auto" (derive the mask from the
    macro's own luminance - so it applies where you painted), or a path to a
    grayscale mask.
    """
    if alpha is None:
        return rgb
    if alpha == "auto":
        # "where painted" - brightest channel, so any painted colour = full mask,
        # black = no macro (independent of hue)
        a = rgb.max(axis=2)
    else:
        a = _load_gray(alpha)
        if a.shape != rgb.shape[:2]:
            img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "L")
            img = img.resize((rgb.shape[1], rgb.shape[0]), Image.LANCZOS)
            a = np.asarray(img, dtype=np.float32) / 255.0
    return np.dstack([rgb, np.clip(a, 0.0, 1.0)])


def _blend_pair(a, b, mode):
    """Blend two [0,1] RGB arrays. For 'lighten'/'screen'/'add' black is neutral,
    so unpainted (black) User channels don't ruin the mix."""
    if mode == "lighten":
        return np.maximum(a, b)
    if mode == "darken":
        return np.minimum(a, b)
    if mode == "add":
        return np.clip(a + b, 0.0, 1.0)
    if mode == "screen":
        return 1.0 - (1.0 - a) * (1.0 - b)
    if mode == "multiply":
        return a * b
    if mode == "average":
        return (a + b) * 0.5
    if mode == "overlay":
        return np.where(a < 0.5, 2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b))
    return np.maximum(a, b)


def convert_mc_combined(user_paths, output_path, blend="lighten", resolution=1024,
                        alpha=None):
    """
    _mc built by stacking several Painter User channels on top of each other with
    a blend mode (default 'lighten' - black areas stay neutral, so you can paint
    parts of the macro across different User channels). `alpha` sets the DayZ blend
    mask (see _apply_mc_alpha).
    """
    try:
        base = None
        for p in user_paths:
            if not p:
                continue
            arr = _load_rgb(p)
            if base is None:
                base = arr
                continue
            if arr.shape != base.shape:
                img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGB")
                img = img.resize((base.shape[1], base.shape[0]), Image.LANCZOS)
                arr = np.asarray(img, dtype=np.float32) / 255.0
            base = _blend_pair(base, arr, blend)
        if base is None:
            raise ValueError("No User channels supplied for the combined _mc.")
        out = _apply_mc_alpha(np.clip(base, 0.0, 1.0), alpha)
        _save(out, output_path, resolution)
        print(f"_mc saved (combined {len(user_paths)} User channels, {blend}, "
              f"alpha={alpha}): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating combined _mc texture: {e}")
        raise


def convert_mc_texture(user_path, output_path, resolution=1024, alpha=None):
    """
    _mc (macro) - the macro / large-scale colour variation from a Painter User
    channel. DayZ blends base<->macro by the alpha channel, so `alpha` sets the
    mask (see _apply_mc_alpha).
    """
    try:
        mc = _apply_mc_alpha(_load_rgb(user_path), alpha)
        _save(mc, output_path, resolution)
        print(f"_mc saved (macro, alpha={alpha}): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _mc texture: {e}")
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


def _srgb_to_linear(c):
    """sRGB (0..1) -> linear (0..1), standard IEC 61966-2-1 transfer."""
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def convert_smdi_pbr(metal_path, roughness_path, basecolor_path, output_path,
                     specular_factor=1.0, glossiness_factor=1.0, resolution=1024):
    """
    _smdi packed with a physically-based specular level (metalness workflow).

        R = 1.0 (white)
        G = specular level = lerp(0.04, luminance(linear base colour), metallic)
        B = gloss = 1 - roughness

    Unlike ``convert_smdi_texture`` (which pushes every metal to a flat ~1.0),
    the green channel here uses each metal's own reflectance: dielectrics keep
    the 0.04 floor, and metals take the luminance of their (linearised) base
    colour - so dull/oxidised metal stays darker than polished metal. This is
    the standard metalness -> specular-level conversion, done straight from the
    channels (no converted maps needed) beyond the base colour.
    """
    try:
        if not (metal_path and roughness_path and basecolor_path):
            raise ValueError("metallic, roughness and base colour are required "
                             "for the PBR _smdi method.")
        metal = _load_gray(metal_path)
        rough = _load_gray(roughness_path)
        base_lin = _srgb_to_linear(_load_rgb(basecolor_path))
        # Rec.709 luminance of the linear base colour = the metal's F0 level.
        lum = (0.2126 * base_lin[..., 0]
               + 0.7152 * base_lin[..., 1]
               + 0.0722 * base_lin[..., 2])
        reflectance = (1.0 - metal) * DIELECTRIC_F0 + metal * lum

        red = np.ones_like(metal)
        green = np.clip(reflectance * specular_factor, 0.0, 1.0)
        blue = np.clip((1.0 - rough) * glossiness_factor, 0.0, 1.0)
        smdi = np.stack([red, green, blue], axis=2)
        _save(smdi, output_path, resolution)
        print(f"_smdi saved (PBR base-colour reflectance): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _smdi (PBR) texture: {e}")
        raise


def _perceived_brightness(rgb):
    """glTF getPerceivedBrightness: sqrt(0.299 R^2 + 0.587 G^2 + 0.114 B^2)."""
    return np.sqrt(0.299 * rgb[..., 0] ** 2
                   + 0.587 * rgb[..., 1] ** 2
                   + 0.114 * rgb[..., 2] ** 2)


def convert_smdi_gltf(metal_path, roughness_path, basecolor_path, output_path,
                      specular_factor=1.0, glossiness_factor=1.0, resolution=1024):
    """
    _smdi packed with the canonical glTF metal/rough -> spec/gloss specular level.

        R = 1.0 (white)
        G = perceivedBrightness( mix(0.04, baseColor_linear, metallic) )
        B = gloss = 1 - roughness

    This is the exact glTF forward conversion: the specular colour is the
    per-channel F0 = mix(0.04, baseColor, metallic), and its single-channel level
    for _smdi is glTF's perceived brightness (sqrt-weighted luma) rather than a
    flat Rec.709 luminance. Very close to the 'pbr' method, just the canonical
    brightness metric.
    """
    try:
        if not (metal_path and roughness_path and basecolor_path):
            raise ValueError("metallic, roughness and base colour are required "
                             "for the glTF _smdi method.")
        metal = _load_gray(metal_path)[..., None]
        rough = _load_gray(roughness_path)
        base_lin = _srgb_to_linear(_load_rgb(basecolor_path))
        # Colored F0, then glTF perceived brightness for the single SMDI level.
        f0 = base_lin * metal + (1.0 - metal) * DIELECTRIC_F0
        level = _perceived_brightness(f0)

        red = np.ones_like(rough)
        green = np.clip(level * specular_factor, 0.0, 1.0)
        blue = np.clip((1.0 - rough) * glossiness_factor, 0.0, 1.0)
        smdi = np.stack([red, green, blue], axis=2)
        _save(smdi, output_path, resolution)
        print(f"_smdi saved (glTF spec/gloss level): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _smdi (glTF) texture: {e}")
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


# --- DayZ shader-correct _smdi ------------------------------------------------
# Measured against the game (RenderDoc captures of DayZDiag, DayZ Shader project):
#   * the Super shader weights every reflection with ks = SMDI.G x Fresnel(N.V), and the
#     rvmat's fresnel(n,k) stage already carries F0 (physical complex-IOR Fresnel). So G is
#     the fraction of that stage's reflectance, not F0 itself - writing F0 into G applies it
#     twice (a dielectric ends up ~25x too dull);
#   * the highlight exponent is SMDI.B x specularPower (unnormalised Blinn-Phong), and the
#     engine scales the highlight by ~0.11 x specularPower for the whole material. Multiplying
#     G by B makes that roughly energy-conserving per pixel.

def fresnel_f0(n, k=0.0):
    """Reflectance at normal incidence of the fresnel(n,k) stage."""
    n, k = float(n), float(k)
    return ((n - 1.0) ** 2 + k * k) / ((n + 1.0) ** 2 + k * k)


def dayz_gloss(rough, specular_power):
    """_smdi B for a roughness map: the GGX-equivalent Blinn-Phong exponent 2/r^4 - 2,
    as a fraction of the rvmat's specularPower (clipped to 0..1)."""
    r = np.clip(rough, 0.02, 1.0)
    return np.clip((2.0 / r ** 4 - 2.0) / max(float(specular_power), 1.0), 0.0, 1.0)


def dayz_specular_power(rough, cap=400.0):
    """specularPower that the smoothest part of a roughness map needs (5th percentile),
    so dayz_gloss() does not clip. Capped: _smdi ends up BC1 in game (5-bit blue), so a
    huge specularPower would crush every rough area into the lowest steps; the engine's
    highlight brightness stops growing at ~219 anyway."""
    r = max(float(np.percentile(rough, 5)), 0.02)
    return float(min(cap, max(1.0, round(2.0 / r ** 4 - 2.0))))


def _dayz_green(metal, rough, base_lin, specular_power, fresnel_n, fresnel_k, normalize):
    """_smdi G: the pixel's F0 (glTF: mix(0.04, base colour, metallic), perceived
    brightness) relative to the fresnel stage's F0, times B for energy."""
    if base_lin is None:
        level = DIELECTRIC_F0 + (1.0 - DIELECTRIC_F0) * metal
    else:
        m = metal[..., None]
        level = _perceived_brightness(base_lin * m + (1.0 - m) * DIELECTRIC_F0)
    green = level / max(fresnel_f0(fresnel_n, fresnel_k), 1e-3)
    if normalize:
        green = green * dayz_gloss(rough, specular_power)
    return green


def convert_smdi_dayz(metal_path, roughness_path, basecolor_path, output_path,
                      specular_power=100.0, fresnel_n=1.5, fresnel_k=0.0,
                      normalize_highlight=True, specular_factor=1.0,
                      glossiness_factor=1.0, resolution=1024):
    """
    _smdi matched to the DayZ Super shader (see the notes above).

        R = 1.0 (white)
        G = F0_pixel / F0(fresnel stage)  [x B with normalize_highlight]
        B = (2 / roughness^4 - 2) / specularPower

    specular_power and fresnel_n/k must be the values written into the rvmat.
    The base colour is optional (without it every metal gets a flat F0 of 1).
    """
    try:
        if not (metal_path and roughness_path):
            raise ValueError("metallic and roughness are required for the DayZ _smdi method.")
        metal = _load_gray(metal_path)
        rough = _load_gray(roughness_path)
        base_lin = _srgb_to_linear(_load_rgb(basecolor_path)) if basecolor_path else None
        red = np.ones_like(rough)
        green = np.clip(_dayz_green(metal, rough, base_lin, specular_power, fresnel_n,
                                    fresnel_k, normalize_highlight) * specular_factor, 0.0, 1.0)
        blue = np.clip(dayz_gloss(rough, specular_power) * glossiness_factor, 0.0, 1.0)
        _save(np.stack([red, green, blue], axis=2), output_path, resolution)
        print(f"_smdi saved (DayZ shader, specularPower {specular_power}, "
              f"fresnel F0 {fresnel_f0(fresnel_n, fresnel_k):.3f}): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _smdi (DayZ) texture: {e}")
        raise


def _dayz_specgloss(spec_path, gloss_path, spec_srgb, specular_power, fresnel_n, fresnel_k,
                    normalize):
    """_smdi G and B for PBR spec/gloss maps: Specular = F0 (a Specular colour map is
    sRGB and is linearised first, a Specular Level map is raw), roughness = 1 -
    glossiness, then the same maths as convert_smdi_dayz."""
    if spec_srgb:
        level = _perceived_brightness(_srgb_to_linear(_load_rgb(spec_path)))
    else:
        level = _load_gray(spec_path)
    rough = 1.0 - _load_gray(gloss_path)
    green = level / max(fresnel_f0(fresnel_n, fresnel_k), 1e-3)
    blue = dayz_gloss(rough, specular_power)
    if normalize:
        green = green * blue
    return green, blue


def convert_smdi_dayz_specgloss(spec_path, gloss_path, output_path, spec_srgb=True,
                                specular_power=100.0, fresnel_n=1.5, fresnel_k=0.0,
                                normalize_highlight=True, specular_factor=1.0,
                                glossiness_factor=1.0, resolution=1024):
    """
    _smdi matched to the DayZ Super shader from PBR spec/gloss maps (Painter's
    "PBR - Specular Glossiness" channels):

        R = 1.0 (white)
        G = F0 (Specular) / F0(fresnel stage)  [x B with normalize_highlight]
        B = (2 / (1 - glossiness)^4 - 2) / specularPower
    """
    try:
        green, blue = _dayz_specgloss(spec_path, gloss_path, spec_srgb, specular_power,
                                      fresnel_n, fresnel_k, normalize_highlight)
        green = np.clip(green * specular_factor, 0.0, 1.0)
        blue = np.clip(blue * glossiness_factor, 0.0, 1.0)
        _save(np.stack([np.ones_like(green), green, blue], axis=2), output_path, resolution)
        print(f"_smdi saved (DayZ shader from spec/gloss, specularPower {specular_power}, "
              f"fresnel F0 {fresnel_f0(fresnel_n, fresnel_k):.3f}): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _smdi (DayZ spec/gloss) texture: {e}")
        raise


def _detail_from_maps(detail_paths, shape_hw, strength=1.0):
    """A DT-style grayscale detail channel (average ~0.5, high-frequency) combined
    from one or more height / normal sources, for the _dtsmdi R channel.

    Each source is high-pass filtered (source minus a blurred copy); the deltas are
    summed and re-centred at 0.5, so a raw **height** map, the baked **mesh** normal
    and the **tangent** normal all contribute their fine detail. It fades neutrally
    in the mipmaps - exactly what a DayZ detail (DT) map wants. Falls back to a flat
    0.5 when no usable source is given. ``detail_paths`` may be a single path or a
    list.
    """
    from PIL import ImageFilter
    h, w = shape_hw
    if isinstance(detail_paths, str):
        detail_paths = [detail_paths]
    paths = [p for p in (detail_paths or []) if p and os.path.exists(p)]
    if not paths:
        return np.full((h, w), 0.5, dtype=np.float32)
    delta = np.zeros((h, w), dtype=np.float32)
    for p in paths:
        g = _load_gray(p)
        if g.shape != (h, w):                          # match the target size first
            g = np.asarray(
                Image.fromarray((np.clip(g, 0.0, 1.0) * 255).astype(np.uint8), "L")
                     .resize((w, h), Image.LANCZOS), dtype=np.float32) / 255.0
        radius = max(2.0, min(h, w) / 128.0)
        blur = np.asarray(
            Image.fromarray((np.clip(g, 0.0, 1.0) * 255).astype(np.uint8), "L")
                 .filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0
        delta += (g - blur)
    return np.clip(0.5 + delta * strength, 0.0, 1.0)


def convert_dtsmdi(metal_path, roughness_path, output_path, method="gltf",
                   basecolor_path=None, spec_path=None, gloss_path=None,
                   detail_paths=None, detail_strength=1.0,
                   specular_factor=1.0, glossiness_factor=1.0, resolution=1024,
                   specular_power=100.0, fresnel_n=1.5, fresnel_k=0.0,
                   normalize_highlight=True, spec_srgb=True):
    """
    _dtsmdi (Detail + SMDI) - the SMDI variant used by the DayZ Multimaterial
    shader, which packs a tiling detail map into the R channel:

        R = detail map  (high-frequency, average ~0.5; combined from the height +
                         mesh + normal sources, or a flat 0.5 when none is given)
        G = specular level  (identical to the chosen _smdi method)
        B = gloss = 1 - roughness

    ``method`` selects the green (specular level) exactly like the _smdi
    variants: 'dayz' | 'gltf' | 'pbr' | 'metrough' | 'specgloss' | 'specgloss_dayz'.
    """
    try:
        # --- green + blue: identical maths to the matching _smdi variant ---
        if method == "specgloss_dayz":
            if not (spec_path and gloss_path):
                raise ValueError("dtsmdi 'specgloss_dayz' needs spec + gloss maps.")
            green, blue = _dayz_specgloss(spec_path, gloss_path, spec_srgb, specular_power,
                                          fresnel_n, fresnel_k, normalize_highlight)
            green = np.clip(green * specular_factor, 0.0, 1.0)
            blue = np.clip(blue * glossiness_factor, 0.0, 1.0)
        elif method == "dayz":
            if not (metal_path and roughness_path):
                raise ValueError("dtsmdi 'dayz' needs metallic + roughness.")
            metal = _load_gray(metal_path)
            rough = _load_gray(roughness_path)
            base_lin = _srgb_to_linear(_load_rgb(basecolor_path)) if basecolor_path else None
            green = np.clip(_dayz_green(metal, rough, base_lin, specular_power, fresnel_n,
                                        fresnel_k, normalize_highlight) * specular_factor,
                            0.0, 1.0)
            blue = np.clip(dayz_gloss(rough, specular_power) * glossiness_factor, 0.0, 1.0)
        elif method == "specgloss":
            if not (spec_path and gloss_path):
                raise ValueError("dtsmdi 'specgloss' needs spec + gloss maps.")
            green = np.clip(_load_gray(spec_path) * specular_factor, 0.0, 1.0)
            blue = np.clip(_load_gray(gloss_path) * glossiness_factor, 0.0, 1.0)
        else:
            if not (metal_path and roughness_path):
                raise ValueError("dtsmdi needs metallic + roughness.")
            metal = _load_gray(metal_path)
            rough = _load_gray(roughness_path)
            blue = np.clip((1.0 - rough) * glossiness_factor, 0.0, 1.0)
            if method in ("gltf", "pbr"):
                if not basecolor_path:
                    raise ValueError("dtsmdi 'gltf'/'pbr' needs a base colour.")
                base_lin = _srgb_to_linear(_load_rgb(basecolor_path))
                if method == "gltf":
                    m = metal[..., None]
                    f0 = base_lin * m + (1.0 - m) * DIELECTRIC_F0
                    level = _perceived_brightness(f0)
                else:  # pbr
                    level = ((1.0 - metal) * DIELECTRIC_F0 + metal * (
                        0.2126 * base_lin[..., 0] + 0.7152 * base_lin[..., 1]
                        + 0.0722 * base_lin[..., 2]))
                green = np.clip(level * specular_factor, 0.0, 1.0)
            else:  # metrough
                green = np.clip((DIELECTRIC_F0 + (1.0 - DIELECTRIC_F0) * metal)
                                * specular_factor, 0.0, 1.0)

        red = _detail_from_maps(detail_paths, green.shape, detail_strength)
        dtsmdi = np.stack([red, green, blue], axis=2)
        _save(dtsmdi, output_path, resolution)
        print(f"_dtsmdi saved (method={method}, "
              f"detail={'derived' if detail_paths else 'flat 0.5'}): {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating _dtsmdi texture: {e}")
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
