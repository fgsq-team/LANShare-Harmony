import io, re

b = io.open(r'E:\lanshare-harmony\logs\c525.log', 'rb').read()
h = b.decode('utf-8', 'replace').replace('\x00', '')
lines = h.split('\n')

TS = re.compile(r'(\d\d:\d\d:\d\d\.\d+)')

ups = []
kill = None
for l in lines:
    m = TS.search(l)
    if not m:
        continue
    t = m.group(1)
    if '[UP]' in l:
        ups.append(t)
    if 'exit with signal' in l and kill is None:
        kill = t

def sec(x):
    a, b_, c = x.split(':')
    return int(a) * 3600 + int(b_) * 60 + float(c)

print('[UP] 首条 : %s' % (ups[0] if ups else '(无)'))
print('[UP] 末条 : %s' % (ups[-1] if ups else '(无)'))
print('[UP] 条数 : %d' % len(ups))
print('SIGKILL  : %s' % kill)
if ups and kill:
    print('=> 末条距被杀 %.2f 秒' % (sec(kill) - sec(ups[-1])))
    print('=> 首条距被杀 %.2f 秒' % (sec(kill) - sec(ups[0])))

print()
print('=== 冻结检测相关异常 ===')
KEYS = ('hitrace id is invalid', 'getThreadCpuLoad failed',
        'enbleMainThreadSample', 'no freeze callback', 'XCollie', 'watchdog')
for l in lines:
    if any(k in l for k in KEYS):
        print('  ' + l.strip()[:190])
