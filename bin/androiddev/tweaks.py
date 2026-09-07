"""The three display tweaks flipped while checking a UI: dark mode, the
font scale and the display scale (density). Read all in one `adb shell`,
set one with the framework's own commands, re-read all.

The read is one fixed shell script (no device data in it), like the
toggles'. Dark mode is `cmd uimode night yes|no` (API 29 and later; an
older shell answers an error line, which reads as unknown). The font scale
is `system font_scale` (`null` is 1.0). The density is `wm density`, which
prints the physical value and, when one is set, the override; an override
survives a reboot, so the picker's Default row is `wm density reset`.
"""

from . import fmt
from .adb import AdbError

NAMES = ("dark", "font", "density")

LABELS = {"dark": "Dark mode", "font": "Font scale", "density": "Display scale"}

# The steps Android's own font size slider offers (Settings › Display ›
# Display size and text), with the words the older four-stop picker used.
FONT_STEPS = (0.85, 1.0, 1.15, 1.3, 1.5, 1.8, 2.0)
FONT_WORDS = {0.85: "Small", 1.0: "Default", 1.15: "Large", 1.3: "Larger", 1.5: "Largest"}
FONT_MIN, FONT_MAX = 0.5, 3.0

# The ratios of the physical density the Display size slider steps through
# (Settings' DisplayDensityUtils: 0.85 below the default, then steps of
# about 0.15 above it, five stops on a phone); the 1.0 stop is the reset.
DENSITY_STEPS = ((0.85, "Small"), (1.0, "Default"), (1.15, "Large"), (1.3, "Larger"), (1.45, "Largest"))
DENSITY_MIN, DENSITY_MAX = 72, 1000  # `wm density` refuses under 72

READ_SCRIPT = (
    'echo api=$(getprop ro.build.version.sdk); echo night=$(cmd uimode night 2>&1); '
    'echo font=$(settings get system font_scale); wm density 2>&1'
)


def parse_read(text):
    raw = {}
    for line in fmt.lines(text):
        line = line.strip()
        if line.startswith("Physical density:"):
            raw["physical"] = fmt.clean(line.partition(":")[2].strip(), 16)
        elif line.startswith("Override density:"):
            raw["override"] = fmt.clean(line.partition(":")[2].strip(), 16)
        else:
            key, sep, value = line.partition("=")
            if sep:
                raw[key] = fmt.clean(value, 64)
    return raw


def scale_text(value):
    """1 → 1.0, 1.15 → 1.15, 0.85 → 0.85: what `settings put` gets and the row shows."""
    s = f"{value:.2f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def parse_scale(text):
    try:
        v = float(str(text).strip())
    except ValueError:
        return None
    return v if FONT_MIN <= v <= FONT_MAX else None


def parse_density(text):
    try:
        v = int(str(text).strip())
    except ValueError:
        return None
    return v if DENSITY_MIN <= v <= DENSITY_MAX else None


def _dark_state(night):
    """`Night mode: yes|no|auto|custom_*`; anything else (an old shell's
    error line) is unknown."""
    word = (night or "").strip()
    if word.lower().startswith("night mode:"):
        word = word.partition(":")[2].strip().lower()
    else:
        word = ""
    if word == "yes":
        return {"on": True, "text": "on", "mode": word}
    if word == "no":
        return {"on": False, "text": "off", "mode": word}
    if word:
        return {"on": None, "text": fmt.clean(word, 32), "mode": fmt.clean(word, 32)}
    return {"on": None, "text": "unknown", "mode": None}


def _nearest_index(value, values):
    return min(range(len(values)), key=lambda i: abs(values[i] - value))


def font_state(raw):
    text = (raw.get("font") or "").strip()
    value = 1.0 if text in ("", "null") else parse_scale(text)
    steps = []
    for step in FONT_STEPS:
        word = FONT_WORDS.get(step)
        command = "settings put system font_scale " + scale_text(step)
        steps.append({"value": step, "text": scale_text(step), "word": word,
                      "detail": (word + " · " if word else "") + command,
                      "current": value is not None and abs(value - step) < 0.005})
    if value is None:
        shown = "unknown"
    else:
        word = next((s["word"] for s in steps if s["current"] and s["word"]), None)
        shown = scale_text(value) + (" · " + word if word else "")
    return {"value": value, "text": shown, "label": LABELS["font"], "steps": steps}


