# -*- coding: utf-8 -*-
"""把 5.1.2 / 5.1.3 的判据写进 MEMORY.md「方法论」节 + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

# ---------------- 1) MEMORY.md ----------------
s = io.open(MEM, encoding='utf-8').read()
if '5.1.2' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4b. ★★★★★ **两套「同形不同义」的状态不要硬复用，要新开一套 + 贴对应表**（5.1.2）。
    本项目已有 `albumMap`（消息 id+序号 → `相册URI|缩略图`），给非媒体文件加「已存入本地/已删除」时**不能复用** —— key 形态不同、value 语义不同（相册 vs 本地）。
    ★ 做法 = **照抄那套成熟套路，一比一对应**（内存 Map / preferences key / 落盘方法 / 加载段 / 查询方法 / 写点），并在注释里贴**对应表**。
    ★ **加载要与老的那次合并**（同一个 `preferences` 会话里一起读），不另开一次 IO。
    ★ 行格式 `key|value`，**key 必须一起写**（5.0.43 踩过：只写 value ⇒ 读回来还原不出 key ⇒ 索引全废且**无任何报错**）。
4c. ★★★★ **「按名字反查」必须先确认「名字真的在那个字段里」**（5.1.3 的实测教训）。
    ⚠️ v5.1.2 拿 `m.content` 比 `f.name` ⇒ **多发时永远匹配不上**（`content` 只是「N 个文件」那句），而**单发能对上、编译完全通过** ⇒ 极难发现。
    ★ 正确做法 = 查**消息是怎么建的**（`LanService.appendFileChat`）：媒体批 `content`=名字、`files`=名字；**非媒体 `content`=label、`files`=全部文件名（`\\n` 分隔）** ⇒ **必须查 `files` 并逐行比**，`content` 只作兜底。
    ★ 归入既有方法论第 2 条「1 个不触发、多个才触发 = 时序依赖」—— 这里其实是**数据结构差异**，但**症状形状相同**（单发对、多发错）⇒ 看到这形状要立刻想到「多发路径是不是另一条代码」。
    ★ 配套：既有反查口径是「**时间就近**」（`recvPathFor`），**记账必须与它一致**，否则「气泡 A 显示已存、实际存的是 B 那份」⇒ 命中多条时**各记一笔**。
4d. ★★★★ **记账时机：动作「真正完成」之后，不是「发起」时**（5.1.2）。另存为要**删完沙箱副本**才记「已存本地」（删失败时内容还在沙箱里）；删除要**仅当 `err === null`** 才记。
    ★ 通则：**「状态文案」必须与「事实真正成立」同步**，否则用户看到的是一个还没发生的将来时。
4e. ★★★★★ **判据按「事实维度」分派，不按「控件」分派**（5.1.2）。非媒体三态（`点击查看`/`已存入本地`/`已删除`）全部落在**同一个方法** `bubbleFooterText`，**顺序固定：先问「有没有动过」再落具体状态**。5.1.1 刚踩过「判据缺一维」，本轮把新维度**补在同一个方法**而不是散到别处。
4f. ★★★★★★ **ArkTS 注释里绝不能出现 `*/`**（5.1.3 踩到，编译直接失败）。我在 `/** */` 里写了 `/* 某参数 */` ⇒ **内层 `*/` 提前闭合外层** ⇒ 后面几十万字符被当代码解析 ⇒ 报出一堆**假错误**（`used before being assigned` 的 `ext`/`src`/`thumb`/`paths` 全是幻影，真错误只有一个 `Unexpected token`）。
    ★ **判据**：要表达「某参数是 N 个文件」就写纯文本，别用 `/* */` 行内注释。
    ★ 与「`.bat` 必须 ASCII-only（GBK 乱码吞行尾）」同族 —— 都是「注释里的语法会影响后续解析」。
    ★★ **配套：判据本身要先在真实数据上验证一次**。这轮查「嵌套注释」的判据连错两次：① `*/  /**`（相邻注释块）**不是**嵌套注释；② 但 `l.strip().startswith('*')` **会命中它**（strip 后确实以 `*` 开头）⇒ 正确判据必须**再排除以 `*/` 开头的行**。误判会让你以为修复没生效、反复重跑。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.2' in s and '5.1.3' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.2，跳过')

# ---------------- 2) VERSION_HISTORY.md ----------------
s2 = io.open(VER, encoding='utf-8').read()
if '5.1.3' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.2 / 5.1.3（2026-10-02 21:16 / 21:24）
- **5.1.2**：非媒体文件（zip/pdf/apk）气泡底部加「已存入本地 / 已删除」记账。
  新增 `localMap`（照抄 `albumMap` 套路，preferences key `localFileIndex`，行格式 `id|状态`）。
  写点：另存为**删完沙箱副本后**记「已存本地」；删除**仅当 `err === null`** 记「已删除」。
- **5.1.3**：修 5.1.2 **记账不生效** —— 文件名在 `m.files`（`\\n` 分隔）里，
  **不在 `m.content`**（非媒体的 `content` 只是「N 个文件」那句）⇒
  多发时匹配永远失败，而**单发能对上、编译完全通过**。
  ⚠️ 同时修 **ArkTS 不支持嵌套注释**（注释里有 `*/` 提前闭合 ⇒ 后面全文被当代码）。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

# ---------------- 3) 今日日志 ----------------
s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.3' not in s3:
    s3 = s3.rstrip('\n') + '''

## 21:24 v5.1.2 / v5.1.3 —— 非媒体气泡「已存入本地/已删除」+ 修它不生效

vivi 21:12 提需求，21:2x 反馈「功能没生效」。

### 5.1.2 设计：不能复用 `albumMap`，要新开一套
`albumMap` 的 key 是「消息 id+序号」、value 是「相册URI|缩略图」——
非媒体文件既没有相册 URI 也没有缩略图，两边都对不上。
⇒ **照抄那套成熟套路一比一对应**（`localMap` / preferences key `localFileIndex` /
落盘 / 加载 / 查询 / 写点），并在注释里贴**对应表**。
★ 加载与 `albumIndex` **同一次 preferences 会话**里一起读（不另开 IO）。
★ 行格式 `id|状态`，**key 必须一起写**（5.0.43 踩过：只写 value ⇒ 索引全废且无报错）。
★ 写点时机：另存为**删完沙箱副本后**才记；删除**仅当 `err === null`** 才记
   ⇒ 状态文案必须与「事实真正成立」同步，不能是「还没发生的将来时」。

### 5.1.3 根因：文件名在 `m.files`，不在 `m.content`
`appendFileChat` 的非媒体分支是
`appendChat(..., label /* 「N 个文件」 */, ..., names.join('\\n'))`
⇒ `content` 只是那句 label，**文件名全在 `files`（换行分隔）**。
v5.1.2 拿 `content` 比 ⇒ **多发 zip 永远匹配不上**，而
**单发能对上、编译完全通过** ⇒ 极难发现（形状上就是「1 个不触发、多个才触发」）。
修法：新增 `msgCarriesFileName()`，**按 `\\n` 拆 `files` 逐行比**，`content` 只作兜底
（媒体批两者同值，留着零成本且兼容历史数据）。

### ★★ 编译踩坑：ArkTS **不支持嵌套注释**
第一版修完编译失败，报 `Unexpected token` 在 3338 —— 我在注释里写了
`/* 「N 个文件」 */`，外层 `/** */` 被内层 `*/` **提前闭合** ⇒
后面几十万字符被当代码解析 ⇒ 报出一堆 `used before being assigned` 的**假错误**
（`ext`/`src`/`thumb`/`paths` 全是幻影，真错误只有那一个 `Unexpected token`）。

★ **注释里绝不能出现 `*/`**，哪怕本意是行内注释。
★ 与「`.bat` 必须 ASCII-only」同族 —— 注释里的语法会影响后续解析。

⚠️ 查「嵌套注释」的判据**连错两次**：`*/  /**`（相邻注释块，原文件 4345 行就有）
不是嵌套注释；但 `l.strip().startswith('*')` **会命中它**（strip 后确实以 `*` 开头）
⇒ 正确判据必须**再排除以 `*/` 开头的行**。
★ **判据本身要先在真实数据上验证一次**，否则误判会让你以为修复没生效、反复重跑。

**产物**：`LANShare-5.1.3.hap`（2,497,696 B，已推手机 Download）；
commit `ee93d3b`(5.1.2) + `feb55cb`(5.1.3)，tag `v5.1.3`。

**待 vivi 复测**：① 另存 zip 到本地后该气泡变「已存入本地」；
② 文件页删除后变「已删除」；③ **多发 zip 也要对**（5.1.3 修的就是这个）；
④ 重启 App 后状态仍在（`localFileIndex` 持久化）；⑤ 图片/视频的三分支不受影响。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
