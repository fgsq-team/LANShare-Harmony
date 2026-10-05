# -*- coding: utf-8 -*-
"""
5.0.21 收尾：把「官方安卓发文字收不到 / 鸿蒙发文字安卓收到两次」的根因、修复与实测
写进 docs/PENDING_TEST.md、工作区日志、MEMORY.md 与技能 harmonyos-live-device-probe。

工程铁律：
  - 哨兵幂等（重跑直接 SKIP，不写不报错）
  - 双断言：assert s.count(new) == 0 且 assert s.count(old) == 1
  - 先全部校验 + 内存构造，最后统一落盘（任一失败一个字都不写）
"""
import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
WSDOC = r'E:\lanshare项目\.workbuddy\memory'

PENDING = os.path.join(ROOT, 'docs', 'PENDING_TEST.md')
WSLOG = os.path.join(WSDOC, '2026-10-01.md')
WSMEM = os.path.join(WSDOC, 'MEMORY.md')
SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-live-device-probe\SKILL.md'

S_PENDING = '# 5.0.21 —— 修复「官方安卓发文字鸿蒙收不到 / 鸿蒙发文字安卓收到两次」'
S_WSLOG = '## 5.0.21 —— 官方安卓 UDP 消息收不到 + 同 IP 重复投递'
S_WSMEM = '### V5 UDP 消息与同 IP 去重（5.0.21 定案）'
S_SKILL = '## ★ 同一魔数下的协议版本分叉：按对端广播版本号分流，别无条件解析'


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read()


_docs = {}
_origs = {}


def load(p):
    if p not in _docs:
        _origs[p] = read(p)
        _docs[p] = _origs[p]
    return _docs[p]


def edit(p, old, new, label):
    s = load(p)
    if s.count(new) != 0:
        raise AssertionError('[%s] 新文本已存在（重复插入风险）' % label)
    if s.count(old) != 1:
        raise AssertionError('[%s] 锚点命中 %d 次（期望 1）' % (label, s.count(old)))
    _docs[p] = s.replace(old, new)
    print('  [PLAN] %-46s %s' % (label, os.path.basename(p)))


def write_all():
    n = 0
    for p, new in _docs.items():
        if new == _origs[p]:
            continue
        # 按原文件行尾还原
        orig = _origs[p]
        crlf = '\r\n' in orig
        out = new.replace('\n', '\r\n') if crlf else new
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(out)
        n += 1
        print('  [WRITE] %s (%d -> %d B)' % (p, len(orig), len(out)))
    print('  落盘文件数：%d' % n)


