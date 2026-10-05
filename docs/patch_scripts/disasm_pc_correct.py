# -*- coding: utf-8 -*-
"""按正确边界（符号表 RVA + 0x1000）精确反汇编发送路径三函数。"""
import io, os, re, subprocess, collections

OD = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"
OUT = r"E:\lanshare-harmony\logs\disasm"
os.makedirs(OUT, exist_ok=True)


def dump(exe, lo, hi):
    return subprocess.run([OD, "-d", "--no-show-raw-insn",
                           "--start-address=0x%x" % lo, "--stop-address=0x%x" % hi, exe],
                          capture_output=True, text=False).stdout.decode('utf-8', 'ignore')


def analyze(txt, label, save=None):
    lines = txt.splitlines()
    if save:
        io.open(os.path.join(OUT, save), "w", encoding="utf-8", newline="\n").write(txt)
    print("=" * 72)
    print("### %s   lines=%d" % (label, len(lines)))
    calls = collections.Counter()
    for l in lines:
        m = re.search(r"callq?\s+\S+\s+<([^>]+)>", l)
        if m:
            calls[m.group(1)] += 1
    # 只看与网络/协议/线程相关的
    keys = ["makeSocket", "close", "setCmd", "setByteCmd", "send", "recvo", "thread",
            "IOUtils", "read", "Parallel", "Seg", "join", "detach", "DataEnc", "putLong",
            "putString", "putInt", "putBool", "setCount", "getFileSize", "getDevIp", "getDevPort",
            "MTCPClient", "startHandle"]
    for name, c in sorted(calls.items(), key=lambda x: -x[1]):
        if any(k.lower() in name.lower() for k in keys):
            print("   %3d x %s" % (c, name[:96]))
    # setCmd / setByteCmd 立即数
    pend = None
    seen = []
    for i, l in enumerate(lines):
        m = re.search(r"movl\s+\$(\d+), %e(?:dx|cx|ax|r8d)", l)
        if m:
            pend = m.group(1)
        m2 = re.search(r"callq\s+\S+\s+<(?:[^>]*)(setCmd|setByteCmd|setCount|setDataIndex)[^>]*>", l)
        if m2 and pend is not None:
            seen.append("%s(%s)" % (m2.group(1), pend))
            pend = None
        elif re.search(r"callq", l):
            pend = None
    if seen:
        print("   cmd 立即数序列:", seen)
    return lines


print("\n\n############ 1) 修改版 sendFile  0x140028c50 - 0x140029ea0 ############")
t = dump(MOD, 0x140028c50, 0x140029ea0)
analyze(t, "MOD LANShare::sendFile", "MOD_sendFile_correct.txt")

print("\n\n############ 2) 修改版 sendFileParallelOne  0x140025030 - 0x140026020 ############")
t2 = dump(MOD, 0x140025030, 0x140026020)
analyze(t2, "MOD sendFileParallelOne", "MOD_sendFileParallelOne.txt")
print("   --- 线程相关指令 ---")
for l in t2.splitlines():
    if re.search(r"callq|movl\s+\$", l) and re.search(r"thread|join|detach|Parallel", l):
        print("     ", re.sub(r"^\s+", "", l)[:110])

print("\n\n############ 3) 修改版 sendFileParallel  0x140026020 - 0x140026090 ############")
t3 = dump(MOD, 0x140026020, 0x140026090)
analyze(t3, "MOD sendFileParallel", "MOD_sendFileParallel.txt")
for l in t3.splitlines():
    if "callq" in l or re.search(r"movl\s+\$|cmpl|test", l):
        print("     ", re.sub(r"^\s+", "", l)[:110])

print("\n\n############ 4) 源码版 sendFile  0x1400207c0 - 0x140022350 ############")
t4 = dump(SRC, 0x1400207c0, 0x140022350)
analyze(t4, "SRC LANShare::sendFile", "SRC_sendFile_correct.txt")
