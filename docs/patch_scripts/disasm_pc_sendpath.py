# -*- coding: utf-8 -*-
"""按地址范围精确 dump 修改版发送链路的三个核心函数，并抽 ack/发送上下文。
VA = 0x140000000 + RVA
"""
import io, os, re, subprocess

OD = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"
OUT = r"E:\lanshare-harmony\logs\disasm"
os.makedirs(OUT, exist_ok=True)


def run(args):
    return subprocess.run([OD] + args, capture_output=True, text=False).stdout.decode('utf-8', 'ignore')


def dump_range(exe, lo, hi, tag):
    """按虚拟地址 dump（objdump 的 --start-address 用 VA）"""
    txt = run(["-d", "--no-show-raw-insn",
               "--start-address=0x%x" % (0x140000000 + lo),
               "--stop-address=0x%x" % (0x140000000 + hi), exe])
    p = os.path.join(OUT, "%s_%06x_%06x.txt" % (tag, lo, hi))
    io.open(p, "w", encoding="utf-8", newline="\n").write(txt)
    return txt, p


def ctx(txt, pat, before=6, after=8, limit=99):
    lines = txt.splitlines()
    hits = [i for i, l in enumerate(lines) if re.search(pat, l)]
    print("    hits: %d" % len(hits))
    for k, i in enumerate(hits[:limit]):
        lo, hi = max(0, i - before), min(len(lines), i + after)
        print("    ---- #%d line %d ----" % (k, i))
        for j in range(lo, hi):
            mark = ">>" if j == i else "  "
            print("    %s %s" % (mark, re.sub(r"^\s+", "", lines[j])[:118]))


print("#" * 74)
print("# 1) sendFileParallelOne  0x24030 - 0x25020")
print("#" * 74)
t, p = dump_range(MOD, 0x24030, 0x25020, "MOD")
print("lines:", len(t.splitlines()), "file:", p)
calls = sorted(set(re.findall(r"callq?\s+.*?<([^>]+)>", t)))
print("calls:", [c for c in calls][:40])
print()
print("  线程体 lambda _M_run (0x2e3f0 - 0x2f2c0) 的完整调用与参数线索:")
t2, p2 = dump_range(MOD, 0x2e3f0, 0x2f2c0, "MOD")
io.open(p2, "w", encoding="utf-8", newline="\n").write(t2)
print("lines:", len(t2.splitlines()), "file:", p2)
for l in t2.splitlines():
    if "callq" in l or "movl" in l and "$" in l:
        print("   ", re.sub(r"^\s+", "", l)[:118])

print()
print("#" * 74)
print("# 2) sendOneSeg  0x2de50 - 0x2e3f0  （真正的发送实现）")
print("#" * 74)
t3, p3 = dump_range(MOD, 0x2de50, 0x2e3f0, "MOD")
print("lines:", len(t3.splitlines()), "file:", p3)
calls3 = sorted(set(re.findall(r"callq?\s+.*?<([^>]+)>", t3)))
print("calls:")
for c in calls3:
    print("   ", c[:110])
print()
print("  --- recvo / send 调用点上下文 ---")
ctx(t3, r"recvo|<[^>]*(?:4send|baseSend)")

print()
print("#" * 74)
print("# 3) 修改版 sendFile  0x27c50 - 0x29590（调用方）")
print("#" * 74)
t4, p4 = dump_range(MOD, 0x27c50, 0x29590, "MOD")
print("lines:", len(t4.splitlines()), "file:", p4)
calls4 = sorted(set(re.findall(r"callq?\s+.*?<([^>]+)>", t4)))
print("calls:")
for c in calls4:
    if any(k in c for k in ["sendFile", "sendOneSeg", "Parallel", "recvo", "4send", "baseSend", "makeDataEnc", "MTCPClient"]):
        print("   ", c[:110])
print()
print("  --- recvo / send 调用点上下文 ---")
ctx(t4, r"recvo|<[^>]*(?:4send|baseSend)")
