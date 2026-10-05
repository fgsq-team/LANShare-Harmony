# -*- coding: utf-8 -*-
"""5.0.67：把「闪可能是文件被原地覆盖」写进 MEMORY + skill 第 31 节。"""
import io, sys

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'

s = io.open(MEM, encoding='utf-8').read()
sk = io.open(SKILL, encoding='utf-8').read()
if '5.0.67' in s:
    print('ALREADY APPLIED'); sys.exit(0)

# ---- 1. MEMORY：接在「缓冲只能用于通知型」那条后面 ----
OLD = '实际是数据依赖被破坏。'
NEW = OLD + (
    '\n    ' + '\n    ' + '★★★ **「闪」不一定是渲染问题 —— 可能是「文件被原地覆盖」**（5.0.67）。'
    '`cacheThumb` 用 `OpenMode.TRUNC` 打开输出文件且**无「已存在就跳过」短路** ⇒ '
    '预生成已写好的 `album_thumbs/<key>.jpg` 在存相册时**被清空重写**，'
    '`Image` 正在读它 ⇒ 闪。'
    '⚠️ 此时 `src`/`rot`/key/`rows`/重渲染次数**全都没变**，'
    '所以「改 key」「合并重渲染」「改分组结构」**一个都治不了它**。'
    '判据：**闪的瞬间问「那个文件/资源的内容是不是被原地改了」**。'
    '修法 = 写前 stat，**存在且 size>0 就复用**。'
    '⚠️ 必须判「非空」：`TRUNC` 打开瞬间 size=0，只判「存在」在并发下会返回**半截文件**。\n')
assert s.count(OLD) == 1, 'MEMORY 锚点 %d' % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ---- 2. skill 第 31 节：把「文件被原地覆盖」加进变数源清单 ----
OLD2 = '### 排查顺序（下次「列表又闪了」照这个走）'
NEW2 = '''### 变数源⑤：显示的文件/资源被**原地覆盖**（最隐蔽，因为「什么都没变」）
症状：`Image`/视频/文档类元素闪一下，而**所有状态都没变** ——
key 稳、rot 稳、`rows` 稳、重渲染次数也已合并。
真因：那个**文件被截断重写**了，而组件正在读它。

本项目实例（5.0.67）：`cacheThumb` 用
`fileIo.OpenMode.CREATE | READ_WRITE | TRUNC` 打开输出文件，且**没有
「已存在就跳过」的短路** ⇒ 预生成（渲染时按需补）与存相册（`autoSaveAlbumBatch`）
对**同一路径**各写一次 ⇒ 第二次把第一次写的**清空重写** ⇒ `Image` 读到截断内容 ⇒ 闪。

★ 通用修法：**写之前先 stat，存在且非空就复用，不覆盖**。
⚠️ **必须判「非空」**：`TRUNC` 打开的瞬间 size 就是 0；同 key 并发时
只判「存在」会误判为已就绪而返回**半截文件** —— 那比闪更糟。
★ 配套习惯：**「幂等输出路径」的生成函数都要有「已存在就跳过」短路** ——
只要路径只由 key 决定（幂等），重写就是纯风险。
⚠️ 也提醒一句：这类保护往往**手动路径有、自动路径漏**（本项目 5.0.45 给手动存图
写了「源就是已有缓存缩略图时别再 cacheThumb 一遍」，自动存相册却一直漏着）。
**写完一条路径记得问：还有别的路径会调同一个生成函数吗？**

### 排查顺序（下次「列表又闪了」照这个走）'''
assert sk.count(OLD2) == 1, 'SKILL 锚点 %d' % sk.count(OLD2)
sk = sk.replace(OLD2, NEW2, 1)

# 排查顺序补第 6 步
OLD3 = '5. 上面都不是 ⇒ 查「一次操作换了几个 `@State`」—— 用换引用闸门合并。'
NEW3 = ('5. 上面都不是 ⇒ 查「一次操作换了几个 `@State`」—— 用换引用闸门合并。\n'
        '6. ★ **全都稳 ⇒ 查「那个文件/资源是不是被原地覆盖了」**（`TRUNC` 重写、'
        '`Image` 正在读）。这类最隐蔽，因为「所有状态都没变」。')
assert sk.count(OLD3) == 1
sk = sk.replace(OLD3, NEW3, 1)

io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
io.open(SKILL, 'w', encoding='utf-8', newline='\n').write(sk)
print('OK  MEMORY -> %d  |  SKILL -> %d' % (len(s), len(sk)))
