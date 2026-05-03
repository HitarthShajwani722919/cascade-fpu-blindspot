# Full pipeline comparison: baseline vs enhanced
# Runs complete Spike + RTL sim and tracks mismatches
#
# Usage:
#   python3 do_fpu_fullrun.py --design cva6 --runs 300 --seed 42 --label baseline --out /tmp/fullrun_baseline.json
#   python3 do_fpu_fullrun.py --design cva6 --runs 300 --seed 42 --label enhanced --out /tmp/fullrun_enhanced.json

import argparse
import json
import os
import random
import time

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--runs",   type=int, default=100)
    p.add_argument("--design", type=str, default="cva6")
    p.add_argument("--seed",   type=int, default=42)
    p.add_argument("--label",  type=str, default="")
    p.add_argument("--out",    type=str, required=True)
    return p.parse_args()

def main():
    args = parse_args()

    from cascade.fuzzfromdescriptor import fuzz_single_from_descriptor
    from common.profiledesign import profile_get_medeleg_mask
    from common.spike import calibrate_spikespeed

    calibrate_spikespeed()
    profile_get_medeleg_mask(args.design)

    design_name = args.design
    runs        = args.runs

    results = {
        "total":      0,
        "mismatches": 0,
        "failures":   0,
        "timings":    [],
        "mismatch_seeds": [],
    }

    print(f"[fullrun] {args.label} — {runs} runs on {design_name}")

    for i in range(runs):
        seed = args.seed + i
        random.seed(seed)
        memsize = random.randrange(1 << 14, 1 << 20)
        nmax_bbs = random.randrange(20, 100)
        auth_priv = True

        try:
            t0 = time.time()
            result = fuzz_single_from_descriptor(
                memsize, design_name, seed, nmax_bbs, auth_priv,
                check_pc_spike_again=True
            )
            elapsed = time.time() - t0
            results["timings"].append(elapsed)
            results["total"] += 1

            # fuzz_single_from_descriptor raises an exception on mismatch,
            # so if we get here it completed cleanly
        except SystemExit:
            # SystemExit is raised when a mismatch is found
            results["mismatches"] += 1
            results["mismatch_seeds"].append(seed)
            results["total"] += 1
            print(f"  [!] MISMATCH at seed {seed}")
        except Exception as e:
            results["failures"] += 1
            if results["failures"] <= 5:
                print(f"  [warn] seed {seed} failed: {e}")

        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{runs} — mismatches: {results['mismatches']}, failures: {results['failures']}")

    # Summary
    avg_time = sum(results["timings"]) / len(results["timings"]) if results["timings"] else 0
    results["avg_time_per_run"] = avg_time
    results["mismatch_rate"] = results["mismatches"] / results["total"] if results["total"] else 0

    output = {
        "_meta": {
            "label":          args.label or args.out,
            "design":         design_name,
            "runs":           runs,
            "seed":           args.seed,
            "mismatches":     results["mismatches"],
            "failures":       results["failures"],
            "mismatch_rate":  results["mismatch_rate"],
            "avg_time_per_run_s": avg_time,
        },
        "mismatch_seeds": results["mismatch_seeds"],
        "timings": results["timings"],
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[fullrun] Done. Mismatches: {results['mismatches']}/{results['total']} "
          f"({results['mismatch_rate']*100:.1f}%) — avg {avg_time:.2f}s/run")
    print(f"[fullrun] Saved to {args.out}")

if __name__ == "__main__":
    if "CASCADE_ENV_SOURCED" not in os.environ:
        raise Exception("Run: source /cascade-meta/env.sh first")
    main()