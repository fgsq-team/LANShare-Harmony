# -*- coding: utf-8 -*-
"""
技能库更新 —— 把 5.0.20 这轮的三条通用教训沉淀进去（幂等）。

  ① harmonyos-tcp-socket-server  ← 「记录结束帧」坑（单条通过 ≠ 多条通过）
  ② harmonyos-hvigor-cli-build   ← python 补丁脚本骨架 + 延迟落盘纪律
  ③ harmonyos-live-device-probe  ← 反汇编未 strip 的对端 exe 定协议 + N≥2 验收

三个技能都是 agent_created: true，可修改。
"""

import io
import os
import sys

SK = r'C:\Users\vivi\.workbuddy\skills'
TCP = os.path.join(SK, 'harmonyos-tcp-socket-server', 'SKILL.md')
HVG = os.path.join(SK, 'harmonyos-hvigor-cli-build', 'SKILL.md')
PRB = os.path.join(SK, 'harmonyos-live-device-probe', 'SKILL.md')

S1 = '## ★ 坑十六：每条记录的「结束帧」—— 单条通过 ≠ 多条通过'
S2 = '## 无 IDE 时怎么批量改源码：python 补丁脚本 + 延迟落盘'
S3 = '## ★ 对端是未 strip 的桌面程序时：直接反汇编定协议'


