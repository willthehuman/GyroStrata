"""The tuner's selection rule and the launcher's tuning overlay; no GPU required."""

import json, pathlib, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tuning

HW = dict(gpu=dict(name="TEST", total_mib=12280, uuid="GPU-TEST"), physical_cores=16, ram_gib=31.9)
SEL = dict(ram_experts_gib=13)
PINS = json.loads((ROOT / "pins.json").read_text())


def overlay(**changes):
    o = dict(version=tuning.VERSION, quality="balanced", chosen="file3+tail6", date="2026-10-19",
             env={"STRATA_ROUTE_TAIL_SKIP": "6", "STRATA_FILE_SKIP": "3"}, args={},
             ram_experts_gib=13, fingerprint=tuning.fingerprint(HW, PINS))
    o.update(changes)
    return o


def cfg():
    return dict(args=["--spec", "4", "--pcie-frac", "0.75", "--kv", "q4_0"])


class Selection(unittest.TestCase):
    def results(self):
        q = lambda d, kl: dict(tokens=3357, d_nll=d, top1=0.9, kl=kl)
        return {
            "off": dict(speeds=[27, 24, 26], quality=q(0, 0)),
            "tail7": dict(speeds=[35], quality=q(0.0004, 0.024)),
            "file3+tail6": dict(speeds=[72, 70, 73], quality=q(0.0164, 0.048)),
            "file2+tail7": dict(speeds=[74, 73, 74], quality=q(0.0283, 0.055)),
            "file3": dict(speeds=[60, 61, 60], quality=q(0.0105, 0.034)),
        }

    def test_quality_levels(self):
        r = self.results()
        self.assertEqual(tuning.pick(r, "exact"), "off")
        self.assertEqual(tuning.pick(r, "balanced"), "file3+tail6")   # file2+tail7 is over the 0.020 budget
        # fast: file2+tail7 is under 3% faster than file3+tail6, which has the better quality
        self.assertEqual(tuning.pick(r, "fast"), "file3+tail6")

    def test_clear_gain_wins(self):
        r = self.results()
        r["file2+tail7"]["speeds"] = [80, 81, 79]
        self.assertEqual(tuning.pick(r, "fast"), "file2+tail7")

    def test_nothing_fits(self):
        with self.assertRaises(ValueError):
            tuning.pick({"tail3": dict(speeds=[50], quality=dict(d_nll=0.06, kl=0.09, top1=0.85))}, "balanced")

    def test_quality_from_logpos(self):
        ref = tuning.parse_logpos("0\t5\t-1.0\t5\t-1.0\t1\tnan\tnan\t5:-1.0\t6:-2.0\n"
                                  "1\t7\t-0.5\t7\t-0.5\t1\tnan\tnan\t7:-0.5\t8:-1.5\n")
        same = tuning.quality(ref, ref)
        self.assertEqual((same["d_nll"], same["top1"], same["kl"]), (0.0, 1.0, 0.0))
        arm = tuning.parse_logpos("0\t5\t-2.0\t6\t-0.5\t0\tnan\tnan\t6:-0.5\t5:-2.0\n"
                                  "1\t7\t-0.5\t7\t-0.5\t1\tnan\tnan\t7:-0.5\t8:-1.5\n")
        q = tuning.quality(ref, arm)
        self.assertAlmostEqual(q["d_nll"], 0.5)
        self.assertEqual(q["top1"], 0.5)
        self.assertGreater(q["kl"], 0)

    def test_settings_follow_the_ssd_tier(self):
        line = "FileExpertSource: RAM budget {} GiB: 10691 of the 26.31 GiB of experts the GPU cache does not hold"
        self.assertTrue(tuning.file_tier_from_log(line.format("13.00")))
        self.assertFalse(tuning.file_tier_from_log(line.format("13.00") + "\n" + line.format("27.00")))   # latest start
        self.assertIsNone(tuning.file_tier_from_log("no such line"))
        names = lambda arms: [tuning.arm_name(a) for a in arms]
        self.assertEqual(tuning.arms_for("exact", True), [(0, 0)])
        for tier in (True, None):   # unknown: the SSD tier is assumed
            self.assertEqual(names(tuning.arms_for("balanced", tier))[0], "off")
            self.assertIn("file3+tail6", names(tuning.arms_for("balanced", tier)))
        self.assertTrue(all(file == 0 for _, file in tuning.arms_for("fast", False)))
        self.assertEqual(len(tuning.arms_for("balanced", True, thorough=True)), 9)

    def test_every_arm_has_valid_env(self):
        for arm in tuning.ARMS:
            tuning.validate(overlay(env=tuning.arm_env(arm)))
        self.assertIn(tuning.DEFAULT_ARM, tuning.ARMS)


