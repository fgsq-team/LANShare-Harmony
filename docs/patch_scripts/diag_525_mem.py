import io, re

for name in ('mem525.log',):
    p = r'E:\lanshare-harmony\logs' + '\\' + name
    b = io.open(p, 'rb').read()
    h = b.decode('utf-8', 'replace').replace('\x00', '')
    print('=== %s (%d bytes) ===' % (name, len(h)))
    # 全量输出（该文件是我们 grep 过的，应该不长）
    seen = set()
    for l in h.split('\n'):
        t = l.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        print('  ' + t[:200])
    print()
