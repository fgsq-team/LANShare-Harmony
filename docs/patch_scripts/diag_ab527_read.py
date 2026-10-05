import io, re

b = io.open(r'E:\lanshare-harmony\logs\ablate527.log', 'rb').read()
s = b.decode('utf-8', 'replace').replace('\x00', '')
lines = s.split('\n')
TS = re.compile(r'(\d\d:\d\d:\d\d\.\d+)')

hb = [l for l in lines if '[HB]' in l]
up = [l for l in lines if '[UP]' in l]
mark = [l for l in lines if '[UP27]' in l]

print('=== [UP27] 实验标记: %d 条 ===' % len(mark))
for l in mark:
    print('  ' + l.strip()[:150])
print()
print('=== [HB] 心跳异常（>500ms）: %d 条 ===' % len(hb))
for l in hb:
    print('  ' + l.strip()[:150])
print()
print('=== [UP] 打点: %d 条 ===' % len(up))
for l in up[-16:]:
    print('  ' + l.strip()[:190])
print()

rows = []
for l in up:
    m = re.search(r'\[UP\] blk#(\d+) ([\d.]+)MB tot=(\d+)ms read=(\d+) feed=(\d+) other=(\d+) hblag=(\d+)', l)
    if m:
        g = m.groups()
        rows.append((int(g[0]), float(g[1]), int(g[2]), int(g[3]), int(g[4]), int(g[5]), int(g[6])))
if rows:
    print('=== 累计口径（最后一条）===')
    r = rows[-1]
    tt = r[2]
    print('  已收 %.1f MB，总耗时 %d ms' % (r[1], tt))
    print('  read 累计  %6d ms  (%5.2f%%)' % (r[3], r[3] * 100.0 / tt))
    print('  feed 累计  %6d ms  (%5.2f%%)' % (r[4], r[4] * 100.0 / tt))
    print('  other 累计 %6d ms  (%5.2f%%)' % (r[5], r[5] * 100.0 / tt))
    print('  hblag(瞬时) %d ms' % r[6])
    print()
    print('=== 与 5.1.26（有 UI）对比 ===')
    print('  5.1.26: 480.2MB / 29010ms = 16.6 MB/s，有 [HB] 报警 9 条')
    print('  5.1.27: %.1fMB / %dms = %.1f MB/s，%s'
          % (r[1], tt, r[1] * 1024 / (tt / 1000.0),
             ('[HB] 报警 %d 条' % len(hb)) if hb else '[HB] 报警 0 条 ★'))
    print()
    print('=== 逐段速率（判断是否全程恒定）===')
    for i in range(max(1, len(rows) - 6), len(rows)):
        a, c = rows[i-1], rows[i]
        dmb = c[1] - a[1]
        dt = c[2] - a[2]
        if dt > 0:
            print('  blk#%-5d Δ%6.1fMB Δ%6dms -> %.1f MB/s'
                  % (c[0], dmb, dt, dmb * 1024 / dt))

print()
print('=== ui_log 尾部（是否记录了「网页上传完成」）===')
import os
p2 = r'E:\lanshare-harmony\logs\ui_ab527.txt'
if os.path.exists(p2):
    t = io.open(p2, encoding='utf-8', errors='replace').read()
    for line in t.split('\n')[-14:]:
        print('  ' + line.strip()[:130])
    print()
    print('  「网页上传完成」出现次数: %d' % t.count('网页上传完成'))
    print('  「上传失败/超时」出现次数: %d' % (t.count('上传失败') + t.count('上传超时')))
