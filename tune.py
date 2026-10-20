"""Measure this PC and choose the fastest engine settings within a quality budget (writes .gyro-recipe/M.tune.json).

    TUNE.cmd [--model-dir "D:\\models\\Gyro"] [--quality exact|balanced|fast] [--quick] [--confirm] [--dry-run]

Like Strata's tools/calibrate.py it measures on this PC, re-measures the leaders interleaved and keeps a setting only
when it wins by more than 3%. Unlike it, it measures what decides a 12 GB / 32 GB PC's speed: which missed experts may
be skipped (STRATA_ROUTE_TAIL_SKIP, STRATA_FILE_SKIP) and what that costs. Each setting reads a fixed reasoning text
(data/tune-reference.txt) through the real decode windows with STRATA_LOGPOS on, so one run gives its speed and the
exact log-probability of every token: the quality cost is measured, not assumed. The launcher's guards stay on.
"""

import argparse, datetime, json, pathlib, secrets, shutil, socket, statistics, subprocess, sys, threading, time
import urllib.request

import psutil

import tuning
from hardware import resource_info, adapt
from runtime import (check_build, check_config, engine_environment, profile_lock, read_json, require_free_port,
                     stop_owned, write_json)

ROOT = pathlib.Path(__file__).resolve().parent
REFERENCE = ROOT / "data" / "tune-reference.txt"
SHORT_READ = "4096"
CONFIRM_QUESTION = ("\n\nThe text above is part of a code review. Continue it: find two more risks in the same style, "
                    "with a concrete failure scenario and a fix for each.")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Engine:
    """One engine with the installed profile plus `env`/`args` changes, behind the launcher's guards."""

    def __init__(self, ctx, env_changes, pcie, work, logpos=True, short_read=None):
        self.ctx, self.work = ctx, work
        short_read = logpos if short_read is None else short_read
        cfg = json.loads(json.dumps(ctx["cfg"]))
        args = cfg["args"]
        if pcie == "auto":
            if "--pcie-frac" in args:
                i = args.index("--pcie-frac")
                del args[i:i + 2]
        elif pcie is not None and "--pcie-frac" in args:
            args[args.index("--pcie-frac") + 1] = pcie
        if short_read:   # prompts of up to 4096 new tokens go through the decode windows, as replies do
            if "--short-read" in args:
                args[args.index("--short-read") + 1] = SHORT_READ
            else:
                args += ["--short-read", SHORT_READ]
        i = args.index("--expert-profile") + 1
        copy = work / ("expert" + pathlib.Path(args[i]).suffix)
        shutil.copy2(args[i], copy)        # the engine may learn into its profile: never the installed one
        args[i] = str(copy)
        for name in [n for n in cfg if n.startswith("expert_profile_save")]:
            cfg.pop(name)
        values = dict(ctx["values"])
        values.update(env_changes)
        self.logpos = work / "logpos.tsv"
        self.logpos.unlink(missing_ok=True)
        if logpos:
            values.update(STRATA_LOGPOS=str(self.logpos), STRATA_LOGPOS_TOPK="20")
        self.key = secrets.token_urlsafe(32)
        self.port = free_port()
        cfg.update(host="127.0.0.1", port=self.port, log=str(work / "engine.log"), api_key=self.key,
                   open_browser=False, api_monitor=False)
        write_json(work / "config.json", cfg)
        self.cfg = cfg
        env = engine_environment(values, ctx["build"])
        env["PYTHONUNBUFFERED"] = "1"
        self.stop = threading.Event()
        self.tripped = None
        self.peak_vram, self.min_ram = 0, 1e12
        self.seen = {}
        self.log = (work / "server.log").open("w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-m", "serve.server", "--engine", "strata", "--config",
                                      str(work / "config.json"), "--host", "127.0.0.1", "--port", str(self.port)],
                                     cwd=cfg["cwd"], env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.guard = threading.Thread(target=self._guard, daemon=True)
        self.guard.start()
        t0 = time.time()
        while not self._loaded():
            if self.proc.poll() is not None or self.tripped:
                self.close()
                raise RuntimeError("the engine stopped during start-up: " + str(self.tripped or self.proc.returncode)
                                   + f" (see {work / 'engine.log'})")
            if time.time() - t0 > 900:
                self.close()
                raise RuntimeError("the engine did not start within 15 minutes")
            time.sleep(1)

    def _gpu_used(self):
        gpu = self.ctx["hardware"]["gpu"]
        if gpu.get("backend") == "hip":
            from amd import memory_used
            return memory_used(gpu["luid"])
        out = subprocess.check_output(["nvidia-smi", f"--id={gpu['uuid']}", "--query-gpu=memory.used",
                                       "--format=csv,noheader,nounits"], text=True, timeout=10)
        return int(out.splitlines()[0])

    def _guard(self):   # the launcher's guards, unchanged
        while not self.stop.is_set():
            try:
                for child in psutil.Process(self.proc.pid).children(recursive=True):
                    self.seen[child.pid] = child.create_time()
            except psutil.Error:
                pass
            try:
                used = self._gpu_used()
                avail = psutil.virtual_memory().available / 1048576
            except Exception as error:   # telemetry gone: stop, as the launcher does
                self.tripped = "GPU telemetry unavailable: " + repr(error)
            else:
                self.peak_vram, self.min_ram = max(self.peak_vram, used), min(self.min_ram, avail)
                if used > self.ctx["selection"]["gpu_limit_mib"]:
                    self.tripped = f"GPU memory {used} MiB over the guard {self.ctx['selection']['gpu_limit_mib']} MiB"
                elif avail < self.ctx["selection"]["ram_floor_mib"]:
                    self.tripped = f"available RAM {avail:.0f} MiB under the {self.ctx['selection']['ram_floor_mib']} MiB floor"
            if self.tripped:
                stop_owned(self.proc, self.seen)
                return
            self.stop.wait(0.5)

    def _request(self, path, body=None, timeout=10):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def _loaded(self):
        try:
            return bool(self._request("/health", timeout=3).get("loaded"))
        except (OSError, ValueError):
            return False

    def chat(self, content, max_tokens, thinking, sampling):
        body = dict(model=self.cfg["model_name"], messages=[dict(role="user", content=content)],
                    max_tokens=max_tokens, stream=False, chat_template_kwargs=dict(enable_thinking=thinking))
        body.update(sampling)
        try:
            data = self._request("/v1/chat/completions", body, timeout=3600)
        except OSError as error:
            raise RuntimeError("request failed: " + str(self.tripped or error)) from error
        if self.tripped:
            raise RuntimeError(self.tripped)
        return data.get("timings") or {}

    def close(self):
        self.stop.set()
        self.guard.join(timeout=20)   # it records the engine's child processes: let it finish before they are stopped
        stop_owned(self.proc, self.seen)
        self.log.close()


