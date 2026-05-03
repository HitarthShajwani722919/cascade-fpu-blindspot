# cascade-fpu-blindspot

> Demonstrating a structural FPU blind spot in [Cascade](https://comsec.ethz.ch/wp-content/files/cascade_sec24.pdf) (USENIX Security '24) — bugs where the RTL computes correct values but wrong IEEE 754 exception flags are completely invisible to the original oracle.

---

## Background

**Cascade** is a differential fuzzer for RISC-V CPUs. It generates random programs, runs them through the **Spike ISA simulator** (golden reference), and compares register values against **RTL simulation** (Verilator). Mismatches = bugs.

This project identifies and demonstrates two structural gaps in Cascade's FPU testing:

1. **No special value injection** — FP registers are loaded from random memory bytes. The probability of accidentally generating a NaN (`0x7FC00000`) is ~1 in 2²³. Edge-case FPU paths are almost never exercised.
2. **No fflags comparison** — The `fflags` CSR (IEEE 754 exception flags: NV, DZ, OF, UF, NX) is read by Spike but thrown away. The RTL comparison in `fuzzsim.py` has zero mentions of `fflags`. An entire class of FPU correctness bugs is structurally invisible.

---

## Setup

Pull and start the Cascade artifacts Docker image:

```bash
docker pull docker.io/ethcomsec/cascade-artifacts
docker run -it docker.io/ethcomsec/cascade-artifacts
source /cascade-meta/env.sh
cd /cascade-meta/fuzzer
```

Then apply the changes from this repo (see **Applying the Changes** below).

---

## Applying the Changes

Clone this repo and copy the modified files into the running container.

First get your container ID:
```bash
docker ps
# note the container ID, e.g. a1a52c02a882
```

Then copy each modified file in:
```bash
docker cp modified_files/cascade/randomize/pickisainstrclass.py <container_id>:/cascade-meta/fuzzer/cascade/randomize/
docker cp modified_files/cascade/randomize/pickinstrtype.py     <container_id>:/cascade-meta/fuzzer/cascade/randomize/
docker cp modified_files/cascade/randomize/pickfpuop.py         <container_id>:/cascade-meta/fuzzer/cascade/randomize/
docker cp modified_files/cascade/basicblock.py                  <container_id>:/cascade-meta/fuzzer/cascade/

docker cp fuzzer/demo_b11_final.py      <container_id>:/cascade-meta/fuzzer/
docker cp fuzzer/do_fpu_telemetry.py    <container_id>:/cascade-meta/fuzzer/
docker cp fuzzer/do_fpu_fullrun.py      <container_id>:/cascade-meta/fuzzer/
```

The directory structure under `modified_files/` mirrors the path inside the container (`/cascade-meta/`), so each file goes exactly where it belongs.

---

## What Was Changed

### `cascade/randomize/pickisainstrclass.py`
FPU instruction class weights increased from `0.1` → `0.4` for `FPUFSM`, `MEMFPU`, `FPU`, `FPU64`, `FPUD`, `FPUD64`, and `0.5` for `MEMFPUD`. This makes the fuzzer generate FPU-heavy programs far more frequently.

### `cascade/randomize/pickinstrtype.py`
Two changes:
- Added a global instruction counter (`_instr_counts`) and `get_instr_counts()` / `reset_instr_counts()` / `save_instr_counts()` for telemetry collection.
- Boosted weights for edge-case-triggering instructions (`fmadd`, `fmsub`, `fnmadd`, `fnmsub`, `fmin`, `fmax` — both `.s` and `.d` variants) from weight `1` → `4`.

### `cascade/randomize/pickfpuop.py`
Added `IEEE754_SPECIAL_VALUES_F32` — a catalogue of 10 known special bit patterns (+Inf, -Inf, qNaN, sNaN, ±0, subnormals, largest finite, 1.0) — and `inject_fpu_edge_case_vals()` which uses `fmv.w.x` to load these directly into FP registers, bypassing the random memory load path.

### `cascade/basicblock.py`
Added a call to `inject_fpu_edge_case_vals()` at the start of each basic block generation (probability `PROBA_INJECT_FPU_EDGE_CASE` per block, only when the design has FPU activated). The injector is placed here rather than inside `gen_fpufsm_instrs()` so it fires independently of FPUFSM instruction class scheduling.

---

## Getting Started with Cascade

Before applying our changes, it helps to get familiar with Cascade's original behavior — how it finds bugs, how it measures time-to-bug, and how its coverage compares to DifuzzRTL. The workflows below use stock Cascade scripts already inside the Docker image, no changes needed.

### Rediscovering paper bugs with `do_fuzzdesign.py`

```
python3 do_fuzzdesign.py <design> <num_cores> <seed_offset> <authorize_privileges> <tolerate_some_bug>
```

- `design` — one of the designs from `design_repos.json` (e.g. `cva6`, `cva6-c1`, `picorv32`, `vexriscv-v1-7`)
- `num_cores` — parallel workers. Use however many your machine has
- `seed_offset` — start seeds from this offset. Use `0` to start from the beginning
- `authorize_privileges` — `1` to allow privileged instructions (default), `0` to disable
- `tolerate_some_bug` — `0` normally. Set to `1` only when you want to fuzz past a known bug to find others

To rediscover the CVA6 C1 bug from the paper (register mismatch in `f2`):

```bash
source /cascade-meta/env.sh
cd /cascade-meta/fuzzer
python3 do_fuzzdesign.py cva6-c1 16 0 0 0
```

You should see output like:

```
/cascade-cva6-c1/cascade
Starting parallel testing of `cva6-c1` on 16 processes.
Failed test_run_rtl_single for params memsize: `396719`, design_name: `cva6-c1`, check_pc_spike_again: `True`, randseed: `3`, nmax_bbs: `55`
Register mismatch (f2) for params: memsize: `396719`, design_name: `cva6-c1`, nmax_bbs: `55`, randseed: `3`. Expected `0xffffffff7fc00000`, got `0xffffffff00000000`.
```

The fuzzer runs indefinitely — `Ctrl+C` to stop. Mismatches and timeouts are printed as they're found. Each failure line gives you the exact `randseed` and `nmax_bbs` to reproduce it with `do_fuzzsingle.py`.

Other designs worth trying to see different bug classes:

```bash
python3 do_fuzzdesign.py picorv32 16 0 0 0       # P-series bugs
python3 do_fuzzdesign.py vexriscv-v1-7 16 0 0 0  # V-series bugs
python3 do_fuzzdesign.py boom-b1 16 0 0 0         # B1 bug
```

---

### Reproducing Figure 18 (bug detection timings) with `do_timetobug_boxes.py`

This measures how long Cascade takes to detect each of the 40 bugs in the paper, repeated `NUM_REPS` times per bug. It saves per-bug JSON files to `/tmp/`, then the plot script reads them all and generates the figure.

```
python3 do_timetobug_boxes.py <num_cores> <num_reps>
python3 do_timetobug_boxes_plot.py <num_cores> <num_reps>
```

- `num_cores` — parallel workers, same as above
- `num_reps` — how many times to repeat each bug measurement. Paper uses `10`. Lower values finish faster but are noisier

To reproduce Figure 18 quickly (lower quality, finishes in minutes):

```bash
source /cascade-meta/env.sh
cd /cascade-meta/fuzzer
python3 do_timetobug_boxes.py 16 5
python3 do_timetobug_boxes_plot.py 16 5
```

For paper-quality results (needs a 64-core machine, takes hours):

```bash
python3 do_timetobug_boxes.py 64 10
python3 do_timetobug_boxes_plot.py 64 10
```

The `num_cores` and `num_reps` arguments **must match** between the two scripts — the plot script uses them to find the right JSON files in `/tmp/`.

`do_timetobug_boxes.py` iterates over all 40 bugs (`p1`–`p6`, `v1`–`v14`, `k1`–`k5`, `c1`–`c10`, `b1`–`b2`, `r1`, `y1`), temporarily tolerating each other bug while measuring time-to-detect for the target one. Each result is saved to `/tmp/bug_timings_<bug>_<num_cores>_<num_reps>.json`. Once all JSON files exist, `do_timetobug_boxes_plot.py` reads them and writes the figure.

---

### Understanding Coverage: Cascade vs DifuzzRTL (Figure 13)

This reproduces the register coverage comparison between Cascade and DifuzzRTL on RocketTile. It reads pre-captured log files already inside the Docker image so it completes in seconds.

```bash
source /cascade-meta/env.sh
cd /cascade-meta/fuzzer
python3 do_collect_difuzz_coverage.py
```

Expected output:

```
Time DifuzzRTL: [47.99]
Time Cascade (with corpus) for getting the same coverage: [0.26]
Time Cascade (live generation) for getting the same coverage: [0.49]
Speedup of Cascade (with corpus) over DifuzzRTL: 186.47x
Speedup of Cascade (live generation) over DifuzzRTL: 97.15x
```

To reach the same register coverage that DifuzzRTL achieves in ~48 seconds of fuzzing time, Cascade needs only **0.26s using its corpus** or **0.49s generating live**. This maps to Figure 13 in the paper — Cascade reaches 1,083,541 coverage points in 4,520 iterations while DifuzzRTL plateaus at 162,595.

The figure is saved inside the container at `/cascade-meta/figures/difuzzrtl_coverage.png`. To extract it:

```bash
docker cp <container_id>:/cascade-meta/figures/difuzzrtl_coverage.png .
```

---

### Step 1 — Structural proof: Cascade never checks fflags

Inside the container:
```bash
grep -n "fflags\|fcsr" /cascade-meta/fuzzer/cascade/fuzzsim.py
```

Output: nothing. `fuzzsim.py` has zero mentions of `fflags` or `fcsr`. The comparison loop only checks integer and FP value registers.

Also in `spikeresolution.py`, Spike reads `fcsr` at line 120 but line 277 throws it away — only `finalintregvals` and `finalfpuregvals` are returned, never `fflags`.

### Step 2 — Instruction telemetry: baseline vs enhanced

```bash
# Baseline (before changes)
python3 do_fpu_telemetry.py run \
  --design cva6 --runs 300 \
  --out /tmp/baseline_cva6.json --label baseline

# Enhanced (after applying changes)
python3 do_fpu_telemetry.py run \
  --design cva6 --runs 300 \
  --out /tmp/enhanced_cva6.json --label enhanced

# Plot
python3 do_fpu_telemetry.py plot \
  /tmp/baseline_cva6.json /tmp/enhanced_cva6.json \
  --out /tmp/fpu_comparison.png
```

Results across 300 programs on CVA6 — boosted instructions roughly double, non-boosted decrease proportionally confirming the weight shift is working:

| Instruction | Baseline | Enhanced | Ratio |
|---|---|---|---|
| `fmadd.s` | 3,174 | 7,055 | **2.22x** |
| `fmin.s` | 3,232 | 7,259 | **2.25x** |
| `fmax.d` | 4,513 | 9,455 | **2.10x** |
| `fnmadd.d` | 4,450 | 9,534 | **2.14x** |
| `fadd.s` (control) | 3,208 | 1,809 | 0.56x ↓ expected |

### Step 3 — CVA6 B11 (CVE-2024-35033): a bug Cascade cannot see

First build the linker script (needed once):
```bash
cat > /tmp/link.ld << 'EOF'
SECTIONS {
  . = 0x80000000;
  .text : { *(.text) }
}
EOF
```

Then run the demo:
```bash
python3 demo_b11_final.py
```

Expected output:
```
=================================================================
B11 (CVE-2024-35033): fsqrt fflags bug on CVA6
Exact inputs (1,4,9): Spike=0x00, CVA6 should=0x00
=================================================================
Input    Spike fflags   CVA6 fflags    fflags OK?   Verdict
-----------------------------------------------------------------
1.0      0x0            0x1            False      *** BUG B11 *** (exact)
2.0      0x1            0x1            True       OK (inexact)
4.0      0x0            0x1            False      *** BUG B11 *** (exact)
9.0      0x0            0x1            False      *** BUG B11 *** (exact)
...
=================================================================
Result values ALL match Spike -> Cascade sees NO mismatch
Only fflags reveals B11 -> Cascade blind, our method finds it
=================================================================
```

CVA6 spuriously sets the NX (inexact) flag for `fsqrt` of exact perfect squares (1.0, 4.0, 9.0). The result value is correct — Cascade sees no mismatch. The bug is only detectable by reading `fflags` via `frflags` and comparing against Spike.

This is **CVE-2024-35033**, independently found by [DiveFuzz (CCS '25)](https://dl.acm.org/doi/10.1145/3719027.3765167).

---

## Why This Class of Bug Matters

Cascade's differential oracle compares register values. It cannot see bugs where the RTL computes **correct values but wrong exception flags** — a class that matters for any software using `fetestexcept()`: numerical libraries, safety-critical systems, OS context switches saving/restoring FPU state.

| Check | Cascade (original) | This work |
|---|---|---|
| Result value `ft1` matches Spike | ✓ checked | ✓ checked |
| `fflags` compared | ✗ zero mentions in `fuzzsim.py` | ✓ read via `frflags`, compared |
| NaN/special values as inputs | ✗ ~1 in 8M chance | ✓ injected directly |

---

## Files in This Repo

```
modified_files/
  cascade/randomize/pickisainstrclass.py   FPU class weights 0.1 → 0.4
  cascade/randomize/pickinstrtype.py       Telemetry counter + edge-case boosts (weight 4)
  cascade/randomize/pickfpuop.py           IEEE 754 special value catalogue + injector
  cascade/basicblock.py                    Injection call at start of each basic block
fuzzer/
  demo_b11_final.py                        CVE-2024-35033 reproduction demo
  do_fpu_telemetry.py                      Instruction distribution measurement and plotting
  do_fpu_fullrun.py                        Full pipeline comparison with mismatch tracking
```