def density_step(physical, ratio):
    """What Settings does: the physical value scaled, made even."""
    return int(physical * ratio) & ~1


def density_state(raw):
    physical = parse_density(raw.get("physical") or "")
    override = parse_density(raw.get("override") or "")
    value = override if override is not None else physical
    steps = []
    if physical is not None:
        for ratio, word in DENSITY_STEPS:
            reset = ratio == 1.0
            dpi = physical if reset else density_step(physical, ratio)
            steps.append({"value": dpi, "ratio": ratio, "word": word, "reset": reset,
                          "text": f"{dpi} dpi",
                          "detail": (f"{word} · the physical density · wm density reset" if reset
                                     else f"{word} · {int(round(ratio * 100))}% of {physical} · wm density {dpi}"),
                          "current": value == dpi and (override is None if reset else override is not None)})
    if value is None:
        shown = "unknown"
    elif override is None:
        shown = f"{physical} dpi"
    else:
        shown = f"{override} dpi · overridden (physical {physical})"
    return {"value": value, "physical": physical, "override": override, "text": shown,
            "label": LABELS["density"], "steps": steps}


def states(raw):
    dark = _dark_state(raw.get("night"))
    dark["label"] = LABELS["dark"]
    return {"dark": dark, "font": font_state(raw), "density": density_state(raw)}


def api_level(raw):
    try:
        return int(raw.get("api") or 0)
    except ValueError:
        return 0


def read_all(adb, serial):
    raw = parse_read(adb.shell(serial, READ_SCRIPT).text)
    return {"tweaks": states(raw), "api": api_level(raw)}


def _next_font(current):
    if current is None:
        return FONT_STEPS[1]
    i = _nearest_index(current, FONT_STEPS)
    return FONT_STEPS[(i + 1) % len(FONT_STEPS)]


def _next_density(state):
    """The step after the current one, by ratio; `None` means reset."""
    physical = state["physical"]
    if physical is None:
        raise AdbError("adb_failed", "The device did not answer wm density")
    ratios = [r for r, _ in DENSITY_STEPS]
    current = state["value"] / physical if state["value"] else 1.0
    i = _nearest_index(current, ratios)
    ratio = ratios[(i + 1) % len(ratios)]
    return None if ratio == 1.0 else density_step(physical, ratio)


def set_tweak(adb, serial, name, value=None):
    """Set `name` to `value`, or step it (dark: flip; font and density:
    the next step, wrapping); returns the fresh tweaks."""
    if name not in NAMES:
        raise AdbError("bad_args", f"Unknown tweak '{name}'; one of {', '.join(NAMES)}")
    before = read_all(adb, serial)
    state = before["tweaks"][name]
    label = LABELS[name]
    try:
        if name == "dark":
            if value is None:
                target = not (state["on"] is True)
            elif value in ("on", "off"):
                target = value == "on"
            else:
                raise AdbError("bad_args", "tweak dark [on|off]")
            adb.shell(serial, "cmd", "uimode", "night", "yes" if target else "no")
            notice, result = f"{label} {fmt.on_off(target)}", target
        elif name == "font":
            if value is None or value == "next":
                target = _next_font(state["value"])
            else:
                target = parse_scale(value)
                if target is None:
                    raise AdbError("bad_args", f"tweak font takes a scale between {scale_text(FONT_MIN)} and {scale_text(FONT_MAX)}, or next")
            adb.shell(serial, "settings", "put", "system", "font_scale", scale_text(target))
            notice, result = f"{label} {scale_text(target)}", target
        else:
            if value is None or value == "next":
                target = _next_density(state)
            elif value == "reset":
                target = None
            else:
                target = parse_density(value)
                if target is None:
                    raise AdbError("bad_args", f"tweak density takes a dpi between {DENSITY_MIN} and {DENSITY_MAX}, reset, or next")
            if target is None:
                adb.shell(serial, "wm", "density", "reset")
                notice = f"{label} reset" + (f" to {state['physical']} dpi" if state["physical"] else "")
            else:
                adb.shell(serial, "wm", "density", str(target))
                notice = f"{label} {target} dpi"
            result = target
    except AdbError as e:
        if e.code == "bad_args":
            raise
        raise AdbError(e.code, f"Failed to set {label.lower()}: {e.message}", e.stderr) from e
    after = read_all(adb, serial)
    return {"notice": notice, "tweak": name, "value": result, "tweaks": after["tweaks"], "api": after["api"]}
