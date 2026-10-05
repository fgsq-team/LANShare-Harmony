# -*- coding: utf-8 -*-
"""5.0.65：纠正 5.0.64 的判断错误 + 补「闸门要上提到真正的事务边界」。"""
import io, sys

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'

s = io.open(MEM, encoding='utf-8').read()
sk = io.open(SKILL, encoding='utf-8').read()
if '5.0.65' in s:
    print('ALREADY APPLIED'); sys.exit(0)

# ---- 1. MEMORY：UI 节补「闸门要上提到事务边界」+ 纠正 thumbTick 的判断 ----
OLD = '**只能合并，不能跳过。**'
NEW = OLD + (
    '\n- ★★★ **5.0.65：闸门要罩住「一次用户动作的整个事务边界」，不是某个函数。** '
    '5.0.64 把闸门只包在 `refreshReceived` 内部 ⇒ 结果一次接收完成仍换了 '
    '`tText`/`tPercent`/`transferring`/`chat`/`chatMediaPaths`/`chatGroups` '
    '**6~7 个 @State**（都在闸门外）⇒ 还闪一次。'
    '⚠️ 判据 = **数「一次 emit / 一次回调里换了几个 @State」**，不是「我这次改了哪个函数」。'
    '⚠️ 闸门内**幂等标记必须立即落值**（`lastChatCount`/`lastHadTransferText`）—— '
    '它们不是给 UI 看的，延迟落值会让下一次 emit 重复进同一分支。'
    '⚠️ **依赖布局的调用（`scrollEdge`）必须放闸门外**：要在布局更新后再滚，'
    '放闸门内会滚到旧布局位置。\n')
assert s.count(OLD) == 1, 'MEMORY 锚点 %d' % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ---- 2. MEMORY：方法论补一条「移动代码要处理原位置残留」 ----
OLD2 = '5. ★ **「上一版好好的、这一版坏了」→ 先 `git diff vPrev vCur`**。'
NEW2 = ('5. ★ **移动一段代码时，必须同时删掉「它原来所在位置的残留」**（5.0.65）：把 '
        '`transferring` 赋值挪进新闸门时忘了删原处那两行 ⇒ `hadTransfer` 重复声明 ⇒ '
        '`10505001`（报错**只给行号不给文件名**，skill 里记过这个坑）。'
        '定位法 = 完整构建日志落盘 + `grep 10505001 -B 6`。\n'
        + OLD2)
assert s.count(OLD2) == 1, '方法论5 锚点 %d' % s.count(OLD2)
s = s.replace(OLD2, NEW2, 1)

# ---- 3. SKILL 第 31 节：补「闸门边界」与「先核实再下结论」 ----
OLD3 = '''★ 顺带一个设计手法：把原函数变成**薄包装**（开闸→调真身→关闸），真身改名
  `xxxInner`。这样**所有既有调用点零改动**，不必逐个跟改，也不必担心漏改。'''
NEW3 = OLD3 + '''

### ⚠️ 闸门必须罩住「一次用户动作的整个事务边界」，不是某个函数
实战踩坑：闸门只包在 `refreshReceived` 内部，结果一次接收完成**仍然**换了
`tText` / `tPercent` / `transferring` / `chat` / `chatMediaPaths` / `chatGroups`
**6~7 个 `@State`**（全在闸门外）⇒ 观感还是闪一下。
⇒ **判据是「一次 emit / 一次回调里换了几个 `@State`」，要数到这个粒度**，
不是「我这次改了哪个函数」。自问：**这次用户动作一共会换几个可观察量？**

三条配套注意：
1. ⚠️ 闸门内**幂等标记必须立即落值**（如 `lastChatCount`）—— 它不是给 UI 看的；
   延迟落值会让下一次 emit 重复进同一分支。
2. ⚠️ **依赖布局的调用（`scrollEdge` / `scrollTo`）必须放闸门外** ——
   要在布局更新后再滚，放闸门内会滚到旧布局位置。
3. ⚠️ 移动代码时**同时删掉原位置的残留**（见方法论：移动一段代码要处理原位置残留）。

### ⚠️ 别凭「看起来相关」就锁定病因 —— 先读消费者
实战踩坑：症状是「消息页图片列表闪」，我直接锁定了 `thumbTick`（全局比例计数器）。
读代码发现**消息页宫格根本不读比例** —— `chatMediaFixed(path, GRID_SIDE)` 是
**固定正方形**（为了「每行固定 N 个」），`autoResize(true)` 也不需要预知比例；
`ratioOf`/`thumbW`/`thumbH` 只服务**另一个页面**。
⇒ **锁定病因前，先确认「那个变量真的被出问题的那个 UI 消费」**。
把相邻的同类计数器当成元凶，会白改一整轮。'''
assert sk.count(OLD3) == 1, 'SKILL 锚点 %d' % sk.count(OLD3)
sk = sk.replace(OLD3, NEW3, 1)

io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
io.open(SKILL, 'w', encoding='utf-8', newline='\n').write(sk)
print('OK  MEMORY -> %d  |  SKILL -> %d' % (len(s), len(sk)))