def probe(ctx, env_changes, pcie, say):
    """Speed (tokens/s through the decode windows) and the teacher-forced log-probabilities of the reference."""
    work = ctx["work"]
    eng = Engine(ctx, env_changes, pcie, work)
    try:
        t = eng.chat(ctx["reference"], 1, False, dict(temperature=0, top_p=1, top_k=1, seed=42))
        rows = tuning.parse_logpos(eng.logpos.read_text())
        if not t.get("prompt_ms") or len(rows) < 1000:
            raise RuntimeError("the reference was not read through the decode windows (no STRATA_LOGPOS rows)")
        speed = float(t["prompt_n"]) / (float(t["prompt_ms"]) / 1000.0)
        return speed, rows, dict(peak_vram=eng.peak_vram, min_ram=round(eng.min_ram))
    finally:
        eng.close()


def compare_pcie(ctx, env_changes, base, say, rounds=2):
    """The PCIe share on one engine started without --pcie-frac (the engine's probe and PcieAuto: "auto"); a fixed
    share is sent per request (strata_tune pcie_frac). Speed only, so a shorter text; each read starts with its own
    line so the prompt cache never reuses one, and the order alternates per round to cancel the engine warming up."""
    choices = [base, "auto"] + (["0.55"] if base != "0.55" else [])
    text = ctx["reference"][:4500]
    eng = Engine(ctx, env_changes, "auto", ctx["work"], logpos=False, short_read=True)
    results = {c: [] for c in choices}
    try:
        def read(i, choice):
            sampling = dict(temperature=0, top_p=1, top_k=1, seed=42)
            if choice != "auto":
                sampling["strata_tune"] = {"pcie_frac": float(choice)}
            t = eng.chat(f"Measurement {i}.\n" + text, 1, False, sampling)
            if not t.get("prompt_ms") or (t.get("cache_n") or 0) > 64:
                raise RuntimeError("a PCIe measurement was not read through the decode windows")
            return float(t["prompt_n"]) / (float(t["prompt_ms"]) / 1000.0)

        read(0, "auto")   # two warm-up reads, not counted: the first ones of an engine are the slowest
        read(1, choices[0])
        i = 2
        for rnd in range(rounds):
            for c in (choices if rnd % 2 == 0 else list(reversed(choices))):
                results[c].append(round(read(i, c), 2))
                i += 1
            say(f"  round {rnd + 1}: " + ", ".join(f"{c} {results[c][-1]:.1f}" for c in choices))
    finally:
        eng.close()
    return results


