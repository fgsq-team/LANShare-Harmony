import io, re

p = r'E:\lanshare-harmony\logs\hb_full.log'
b = io.open(p, 'rb').read()
s = b.decode('utf-8', 'replace').replace('\x00', '')
lines = [l for l in s.split('\n') if l.strip()]

TS = re.compile(r'(\d\d:\d\d:\d\d\.\d+)')

hb = []
first_up = None
up_early = []
cnt = None
for l in lines:
    m = TS.search(l)
    if not m:
        if 'grep -c' in l or l.strip().isdigit():
            cnt = l.strip()
        continue
    t = m.group(1)
    if '[HB]' in l:
        hb.append(t)
    if '[UP]' in l:
        blk = re.search(r'blk#(\d+)', l)
        if blk and int(blk.group(1)) <= 256:
            up_early.append((t, int(blk.group(1))))
        if first_up is None:
            first_up = t

print('[HB] 总条数(grep -c): %s   实际解析到: %d' % (cnt, len(hb)))
if hb:
    print('[HB] 首条: %s' % hb[0])
    print('[HB] 末条: %s' % hb[-1])
print('[UP] 首条: %s' % first_up)
print()
if up_early:
    print('=== 上传早期 [UP]（前 256 块 = 前 64MB）===')
    for t, blk in up_early[:8]:
        print('  %s  blk#%d' % (t, blk))
print()
if hb and first_up:
    def sec(x):
        a, b_, c = x.split(':')
        return int(a) * 3600 + int(b_) * 60 + float(c)
    d = sec(first_up) - sec(hb[0])
    print('=== ★ 关键 ===')
    print('  第一次心跳报警  : %s' % hb[0])
    print('  上传第一块打点  : %s' % first_up)
    print('  差值            : %+.2f 秒（正 = 心跳早于上传）' % d)
    if d > 0:
        print('  ⇒ 心跳在上传**开始之前**就已报警 ⇒ 事件循环延迟不是上传造成的')
    else:
        print('  ⇒ 心跳报警晚于上传起点 %.2f 秒' % -d)
