# -*- coding: utf-8 -*-
"""全量反汇编 -> 建立 调用者 -> 被调用者 映射，用于定位「谁调用了 X」。"""
import re, subprocess, sys, collections

OBJ = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"

def full_dump(exe):
    p = subprocess.run([OBJ, "-d", "--no-show-raw-insn", exe],
                       capture_output=True, text=True, errors='replace')
    return p.stdout

FUNCRE = re.compile(r'^[0-9a-f]+ <([^>]+)>:$')
CALLRE = re.compile(r'callq?\s+\*?0x[0-9a-f]+\s+<([^>]+)>')

def main():
    exe = sys.argv[1]
    needles = sys.argv[2:]
    dump = full_dump(exe)
    cur = "?"
    hits = collections.defaultdict(list)   # needle -> [(caller, addr)]
    for line in dump.splitlines():
        m = FUNCRE.match(line)
        if m:
            cur = m.group(1)
            continue
        c = CALLRE.search(line)
        if not c:
            continue
        callee = c.group(1).split('+')[0]
        for n in needles:
            if n in callee:
                addr = line.split(':')[0].strip()
                hits[n].append((cur, addr, callee))
    print("### 文件: %s" % exe)
    for n in needles:
        lst = hits.get(n, [])
        print("  --- 被调目标包含 %r : %d 处 ---" % (n, len(lst)))
        for caller, addr, callee in lst:
            print("      0x%s  caller=%s" % (addr, caller))
    if not needles:
        print("(未指定 needle)")

main()
