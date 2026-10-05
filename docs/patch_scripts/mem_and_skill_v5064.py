# -*- coding: utf-8 -*-
"""把 5.0.64 的新约束并进 MEMORY.md（UI 节 + skill 第 31 节补「@State 不合并」）。"""
import io, sys

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'

s = io.open(MEM, encoding='utf-8').read()
sk = io.open(SKILL, encoding='utf-8').read()
if '5.0.64' in s:
    print('ALREADY APPLIED'); sys.exit(0)

# ---- MEMORY：UI 节补「@State 换引用不合并 + 闸门模式 + try/finally 铁律」 ----
OLD = ('- ★★ **5.0.63：`@State` 的 Map/数组「换引用」= 整个组件重渲染** —— `albumIndex` 是 '
       '`@State`，逐张换引用 ⇒ 收 15 张重渲染 15 次（观感是「闪一批」）。修法 = '
       '**去抖批量提交**（缓冲 + 150ms `setTimeout`），一批只换一次。⚠️ **必须去抖而非'
       '「攒够 N 张就提交」**：预任务是并发的，攒够会漏掉最后几张 ⇒「有的图永远不出现」。\n')
NEW = OLD + (
    '- ★★★ **5.0.64：ArkTS 的 `@State` 赋值**不会合并** —— 连续换 N 次引用 = N 次独立重渲染。'
    '修法 = **换引用闸门**：`beginStateSwap()` / `endStateSwap()` / `flushStateSwap()`，'
    '闸门内只往 `xxxNext` 缓冲记，最末一次性落地（存相册一次原本换 4 个 @State ⇒ 4 次重渲染 → 1 次）。'
    '⚠️ ①闸门**用计数器不用 boolean**（`refreshReceivedInner` 内部会调 `flushAutoSave` ⇒ 可重入）；'
    '② 内层 `endStateSwap` 在 depth>0 时必须**直接 return 不提前 flush**；'
    '③ **必须 try/finally** —— 内部有磁盘 IO，抛出则 depth 永久卡在 >0 ⇒ 之后**所有** @State '
    '只进缓冲不落地 ⇒ 界面永不更新且**无任何报错**（比闪严重得多）。'
    '⚠️ 绝不能靠「不换引用」消闪：数据真变了（沙箱副本已删），不换 = 界面不更新。**只能合并，不能跳过。**\n')
assert s.count(OLD) == 1, 'MEMORY 锚点 %d' % s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ---- skill 第 31 节：补「@State 不合并」与闸门模式 ----
OLDSK = '''### 排查顺序（下次「列表又闪了」照这个走）'''
NEWSK = '''### 变数源④：`@State` 赋值**不会合并**（比前三类更隐蔽）
ArkTS 里 `@State` **每换一次引用就触发一次独立重渲染**，连续赋值**不会**攒成一次。
「一次操作换了 4 个 `@State`」= 4 次重渲染 = 观感「闪几下」。

修法 = **换引用闸门**（先算完全部新值，最后统一落地）：
```typescript
private stateSwapDepth: number = 0;          // ⚠️ 计数器，不是 boolean（可重入）
private xxxNext: T | null = null;

private beginStateSwap(): void { this.stateSwapDepth += 1; }
private endStateSwap(): void {
  if (this.stateSwapDepth > 0) { this.stateSwapDepth -= 1; }
  if (this.stateSwapDepth > 0) { return; }   // ⚠️ 内层不得提前 flush
  this.flushStateSwap();
}
private flushStateSwap(): void { /* 逐个换引用，各处原有的「没变就不换」判断继续有效 */ }
```
四条容易踩的：
1. ⚠️ **必须 try/finally**。内部有磁盘 IO 等会抛异常的调用；一旦抛出而闸门没关，
   `depth` 永久卡在 >0 ⇒ 之后**所有** `@State` 更新只进缓冲不落地 ⇒
   **界面再也不更新、且没有任何报错**，只是「点了没反应」。**这比闪一次严重得多。**
2. ⚠️ 用**计数器**不用 boolean：包装层内部常会调另一个也走闸门的方法（可重入）。
3. ⚠️ 内层 `endStateSwap` 在 depth>0 时**直接 return**，否则会提前触发重渲染，白改。
4. ⚠️ **绝不能靠「不换引用」来消闪** —— 数据真的变了（文件已删、已记账），
   不换 = 界面不更新。**只能合并，不能跳过。**

★ 顺带一个设计手法：把原函数变成**薄包装**（开闸→调真身→关闸），真身改名
  `xxxInner`。这样**所有既有调用点零改动**，不必逐个跟改，也不必担心漏改。

### 排查顺序（下次「列表又闪了」照这个走）'''
assert sk.count(OLDSK) == 1, 'SKILL 锚点 %d' % sk.count(OLDSK)
sk = sk.replace(OLDSK, NEWSK, 1)

# 排查顺序补第 5 步
OLD5 = '4. 再查有没有在热路径里逐个 `this.someState = 快照()`。'
NEW5 = ('4. 再查有没有在热路径里逐个 `this.someState = 快照()`。\n'
        '5. 上面都不是 ⇒ 查「一次操作换了几个 `@State`」—— 用换引用闸门合并。')
assert sk.count(OLD5) == 1
sk = sk.replace(OLD5, NEW5, 1)

io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
io.open(SKILL, 'w', encoding='utf-8', newline='\n').write(sk)
print('OK  MEMORY -> %d  |  SKILL -> %d' % (len(s), len(sk)))
