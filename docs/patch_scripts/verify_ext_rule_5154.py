# -*- coding: utf-8 -*-
"""验证 5.1.54 的改名规则：只看末尾后缀，正确则不动，不正确则「追加」到文件名最后。"""

def rtrim(s):
    return s.rstrip(' \t\n\r')

def strip_copy(name):
    n = name
    for _ in range(8):
        n = rtrim(n)
        if not n.endswith(')'):
            return n
        lp = n.rfind('(')
        if lp < 0:
            return n
        inner = n[lp + 1:len(n) - 1]
        if not (1 <= len(inner) <= 6) or not all('0' <= c <= '9' for c in inner):
            return n
        n = n[:lp]
    return n

# ★ 同一媒体类型的「等价后缀组」：判「末尾后缀对不对」的唯一标准
GROUPS = {
    'jpg':  ['jpg', 'jpeg', 'jpe', 'jfif'],
    'png':  ['png'],
    'gif':  ['gif'],
    'bmp':  ['bmp'],
    'webp': ['webp'],
    'heic': ['heic', 'heif', 'heics'],
    'avif': ['avif'],
    'tiff': ['tif', 'tiff'],
    'mp4':  ['mp4', 'm4v', 'mpeg4'],
    'mov':  ['mov', 'qt'],
    '3gp':  ['3gp', '3g2', '3gpp'],
    'mkv':  ['mkv', 'webm'],
    'avi':  ['avi'],
    'flv':  ['flv'],
    'mp3':  ['mp3'],
    'm4a':  ['m4a', 'aac', 'mp4a'],
    'wav':  ['wav', 'wave'],
    'ogg':  ['ogg', 'opus'],
    'flac': ['flac'],
}

def same_kind(tail, det):
    """末尾后缀与探测结果是否属于同一媒体类型。★ 大小写不敏感。"""
    t = tail.lower()
    alts = GROUPS.get(det.lower())
    if alts is not None:
        return t in alts
    return t == det.lower()

def tail_of(base):
    dot = base.rfind('.')
    if dot > 0 and dot < len(base) - 1:
        return rtrim(base[dot + 1:]).lower()
    return ''

def decide(name, det):
    base = rtrim(strip_copy(name))
    if same_kind(tail_of(base), det):
        return base, '不动'
    return base + '.' + det, '追加'

# ---- 自检：等价组必须自洽 ----
assert same_kind('jpg', 'jpg') and same_kind('jpeg', 'jpg') and same_kind('JFIF', 'jpg')
assert not same_kind('png', 'jpg') and not same_kind('1', 'jpg') and not same_kind('', 'jpg')
assert same_kind('webm', 'mkv') and same_kind('mov', 'mov') and not same_kind('mp4', 'mov')
print('等价组自检通过\n')

CASES = [
    # (原名, 魔数探测, 期望动作, 期望结果)
    ('a.jpg',               'jpg', '不动', 'a.jpg'),
    ('a.jpeg',              'jpg', '不动', 'a.jpeg'),          # jpeg ≡ jpg
    ('a.JPG',               'jpg', '不动', 'a.JPG'),           # 大小写无关
    ('a.jfif',              'jpg', '不动', 'a.jfif'),
    ('movie.mp4',           'mp4', '不动', 'movie.mp4'),
    ('v.MOV',               'mov', '不动', 'v.MOV'),
    ('x.webm',              'mkv', '不动', 'x.webm'),          # webm ≡ mkv
    ('扫描全能王 09.47.jpg (1)', 'jpg', '不动', '扫描全能王 09.47.jpg'),
    # ↓ 不正确 / 没有 ⇒ 追加
    ('abc.1',               'jpg', '追加', 'abc.1.jpg'),
    ('IMG_x.jpg.1',         'jpg', '追加', 'IMG_x.jpg.1.jpg'),
    ('test.png',            'jpg', '追加', 'test.png.jpg'),
    ('data.dat',            'png', '追加', 'data.dat.png'),
    ('无扩展名',              'png', '追加', '无扩展名.png'),
    ('a.jpg (1)',           'jpg', '不动', 'a.jpg'),           # 复制后缀先剥掉
]

bad = 0
for name, det, exp_act, exp_res in CASES:
    res, act = decide(name, det)
    ok = (act == exp_act and res == exp_res)
    if not ok:
        bad += 1
    print('%s %-30r det=%-5s -> %-32r %s（期望 %s %r）'
          % ('OK  ' if ok else 'FAIL', name, det, res, act, exp_act, exp_res))

print('\n用例 %d，失败 %d' % (len(CASES), bad))
raise SystemExit(1 if bad else 0)