# ==========================================================================
# 1) docs/PENDING_TEST.md —— 追加一节
# ==========================================================================
PENDING_SEC = S_PENDING + r'''

**用户报告**：官方安卓版发文字消息 → 鸿蒙版收不到；鸿蒙版发文字 → 安卓版**收到两次**。

## 根因 1：UDP 帧解析无条件读「已知设备表」（→ 官方安卓的文字一条都收不到）

UDP 帧 = 明文 MAGIC `0x66677371`(4B) + 整帧逐字节 `((b-1)&0xFF)^0x45` 混淆。
设备头固定 8 个字段（`port / ip / name / devMode / uuid / dataVersion / 77 / 2`），
**第 8 个字段之后 v4 与 v5 就分叉了**：

| 版本 | 8 字段之后 |
|---|---|
| **v4**（官方 `Config.DATA_VERSION = LVersion.DATA_VERSION_4`） | **直接就是命令专属参数**（`messageEnc` 密文 hex / 包名 / 剪贴板） |
| **v5**（1.35 修改版） | `int 已知设备数` → `N×(int port, String ip, String name)` → 命令参数 |

证据（官方 Java 源码，非推断）：
- `LANService.java:1917` `makeDataEncUdp()` 只写 8 个设备字段，**没有**已知设备表。
- `handleUdp()` 读完 8 字段后直接 `dec.readUTF()` 取命令参数。

旧 `V5Udp.parse` **无条件** `dec.int()` 当设备数 → 把 v4 的 `messageEnc` 长度前缀
（实测 181）当成设备数 → `readKnown` 把整段消息吃穿 → `extras` 全空 →
收到 `1004` 时打 `UDP 消息帧缺少密文字段` → **消息被丢弃**。
（设备发现不受影响，因为发现只读 8 字段 —— 症状就是「能看到设备、收不到文字」。）

**修复**：按对端广播的 `dataVersion`（= uuid 后缀，`V5Header.read` 已解析并剥掉）分流：

```ts
frame.device = dev;
if (dev.dataVersion >= LanConfig.V5_MIN_DATA_VERSION) {
  const knownCount: number = dec.int();
  frame.known = V5Header.readKnown(dec, Math.min(knownCount, 64));
}
```

**修复前真机日志**（未修的 5.0.20）：
```
W .../V5Codec: 字符串长度越界: 825255268 > 78      ← 长度前缀被当成设备数
I .../LanService: UDP 消息帧缺少密文字段，来自 192.168.10.186
```

## 根因 2：设备表 key 用 uuid、存活续命用 IP（→ 安卓收到两次）

`devices` 的 key 是 `uniqueUuid`，而 `tcpProbeStep` 的 TCP 复核**只认 IP** ——
复核成功就把 `d.lastSeenMs` 刷新。于是同一台物理机只要换过 uuid
（重装 App / 官方版与 1.35 双版本共存 / 清数据），**旧条目会被新条目的存活续命**，
`DEVICE_OFFLINE_MS`(8s) 永远清不掉。

`onlineDeviceList()` 返回多条同 IP 记录 → 群发时**同一台设备收到 N 份**。

**修复前真机 hilog（同一秒三条，来自同一台 DBY-W09 @ 192.168.10.100）**：
```
已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4，3 字）
已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4，3 字）
已发送消息到 DBY-W09（192.168.10.100:5856，协议 v5，3 字）
```

**修复（两道保险）**：
1. `dropSameIpExcept(ip, keepKey)` —— UDP 发现（`:901`）与 `trackPeer` 入站（`:2378`）
   两个写入点都先清掉同 IP 的旧条目。**不清 per-IP 探测状态**
   （`probeSentAt / tcpEverOk / tcpProbeMiss / lastTcpProbeAt` 键是 IP，继续有效）。
2. `onlineDeviceList()` 兜底护栏 —— 即使残留多条同 IP 也只会各投一份，
   保留 `lastSeenMs` 最新的那条。

## 自主复现（不依赖安卓真机）

`tests/live-probe/v4_udp_dup_probe.mjs` 在 PC 上伪造 **2 台同 IP、不同 uuid** 的设备
心跳 → 真机设备表出现 **3 条 `192.168.10.186`**（`vivi` / `DUP-A` / `DUP-B`），
与用户日志里 `DBY-W09` 的 3 条完全同构。

## 实测结果（5.0.21，已装在真机）

| 验证项 | 判据 | 结果 |
|---|---|---|
| **v4 形态**（官方安卓）UDP 1004 消息 | WS 收到 `cmd=1` 且文本匹配 | ✓ PASS |
| **v5 形态**（1.35，带已知设备表）回归 | 同上 | ✓ PASS |
| **同 IP 去重** | 设备表 `192.168.100 ×1`、`192.168.186 ×1` | ✓ 由 3 条降为 1 条 |

端到端断言脚本：`tests/live-probe/udp_msg_e2e.mjs`
（连 WebSocket → 发 UDP 探针包 → 断言收到聊天推送）。
探针：`v4_udp_msg_probe.mjs`（支持 `--ver 4/5` 切换形态）/ `v4_udp_dup_probe.mjs`。

> 验证期间 WS 里连续收到安卓真机发的 `gghhhjjj`、`hhhjjjjk`、`回来看看能不能自动的`
> —— 安卓 → 鸿蒙方向已实际打通。

## 仍需 vivi 手工确认
用安卓真机发**长文本**（> 700 字节，官方走 TCP `1105` 而不是 UDP），
确认 TCP 路径同样正常（本轮只验证了 UDP 短消息路径）。
'''

# ==========================================================================
# 2) 工作区日志 —— 追加
# ==========================================================================
WSLOG_SEC = '''
''' + S_WSLOG + r'''

- 用户报告：官方安卓发文字 → 鸿蒙收不到；鸿蒙发文字 → 安卓**收到两次**。
- **根因 1（收不到）**：UDP 帧的第 8 个设备字段之后 **v4/v5 分叉**。
  官方 v4（`Config.DATA_VERSION = DATA_VERSION_4`）**没有**「已知设备表」，
  8 字段后直接是命令参数；1.35 v5 才多出 `int 已知设备数 + N×表`。
  旧 `V5Udp.parse` 无条件 `dec.int()` → 把 v4 的 `messageEnc` 长度前缀（181）当设备数
  → `readKnown` 把消息吃穿 → `extras` 空 → 打 `UDP 消息帧缺少密文字段` → 丢弃。
  官方源码证据：`LANService.java:1917 makeDataEncUdp()` 只写 8 字段；
  `handleUdp()` 读完 8 字段直接 `readUTF()` 取参数。
  修法：`if (dev.dataVersion >= LanConfig.V5_MIN_DATA_VERSION) { ...读已知表... }`。
- **根因 2（收到两次）**：`devices` 的 key 是 `uniqueUuid`，但 `tcpProbeStep` 的
  TCP 复核**只认 IP** 并刷新 `lastSeenMs` ⇒ 同一台机器换过 uuid 后
  **旧条目被新条目续命**，`DEVICE_OFFLINE_MS`(8s) 永远清不掉 ⇒
  `onlineDeviceList()` 多条同 IP ⇒ 群发多投。
  修法两道保险：`dropSameIpExcept()`（UDP 发现 + trackPeer 两处写入点都调用，
  **不清** per-IP 探测状态）+ `onlineDeviceList()` 按 IP 归并兜底。
- **自主复现**：`v4_udp_dup_probe.mjs` 在 PC 上伪造 2 台同 IP 不同 uuid 的心跳
  → 设备表出现 3 条 `192.168.10.186`，与用户日志同构。
- **实测（5.0.21）**：v4 形态 PASS / v5 形态回归 PASS / 同 IP 去重 3→1。
  端到端断言走 `udp_msg_e2e.mjs`（WS 收 `cmd=1` 断言）。
- 新增探针：`v4_udp_msg_probe.mjs`（ver 4/5 切换）/ `v4_udp_dup_probe.mjs` / `udp_msg_e2e.mjs`。
'''

