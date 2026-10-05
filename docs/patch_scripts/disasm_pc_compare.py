# -*- coding: utf-8 -*-
"""对比源码版 / 修改版 PC 端 LANShare.exe 的发送路径。
不依赖跨命令的 /tmp：所有 objdump 输出在本进程内即时解析。
"""
import io, os, re, subprocess, sys

OD = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
OUT = r"E:\lanshare-harmony\logs\disasm"
os.makedirs(OUT, exist_ok=True)


def run(args):
    p = subprocess.run([OD] + args, capture_output=True, text=False)
    return p.stdout.decode('utf-8', 'ignore')


def symtab(exe):
    """返回 [(rva:int, name:str)] 按地址排序；仅取函数符号(ty 20)。"""
    txt = run(["-t", exe])
    out = []
    for line in txt.splitlines():
        m = re.search(r"\(sec\s+(\d+)\).*?\(ty\s+20\).*?\s(0x[0-9a-f]+)\s+(\S+)$", line)
        if not m:
            continue
        if m.group(1) not in ("1", "2"):   # .text / maybe ilt
            continue
        out.append((int(m.group(2), 16), m.group(3)))
    out.sort()
    return out


def sizes(syms, want_substr):
    """对每个匹配名，用「下一个函数地址 - 本地址」估算大小。"""
    res = {}
    for i, (a, n) in enumerate(syms):
        if any(w in n for w in want_substr):
            nxt = None
            for j in range(i + 1, len(syms)):
                if syms[j][1] != n:
                    nxt = syms[j][0]
                    break
            sz = (nxt - a) if nxt and nxt > a else -1
            res[n] = (a, sz)
    return res


def disasm_sym(exe, name, tag, maxlines=400):
    txt = run(["-d", "--no-show-raw-insn", "--disassemble-symbols=" + name, exe])
    lines = txt.splitlines()
    fn = [l for l in lines if ">:" in l or re.match(r"^[0-9a-f]+ <", l)]
    path = os.path.join(OUT, "%s_%s.txt" % (tag, re.sub(r"\W+", "_", name)[:60]))
    io.open(path, "w", encoding="utf-8", newline="\n").write(txt)
    return txt, path


def calls(txt):
    """提取所有 call 目标（符号化）。"""
    out = []
    for line in txt.splitlines():
        m = re.search(r"\bcallq?\s+.*?<([^>]+)>", line)
        if m:
            out.append(m.group(1))
        else:
            m2 = re.search(r"\bcallq?\s+(\*0x[0-9a-f]+)", line)
            if m2:
                out.append(m2.group(1))
    return out


print("=" * 70)
print("1) 符号与函数尺寸对比")
print("=" * 70)
want = ["sendFile", "sendOneSeg", "recvSegFile", "isParallelEligible",
        "isFileParallelEligible", "baseSend", "baseRecv", "TCPClient"]
ss = sizes(symtab(SRC), want)
sm = sizes(symtab(MOD), want)
names = sorted(set(list(ss.keys()) + list(sm.keys())))
print("%-62s %10s %10s" % ("symbol", "SRC size", "MOD size"))
for n in names:
    a = ss.get(n, (0, None))[1]
    b = sm.get(n, (0, None))[1]
    mark = ""
    if a is not None and b is not None and a != b:
        mark = "   <== DIFF"
    elif a is None:
        mark = "   <== only MOD"
    elif b is None:
        mark = "   <== only SRC"
    print("%-62s %10s %10s%s" % (n[:62],
                                 "-" if a is None else a,
                                 "-" if b is None else b, mark))

print()
print("=" * 70)
print("2) 调用关系：谁调用 sendFile / sendFileParallel")
print("=" * 70)
for tag, exe in (("SRC", SRC), ("MOD", MOD)):
    calls_ = {}
    for caller in ["_ZN14LANShareWindow21on_sendButton_clickedEv",
                   "_ZN14LANShareWindow30on_select_send_devices_clickedEv"]:
        txt, _ = disasm_sym(exe, caller, tag)
        calls_[caller] = calls(txt)
    print("---", tag, "---")
    for c, v in calls_.items():
        hit = [x for x in v if "sendFile" in x or "Parallel" in x or "sendOneSeg" in x]
        print("  ", c.split("_ZN")[-1][:40], "->", hit if hit else "(无发送调用)")

print()
print("=" * 70)
print("3) 修改版 sendFileParallel 主体（顺序回退路径）")
print("=" * 70)
txt, path = disasm_sym(MOD, "_ZN8LANShare16sendFileParallelERK6DeviceSt6vectorIP5LFileSaIS5_EE", "MOD", 1200)
print("dumped:", path, "lines:", len(txt.splitlines()))
print("calls:", sorted(set(calls(txt))))

print()
print("=" * 70)
print("4) 修改版 sendFile（老路径）主体")
print("=" * 70)
txt2, path2 = disasm_sym(MOD, "_ZN8LANShare8sendFileERK6DeviceSt6vectorIP5LFileSaIS5_EEi", "MOD", 3000)
print("dumped:", path2, "lines:", len(txt2.splitlines()))
print("calls:", sorted(set(calls(txt2))))

print()
print("=" * 70)
print("5) 源码版 sendFile 主体")
print("=" * 70)
txt3, path3 = disasm_sym(SRC, "_ZN8LANShare8sendFileERK6DeviceSt6vectorIP5LFileSaIS5_EEi", "SRC", 3000)
print("dumped:", path3, "lines:", len(txt3.splitlines()))
print("calls:", sorted(set(calls(txt3))))