def confirm(ctx, env_changes, pcie, say):
    """A real reasoning reply (thinking on, the profile's sampling): its decode tok/s."""
    eng = Engine(ctx, env_changes, pcie, ctx["work"], logpos=False)
    try:
        sampling = {k: v for k, v in ctx["cfg"].get("sampling", {}).items() if k != "penalty_last_n"}
        t = eng.chat(ctx["reference"] + CONFIRM_QUESTION, 2048, True, dict(sampling, seed=42))
        return round(float(t.get("predicted_per_second") or 0), 2)
    finally:
        eng.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", help="the folder with the weights (default: the one DOWNLOAD-MODEL.cmd selected)")
    ap.add_argument("--profile", default="M")
    ap.add_argument("--quality", choices=sorted(tuning.BUDGETS), default="balanced",
                    help="exact: no skipping; balanced (default): mean NLL +0.020 at most; fast: +0.035 at most")
    ap.add_argument("--quick", action="store_true", help="every setting once, without re-measuring or the PCIe step")
    ap.add_argument("--thorough", action="store_true",
                    help="all nine settings, the leaders re-measured twice (the slower 1.2.0 search)")
    ap.add_argument("--confirm", action="store_true", help="also time a real 2,048-token reasoning reply, off vs chosen")
    ap.add_argument("--dry-run", action="store_true", help="measure and print; do not write the tuning file")
    ap.add_argument("--skip-if-current", action="store_true",
                    help="do nothing when a tuning file for this PC, engine patch and quality level already exists")
    o = ap.parse_args()
    from setup import select_model_directory   # the same choice INSTALL.cmd makes on a double-click
    recipe = select_model_directory(o.model_dir, ROOT / ".model-dir") / ".gyro-recipe"
    path = recipe / f"{o.profile}.json"
    if not path.is_file():
        raise RuntimeError("Installed profile is missing. Run INSTALL.cmd with this model folder first.")
    if not REFERENCE.is_file():
        raise RuntimeError("data/tune-reference.txt is missing. Extract a fresh copy of this release.")
    with profile_lock(recipe):
        cfg = read_json(path)
        require_free_port(cfg["host"], cfg["port"])   # the model must not be running while it is measured
        backend = cfg.get("_recipe_backend", "cuda")
        hardware = resource_info(cfg.get("_recipe_gpu_index", 0), backend if backend == "hip" else None)
        build = check_build(hardware)
        check_config(cfg)
        cfg, values, selection = adapt(cfg, read_json(path.with_suffix(".env.json")), hardware,
                                       cfg.get("_recipe_workers"), cfg.get("_recipe_tuning"))
        if o.skip_if_current:
            try:
                saved = tuning.load_overlay(recipe / f"{o.profile}.tune.json")
                tuning.validate(saved)
            except (OSError, ValueError, TypeError):
                saved = None
            if (saved and saved.get("quality") == o.quality and
                    saved.get("fingerprint") == tuning.fingerprint(hardware, read_json(ROOT / "pins.json")) and
                    selection["ram_experts_gib"] >= saved["ram_experts_gib"]):
                print(f"Tuning is current for this PC ({saved.get('chosen')}, {saved.get('date')}); "
                      "run TUNE.cmd to measure again.", flush=True)
                return 0
        work = recipe / "tune"
        work.mkdir(exist_ok=True)
        (work / "engine.log").unlink(missing_ok=True)   # the server appends: keep only this run's starts
        ctx = dict(cfg=cfg, values=values, selection=selection, hardware=hardware, build=build, work=work,
                   reference=REFERENCE.read_text(encoding="utf-8"))
        return run(ctx, o, recipe, read_json(ROOT / "pins.json"))


