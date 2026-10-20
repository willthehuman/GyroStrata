"""Per-PC tuning: the search space, the selection rule and the overlay the launcher applies (tune.py measures).

The overlay lives in .gyro-recipe/<profile>.tune.json, which INSTALL never deletes. It is applied after adapt() and
only when the PC still matches the one it was measured on (GPU, RAM, CPU cores, engine patch).
"""

import json, math, pathlib, statistics

VERSION = 2   # 2: records the RAM expert tier it was measured with (ram_experts_gib)
MIN_GAIN = 0.03   # as Strata's calibrate: a faster setting must beat a better-quality one by more than this
# mean teacher-forced NLL increase allowed over skips off, per quality level (measured 2026-10-19: tail 7 +0.0004,
# file 3 + tail 6 +0.016, file 2 + tail 7 +0.028, tail 3 +0.061)
BUDGETS = {"exact": 0.0, "balanced": 0.020, "fast": 0.035}
# (STRATA_ROUTE_TAIL_SKIP, STRATA_FILE_SKIP): 0 = off. Rank R skips an expert every token routes at rank R..9 of 10.
ARMS = [(0, 0), (7, 0), (6, 0), (5, 0), (0, 3), (7, 3), (6, 3), (7, 2), (6, 2)]   # --thorough
# The default search measures only the settings that can win on the PC at hand (four full runs on the reference PC:
# while experts spill to the SSD, every tail-only setting was slower than a file-skip setting of equal or better
# quality; with no SSD tier the file skip does nothing and only the tail rank matters).
ARMS_FILE_TIER = [(0, 0), (0, 3), (7, 3), (6, 3), (7, 2), (6, 2)]
ARMS_NO_FILE_TIER = [(0, 0), (7, 0), (6, 0), (5, 0), (4, 0)]
DEFAULT_ARM = (6, 3)   # what the shipped profile uses
RECHECK = (0.015, 0.045)   # re-measure the two fastest when their gap could flip the 3% rule


def arms_for(level, file_tier, thorough=False):
    """The settings to measure: skips off first (the quality reference)."""
    if level == "exact":
        return [(0, 0)]
    if thorough:
        return list(ARMS)
    return list(ARMS_FILE_TIER if file_tier is not False else ARMS_NO_FILE_TIER)


def file_tier_from_log(text):
    """True when the engine reads some experts from the SSD, False when the RAM copy holds every expert the GPU cache
    does not, None when its start-up log does not say (then the SSD tier is assumed)."""
    import re
    found = re.findall(r"RAM budget ([\d.]+) GiB: \d+ of the ([\d.]+) GiB of experts the GPU cache does not hold", text)
    if not found:
        return None
    budget, total = found[-1]   # the latest start (the log is appended to)
    return float(budget) + 0.05 < float(total)
PCIE_CHOICES = ("0.75", "auto", "0.55")
ENV_KEYS = ("STRATA_ROUTE_TAIL_SKIP", "STRATA_FILE_SKIP")


def arm_name(arm):
    tail, file = arm
    parts = ([f"file{file}"] if file else []) + ([f"tail{tail}"] if tail else [])
    return "+".join(parts) or "off"


def arm_env(arm):
    return {"STRATA_ROUTE_TAIL_SKIP": str(arm[0]), "STRATA_FILE_SKIP": str(arm[1]) if arm[1] else ""}


def quality(ref_rows, rows):
    """dNLL, top-1 agreement and KL(ref || arm) on the reference's top-20, from STRATA_LOGPOS rows
    {pos: (logprob of the text's token, argmax, {token: logprob})}."""
    pos = sorted(set(ref_rows) & set(rows))
    if not pos:
        raise ValueError("no common positions to compare")
    kl = agree = dnll = 0.0
    for p in pos:
        r_lp, r_arg, r_top = ref_rows[p]
        q_lp, q_arg, q_top = rows[p]
        floor = min(q_top.values()) if q_top else -30.0
        kl += sum(math.exp(lr) * (lr - q_top.get(t, floor)) for t, lr in r_top.items())
        agree += r_arg == q_arg
        dnll += r_lp - q_lp
    n = len(pos)
    return dict(tokens=n, d_nll=round(dnll / n, 5), top1=round(agree / n, 4), kl=round(kl / n, 5))


def parse_logpos(text):
    rows = {}
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 8:
            continue
        top = {int(a): float(b) for a, b in (x.split(":") for x in f[8:])}
        rows[int(f[0])] = (float(f[2]), int(f[3]), top)
    return rows


