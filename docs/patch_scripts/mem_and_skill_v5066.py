# -*- coding: utf-8 -*-
"""5.0.66：把「缓冲只能用于通知型状态」这条铁律写进 MEMORY + skill 第 31 节。"""
import io, sys

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'

s = io.open(MEM, encoding='utf-8').read()
sk = io.open(SKILL, encoding='utf-8').read()
if '5.0.66' in s:
    print('ALREADY APPLIED'); sys.exit(0)

# ---- 1. MEMORY：接在 5.0.65 那条后面 ----
OLD = '⚠️ **依赖布局的调用（`scrollEdge`）必须放闸门外**：要在布局更新后再滚，放闸门内会滚到旧布局位置。'
NEW = OLD + (
    '\n    ' + '\n    ' + '★★ **闸门缓冲只能用于「通知型」状态 —— 搞错会「功能整个坏掉」**（5.0.66 回归）。'
    '前提 = 该值**只给 UI 读**、**没有别的代码在同一条链上读它**。'
    '分类：**数据源**（`chat` / `receivedFiles`）⇒ **必须立即落地**；'
    '**通知型派生表**（`chatMediaPaths` / `chatGroups` / `chatMediaGroups` / `albumIndex`）⇒ 可缓冲合并。'
    '⚠️ 5.0.65 把 `chat` 也缓冲了，而同闸门内 `syncChatMediaPaths`/`buildChatGroups`/'
    '`autoSaveNewMedia` 都读 `this.chat` ⇒ 读到旧数组 ⇒ '
    '**`autoSaveNewMedia` 第一行 `if (oldCount >= this.chat.length) return;` 直接 return '
    '⇒ 自动存相册整个不执行**；另两个遍历旧数组 ⇒ 新消息不进消息页（切 TAB 才补上）。'
    '**一个原因 ⇒ 两个症状**。★ 症状表现为「UI 没更新」，极易误判成渲染问题，'
    '实际是数据依赖被破坏。\n')
assert s.count(OLD) == 1, 'MEMORY 锚点 %d' % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ---- 2. MEMORY：方法论第 3 条补「优化类改动的风险等级更高」 ----
OLD2 = ('3. ★ **防失败改动本身可能引入新 bug**（5.0.49 `release()` 改 `await` 反引入**挂起**）'
        '—— 每个防失败改动都要问「它会不会引入新的失败模式」。定不出真因就做看门狗。')
NEW2 = ('3. ★ **防失败改动本身可能引入新 bug**（5.0.49 `release()` 改 `await` 反引入**挂起**）'
        '—— 每个防失败改动都要问「它会不会引入新的失败模式」。定不出真因就做看门狗。'
        '★ **「优化类改动」（消除闪烁/卡顿/重绘）风险等级更高**：'
        '它们往往动「数据落地时机」，一旦破坏数据依赖，症状不是「变慢」而是'
        '**功能整个坏掉**（5.0.65→66：存相册整个失效）。'
        '**动优化前先画清「谁读这个值」**：数据源立即落地，只有纯通知才缓冲。')
assert s.count(OLD2) == 1, '方法论3 锚点 %d' % s.count(OLD2)
s = s.replace(OLD2, NEW2, 1)

# ---- 3. SKILL 第 31 节：补「缓冲资格判据」 ----
OLD3 = '''### ⚠️ 别凭「看起来相关」就锁定病因 —— 先读消费者'''
NEW3 = '''### ⚠️⚠️ 闸门缓冲只能用于「通知型」状态 —— 搞错会让**功能整个坏掉**
实战踩坑（比闪烁严重得多）：把 `chat` 也放进闸门缓冲，结果
- `autoSaveNewMedia()` 第一行 `if (oldCount >= this.chat.length) return;`
  —— `chat` 还在缓冲里没落地，`this.chat` 是旧数组 ⇒ **直接 return
  ⇒ 自动存相册整个不执行**（vivi 反馈「保存到相册功能没了」）；
- `syncChatMediaPaths()` / `buildChatGroups()` 遍历旧数组
  ⇒ 新消息不进消息页，「切一下 TAB 才对」。

**一个原因 ⇒ 两个症状**，且症状表现为「UI 没更新」，极易误判成渲染/性能问题。

★★ **缓冲资格判据（动闸门前先问）**：
> 这个值，**除了 UI 之外，还有别的代码会在同一条链上读它吗？**

| 类别 | 例子 | 处置 |
|---|---|---|
| **数据源** | `chat`、`receivedFiles` | **必须立即落地** —— 同链代码要读它 |
| **通知型派生表** | `*Paths`、`*Groups`、`albumIndex` | 可缓冲合并（计算已完成，只差通知） |

判据一句话：**派生表的「计算」读已落地的数据源，「通知」才进缓冲。**
⚠️ 典型隐患：数据源缓冲后，派生表的计算也会跟着错（两者都基于旧值），
    所以「只缓冲派生表」不只是省事，是**正确性要求**。

### ⚠️ 别凭「看起来相关」就锁定病因 —— 先读消费者'''
assert sk.count(OLD3) == 1, 'SKILL 锚点 %d' % sk.count(OLD3)
sk = sk.replace(OLD3, NEW3, 1)

io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
io.open(SKILL, 'w', encoding='utf-8', newline='\n').write(sk)
print('OK  MEMORY -> %d  |  SKILL -> %d' % (len(s), len(sk)))
