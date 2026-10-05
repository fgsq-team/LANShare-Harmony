# -*- coding: utf-8 -*-
"""把 5.1.2 的四条判据写进 MEMORY.md 的「方法论」节（第 4 条之后）。"""
import io

P = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
s = io.open(P, encoding='utf-8').read()
if '5.1.2' in s:
    print('ALREADY')
    raise SystemExit(0)

ANCHOR = '5. ★ `hdc` 无设备时交付不停（夸克网盘）'
assert s.count(ANCHOR) == 1, s.count(ANCHOR)

ADD = '''4b. ★★★★★ **两套「同形不同义」的状态不要硬复用，要新开一套 + 明确对应表**（5.1.2）。
    本项目已有 `albumMap`（消息 id+序号 → `相册URI|缩略图`），要给非媒体文件加「已存入本地/已删除」时**不能复用** —— key 形态不同、value 语义不同（相册 vs 本地）。
    ★ 做法 = **照抄那套成熟套路，一比一对应**（内存 Map / preferences key / 落盘方法 / 加载段 / 查询方法 / 写点，六项逐一对应），并在注释里贴出**对应表** ⇒ 读代码时「这两套凭什么分开」一眼可见。
    ★ **加载要与老的那次合并**（同一个 `preferences` 会话里一起读），不另开一次 IO。
    ★ 行格式 `key|value`，**key 必须一起写**（5.0.43 踩过：只写 value ⇒ 读回来还原不出 key ⇒ 索引全废且**无任何报错**）。
4c. ★★★★ **「按名字反查」必须与既有反查口径一致**（5.1.2）。文件页按钮拿到的是 `ReceivedFile`，与 `ChatMessage` **无共享引用**（5.0.55「显示聚合≠记账聚合」的必然结果）⇒ 只能按 `f.name` 反查消息。
    ⚠️ 既有口径是「**时间就近**」（`recvPathFor` 按 `|f.time-msg.timeMs|` 排序取最近），**记账必须与它一致**，否则「气泡 A 显示已存、实际存的是 B 那份」⇒ 命中多条时**各记一笔**，别只记一条。
4d. ★★★★ **记账时机：动作「真正完成」之后，不是「发起」时**（5.1.2）。另存为要**删完沙箱副本**才记「已存本地」（删失败时内容还在沙箱里）；删除要**仅当 `err === null`** 才记。
    ★ 通则：**「状态文案」必须与「事实真正成立」同步**，否则用户看到的是一个还没发生的将来时。
4e. ★★★★★ **判据按「事实维度」分派，不按「控件」分派**（5.1.2）。非媒体三态（`点击查看`/`已存入本地`/`已删除`）全部落在**同一个方法** `bubbleFooterText` 里，**顺序固定：先问「有没有动过」再落具体状态**。
    ★ 5.1.1 刚踩过「判据缺一维」，本轮把新维度**补在同一个方法**而不是散到别处 —— 散开就会出现「某类输入漏判」而**编译期完全无感**。
'''

s = s.replace(ANCHOR, ADD + ANCHOR, 1)
assert '5.1.2' in s and chr(0xFFFD) not in s
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('OK MEMORY -> %d chars, 坏字符=%d' % (len(s), s.count(chr(0xFFFD))))