def feasible(q, level):
    budget = BUDGETS[level]
    return q["d_nll"] <= budget + 1e-9 and q["kl"] <= 2.5 * budget + 0.01 if budget > 0 else q["d_nll"] == 0 and q["kl"] == 0


def pick(results, level, min_gain=MIN_GAIN):
    """results: {name: {"speeds": [tok/s...], "quality": {...}}}. The fastest feasible arm by median speed, unless a
    feasible arm with lower dNLL is within min_gain of it (quality wins near-ties)."""
    ok = {n: r for n, r in results.items() if r.get("speeds") and feasible(r["quality"], level)}
    if not ok:
        raise ValueError("no setting fits the quality level " + level)
    speed = {n: statistics.median(r["speeds"]) for n, r in ok.items()}
    best = max(speed, key=speed.get)
    for n in sorted(ok, key=lambda n: ok[n]["quality"]["d_nll"]):
        if speed[best] <= speed[n] * (1 + min_gain):
            return n
    return best


def fingerprint(hardware, pins):
    gpu = hardware["gpu"]
    return dict(gpu=gpu["name"], gpu_mib=int(gpu["total_mib"]), ram_gib=round(hardware["ram_gib"]),
                cores=int(hardware["physical_cores"]), patch_sha256=pins["strata"]["patch_sha256"])


def load_overlay(path):
    path = pathlib.Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(overlay):
    if not isinstance(overlay, dict) or overlay.get("version") != VERSION:
        raise ValueError("unknown tuning file version")
    env, args = overlay.get("env", {}), overlay.get("args", {})
    if not isinstance(env, dict) or not isinstance(args, dict):
        raise ValueError("tuning file is malformed")
    ram = overlay.get("ram_experts_gib")
    if isinstance(ram, bool) or not isinstance(ram, int) or not 0 <= ram <= 64:
        raise ValueError("tuning file has no valid RAM expert tier")
    if set(env) - set(ENV_KEYS) or set(args) - {"--pcie-frac"}:
        raise ValueError("tuning file has settings it may not change")
    for k, v in env.items():
        if not isinstance(v, str) or (v != "" and not (v.isdigit() and 0 <= int(v) <= 9)):
            raise ValueError(k + " must be a rank from 0 to 9, as text")
    if "--pcie-frac" in args:
        v = args["--pcie-frac"]
        if not isinstance(v, str) or (v != "auto" and not (math.isfinite(float(v)) and 0.0 <= float(v) <= 1.0)):
            raise ValueError("--pcie-frac must be auto or a number from 0 to 1, as text")


def apply_file(cfg, env, profile_path, hardware, selection):
    """The launcher's entry: <profile>.tune.json beside the installed profile, when present and valid."""
    root = pathlib.Path(__file__).resolve().parent
    try:
        overlay = load_overlay(pathlib.Path(profile_path).with_suffix(".tune.json"))
        pins = json.loads((root / "pins.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        return f"tuning: ignored (unreadable tuning file: {error})"
    return apply_overlay(cfg, env, overlay, hardware, pins, selection)


def apply_overlay(cfg, env, overlay, hardware, pins, selection):
    """Returns a note for the launcher's output. cfg/env are changed in place; nothing applies on a mismatch."""
    if overlay is None:
        return "tuning: none (run TUNE.cmd to measure this PC)"
    try:
        validate(overlay)
    except (ValueError, TypeError) as error:
        return f"tuning: ignored ({error}; run TUNE.cmd again)"
    if overlay.get("fingerprint") != fingerprint(hardware, pins):
        return "tuning: ignored (measured on different hardware or another engine patch; run TUNE.cmd again)"
    # The file skip drops experts that are in neither VRAM nor RAM. With a smaller RAM tier than when it was measured,
    # more experts are on the SSD and the measured quality cost no longer holds: use the profile's defaults instead.
    if selection["ram_experts_gib"] < overlay["ram_experts_gib"]:
        return (f"tuning: not applied (RAM experts {selection['ram_experts_gib']} GiB now, {overlay['ram_experts_gib']} GiB "
                "when measured; close memory-heavy apps before starting); using the profile's defaults")
    env.update(overlay.get("env", {}))
    v = overlay.get("args", {}).get("--pcie-frac")
    args = cfg["args"]
    if v is not None and "--pcie-frac" in args:
        i = args.index("--pcie-frac")
        if v == "auto":
            del args[i:i + 2]
        else:
            args[i + 1] = v
    share = f", PCIe share {v}" if v is not None else ""
    return f"tuning: {overlay.get('chosen', '?')}{share} ({overlay.get('quality', '?')}), measured {overlay.get('date', '?')}"