# ==========================================================================
# 3) MEMORY.md —— 追加一节
# ==========================================================================
WSMEM_SEC = '''
''' + S_WSMEM + r'''

- **★ UDP 帧第 8 字段之后 v4 / v5 分叉**（官方安卓的文字一条都收不到的根因）：
  - **v4**（官方，`Config.DATA_VERSION = DATA_VERSION_4`）：8 字段后**直接**是命令参数。
  - **v5**（1.35）：8 字段后多出 `int 已知设备数 → N×(int port, String ip, String name)`。
  - ⚠️ 无条件读这个计数 = 把 v4 的 `messageEnc` 长度前缀（181）当设备数 →
    `readKnown` 吃穿整段消息 → `extras` 空 → `UDP 消息帧缺少密文字段` → 丢弃。
    症状极具迷惑性：**设备能发现（发现只读 8 字段）、文字一条都收不到**。
  - 判据用**对端广播的 dataVersion**（uuid 后缀，`V5Header.read` 已解析并剥掉）：
    `if (dev.dataVersion >= LanConfig.V5_MIN_DATA_VERSION) { ... }`。
  - 证据在 `docs/official_src/LANShare-main/.../LANService.java:1917 makeDataEncUdp()`。
- **★ 设备表的 key 与「存活续命」口径必须一致**（同一条消息收到两次的根因）：
  `devices` 用 `uniqueUuid` 作 key，而 `tcpProbeStep` 的 TCP 复核**按 IP** 刷新
  `lastSeenMs` ⇒ 换过 uuid 的旧条目被新条目**续命**，`DEVICE_OFFLINE_MS` 永远清不掉
  ⇒ 群发多投。两道保险：写入点调 `dropSameIpExcept(ip, keepKey)`
  （**不要**清 per-IP 探测状态，那些键是 IP）+ `onlineDeviceList()` 按 IP 归并兜底。
- **★ 方法论（复用）**：协议兼容问题里「**同一魔数、不同版本字段不同**」是高频坑。
  凡是新增版本才有的字段，解析时必须**按对端广播的版本号分流**，绝不能无条件读。
  判据优先取**包里自带的版本字段**，别靠试错猜。
- 新增探针：`tests/live-probe/v4_udp_msg_probe.mjs`（`--ver 4/5` 切形态）/
  `v4_udp_dup_probe.mjs`（伪造同 IP 多 uuid，复现僵尸条目续命）/
  `udp_msg_e2e.mjs`（连 WebSocket → 发 UDP → 断言收到 `cmd=1` 聊天推送）。
- **判据技巧**：本 App 的 `pushLog()` **只写内存环形缓冲、不进 hilog**。
  验证「消息是否真的收到」不能只 grep hilog，要走 WebSocket 断言
  （`LanService` 收消息会 `broadcastChatToWeb(cmd=1)`）。
'''

# ==========================================================================
# 4) 技能 harmonyos-live-device-probe —— 插入新节
# ==========================================================================
SK_OLD = '''⚠️ 反汇编只能证明**对端怎么做的**。本端改对了没有，仍要靠探针实测
（见「三、PC 侧伪装对端」+ 验收清单的「修复前后各跑一次」）。

---
'''

