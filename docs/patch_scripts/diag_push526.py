import io, re

p = r'E:\lanshare-harmony\logs\push_526.log'
b = io.open(p, 'rb').read()
s = b.decode('utf-8', 'replace').replace('\x00', '').strip()
print(s[-400:])
