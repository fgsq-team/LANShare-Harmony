# -*- coding: utf-8 -*-
"""
v5.1.3 编译修复：把注释里的**嵌套注释**去掉。

## 根因
我在 5.1.3 的注释里写了：
    `appendChat(..., label /* 「N 个文件」 */, ...)`
外层注释是 `/** ... */`，内层又出现 `/* ... */` ⇒ **ArkTS 不支持嵌套注释**，
内层的 `*/` 提前闭合了外层注释 ⇒ 后面几十万字符全被当代码解析
⇒ `Unexpected token` + 一堆「used before being assigned」的**假错误**。

★ 教训（与「.bat 必须 ASCII-only」同族）：**注释里绝不能出现 `*/`**，
哪怕它本意是行内注释。要表达「某个参数是 N 个文件」就写纯文本，别用 `/* */`。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# 两处：把 `/* xxx */` 里的注释内容改成用中文书名号包裹的纯文本
PAIRS = [
    (   chr(32)*3 + '//   ' + chr(96) + 'appendChat(..., label /* 「N 个文件」 */, ..., names.join(' + chr(39)+chr(92)+'n' + chr(39) + '))' + chr(96),
         chr(32)*3 + '//   ' + chr(96) + 'appendChat(..., label, ..., names.join(' + chr(39)+chr(92)+'n' + chr(39) + '))' + chr(96)
             + '  —— label 是「N 个文件」那句文案'),
    (   chr(32)*2 + '*   ' + chr(96) + 'appendChat(..., label /* 「N 个文件」 */, ..., names.join(' + chr(39)+chr(92)+'n' + chr(39) + '))' + chr(96) + '：',
         chr(32)*2 + '*   ' + chr(96) + 'appendChat(..., label, ..., names.join(' + chr(39)+chr(92)+'n' + chr(39) + '))' + chr(96)
             + '，label 就是「N 个文件」那句：'),
]

s = io.open(IDX, encoding='utf-8').read()
if '/* 「N 个文件」 */' not in s:
    print('ALREADY')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v513bpre'), 'w', encoding='utf-8', newline='\n').write(s)
print('备份完成')

for old, new in PAIRS:
    n = s.count(old)
    assert n == 1, '锚点命中 %d 次: %r' % (n, old[:50])
    s = s.replace(old, new, 1)

# 不变量：整文件里再也不能出现注释内的 */
assert '/* 「N 个文件」 */' not in s
# 全文件扫一遍：**注释行内**不能出现 '/*'（那才是嵌套注释）
# ⚠️ 判据连踩两次坑，教训记清：
#   ① `*/  /**` 是【合法的相邻注释块】（原文件 4345 行就有），不是嵌套注释；
#   ② 但 `l.strip().startswith('*')` **会命中它**（strip 后确实以 * 开头），
#      所以必须再排除掉以 `*/` 开头的行。
#   ⇒ 正确判据 = 「以 `*` 开头」**且**「不以 `*/` 开头」**且**「行内有 `/*`」。
bad = [l for l in s.split('\n')
       if l.strip().startswith('*')
       and not l.strip().startswith('*/')
       and '/*' in l]
assert not bad, '仍有嵌套注释: %r' % bad[:3]

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
print('OK  Index.ets %d chars（已清掉嵌套注释）' % len(s))
