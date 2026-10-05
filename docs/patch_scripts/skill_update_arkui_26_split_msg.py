# -*- coding: utf-8 -*-
"""
更新 skill `harmonyos-arkui-ui-pitfalls` 第二十六节：
5.0.52 的「消息id#媒体序号」只是**备选**方案；5.0.53 的真机反馈证明它治不彻底
（删一张后其余几张也不再跳相册 —— 因为气泡只有一个点击入口）。
把「**拆消息**」提升为首选修法。

幂等：哨兵判重。写文件保持 LF。
"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '首选修法（5.0.53）：把消息**拆开**'

OLD_TITLE = '## 二十六、一批多个文件 = **一条**消息 —— 按「消息 id」记账的东西必须加「媒体序号」'
NEW_TITLE = '## 二十六、一批多个文件 = **一条**消息 —— 记账粒度必须跟「最细的可变化单位」对齐'

OLD_ANCHOR = '### 修法 ①：key 改成 `消息id#媒体序号`'

NEW_BLOCK = '''### ★★ 首选修法（5.0.53）：把消息**拆开**，别在下标上做文章

下面的 `消息id#媒体序号` 只是「在一条消息里硬塞 N 个槽位」—— **能治，但治不彻底**：

- 气泡仍然只有**一个**点击入口，只能指向这一批的第 1 张，用户**根本点不到第 2 张**；
- 于是「在相册里删掉第 1 张」会把那个**唯一入口**的判定摘掉，**其余几张也跟着不再跳相册**
  （5.0.52 真机反馈原话）；下标还得靠 `m.files` 反推、路径还得靠「时间就近」去猜。

**更根本的做法：在「生成消息」那一步就把批量媒体拆成 N 条消息。**

```ts
// 接收终态的入口：整批**全是**图片/视频且 N>1 → 每个文件一条消息
private appendFileChat(incoming: boolean, peerName: string, peerIp: string,
                       label: string, names: string[], source: string): void {
  if (incoming && names.length > 1 && LanService.allMedia(names)) {
    for (let i: number = 0; i < names.length; i++) {
      this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i]);
    }
    return;
  }
  this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\\n'));
}
```

好处是**不用改任何下游代码**：每条消息的 `id` 天然唯一 ⇒ 相册索引 / 缩略图文件名 /
旋转角 / `ForEach` key 全部自动正确；点击时「第 i 条 = 第 i 张」，再也不会指向别人。
（5.0.52 那套 `#序号` 机制可以原样留着做**旧数据兼容**，新数据上它退化成 k 恒为 0。）

**拆与不拆的边界**（按用户预期定，别自作主张）：

| 情况 | 处理 | 理由 |
|---|---|---|
| 接收 · 整批全是图片/视频 · N>1 | **拆成 N 条** | 每张要有自己独立的相册记录与点击入口 |
| 接收 · 混合批（1 张图 + 1 个 zip） | 保持一条 | 否则用户以为收了两次 |
| **发送**方向 | **保持一条** | 发送侧点气泡只跳「文件」页，没有相册语义，拆开只是变啰嗦 |

⚠️ 「是不是媒体」的判定**必须全局唯一**：`LanService.isMediaFileName()` 决定**拆不拆**，
UI 的 `isMediaName()` 决定**显不显示缩略图** —— 两边不一致就会出现
「拆了却没缩略图」或「没拆却有缩略图」。做法：UI 那边**直接委托**给它，不要各留一张扩展名表。

⚠️ 已知边界：同一次传输里出现**两张完全同名**的图（罕见）时，拆开后两条消息的 `timeMs`
只差几毫秒，「时间就近」可能都指向同一个文件。正常相机文件名不重名，不值得为它加复杂度。

---

### 以下是**备选**方案：在一条消息里塞 N 个槽位（5.0.52 的做法，保留兼容旧数据）

'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count(OLD_TITLE) == 1, '标题锚点命中 %d 次' % s.count(OLD_TITLE)
assert s.count(OLD_ANCHOR) == 1, '修法①锚点命中 %d 次' % s.count(OLD_ANCHOR)
assert s.count(NEW_TITLE) == 0 and s.count(NEW_BLOCK) == 0, '新文本此前已存在'

s2 = s.replace(OLD_TITLE, NEW_TITLE).replace(OLD_ANCHOR, NEW_BLOCK + OLD_ANCHOR)
assert s2.count('### ★★ 首选修法') == 1
assert s2.count('### 修法 ①') == 1
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 第二十六节已更新，%d -> %d' % (len(s), len(s2)))
