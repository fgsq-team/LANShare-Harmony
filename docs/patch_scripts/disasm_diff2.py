# -*- coding: utf-8 -*-
"""MOD / SRC 两个 exe：精确反汇编 + 调用集合差分。"""
import re, subprocess, sys, collections

OBJ = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"

def sh(args):
    p = subprocess.run(args, capture_output=True, text=True, errors='replace')
    return p.stdout

SYMRE = re.compile(r'^\s*\[\d+\]\(sec\s+(\d+)\)\(fl 0x[0-9a-f]+\)\(ty\s+\d+\)\(scl\s+\d+\) \(nx \d+\) 0x([0-9a-f]+) (\S+)\s*$')

def symbols(exe):
    out = sh([OBJ, "-t", exe])
    res = {}
    for line in out.splitlines():
        m = SYMRE.match(line)
        if not m:
            continue
        sec = int(m.group(1)); val = int(m.group(2), 16); name = m.group(3)
        if sec == 0:
            continue
        res.setdefault(name, (sec, val))
    return res

def dis(exe, name):
    return sh([OBJ, "-d", "--disassemble-symbols=" + name, exe])

CALLRE = re.compile(r'callq?\s+\*?(?:0x)?([0-9a-f]+)?\s*<([^>]+)>')

def callset(dump):
    c = collections.Counter()
    for line in dump.splitlines():
        m = CALLRE.search(line)
        if m:
            nm = m.group(2)
            nm = nm.split('+')[0].strip()
            c[nm] += 1
    return c

def one(exe, name):
    d = dis(exe, name)
    return d, callset(d)

def main():
    targets = sys.argv[1:]
    if not targets:
        targets = [
            "_ZN8LANShare8sendFileERK6DeviceSt6vectorIP5LFileSaIS5_EEi",
        ]
    for t in targets:
        print("=" * 110)
        print("### " + t)
        dm, cm = one(MOD, t)
        ds, cs = one(SRC, t)
        nm = len([l for l in dm.splitlines() if re.match(r'^[0-9a-f]+:', l)])
        ns = len([l for l in ds.splitlines() if re.match(r'^[0-9a-f]+:', l)])
        print("  指令数 MOD=%d  SRC=%d" % (nm, ns))
        if not cm and not cs:
            print("  !! 两边都反汇编为空")
            continue
        only_m = {k: v for k, v in cm.items() if k not in cs}
        only_s = {k: v for k, v in cs.items() if k not in cm}
        cdiff = {k: (cm[k], cs[k]) for k in cm if k in cs and cm[k] != cs[k]}
        print("  --- 只在 MOD 被调用 ---")
        for k, v in sorted(only_m.items(), key=lambda x: -x[1]):
            print("     %3dx %s" % (v, k))
        print("  --- 只在 SRC 被调用 ---")
        for k, v in sorted(only_s.items(), key=lambda x: -x[1]):
            print("     %3dx %s" % (v, k))
        print("  --- 次数不同 (MOD,SRC) ---")
        for k, v in sorted(cdiff.items(), key=lambda x: -abs(x[1][0] - x[1][1])):
            print("     MOD=%dx SRC=%dx  %s" % (v[0], v[1], k))

main()
