# -*- coding: utf-8 -*-
"""深挖修改版 PC 端发送路径：ack 读写点 / 分片 / 线程。
专注回答一个问题：修改版发 15 张时，每项/每块的 ack 读取次数与源码版差多少。
"""
import io, os, re, subprocess

OD = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
OUT = r"E:\lanshare-harmony\logs\disasm"
os.makedirs(OUT, exist_ok=True)


def run(args):
    return subprocess.run([OD] + args, capture_output=True, text=False).stdout.decode('utf-8', 'ignore')


def symtab(exe):
    txt = run(["-t", exe])
    out = []
    for line in txt.splitlines():
        m = re.search(r"\(sec\s+(\d+)\).*?\(ty\s+20\).*?\s(0x[0-9a-f]+)\s+(\S+)$", line)
        if m and m.group(1) in ("1",):
            out.append((int(m.group(2), 16), m.group(3)))
    out.sort()
    return out


def full_name(syms, key):
    hits = [(a, n) for a, n in syms if key in n]
    return hits


def disasm(exe, name):
    return run(["-d", "--no-show-raw-insn", "--disassemble-symbols=" + name, exe])


def dumpfile(exe, name, tag):
    txt = disasm(exe, name)
    safe = re.sub(r"\W+", "_", name)[:70]
    p = os.path.join(OUT, "%s_%s.txt" % (tag, safe))
    io.open(p, "w", encoding="utf-8", newline="\n").write(txt)
    return txt, p


def summary(txt, label):
    lines = txt.splitlines()
    n_recvo = sum(1 for l in lines if "recvo" in l)
    n_recv = sum(1 for l in lines if re.search(r"<[^>]*TCPClient4recv|<[^>]*recv\(", l))
    n_send = sum(1 for l in lines if re.search(r"callq.*<(?:[^>]*)?(send|baseSend)", l) and "recvo" not in l and "recv(" not in l)
    n_call = sum(1 for l in lines if "callq" in l)
    print("  [%s] lines=%d callq=%d | recvo=%d recv=%d send=%d" %
          (label, len(lines), n_call, n_recvo, n_recv, n_send))
    return n_recvo


SM = symtab(MOD)
SS = symtab(SRC)

print("=" * 72)
print("A. 修改版关键符号全名")
print("=" * 72)
KEYS = ["sendFileParallelOne", "fsSegShare", "sendOneSeg", "recvSegFile", "runSeg",
        "isFileParallelEligible", "isParallelEligible", "sendFile", "MTCPClient5recvo",
        "TCPClient5recvo", "TCPClient4send", "M_runEv"]
found = {}
for k in KEYS:
    h = full_name(SM, k)
    h = [(a, n) for a, n in h if "thread11_State_impl" not in n or k == "M_runEv"]
    found[k] = h
    for a, n in h[:4]:
        print("  %-24s 0x%06x  %s" % (k, a, n[:96]))

print()
print("=" * 72)
print("B. 逐个函数：ack 读写统计")
print("=" * 72)

# B1 sendFileParallelOne（含 lambda _M_run）
for a, n in full_name(SM, "sendFileParallelOne")[:1]:
    txt, p = dumpfile(MOD, n, "MOD")
    summary(txt, "MOD sendFileParallelOne")
    print("     file:", p)
for a, n in full_name(SM, "M_runEv"):
    if "sendFileParallelOne" in n:
        txt, p = dumpfile(MOD, n, "MOD")
        summary(txt, "MOD lambda _M_run (线程体)")
        print("     file:", p)
        calls = sorted(set(re.findall(r"callq?\s+.*?<([^>]+)>", txt)))
        print("     calls:", [c for c in calls if not c.startswith("_ZSt")][:40])

# B2 分片三兄弟
for k in ["fsSegShare", "sendOneSeg", "recvSegFile", "runSeg"]:
    for a, n in full_name(SM, k)[:1]:
        txt, p = dumpfile(MOD, n, "MOD")
        summary(txt, "MOD " + k)
        print("     file:", p)

# B3 sendFile 对比
for tag, exe, syms in (("MOD", MOD, SM), ("SRC", SRC, SS)):
    for a, n in full_name(syms, "sendFile")[:1]:
        if "sendFileParallel" in n:
            continue
        txt, p = dumpfile(exe, n, tag)
        summary(txt, tag + " sendFile")
        print("     file:", p)

print()
print("=" * 72)
print("C. 修改版 sendFile 中 recvo/send 上下文（每处 ±4 行）")
print("=" * 72)
for a, n in full_name(SM, "sendFile")[:1]:
    if "sendFileParallel" in n:
        continue
    txt, _ = dumpfile(MOD, n, "MOD")
    lines = txt.splitlines()
    for i, l in enumerate(lines):
        if "recvo" in l or re.search(r"callq.*<?.*(TCPClient4send|baseSend)", l):
            lo, hi = max(0, i - 4), min(len(lines), i + 5)
            print("  ---- line %d ----" % i)
            for j in range(lo, hi):
                mark = ">>" if j == i else "  "
                print("  %s %s" % (mark, re.sub(r"^\s*", "", lines[j])[:110]))

print()
print("=" * 72)
print("D. 源码版 sendFile 中 recvo/send 上下文（每处 ±4 行）")
print("=" * 72)
for a, n in full_name(SS, "sendFile")[:1]:
    txt, _ = dumpfile(SRC, n, "SRC")
    lines = txt.splitlines()
    cnt = 0
    for i, l in enumerate(lines):
        if "recvo" in l:
            cnt += 1
            if cnt > 12:
                break
            lo, hi = max(0, i - 4), min(len(lines), i + 5)
            print("  ---- line %d ----" % i)
            for j in range(lo, hi):
                mark = ">>" if j == i else "  "
                print("  %s %s" % (mark, re.sub(r"^\s*", "", lines[j])[:110]))
    print("  recvo 总处数:", sum(1 for l in lines if "recvo" in l))

print()
print("=" * 72)
print("E. MTCPClient::recvo / TCPClient::send 两侧实现对比")
print("=" * 72)
for tag, exe, syms in (("SRC", SRC, SS), ("MOD", MOD, SM)):
    for key in ["MTCPClient5recvoEPviyi", "TCPClient4sendEPKvii"]:
        for a, n in full_name(syms, key)[:1]:
            txt, p = dumpfile(exe, n, tag)
            print("  ", tag, key, "lines:", len(txt.splitlines()), "file:", p)
