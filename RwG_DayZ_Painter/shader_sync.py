"""Two-way link between the plugin's material values and the RwG DayZ In-Game
viewport shader (dayz-ingame.glsl).

Painter's Python API does not expose shader parameters yet, so this goes
through the JavaScript API (alg.shaders), the same way Painter's own Python
modules do. Parameter identifiers are the shader's uniform names.
"""

import json

import substance_painter.js

SHADER_TAG = "dayz-ingame"

# _smdi source (settings key) -> shader "_smdi method" combobox value
SMDI_METHOD = {"dayz": 0}          # everything else previews as the glTF-style method


def _instances():
    """Shader instances that run the DayZ In-Game shader."""
    try:
        shaders = substance_painter.js.evaluate("alg.shaders.instances()") or []
    except Exception:
        return []                  # no project open
    return [s for s in shaders if SHADER_TAG in str(s.get("url", "")).lower()]


def available():
    return bool(_instances())


def _floats(text, count, default):
    vals = []
    for part in str(text).split(","):
        try:
            vals.append(float(part.strip()))
        except ValueError:
            pass
    vals = vals[:count]
    return vals + list(default)[len(vals):count]


def _num(text, default):
    try:
        return float(str(text).strip())
    except ValueError:
        return default


def params_from_settings(s):
    """Shader parameter map from the plugin's settings dict (see RwGDock._read_ui)."""
    mc = str(s.get("mc_source", "User0"))
    mc_index = {"User1": 1, "User2": 2}.get(mc, 0)
    return {
        "u_ambient": _floats(s.get("mat_ambient", ""), 3, (1, 1, 1)),
        "u_diffuse": _floats(s.get("mat_diffuse", ""), 3, (1, 1, 1)),
        "u_forced": _floats(s.get("mat_forced", ""), 3, (0, 0, 0)),
        "u_emmisive": _floats(s.get("mat_emmisive", ""), 3, (0, 0, 0)),
        "u_specular": _floats(s.get("mat_specular", ""), 3, (1, 1, 1)),
        "u_power": max(1.0, _num(s.get("mat_power", ""), 30.0)),
        "u_fresnel_n": _num(s.get("mat_fresnel_n", ""), 0.4),
        "u_fresnel_k": _num(s.get("mat_fresnel_k", ""), 0.2),
        "u_smdi_method": SMDI_METHOD.get(s.get("smdi_source"), 1),
        "u_g_factor": float(s.get("smdi_green", 1.0)),
        "u_b_factor": float(s.get("smdi_blue", 1.0)),
        "u_mc_show": bool(s.get("mc_on", False)),
        "u_mc_source": mc_index,
    }


def _mapping():
    """Shader instances and which texture set uses which (alg.shaders.shaderInstancesToObject):
    {"shaders": {name: {"shader": "dayz-ingame", "shaderInstance": name, "parameters": ...}},
     "texturesets": {texture set: {"shader": instance name}}}"""
    try:
        return substance_painter.js.evaluate("alg.shaders.shaderInstancesToObject()") or {}
    except Exception:
        return {}                  # no project open


def instance_for(texture_set, split=True):
    """Name of the DayZ In-Game shader instance a texture set uses, or None if it uses
    another shader. With ``split``, a texture set sharing its instance with others (or
    still on a default-named one) first gets its own copy ("DayZ <texture set>") - every
    texture set paints a different .rvmat, so one shared instance would show the same
    values on all of them."""
    obj = _mapping()
    sets, shaders = obj.get("texturesets") or {}, obj.get("shaders") or {}
    entry = sets.get(texture_set)
    name = entry.get("shader") if entry else None
    inst = shaders.get(name) if name else None
    if not inst or SHADER_TAG not in str(inst.get("shader", "")).lower():
        return None
    shared = [ts for ts, e in sets.items() if e.get("shader") == name]
    # also the last texture set left on a shared default instance ("Main shader")
    # gets its own, so every texture set ends up on "DayZ <texture set>"
    if split and (len(shared) > 1 or not name.startswith("DayZ ")):
        new, i = f"DayZ {texture_set}", 2
        while new in shaders:
            new, i = f"DayZ {texture_set} {i}", i + 1
        copy = json.loads(json.dumps(inst))          # same shader and values to start from
        copy["shaderInstance"] = new
        shaders[new] = copy
        entry["shader"] = new
        # creates the missing instance and assigns it to this texture set only
        substance_painter.js.evaluate(f"alg.shaders.shaderInstancesFromObject({json.dumps(obj)})")
        name = new
    return name


def push(params, texture_set=None):
    """Write the parameters into the DayZ In-Game shader instance of ``texture_set``
    (its own one, split off if shared), or into every instance without a texture set.
    Returns the number of instances updated."""
    shaders = _instances()
    if texture_set:
        name = instance_for(texture_set)
        if name is None:
            return 0
        shaders = [s for s in _instances() if str(s.get("label", "")).strip().lower() == name.strip().lower()]
        if not shaders:
            raise RuntimeError(f"shader instance '{name}' not found among "
                               f"{[s.get('label') for s in _instances()]}")
    payload = json.dumps(params)
    for sh in shaders:
        substance_painter.js.evaluate(
            f"alg.shaders.setParameters({int(sh['id'])}, {payload})")
    return len(shaders)


def pull():
    """Parameter values of the first DayZ In-Game shader instance, or None."""
    shaders = _instances()
    if not shaders:
        return None
    raw = substance_painter.js.evaluate(
        f"alg.shaders.parameters({int(shaders[0]['id'])})") or {}
    out = {}
    for key, entry in raw.items():
        out[key] = entry.get("value") if isinstance(entry, dict) else entry
    return out
