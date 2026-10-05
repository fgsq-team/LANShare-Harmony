# -*- coding: utf-8 -*-
"""
v5.1.3 修 v5.1.2 的记账不生效（vivi 21:2x 反馈「功能没生效」）。

## ★ 根因（读代码确认，不是猜）
`markMessagesLocal` 用 `m.content` 去比 `f.name`：

```typescript
if (m.content === fileName || Index.stripDedupeSuffix(m.content) === bare) {
```

而**非媒体文件的消息，`content` 里根本没有文件名**（`LanService.appendFileChat:2234`）：

```typescript
// 媒体批（names.length > 1 且全是媒体）→ 每条 content = 自己的文件名 ✓
this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i], bid);

// ★ 非媒体走这一条：content = label（「N 个文件」或单发时的文件名）
//   files = 全部文件名，**换行分隔**
this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\n'));
```

⇒ 多发 zip 时 `content` = 「3 个文件」⇒ 匹配**永远失败** ⇒ 状态永远不写 ⇒
提示永远是「点击查看」。**编译完全通过、单发 zip 也能对上**，只有多发时失效
⇒ 这就是「1 个不触发、多个才触发」的典型（见 MEMORY 方法论第 2 条）。

## 修法
改用 **`m.files`**（真正的文件名载体，按 `\n` 拆开逐个比）：
- 单发：`files` = 该文件名 ⇒ 命中
- 多发：`files` = 全部文件名换行分隔 ⇒ 逐行比，命中包含 `fileName` 的那条
- `content` 保留**兜底**（媒体批的消息 `files` 与 `content` 同值，不冲突）

★ 与项目既有口径一致：`recvPathFor` 也是拿 `name` 去 `receivedFiles` 里找，
`f.name` 与 `files` 里的名字是**同一来源**（传输层给的原名）。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：匹配判据从 content 改成 files（逐行）
# =====================================================================
OLD1 = """    const bare: string = Index.stripDedupeSuffix(fileName);
    let hit: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (m.kind !== 'file' || !m.incoming) {
        continue;
      }
      if (m.content === fileName || Index.stripDedupeSuffix(m.content) === bare) {
        this.service.markLocalState(m.id, state);
        hit += 1;
      }
    }"""

NEW1 = """    const bare: string = Index.stripDedupeSuffix(fileName);
    let hit: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (m.kind !== 'file' || !m.incoming) {
        continue;
      }
      // ★★ 5.1.3 修：文件名在 **`m.files`** 里，不在 `m.content`。
      //   `appendFileChat` 的非媒体分支（LanService.ets:2234）是
      //   `appendChat(..., label /* 「N 个文件」 */, ..., names.join('\\n'))`
      //   ⇒ `content` 里根本没有文件名，只有 `files` 才有（换行分隔）。
      //   v5.1.2 误用 `content` ⇒ 多发 zip 时**永远匹配不上**、状态永远不写，
      //   而**编译完全通过、单发 zip 还能对上** ⇒ 极难发现（「1 个不触发、多个才触发」）。
      //   ⚠️ 必须**逐行**比：多发时 `files` 里有多行，`content` 只是那句 label。
      if (this.msgCarriesFileName(m, fileName, bare)) {
        this.service.markLocalState(m.id, state);
        hit += 1;
      }
    }"""

# =====================================================================
# 改 2：新增 msgCarriesFileName helper
# =====================================================================
OLD2 = """  /**
   * ★ 5.1.1：气泡底部**整行**提示。"""

NEW2 = """  /**
   * ★ 5.1.3：这条消息里**是否带了这个文件名**。
   *
   * ⚠️ **看 `files` 字段，不看 `content`** —— `appendFileChat` 的非媒体分支是
   *   `appendChat(..., label /* 「N 个文件」 */, ..., names.join('\\n'))`：
   *   `content` = 合并后的文案（**不含文件名**），`files` = 全部文件名（`\\n` 分隔）。
   *   v5.1.2 拿 `content` 比 ⇒ 多发时必失效（编译却完全通过）。
   *
   * 两处都查（`files` 为主、`content` 兜底）：
   *   - `files` 逐行：单发 = 1 行、多发 = N 行
   *   - `content` 兜底：**媒体批**的消息 `content` 与 `files` 同值（各带自己那个名字），
   *     虽然非媒体用不到，但留着零成本，且能兼容历史数据/将来新增的消息形态。
   */
  private msgCarriesFileName(m: ChatMessage, fileName: string, bare: string): boolean {
    if (m.files.length > 0) {
      const rows: string[] = m.files.split('\\n');
      for (let i: number = 0; i < rows.length; i++) {
        const n: string = rows[i];
        if (n === fileName || Index.stripDedupeSuffix(n) === bare) {
          return true;
        }
      }
    }
    return m.content === fileName || Index.stripDedupeSuffix(m.content) === bare;
  }

  /**
   * ★ 5.1.1：气泡底部**整行**提示。"""

REPL = [
    (OLD1, NEW1, '改1 判据改用 files'),
    (OLD2, NEW2, '改2 新增 msgCarriesFileName'),
]

# =====================================================================
# 改 3：版本号
# =====================================================================
OLDV = '"versionCode": 5000102'
NEWV = '"versionCode": 5000103'

s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if 'msgCarriesFileName' in s_idx:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v513pre'), 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(os.path.join(BAK, 'app.json5.v513pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

s = s_idx
for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.2"') == 1
s_ver = s_ver.replace('"versionName": "5.1.2"', '"versionName": "5.1.3"', 1)

# ---------------- 不变量 ----------------
assert 'private msgCarriesFileName(m: ChatMessage, fileName: string, bare: string): boolean {' in s
assert "const rows: string[] = m.files.split('\\n');" in s
assert 'if (this.msgCarriesFileName(m, fileName, bare)) {' in s
# 旧错判据必须消失
assert 'm.content === fileName || Index.stripDedupeSuffix(m.content) === bare) {\n        this.service.markLocalState' not in s
# 5.1.2 的记账链路完好
assert s.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);') == 1
assert s.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_DELETED);') == 1
assert 'const st: string = this.service.localStateOf(m.id);' in s
# 5.1.1 / 5.1.0 成果仍在
assert "private static readonly HINT_FILE: string = '点击查看';" in s
assert "private static readonly HINT_LOCAL_SAVED: string = '已存入本地';" in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d -> %d' % (len(s_idx), len(s)))
print('OK  versionCode 5000102 -> 5000103 / 5.1.3')