SK_NEW = '''⚠️ 反汇编只能证明**对端怎么做的**。本端改对了没有，仍要靠探针实测
（见「三、PC 侧伪装对端」+ 验收清单的「修复前后各跑一次」）。

---

''' + S_SKILL + r'''

同一个魔数 / 同一个端口下，**不同版本的实现字段可能不一样**。这是协议兼容里最高频、
症状也最具迷惑性的坑：握手能过、设备能发现、但某类数据**一条都收不到**。

**真实案例**（LANShare v4/v5）：UDP 帧 = MAGIC(4B) + 整帧混淆，设备头固定 8 个字段，
8 字段之后分叉：

| 版本 | 8 字段之后 |
|---|---|
| v4（官方 `DATA_VERSION_4`） | **直接**是命令参数（密文 / 包名 / 剪贴板） |
| v5（第三方修改版） | 多出 `int 数量` → `N×(int, String, String)` 表 → 命令参数 |

本端无条件读那个 `int 数量`，就把 v4 的**字符串长度前缀**当成了数量 →
后续解析把整段消息吃穿 → 参数为空 → 静默丢弃。

**为什么难发现**：设备发现路径只读前 8 个字段，所以**设备照常出现**，
只有第 9 个字段开始的命令参数全废 —— 表现为「能发现设备、收不到内容」。

**规则**：

1. 凡是**新版本才新增**的字段，解析时一律按**包里自带的版本字段**分流
   （通常是 `dataVersion` / `version` / 握手里声明的能力位），不要靠试错猜，
   也不要靠「这个字段在这个版本里总是 0」这类巧合。
2. 判据优先取**对端自己广播的值**（案例里 `dataVersion` 就编码在 uuid 后缀里），
   别取本端配置或连接方向。
3. 兼容性修复**必须双向回归**：只验「新版对端」会把旧版路径改坏，反之亦然。
   探针要能**切换形态**（案例里 `v4_udp_msg_probe.mjs --ver 4/5`），一次跑两边。

---

## ★ 缓存表的 key 与「存活续命」口径必须一致（僵尸条目会自己续命）

设备表 / 会话表这类带 TTL 的缓存，**主键口径**和**刷新 TTL 的口径**必须一致，
否则会留下**永不过期的僵尸条目**，表现为「同一条消息发出去收到两份」。

**真实案例**：`devices` 用 `uniqueUuid` 作 key，而 TCP 存活复核**按 IP** 刷新
`lastSeenMs`。同一台物理机换过 uuid（重装 App / 双版本共存 / 清数据）后，
旧条目被新条目的存活**续命**，`DEVICE_OFFLINE_MS` 永远不触发。

**规则**：

1. 刷新 TTL 时用的匹配口径（IP / 连接 / uuid）必须**细于或等于**主键口径。
   「按 IP 续命、按 uuid 去重」= 口径倒挂，必然漏。
2. 在**每个写入点**（发现 / 入站 / 恢复）都先清理同标识的旧条目，而不是只在一处。
3. 再加一道**读取侧兜底**：出列表时按业务标识归并（保留最新的那条）。
   两道保险 —— 写入侧保证不产生，读取侧保证即使产生了也不影响行为。
4. 清理**只删条目本身**，不要连带清掉以**别的口径**（如 IP）为键的附属状态
   （探测时间戳、失败计数），那些要跟着保留下来的条目继续有效。

**自主复现手法**：不需要真机 —— 在 PC 上伪造 N 个**同 IP、不同 id** 的心跳，
观察目标设备表是不是出现 N 条。案例里一次就复现出 3 条同 IP 记录，与用户日志同构。

---
'''

# ==========================================================================
def main():
    print('=== 阶段 1：校验 + 内存构造 ===')

    # PENDING_TEST.md —— 追加到文件末尾
    if S_PENDING in load(PENDING):
        print('  [SKIP] PENDING_TEST.md 已含哨兵')
    else:
        _docs[PENDING] = load(PENDING).rstrip() + '\n\n' + PENDING_SEC
        print('  [PLAN] %-46s %s' % ('追加 5.0.21 一节', 'PENDING_TEST.md'))

    # 工作区日志 —— 追加
    s = load(WSLOG)
    if S_WSLOG in s:
        print('  [SKIP] 工作区日志已含哨兵')
    else:
        _docs[WSLOG] = s.rstrip() + '\n' + WSLOG_SEC
        print('  [PLAN] %-46s %s' % ('追加 5.0.21 工作日志', '2026-10-01.md'))

    # MEMORY.md —— 追加
    s = load(WSMEM)
    if S_WSMEM in s:
        print('  [SKIP] MEMORY.md 已含哨兵')
    else:
        _docs[WSMEM] = s.rstrip() + '\n' + WSMEM_SEC
        print('  [PLAN] %-46s %s' % ('追加 5.0.21 长期记忆', 'MEMORY.md'))

    # 技能 —— 插入
    s = load(SKILL)
    if S_SKILL in s:
        print('  [SKIP] 技能已含哨兵')
    else:
        edit(SKILL, SK_OLD, SK_NEW, '技能新增两节')

    print()
    print('=== 阶段 2：统一落盘 ===')
    write_all()
    print()
    print('DONE')


if __name__ == '__main__':
    main()
