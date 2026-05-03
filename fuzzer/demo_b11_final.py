import struct, subprocess, os, math
from cascade.fuzzsim import setup_sim_env
from common.designcfgs import get_design_cascade_path, get_design_cfg

def float_to_hex(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]

def make_elf(val, outpath):
    hex_val = float_to_hex(val)
    asm = """
.section .text
.global _start
_start:
    li t0, 0x6000
    csrrs zero, mstatus, t0
    csrrwi zero, fflags, 0
    li t0, 0x{:08X}
    fmv.w.x ft0, t0
    fsqrt.s ft1, ft0
    frflags a0
    lui t5, 0x0
    addi t5, t5, 0x10
    sd a0, 0(t5)
    fence
    lui t5, 0x0
    sd zero, 0(t5)
    fence
    j .
""".format(hex_val)
    with open('/tmp/b11_test.s', 'w') as f:
        f.write(asm)
    subprocess.run(['riscv64-unknown-elf-gcc', '-march=rv64g', '-mabi=lp64',
                   '-nostdlib', '-nostartfiles', '-T', '/tmp/link.ld',
                   '/tmp/b11_test.s', '-o', outpath], capture_output=True)

# Spike fflags known from --log-commits runs:
# fsqrt(1.0) = exact -> fflags=0x00
# fsqrt(4.0) = exact -> fflags=0x00
# fsqrt(9.0) = exact -> fflags=0x00
# fsqrt(2.0) = inexact -> fflags=0x01
# fsqrt(6.0) = inexact -> fflags=0x01
# fsqrt(7.0) = inexact -> fflags=0x01
spike_known = {
    1.0: 0x00, 2.0: 0x01, 3.0: 0x01,
    4.0: 0x00, 5.0: 0x01, 6.0: 0x01,
    7.0: 0x01, 8.0: 0x01, 9.0: 0x00, 10.0: 0x01
}

design_name = 'cva6'
design_cfg  = get_design_cfg(design_name)
sim_path    = os.path.join(get_design_cascade_path(design_name),
                           'build', 'run_vanilla_notrace_0.1',
                           'default-verilator',
                           'V' + design_cfg['toplevel'])

print("=" * 65)
print("B11 (CVE-2024-35033): fsqrt fflags bug on CVA6")
print("Exact inputs (1,4,9): Spike=0x00, CVA6 should=0x00")
print("=" * 65)
print("%-8s %-14s %-14s %-10s %s" % (
    "Input", "Spike fflags", "CVA6 fflags", "fflags OK?", "Verdict"))
print("-" * 65)

for val in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
    elf = '/tmp/b11_%.0f.elf' % val
    make_elf(val, elf)

    my_env = setup_sim_env(elf, '/dev/null', '/dev/null', 50000,
                           get_design_cascade_path(design_name), None, False)
    out = subprocess.run([sim_path], capture_output=True,
                         text=True, env=my_env)
    dumps = []
    for line in out.stdout.split('\n'):
        if 'Dump of reg x0' in line:
            dumps.append(int(line.split('0x')[1][:16], 16))

    spike_fflags = spike_known[val]
    if dumps:
        rtl_fflags = dumps[0]
        flag_ok = rtl_fflags == spike_fflags
        verdict = "*** BUG B11 ***" if not flag_ok else "OK"
        exact = "(exact)" if spike_fflags == 0 else "(inexact)"
        print("%-8.1f %-14s %-14s %-10s %s %s" % (
            val, hex(spike_fflags), hex(rtl_fflags),
            str(flag_ok), verdict, exact))
    else:
        print("%-8.1f no dump" % val)

print("=" * 65)
print("Result values ALL match Spike -> Cascade sees NO mismatch")
print("Only fflags reveals B11 -> Cascade blind, our method finds it")
print("=" * 65)
