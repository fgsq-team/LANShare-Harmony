# -*- coding: utf-8 -*-
"""
给 skill `harmonyos-arkui-ui-pitfalls` 追加第二十八节：
「列表按业务批次聚合成一个卡片/气泡（宫格多缩略图）」的做法与红线。

vivi 2026-10-02 要求「接受的图片和视频在一个气泡里显示多个缩略图，不显示文件名」，
而上一轮（5.0.53）刚刚为了「每张独立记账」把一批拆成了 N 条消息 —— 二者看似矛盾，
实则是「显示聚合 vs 记账聚合」的区分。这条经验跨项目通用。

幂等：哨兵判重。写文件保持 LF。
"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '## 二十八、把 N 条消息聚合成**一个**气泡（宫格多缩略图）'

ADD = '''

## 二十八、把 N 条消息聚合成**一个**气泡（宫格多缩略图）—— **显示聚合 ≠ 记账聚合**

### 场景

「同一次接收的 5 张图，界面上要**一个**气泡里显示 5 个缩略图（不要 5 个气泡、
不要文件名）」，但业务上每张图必须**各自独立**：各有自己的相册条目、自己的点击入口、
删掉一张不能影响其余。

这两件事**不矛盾**，前提是把它们分到两层：

| 层 | 粒度 | 说明 |
|---|---|---|
| **记账层**（消息数组 / 存储 / 相册索引 / 删除） | **一条消息 = 一张图** | 每张图独立成条目（本项目 5.0.53 的做法） |
| **显示层**（列表渲染） | **一个批次 = 一个气泡** | 按批号把连续的同批消息聚成一组 |

⚠️ **绝对不要**为了「一个气泡」去把 N 条消息**合并成一条** —— 那会把记账粒度退回到
「一条消息 = N 张图」，症状立刻回来：删一张全批失效、点不到第 2 张、缩略图互相覆盖。

### 做法：加一个「批号」字段 + 派生分组数组

**① 数据层**：给消息加批号，同一批共享同一个值（落盘也要存，否则重启后散开）

```ts
export class ChatMessage {
  batchId: string = '';   // 空串 = 不属于任何批次
}
// 生成时：一次 append 循环共用一个
private nextBatchId(): string { this.batchSeq += 1; return `g${this.batchSeq}-${Date.now()}`; }
```

**② 显示层**：把「消息数组」派生成「分组数组」，只在**结构变化**时换引用

```ts
export class ChatGroup {
  key: string = '';          // 稳定标识（组内 id 拼接）
  msgs: ChatMessage[] = [];  // ⚠️ 元素是原数组里的**同一引用**，不是拷贝
  isMedia: boolean = false;  // 整组都是图片/视频 → 渲染成宫格
  incoming: boolean = false;
  timeMs: number = 0;
}
```

```ts
private buildChatGroups(): void {
  const src: ChatMessage[] = this.chat;
  const out: ChatGroup[] = [];
  let i = 0;
  while (i < src.length) {
    const m = src[i];
    const g = new ChatGroup();
    g.msgs.push(m);
    let j = i + 1;
    // 同批消息一定是**连续**落进去的，所以只往右扫、不跨消息找
    if (m.batchId.length > 0 && m.kind === 'file') {
      while (j < src.length && src[j].batchId === m.batchId && src[j].kind === 'file') {
        g.msgs.push(src[j]); j += 1;
      }
    }
    i = j;
    g.isMedia = this.groupAllMedia(g);
    g.key = /* 组内 id 拼起来 */;
    out.push(g);
  }
  // ⚠️ 签名没变就不换引用 —— 这个方法在每次刷新里都会跑，
  //    无条件换引用等于每次刷新都重建整个列表
  if (sig !== this.groupsSig) { this.groupsSig = sig; this.chatGroups = out; }
}
```

**③ 渲染**：`ForEach` 换数据源；单条组**原样转发**给老的气泡 Builder

```ts
@Builder
chatGroupBubble(g: ChatGroup) {
  if (g.isMedia) { this.chatMediaBubble(g) } else { this.chatBubble(g.msgs[0]) }
}
```

> 单条组原样走老路径，是**零风险**的关键 —— 文本消息、文件名气泡、已发送消息、
> 以及**所有历史数据**（没有批号的）全部行为不变，只有「同批多张媒体」走新分支。

### 五个必须踩对的点

1. **ForEach 的 key 要带上「组内每一行会变的东西」**，不只是组的 id。
   本项目里缩略图路径、相册 uri 都是**组内各条各自**的：
   ```ts
   (g) => `${g.key}|${this.videoThumbTick}|${this.thumbTick}|${this.groupMediaSig(g)}|${this.groupAlbumSig(g)}`
   ```
   只放 `g.key` 的话，缩略图从空变实、相册条目从无到有，这一行都不会重建。

2. **宫格宽度不能写 `width('100%')`**。父 `Column` 是 wrapContent 宽，百分比会落到
   「无限宽」上（本项目 5.0.50 那个老坑的同款），2 张图也会撑满整行。
   按**列数**算一个确定宽度：
   ```ts
   private gridWidth(g: ChatGroup): number {
     const n = Math.min(3, g.msgs.length);
     return n * 92 - 4;   // 每格 88 + 4 间距
   }
   ```

3. **宫格里每个格子要有自己的 `onClick`**，直接落到**它自己那条数据**上
   （普通态打开这一张、多选态切换这一张的勾选）。
   这正是「点第 2 张就能打开第 2 张」的关键 —— 如果只有一个「整个气泡」的点击入口，
   那就退回到了「点不到第 2 张」。

4. **长按的语义要明确**：长按气泡 = 选中**整组**（用户视觉上就是一个卡片），
   多选态下点单格 = 只切换**那一格**。两条路都通，用户不用猜。
   整组勾选圆要有**中间态**（全选 `✓` / 部分 `−` / 未选空）。

5. **「整组都是媒体」的判据只看数据本身**，不要看「沙箱里还剩几个文件」——
   后者会被「自动存相册后删副本」改掉，导致宫格中途塌回文件名气泡。
   ```ts
   private groupAllMedia(g: ChatGroup): boolean {
     if (g.msgs.length < 2 || !g.msgs[0].incoming) { return false; }
     for (let i = 0; i < g.msgs.length; i++) {
       if (this.mediaNamesOf(g.msgs[i]).length === 0) { return false; }
     }
     return true;
   }
   ```

### 顺手做掉的一件事：图片/视频不显示文件名

缩略图已经说明内容了，再挂一串 `IMG_20260907_092804.jpg` 只是噪音。
判据用「**有没有可显示的媒体**」而不是扩展名 —— 后者在媒体还没落盘时
会把文件名闪出来一下再消失：

```ts
if (!(mediaPath.length > 0 && this.isMediaName(mediaPath))) {
  Text(m.content)   // 非媒体的文件（zip/pdf/apk…）没有缩略图，文件名是唯一标识，必须保留
}
```

### 排查口诀

- 「一批的多条想合成一个卡片」→ **先问记账粒度该多细**，再决定在哪一层聚合。
  记账粒度和显示粒度**本来就可以不一样**，别为了显示去动记账。
- 「合并成一个气泡后，点/删不出问题了但显示错乱」→ 查 key 有没有带上组内会变的字段。
- 「宫格宽度撑满一整行」→ 查是不是写了 `width('100%')`。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
anchor = '### 排查口诀（相册相关）'
assert s.count(anchor) == 1, '锚点命中 %d 次' % s.count(anchor)
s2 = s.replace(anchor, ADD.lstrip('\n') + '\n' + anchor)
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 已追加第二十八节，%d -> %d' % (len(s), len(s2)))