def run(ctx, o, recipe, pins):
    log = []

    def say(s):
        log.append(s)
        print(s, flush=True)

    t_start = time.time()
    gpu = ctx["hardware"]["gpu"]
    say(f"Tuning {o.profile} on {gpu['name']} ({gpu['total_mib']} MiB), {ctx['hardware']['ram_gib']:.0f} GiB RAM, "
        f"{ctx['hardware']['physical_cores']} cores, {ctx['selection']['ram_experts_gib']} GiB of experts in RAM; "
        f"quality level {o.quality} "
        f"(mean NLL +{tuning.BUDGETS[o.quality]:.3f} at most)")
    results, ref_rows, arms, file_tier = {}, None, {}, None
    say("Step 1: each setting that can win here, once (speed through the decode windows, quality against skips off)")
    queue = [(0, 0)]
    while queue:
        arm = queue.pop(0)
        name = tuning.arm_name(arm)
        arms[name] = arm
        try:
            speed, rows, mem = probe(ctx, tuning.arm_env(arm), None, say)
        except RuntimeError as error:
            if ref_rows is None:
                raise   # without skips-off there is nothing to compare with
            results[name] = dict(arm=list(arm), speeds=[], quality=None, error=str(error))
            say(f"  {name:12s} failed, left out: {error}")
            continue
        if ref_rows is None:   # skips off: the reference; its start-up log says whether experts spill to the SSD
            ref_rows = rows
            file_tier = tuning.file_tier_from_log((ctx["work"] / "engine.log").read_text(encoding="utf-8", errors="replace"))
            queue = tuning.arms_for(o.quality, file_tier, o.thorough)[1:]
            say("  experts on the SSD: " + {True: "yes (file-skip settings)", False: "no (tail-skip settings)",
                                            None: "unknown (file-skip settings)"}[file_tier])
        q = tuning.quality(ref_rows, rows)
        results[name] = dict(arm=list(arm), speeds=[round(speed, 2)], quality=q, memory=mem)
        say(f"  {name:12s} {speed:6.1f} tok/s  dNLL {q['d_nll']:+.4f}  top-1 {q['top1']:.3f}  KL {q['kl']:.4f}"
            f"{'' if tuning.feasible(q, o.quality) else '  (over the quality budget)'}")
    if not o.quick:
        ok = sorted((n for n, r in results.items() if r["speeds"] and tuning.feasible(r["quality"], o.quality)),
                    key=lambda n: -results[n]["speeds"][0])
        gap = results[ok[0]]["speeds"][0] / results[ok[1]]["speeds"][0] - 1 if len(ok) > 1 else None
        if gap is not None and (o.thorough or tuning.RECHECK[0] <= gap <= tuning.RECHECK[1]):
            lead = ok[:3] if o.thorough else ok[:2]
            say(f"Step 2: the leaders again ({', '.join(lead)}; {gap:.1%} apart, close to the 3% rule)")
            for rnd in range(2 if o.thorough else 1):
                for name in (lead if rnd % 2 else list(reversed(lead))):
                    try:
                        speed, _, _ = probe(ctx, tuning.arm_env(arms[name]), None, say)
                        results[name]["speeds"].append(round(speed, 2))
                    except RuntimeError as error:
                        say(f"  {name} failed: {error}")
                say("  again: " + ", ".join(f"{n} {results[n]['speeds'][-1]:.1f}" for n in lead))
    chosen = tuning.pick(results, o.quality)
    say(f"Chosen: {chosen} (median {statistics.median(results[chosen]['speeds']):.1f} tok/s through the windows, "
        f"dNLL {results[chosen]['quality']['d_nll']:+.4f})")
    pcie, pcie_results = None, {}
    args = ctx["cfg"]["args"]
    if not o.quick and gpu.get("backend", "cuda") == "cuda" and "--pcie-frac" in args:
        base = args[args.index("--pcie-frac") + 1]
        say(f"Step 3: the PCIe share at {chosen}: {base} (the profile's), the engine's own probe (auto) and 0.55, "
            "on one engine")
        try:
            pcie_results = compare_pcie(ctx, tuning.arm_env(arms[chosen]), base, say)
        except RuntimeError as error:   # an incomplete comparison keeps the profile's share
            say(f"  a PCIe measurement failed ({error}); keeping {base}")
        else:
            ref = statistics.median(pcie_results[base])
            best = max(pcie_results, key=lambda v: statistics.median(pcie_results[v]))
            gains = [b / a - 1 for a, b in zip(pcie_results[base], pcie_results[best])]
            if best != base and statistics.median(pcie_results[best]) > ref * (1 + tuning.MIN_GAIN) and min(gains) > 0:
                pcie = best
        say("  PCIe share: " + (pcie or f"{base} (kept: no setting was faster in every round and by more than 3% at the median)"))
    confirmed = None
    if o.confirm:
        say("Step 4: a real 2,048-token reasoning reply, skips off vs chosen")
        try:
            confirmed = dict(off=confirm(ctx, tuning.arm_env((0, 0)), None, say),
                             chosen=confirm(ctx, tuning.arm_env(arms[chosen]), pcie, say))
            say(f"  decode: off {confirmed['off']} tok/s, {chosen} {confirmed['chosen']} tok/s")
        except RuntimeError as error:
            say(f"  the confirmation reply failed ({error}); the measured choice is kept")
    overlay = dict(version=tuning.VERSION, quality=o.quality, chosen=chosen,
                   date=datetime.date.today().isoformat(), env=tuning.arm_env(arms[chosen]),
                   ram_experts_gib=int(ctx["selection"]["ram_experts_gib"]),
                   args={"--pcie-frac": pcie} if pcie else {},
                   fingerprint=tuning.fingerprint(ctx["hardware"], pins), arms=results, pcie=pcie_results,
                   confirm=confirmed, minutes=round((time.time() - t_start) / 60, 1))
    tuning.validate(overlay)
    write_json(ctx["work"] / "last-run.json", overlay)
    (ctx["work"] / "last-run.txt").write_text("\n".join(log), encoding="utf-8")
    if o.dry_run:
        say("Dry run: nothing written to " + str(recipe / f"{o.profile}.tune.json"))
    else:
        write_json(recipe / f"{o.profile}.tune.json", overlay)
        say("Saved " + str(recipe / f"{o.profile}.tune.json") + "; the launcher applies it from the next start.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print("Tuning stopped:", error, file=sys.stderr)
        sys.exit(1)
