import io, re

p = r'E:\lanshare-harmony\logs\probe526.log'
b = io.open(p, 'rb').read()
s = b.decode('utf-8', 'replace').replace('\x00', '')
lines = s.split('\n')
print('总行数 %d' % len(lines))
print()

hb = [l for l in lines if '[HB]' in l]
up = [l for l in lines if '[UP]' in l]
print('=== [HB] 心跳异常行: %d 条 ===' % len(hb))
for l in hb:
    print('  ' + l.strip()[:180])
print()
print('=== [UP] 行: %d 条 ===' % len(up))
for l in up[-14:]:
    print('  ' + l.strip()[:190])
print()
print('=== THREAD_BLOCK / SIGKILL ===')
for l in lines:
    if 'THREAD_BLOCK' in l or 'exit with signal' in l or 'versionName' in l or 'versionCode' in l:
        print('  ' + l.strip()[:180])
