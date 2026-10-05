# -*- coding: utf-8 -*-
"""抽取 MOD / SRC 两个 exe 指定函数的调用集合，做差分。
用法: python disasm_callset_diff.py <func_substr> [<func_substr> ...]
"""
import io, os, re, subprocess, sys, collections

OBJDUMP = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"
OUT = r"E:\lanshare-harmony\logs\disasm"

def sh(args):
    p = subprocess.run(args, capture_output=True, text=True, errors='replace')
    return p.stdout

def get_symbols(exe):
    """返回 [(name, rva, size)]，只保留 F .text 的"""
    out = sh([OBJDUMP, "-t", exe])
    syms = []
    for line in out.splitlines():
        m = re.search(r'([0-9a-f]{16})\s+([lg! ])\s+(F)\s+(\.text\S*)\s+([0-9a-f]{16})\s+(.*)$', line)
        if not m:
            continue
        rva = int(m.group(1), 16)
        sec = m.group(4)
        size = int(m.group(5), 16)
        name = m.group(6).strip()
        if not name:
            continue
        syms.append((name, rva, size, sec))
    return syms

def text_vma(exe):
    """取 .text 段的 VMA 和 file offset，算 VA 修正量"""
    out = sh([OBJDUMP, "-h", exe])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 7 and parts[1] == '.text':
            # Idx Name Size VMA LMA FileOff Algn
            vma = int(parts[3], 16)
            foff = int(parts[5], 16)
            return vma, foff
    return None, None

def disasm_range(exe, lo, hi):
    return sh([OBJDUMP, "-d", "--start-address=0x%x" % lo, "--stop-address=0x%x" % hi, exe])

CALLRE = re.compile(r'\tcallq?\s+([0-9a-f]+)\s+<([^>]+)>')

def callset(dump, lo, hi):
    c = collections.Counter()
    for m in CALLRE.finditer(dump):
        c[m.group(1)] = c[m.group(1)]  # keep addr keyed by name below
    names = collections.Counter()
    for m in CALLRE.finditer(dump):
        nm = m.group(2)
        nm = nm.split('+')[0]
        names[nm] += 1
    return names

def demangle_filter(n):
    return n

def main():
    subs = sys.argv[1:] or ["8LANShare8sendFileR"]
    for sub in subs:
        print("=" * 100)
        print("### 函数匹配: %s" % sub)
        res = {}
        for tag, exe in (("MOD", MOD), ("SRC", SRC)):
            syms = get_symbols(exe)
            vma, foff = text_vma(exe)
            hits = [s for s in syms if sub in s[0]]
            if not hits:
                print("  [%s] 无匹配" % tag)
                continue
            for (name, rva, size, sec) in hits:
                # VA: 符号 RVA 需要加上 (.text VMA - .text 里第一个符号的基准)
                # 经验: objdump -t 的 value 是 ImageBase 相对, 但实际反汇编 VA 多 0x1000
                for delta in (0x1000, 0x0):
                    lo = rva + delta
                    hi = lo + size
                    dump = disasm_range(exe, lo, hi)
                    if len(dump.strip().splitlines()) > 3:
                        break
                print("-" * 90)
                print("[%s] %s  symRVA=0x%x size=%d delta=0x%x VA=0x%x-0x%x" % (tag, name, rva, size, delta, lo, hi))
                cs = callset(dump, lo, hi)
                res.setdefault(sub, {})[tag] = cs
                print("   调用计数 %d 个不同目标, 共 %d 次调用" % (len(cs), sum(cs.values())))
        # diff
        for sub, d in res.items():
            if "MOD" in d and "SRC" in d:
                m, s = d["MOD"], d["SRC"]
                only_m = {k: v for k, v in m.items() if k not in s}
                only_s = {k: v for k, v in s.items() if k not in m}
                cnt_diff = {k: (m[k], s[k]) for k in m if k in s and m[k] != s[k]}
                print("")
                print("### 仅在 MOD 出现:")
                for k, v in sorted(only_m.items(), key=lambda x: -x[1]):
                    print("    %3dx  %s" % (v, k))
                print("### 仅在 SRC 出现:")
                for k, v in sorted(only_s.items(), key=lambda x: -x[1]):
                    print("    %3dx  %s" % (v, k))
                print("### 调用次数不同 (MOD,SRC):")
                for k, v in sorted(cnt_diff.items(), key=lambda x: -abs(x[1][0] - x[1][1])):
                    print("    MOD=%dx SRC=%dx  %s" % (v[0], v[1], k))

main()