class Overlay(unittest.TestCase):
    def test_applies_on_matching_pc(self):
        c, env = cfg(), {"STRATA_ROUTE_TAIL_SKIP": "0"}
        note = tuning.apply_overlay(c, env, overlay(args={"--pcie-frac": "auto"}), HW, PINS, SEL)
        self.assertIn("file3+tail6", note)
        self.assertEqual(env["STRATA_ROUTE_TAIL_SKIP"], "6")
        self.assertNotIn("--pcie-frac", c["args"])
        c = cfg()
        tuning.apply_overlay(c, {}, overlay(args={"--pcie-frac": "0.55"}), HW, PINS, SEL)
        self.assertEqual(c["args"][c["args"].index("--pcie-frac") + 1], "0.55")

    def test_ignored_on_other_hardware_or_patch(self):
        for hw in [dict(HW, ram_gib=63.9), dict(HW, gpu=dict(HW["gpu"], name="OTHER"))]:
            c, env = cfg(), {}
            self.assertIn("ignored", tuning.apply_overlay(c, env, overlay(), hw, PINS, SEL))
            self.assertEqual((c, env), (cfg(), {}))
        pins = json.loads(json.dumps(PINS))
        pins["strata"]["patch_sha256"] = "0" * 64
        self.assertIn("ignored", tuning.apply_overlay(cfg(), {}, overlay(), HW, pins, SEL))

    def test_rejects_unsafe_content(self):
        for bad in [overlay(version=99), overlay(env={"STRATA_RAM_FLOOR": "0"}),
                    overlay(args={"--vram-reserve-mib": "0"}), overlay(args={"--pcie-frac": "2"}),
                    overlay(env={"STRATA_FILE_SKIP": "x"}), "not an object",
                    overlay(env={"STRATA_FILE_SKIP": 3}), overlay(env=["STRATA_FILE_SKIP"]), overlay(args="0.5"),
                    overlay(args={"--pcie-frac": 0.5}), overlay(args={"--pcie-frac": "nan"}),
                    overlay(ram_experts_gib=None), overlay(ram_experts_gib="13"), overlay(version=1)]:
            c, env = cfg(), {}
            self.assertIn("ignored", tuning.apply_overlay(c, env, bad, HW, PINS, SEL))
            self.assertEqual((c, env), (cfg(), {}))

    def test_not_applied_with_a_smaller_ram_tier(self):
        # fewer experts in RAM means more on the SSD: the measured file-skip quality no longer holds
        c, env = cfg(), {}
        note = tuning.apply_overlay(c, env, overlay(), HW, PINS, dict(ram_experts_gib=12))
        self.assertIn("not applied", note)
        self.assertEqual((c, env), (cfg(), {}))
        c, env = cfg(), {}
        self.assertIn("file3+tail6", tuning.apply_overlay(c, env, overlay(), HW, PINS, dict(ram_experts_gib=14)))
        self.assertEqual(env["STRATA_FILE_SKIP"], "3")

    def test_missing_or_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            profile = pathlib.Path(d) / "M.json"
            self.assertIn("none", tuning.apply_file(cfg(), {}, profile, HW, SEL))
            profile.with_suffix(".tune.json").write_text("{broken")
            self.assertIn("ignored", tuning.apply_file(cfg(), {}, profile, HW, SEL))


if __name__ == "__main__":
    unittest.main()
