# -*- coding: utf-8 -*-
"""并排对比：源码版 vs 修改版 的「文件发送循环」。
抓四个决定性数值：握手 cmd / 块大小 / 每块 ack 读取 / 收尾帧。
"""
import io, os, re, subprocess

OD = r"C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native\llvm\bin\llvm-objdump.exe"
SRC = r"C:\Program Files\LANShare\LANShare.exe"
MOD = r"E:\LANShare\LANShare-PC(新)\LANShare\LANShare.exe"
OUT = r"E:\lanshare-harmony\logs\disasm"
os.makedirs(OUT, exist_ok=True)
BASE = 0x140000000


def run(a):
    return subprocess.run([OD] + a, capture_output=True, text=False).stdout.decode('utf-8', 'ignore')


def syms(exe):
    out = []
    for line in run(["-t", exe]).splitlines():
        m = re.search(r"\(sec\s+(\d+)\).*?\(ty\s+20\).*?\s(0x[0-9a-f]+)\s+(\S+)$", line)
        if m and m.group(1) == "1":
            out.append((int(m.group(2), 16), m.group(3)))
    out.sort()
    return out


def size_of(sy, key):
    for i, (a, n) in enumerate(sy):
        if key in n:
            nxt = None
            for j in range(i + 1, len(sy)):
                if sy[j][1] != n:
                    nxt = sy[j][0]
                    break
            return a, (nxt - a if nxt else -1), n
    return None, None, None


def dump_va(exe, lo, hi, tag):
    t = run(["-d", "--no-show-raw-insn",
             "--start-address=0x%x" % (BASE + lo), "--stop-address=0x%x" % (BASE + hi), exe])
    p = os.path.join(OUT, "%s_%06x.txt" % (tag, lo))
    io.open(p, "w", encoding="utf-8", newline="\n").write(t)
    return t


def facts(txt, label):
    lines = txt.splitlines()
    print("  ===== %s =====" % label)
    print("  lines=%d" % len(lines))
    # 立即数 -> 紧跟的调用（识别 setCmd / setByteCmd 的参数）
    pending = None
    for l in lines:
        m = re.search(r"movl\s+\$(\d+), %edx", l)
        if m:
            pending = m.group(1)
            continue
        m2 = re.search(r"callq\s+\S+\s+<([^>]+)>", l)
        if m2 and pending is not None:
            tgt = m2.group(1)
            if "setCmd" in tgt or "setByteCmd" in tgt or "setCount" in tgt or "putBool" in tgt:
                print("    %-28s <- imm %s" % (tgt[:28], pending))
            pending = None
    # 缓冲 / 块大小常量
    big = sorted(set(int(x) for x in re.findall(r"\$(\d{6,}),", txt)))
    print("    大常量:", [hex(b) for b in big if b > 100000][:12], "共", len([b for b in big if b > 100000]))
    # ack 读取
    n = sum(1 for l in lines if "recvo" in l)
    print("    recvo 调用点:", n)
    # send 调用点
    ns = sum(1 for l in lines if re.search(r"<[^>]*(?:TCPClient4send|baseSend|MTCPClient4send)", l))
    print("    send 调用点:", ns)
    # read
    nr = sum(1 for l in lines if "IOUtils4read" in l or "4readE" in l)
    print("    IOUtils::read 调用点:", nr)
    return lines


print("#" * 74)
print("A. 源码版：FileSend 家族地址与大小")
print("#" * 74)
ss = syms(SRC)
for k in ["FileSend4sendE", "FileSend14sendFileStream", "FileSend17sendFileStreamEnc",
          "FileSend8sendFileE", "FileSend18handleFileTransfer", "LANShare8sendFile"]:
    a, sz, n = size_of(ss, k)
    print("  %-58s rva=%s size=%s" % (k, hex(a) if a else "-", sz))

print()
print("#" * 74)
print("B. 修改版：sendOneSeg / sendFileParallelOne 地址与大小")
print("#" * 74)
sm = syms(MOD)
for k in ["sendOneSegERK6DeviceS2_P5LFile", "sendFileParallelOneERK6DeviceP5LFile",
          "fsSegShareER7DataDec", "recvSegFileEP9TCPClient", "runSegEP8SegCoord",
          "isFileParallelEligibleEP5LFile", "LANShare8sendFile"]:
    a, sz, n = size_of(sm, k)
    print("  %-58s rva=%s size=%s" % (k, hex(a) if a else "-", sz))

print()
print("#" * 74)
print("C. 修改版 sendOneSeg 精确反汇编（决定：块大小/ack/收尾）")
print("#" * 74)
a, sz, n = size_of(sm, "sendOneSegERK6DeviceS2_P5LFile")
if a:
    t = dump_va(MOD, a, a + max(sz, 0x5A0), "MOD_sendOneSeg")
    facts(t, "MOD sendOneSeg  rva=0x%x size=%d" % (a, sz))
    print("    文件:", os.path.join(OUT, "MOD_sendOneSeg_%06x.txt" % a))

print()
print("#" * 74)
print("D. 源码版 FileSend::sendFileStreamEnc（真正的发送循环）")
print("#" * 74)
a, sz, n = size_of(ss, "FileSend17sendFileStreamEnc")
if a:
    t = dump_va(SRC, a, a + max(sz, 0x2C0), "SRC_sendFileStreamEnc")
    facts(t, "SRC FileSend::sendFileStreamEnc rva=0x%x size=%d" % (a, sz))
    print("    文件:", os.path.join(OUT, "SRC_sendFileStreamEnc_%06x.txt" % a))

print()
print("#" * 74)
print("E. 源码版 FileSend::send（入口，可能含握手 cmd）")
print("#" * 74)
a, sz, n = size_of(ss, "FileSend4sendE")
if a:
    t = dump_va(SRC, a, a + max(sz, 0x1860), "SRC_FileSend_send")
    facts(t, "SRC FileSend::send rva=0x%x size=%d" % (a, sz))
    print("    文件:", os.path.join(OUT, "SRC_FileSend_send_%06x.txt" % a))

print()
print("#" * 74)
print("F. 源码版 LANShare::sendFile 的 setCmd 值 + recvo 上下文（握手帧）")
print("#" * 74)
a, sz, n = size_of(ss, "LANShare8sendFile")
t = dump_va(SRC, a, a + max(sz, 0x1B90), "SRC_LANShare_sendFile")
lines = facts(t, "SRC LANShare::sendFile rva=0x%x size=%d" % (a, sz))
print("    --- 所有 setCmd/setByteCmd 参数（含上下文 2 行）---")
for i, l in enumerate(lines):
    if "setCmd" in l or "setByteCmd" in l:
        prev = [re.sub(r"^\s+", "", lines[j])[:80] for j in range(max(0, i - 3), i)]
        print("     >", re.sub(r"^\s+", "", l)[:90])
        for pv in prev:
            print("        ", pv)
