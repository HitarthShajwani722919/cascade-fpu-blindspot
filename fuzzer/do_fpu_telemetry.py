# FPU Telemetry Script - baseline vs enhanced instruction frequency comparison
#
# Usage (from /cascade-meta/fuzzer/, after source /cascade-meta/env.sh):
#
#   Baseline run:
#   python3 do_fpu_telemetry.py run --design cva6 --runs 300 --out /tmp/baseline.json --label baseline
#
#   Enhanced run (after patching the weight files):
#   python3 do_fpu_telemetry.py run --design cva6 --runs 300 --out /tmp/enhanced.json --label enhanced
#
#   Plot both:
#   python3 do_fpu_telemetry.py plot /tmp/baseline.json /tmp/enhanced.json --out /tmp/fpu_comparison.png

import argparse
import json
import os
import random
import sys

def parse_args():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")

    run_p = sub.add_parser("run")
    run_p.add_argument("--runs",   type=int, default=200)
    run_p.add_argument("--design", type=str, default="cva6")
    run_p.add_argument("--out",    type=str, required=True)
    run_p.add_argument("--seed",   type=int, default=42)
    run_p.add_argument("--label",  type=str, default="")

    plot_p = sub.add_parser("plot")
    plot_p.add_argument("files", nargs=2)
    plot_p.add_argument("--out",  type=str, default="fpu_comparison.png")
    plot_p.add_argument("--topn", type=int, default=30)

    return p.parse_args()


def run_telemetry(args):
    from cascade.randomize.pickinstrtype import get_instr_counts, reset_instr_counts
    from cascade.fuzzerstate import FuzzerState
    from cascade.basicblock import gen_basicblocks
    from common.designcfgs import get_design_boot_addr, design_has_float_support, is_design_32bit
    #from common.designcfgs import get_design_boot_addr, get_design_num_pickable_regs, get_design_num_pickable_float_regs, get_design_has_fpu, get_design_memsize
    from params.fuzzparams import PROBA_AUTHORIZE_PRIVILEGES

    design_name = args.design
    boot_addr   = get_design_boot_addr(design_name)

    reset_instr_counts()
    print(f"[telemetry] Generating {args.runs} programs for design '{design_name}' ...")

    failed = 0
    for i in range(args.runs):
        seed = args.seed + i
        random.seed(seed)
        try:
            memsize  = 2 * 1024 * 1024
            #memsize  = get_design_memsize(design_name)
            num_bbs  = random.randrange(20, 100)
            auth_priv = random.random() < PROBA_AUTHORIZE_PRIVILEGES
            fs = FuzzerState(boot_addr, design_name, memsize, seed, num_bbs, auth_priv)
            gen_basicblocks(fs)
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  [warn] seed {seed} failed: {e}")
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{args.runs} done ({failed} failures so far)")

    counts = get_instr_counts()
    output = {
        "_meta": {
            "label":        args.label or args.out,
            "design":       design_name,
            "runs":         args.runs,
            "seed":         args.seed,
            "failures":     failed,
            "total_instrs": sum(counts.values()),
        },
        "counts": counts,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(output, f, indent=2, sort_keys=True)
    print(f"[telemetry] Saved to {args.out} ({sum(counts.values())} instructions, {failed} failures)")


def plot_comparison(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    with open(args.files[0]) as f: data_a = json.load(f)
    with open(args.files[1]) as f: data_b = json.load(f)

    label_a  = data_a.get("_meta", {}).get("label", "baseline")
    label_b  = data_b.get("_meta", {}).get("label", "enhanced")
    counts_a = data_a.get("counts", data_a)
    counts_b = data_b.get("counts", data_b)
    runs_a   = data_a.get("_meta", {}).get("runs", 1)
    runs_b   = data_b.get("_meta", {}).get("runs", 1)

    FPU_PREFIXES = ("fadd", "fsub", "fmul", "fdiv", "fsqrt",
                    "fmin", "fmax", "fmadd", "fmsub", "fnmadd", "fnmsub",
                    "fcvt", "fmv", "feq", "flt", "fle", "fclass", "fsgnj",
                    "flw", "fsw", "fld", "fsd")

    all_keys = set(counts_a.keys()) | set(counts_b.keys())
    fpu_keys = sorted(k for k in all_keys if any(k.startswith(p) for p in FPU_PREFIXES))

    combined = {k: counts_a.get(k, 0)/runs_a + counts_b.get(k, 0)/runs_b for k in fpu_keys}
    top_keys = sorted(fpu_keys, key=lambda k: combined[k], reverse=True)[:args.topn]

    vals_a = [counts_a.get(k, 0) / runs_a for k in top_keys]
    vals_b = [counts_b.get(k, 0) / runs_b for k in top_keys]

    x     = list(range(len(top_keys)))
    width = 0.38

    fig, ax = plt.subplots(figsize=(max(12, len(top_keys) * 0.55), 6))
    ax.bar([i - width/2 for i in x], vals_a, width, label=label_a, color="#5B8DB8", alpha=0.85)
    ax.bar([i + width/2 for i in x], vals_b, width, label=label_b, color="#E8854A", alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(top_keys, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Avg instructions per program")
    ax.set_title(f"FPU instruction frequency: {label_a} vs {label_b}")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    # Annotate bars with >50% increase
    for i, k in enumerate(top_keys):
        a, b = vals_a[i], vals_b[i]
        if a > 0 and (b - a) / a > 0.5:
            ax.annotate(f"+{(b-a)/a*100:.0f}%",
                        xy=(x[i] + width/2, b),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=7, color="#C0392B")

    plt.tight_layout()
    plt.savefig(args.out, dpi=150)
    print(f"[plot] Saved to {args.out}")

    print(f"\n{'Instruction':<20} {label_a:>12} {label_b:>12} {'Ratio':>8}")
    print("-" * 56)
    for k in top_keys:
        a = counts_a.get(k, 0) / runs_a
        b = counts_b.get(k, 0) / runs_b
        ratio = f"{b/a:.2f}x" if a > 0 else "new"
        print(f"{k:<20} {a:>12.3f} {b:>12.3f} {ratio:>8}")


def main():
    args = parse_args()
    if args.cmd == "run":
        run_telemetry(args)
    elif args.cmd == "plot":
        plot_comparison(args)
    else:
        print("Usage: do_fpu_telemetry.py run --help  |  do_fpu_telemetry.py plot --help")

if __name__ == "__main__":
    main()