def read(p):
    with io.open(p, 'r', encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\r\n' in s
    return s.replace('\r\n', '\n'), crlf


def write(p, s, crlf):
    if crlf:
        s = s.replace('\n', '\r\n')
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def sub_once(s, old, new, what):
    n = s.count(old)
    assert n == 1, '[%s] 命中 %d 次（期望 1）:\n---\n%s\n---' % (what, n, old[:200])
    return s.replace(old, new, 1)


# ============================================================================
# ① harmonyos-tcp-socket-server
# ============================================================================
B1 = '''## ★ 坑十六：每条记录的「结束帧」—— 单条通过 ≠ 多条通过

TCP 长连接上发**多条记录**（多个文件 / 多条消息）时，发送端通常会在每条记录之后补一帧
**结束标记**（一个 12 字节帧头，或单个魔术字节）。接收端「收到声明长度就收工」、
**不读这一帧** —— 在**只有一条记录时完全看不出来**，因为它后面没有别的记录了。

一旦来第二条，那帧残留就被下一条记录的**帧头解析**吃掉：

```
记录1 数据 …… [结束帧]
                  ↑ 没读走，留在接收缓冲里
记录2 12B 帧头  ← 读到的其实是记录1的「结束帧」
       → cmd == FS_END → break → 本条收到 0 字节 → 判失败 → 回「中止」 → 整体失败
```

真机症状（LANShare v5 / 1101，2026-10-01）：

```
v5 已保存 .../f1.bin (4194280 B, 2 片, 259ms)      ← 第 1 个成功
v5 接收字节数不符: 0 != 4194280（.../f2.bin）        ← 第 2 个收到 0 字节
```

对端（PC）的实际时序反汇编可见：每块数据后**阻塞**等 1 字节 ack，整个文件发完后补发一帧
`head[0]=2 (FS_END)`、`arg=0`、`len=0` 的 12 字节帧，然后**直接开始下一个文件**：

```asm
1400223ad: cmpq 80(%rax),%r14 ; je 0x1400224c0    # 已发字节 == 文件大小
1400224c0: movl $2,%edx ; callq DataEnc::setByteCmd   # → FS_END
1400223c0: ... getData()/getDataLen() -> TCPClient::send(data,len,0)
```

**修法（位置是关键）**：

```ts
while (subTotal < item.length) {          // 原有：收数据块
  ...
  await sendByte(chan, FS_NEXT);          // 块级 ack（见上一个坑）
}
// ★ 必须在循环**之外**：最后一块的块级 ack 已经回过，对端才会发这一帧
if (subTotal === item.length) {
  const tail = await chan.readExactly(12, END_FRAME_WAIT_MS);   // 给短超时兜底
  if (tail !== null) {
    const c = tail[0] & 0xFF;
    if (c === FS_END || c === FS_CLOSE) { /* 吃掉；len>0 也一并吃掉 */ }
    else { return false; }                  // 其它命令 = 帧流错位，明确报错
  }
  // tail === null（对端是「不发结束帧」的旧实现）→ 回退到按字节数判结束
}
```

三条铁律：

1. **顺序不能反**：先等结束帧、再回块级 ack ⇒ **双方对等死锁**
   （对端要等你 ack 才发下一块/才发结束帧，你在等结束帧）。
2. **必须给超时**并**回退到按字节数判结束** —— 别让「对端不发这一帧」变成 60 秒挂死。
3. **验收必须跑 N ≥ 2** —— 单条用例永远测不出这个坑。

**更一般的推论**：任何时候写「按长度判结束」的接收循环，先问一句
**「对端在这条记录之后还会发别的东西吗？」** 对端多发一帧、你少读一帧，
在 N = 1 时都表现为「完全正常」。

'''

s, crlf = read(TCP)
if S1 in s:
    print('SKIP  tcp-socket-server（已含坑十六）')
else:
    s = sub_once(
        s,
        '**该删的全部删干净**：`probePendingAt` / `probeTrust` / `noteProbeAnswer` /\n'
        '`DEADLINE_MS` / `MAX_RTT_MS` / `TRUST`。\n',
        '**该删的全部删干净**：`probePendingAt` / `probeTrust` / `noteProbeAnswer` /\n'
        '`DEADLINE_MS` / `MAX_RTT_MS` / `TRUST`。\n'
        '\n'
        '---\n'
        '\n' + B1,
        'tcp-socket-server / 追加点',
    )
    # frontmatter 关键词补一条
    s = sub_once(
        s,
        '当用户要"鸿蒙写 TCP 服务端""TCPSocketServer listen 收不到连接"',
        '多文件/多记录传输时第 2 个起失败、每条记录结束帧没消费、发送端多发一帧接收端少读一帧、\n'
        '当用户要"鸿蒙写 TCP 服务端""TCPSocketServer listen 收不到连接"',
        'tcp-socket-server / description 关键词',
    )
    write(TCP, s, crlf)
    print('OK    harmonyos-tcp-socket-server  : 新增坑十六 + description 关键词')

# ============================================================================
# ② harmonyos-hvigor-cli-build
# ============================================================================
B2 = '''## 无 IDE 时怎么批量改源码：python 补丁脚本 + 延迟落盘

命令行构建的工程，源码里往往全是中文长注释；用一般的「查找替换」改代码时锚点经常匹配不上、
或者匹配到不该改的地方。固定做法是：**写一个幂等的 python 补丁脚本 → 跑 → 再构建**，
脚本归档到 `docs/patch_scripts/`，每次改代码都留一份可追溯的记录。

### 骨架

```python
def read(p):
    with io.open(p, 'r', encoding='utf-8', newline='') as f:
        s = f.read()
    crlf = '\\r\\n' in s
    return s.replace('\\r\\n', '\\n'), crlf      # 统一按 LF 处理

def write(p, s, crlf):
    if crlf: s = s.replace('\\n', '\\r\\n')      # 按原行尾还原
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)

_doc, _orig = {}, {}                             # ★ 内存工作区

def edit(path, old, new, what):
    if path not in _doc:
        t, c = read(path); _doc[path] = [t, c]; _orig[path] = t
    s = _doc[path][0]
    assert s.count(old) == 1, '[%s] 命中 %d 次' % (what, s.count(old))
    if old not in new:                           # new 含 old 的「追加型」改法跳过这条
        assert s.count(new) == 0, '[%s] 疑似重复应用' % what
    _doc[path][0] = s.replace(old, new, 1)

# ... 所有 edit() 调用（只改内存）...

changed = [(p, v) for p, v in _doc.items() if v[0] != _orig[p]]
for p, (text, crlf) in changed:                  # ★ 最后一步才落盘
    write(p, text, crlf)
```

### ⚠️ 三条实测踩过的坑

1. **「最后统一落盘」必须真的做到。** 有个版本写成 `read → edit → write` **逐文件落盘**，
   在第 6 处锚点断言失败时，**前 5 个文件已经写进磁盘了** —— 只能从改动前快照全量回滚重做。
   所有改动先进 `_doc`，末尾一次性 `write()`。
2. **锚点按原文件逐字抄，含空格数。** `REM  apart` 与 `REM apart` 差一个空格就直接断言失败。
   先 `grep -n "关键字" 文件 | cat -A` 看清不可见字符，别凭记忆写锚点。
3. **幂等靠哨兵串**：每段新增内容里放一个独一无二的小标题，脚本开头见到它就整段跳过。
   重跑时干净 `exit 0`，不会「追加两遍」。
   ⚠️ 只靠 `assert count(new) == 0` 挡不住「new 里包含 old」的追加型改法 —— 必须配哨兵。

### 改完立刻做的三项校验

- `{` 与 `}` 的**增量必须为 0**（「少写一个收尾大括号」这类错误不会自己暴露）。
- 每次替换后 `grep` 被删/新增的**符号**，确认引用数符合预期
  （例：「新增 1 处调用 ⇒ 总数从 6 变 7」）。
- 落盘前先建**改动前快照**目录（如 `.backup_v<版本>/`），出问题可秒回滚。

'''

s, crlf = read(HVG)
if S2 in s:
    print('SKIP  hvigor-cli-build（已含补丁脚本节）')
else:
    s = sub_once(
        s,
        'USB 与 WiFi 指向**同一台手机、同一个目标路径**，所以 **USB 推成功就够了** ——\n'
        '不必为了"双通道"反复重连。\n',
        'USB 与 WiFi 指向**同一台手机、同一个目标路径**，所以 **USB 推成功就够了** ——\n'
        '不必为了"双通道"反复重连。\n'
        '\n'
        '---\n'
        '\n' + B2,
        'hvigor-cli-build / 追加点',
    )
    write(HVG, s, crlf)
    print('OK    harmonyos-hvigor-cli-build : 新增「python 补丁脚本 + 延迟落盘」')

# ============================================================================
# ③ harmonyos-live-device-probe
# ============================================================================
B3 = '''## ★ 对端是未 strip 的桌面程序时：直接反汇编定协议

当对端是 PC 上的 Qt / C++ 程序（不是能抓包解析的 HTTP 服务）时，**不需要猜协议、也不必抓包** ——
很多发布版 exe **没有 strip 符号表**，反汇编能直接读出**常量、帧格式和分支判据**。
比抓包快一个数量级，而且能拿到抓包拿不到的**条件判断**。

```bash
LLVM="/d/.../commandline-tools/sdk/default/openharmony/native/llvm/bin"
EXE="/e/path/Peer.exe"

# 1) 先拿符号地址（--demangle 让 C++ 名字可读；--numeric-sort 按地址排）
"$LLVM/llvm-nm.exe" --demangle --numeric-sort "$EXE" | grep -iE "send|recv|base"

# 2) 按地址切片反汇编（PE 的 .text 通常 va = 0x140000000 + RVA）
"$LLVM/llvm-objdump.exe" -d --demangle --no-show-raw-insn \\
    --start-address=0x140022160 --stop-address=0x1400224f0 "$EXE"
```

一次实测直接拿到的东西（对端是「每收一块回 1 字节、文件末尾补一帧结束标记」的握手协议）：

```asm
140022344: movl $2097152,%ebp        # ← 缓冲区大小常量，直接读到
14002234c: subl %eax,%ebp            # 减 12 字节帧头 = 块尺寸 2097140
14002235d: callq *%rbx               # io->read(buf+hdr, 2097152-12)
140022f48: cmpb $2,%al ; je 0x140022f10   # ← 读到 cmd==2 就结束本条记录
```

三个高价值信号：

| 看到什么 | 说明 |
|---|---|
| `movl $<n>,%e?x` 后紧跟 `sub`/`cmp` | 协议常量（缓冲大小、块尺寸、魔数、超时） |
| 间接调用（`callq *%r??`）+ 紧随的 `cmpb $1,%al` | 虚表分派 + 一字节应答判据 |
| `cmpb $2,%al ; je <退出块>` | **记录结束帧的判据** —— 对端靠这个判「本条记录收完」 |

⚠️ 反汇编只能证明**对端怎么做的**。本端改对了没有，仍要靠探针实测
（见「三、PC 侧伪装对端」+ 验收清单的「修复前后各跑一次」）。

'''

s, crlf = read(PRB)
if S3 in s:
    print('SKIP  live-device-probe（已含反汇编节）')
else:
    # 3a) 验收清单补两条
    s = sub_once(
        s,
        '- [ ] 环境类限制（防火墙 / AP / 设备能力缺失）与代码问题明确分开\n',
        '- [ ] **N ≥ 2 的用例**：单条记录通过 ≠ 多条记录通过 —— 协议里「每记录结束帧」这类\n'
        '      边界只在 ≥2 时现形（详见「★ 对端是未 strip 的桌面程序」一节的推论）\n'
        '- [ ] 环境类限制（防火墙 / AP / 设备能力缺失）与代码问题明确分开\n',
        'probe / 验收清单 N≥2',
    )
    # 3b) 新小节插在「八、」之前
    s = sub_once(
        s,
        '---\n'
        '\n'
        '## 八、验证「界面」而不只是「网络」：截图 + 模拟点击\n',
        '---\n'
        '\n' + B3 + '---\n'
        '\n'
        '## 八、验证「界面」而不只是「网络」：截图 + 模拟点击\n',
        'probe / 插入反汇编小节',
    )
    # 3c) frontmatter 关键词
    s = sub_once(
        s,
        '  内容级校验、标记法校验字节、修复前后对照探针、bm dump 应用级 versionName。\n',
        '  内容级校验、标记法校验字节、修复前后对照探针、bm dump 应用级 versionName、\n'
        '  反汇编未 strip 的对端 exe 定协议、llvm-nm llvm-objdump 读协议常量、\n'
        '  单条记录通过不等于多条记录通过、N≥2 用例验收。\n',
        'probe / description 关键词',
    )
    write(PRB, s, crlf)
    print('OK    harmonyos-live-device-probe: 新增反汇编小节 + N≥2 验收 + 关键词')

print('\n--- 自检 ---')
for p, s_, name in ((TCP, S1, 'tcp'), (HVG, S2, 'hvigor'), (PRB, S3, 'probe')):
    t, _ = read(p)
    assert t.startswith('---'), '%s 的 frontmatter 被破坏' % name
    assert s_ in t, '%s 缺少新增小节' % name
    print('  %-8s  %7d B   frontmatter OK   新节 OK' % (name, os.path.getsize(p)))
