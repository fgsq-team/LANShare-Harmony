import io, sys

APP = r'E:/lanshare-harmony/LANShareV5/AppScope/app.json5'
IDX = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'

OLD_V, NEW_V = '5.1.61', '5.1.62'
OLD_C, NEW_C = '5000161', '5000162'

# ---------- app.json5 ----------
a = io.open(APP, encoding='utf-8').read()
if NEW_V in a:
    print('app.json5 ALREADY APPLIED'); sys.exit(0)
assert a.count('"versionCode": %s' % OLD_C) == 1, 'versionCode anchor'
assert a.count('"versionName": "%s"' % OLD_V) == 1, 'versionName anchor'
a = a.replace('"versionCode": %s' % OLD_C, '"versionCode": %s' % NEW_C)
a = a.replace('"versionName": "%s"' % OLD_V, '"versionName": "%s"' % NEW_V)

# ---------- Index.ets ----------
s = io.open(IDX, encoding='utf-8').read()

# 1) ABOUT_FALLBACK_VER
old1 = "const ABOUT_FALLBACK_VER: string = '%s';" % OLD_V
new1 = "const ABOUT_FALLBACK_VER: string = '%s';" % NEW_V
assert s.count(old1) == 1, 'ABOUT_FALLBACK_VER anchor'
assert s.count(new1) == 0, 'ABOUT_FALLBACK_VER already new'
s = s.replace(old1, new1)

# 2) LAST_STABLE_VER  ★ 缩进敏感：必须带前导 \n
old2 = "\nconst LAST_STABLE_VER: string = '%s';" % OLD_V
new2 = "\nconst LAST_STABLE_VER: string = '%s';" % NEW_V
assert s.count(old2) == 1, 'LAST_STABLE_VER anchor'
assert s.count(new2) == 0, 'LAST_STABLE_VER already new'
s = s.replace(old2, new2)

# 3) 注释块同步（3 处 5.1.61 表述）
old3 = """ * ★ 5.1.61（vivi 10-04「把 5.1.61 标记为正式版，去掉关于页测试版角标」）：
 * **最后一个正式版**的版本号。
 *
 * ## 判据是「发布通道」，不是「新旧」
 * `5.1.61` 及更早 = 正式版；`5.1.61` 之后（如有） = 测试版。"""
new3 = """ * ★ 5.1.62（vivi 10-04「版本号 +1 并上传网盘」）：
 * **最后一个正式版**的版本号。
 *
 * ## 判据是「发布通道」，不是「新旧」
 * `5.1.62` 及更早 = 正式版；`5.1.62` 之后（如有） = 测试版。"""
assert s.count(old3) == 1, 'comment block anchor'
s = s.replace(old3, new3)

# 校验：值层面不应再有裸的 5.1.61 常量
for line in s.split('\n'):
    if OLD_V in line and 'const ' in line and "'" + OLD_V + "'" in line:
        raise AssertionError('leftover const: ' + line.strip())

io.open(APP, 'w', encoding='utf-8', newline='\n').write(a)
io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
print('APPLIED 5.1.62')
