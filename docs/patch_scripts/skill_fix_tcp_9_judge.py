#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修正 skill `harmonyos-tcp-socket-server` 第九节里**已被真机证伪**的判据。

5.0.58 写的判据是「PC 端宣告的地址 == 我方自己的 IP」（依据是 PC 源码
`makeDataEnc(*p1,…)` 填的是"目标设备"）。5.0.60 真机日志证明**从未命中**：
本机 `.146`、PC 宣告的是它**自己**的 `.186`。

根因（`LANShare.cpp:467-474`）：`p1` 是 PC **自己设备列表里「与目标同子网的某一台」**，
可能是它自己、也可能是别的设备 ⇒ `devIp / devName / devMode` **天生不可靠**。
真正可靠的是**同一帧里的 `uniqueUuid`**（= `config.uniqueUUid`，对端自己的 UUID，
与 `p1` 无关）—— 而本机发现表的 key 正好就是它。

幂等：哨兵串命中即跳过。
"""
import io
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-tcp-socket-server\SKILL.md'
SENTINEL = '5.0.60 真机证伪'

# ── A. 复现手法里那句错误的判据依据
A_OLD = """```js
// ① 握手时宣告「对端会宣告的那个地址」
//    PC 端 makeDataEnc(*p1,…) 填的是**目标设备**的信息 ⇒ 它宣告的就是我方自己的 IP
// ② 每块之后读 1 字节，每个文件之间**再读 1 字节**
// ③ 打印每个 ack 的值 —— 错位会立刻现形（读到 2 而不是 5）
```"""
A_NEW = """```js
// ① 握手照抄对端字段即可（判据别依赖它，见下方「判据」小节）
// ② 每块之后读 1 字节，每个文件之间**再读 1 字节**
// ③ 打印每个 ack 的值 —— 错位会立刻现形（读到 2 而不是 5）
```"""

# ── B. 三条修法的第 1 条：判据整段改写
B_OLD = """1. ★★ **ack 字节数按对端分流**。别指望「一种数法通吃」：
   原版 Android（1.35）每文件读 **N+2**（所以 5.0.48 才补了那个 `5`），
   而 PC 只读 **N+1**。判据要**失效安全**：
   ```ts
   // PC 端宣告的是「目标设备」的地址 ⇒ 宣告地址 == 我方自己的 IP
   const pcStyle = announcedIp === myIp && announcedMode !== DeviceMode.ANDROID;
   ```
   ⚠️ 关键是**判错只会退回默认行为**（继续按 1.35 的 N+2 走），所以可以安全上线；
   想靠猜一个「通用值」同时满足两家，一定会在某一端炸。"""

B_NEW = """1. ★★ **ack 字节数按对端分流**。别指望「一种数法通吃」：
   原版 Android（1.35）每文件读 **N+2**（所以 5.0.48 才补了那个 `5`），
   而 PC 只读 **N+1**。**判据必须用「对端身份」，不能用「对端在握手里填的字段」。**

   ★★ **判据的坑（5.0.60 真机证伪，务必照抄教训）**：
   一开始我读 PC 源码看到
   ```cpp
   makeDataEnc(*p1, &dataEnc);   // 以为 p1 = 目标设备
   ```
   就写了「**宣告地址 == 我方自己的 IP** ⇒ 是 PC」。
   **真机从未命中**：本机 `.146`、PC 宣告的是它**自己**的 `.186`。
   真因在同一段源码的**前几行**：
   ```cpp
   std::vector<Device> mDevices = LANShare::getInstance()->getMDevices();
   for (p1 = mDevices.begin(); p1 != mDevices.end(); p1++) {
       if (NetWorldUtils::subNet(..., p1->getDevIp(), device.getDevIp())) {
           makeDataEnc(*p1, &dataEnc);      // ← p1 = 它自己列表里的「同子网某一台」
   ```
   `p1` 可能是它自己、也可能是别的设备 ⇒ 那一帧里的
   **`devIp / devName / devMode` 三个字段天生不可靠**（同子网里另一台设备是什么，
   它就填什么），**任何基于它们的判据都会时灵时不灵**。

   ★ 可靠的是**同一帧里的 `uniqueUuid`** —— 它取自 `config.uniqueUUid`，
   是**对端自己的 UUID**，与 `p1` 无关。做法：**拿它反查本机自己的发现表**
   （发现表的 key 就是 uniqueUuid），读出来的 `devMode` 才是真的。
   ```ts
   // 握手帧解析出的 peer.uniqueUuid 就是「对端自己」
   let mode = DeviceMode.UNKNOWN;
   if (peer.uniqueUuid.length > 0) {
     const known = this.devices.get(peer.uniqueUuid);   // devices: Map<string, LanDevice>
     if (known !== undefined) { mode = known.devMode; }
   }
   // 第二道：按 TCP 对端 IP 反查发现表（同样只信发现表，不信握手字段）
   const pcStyle = mode === DeviceMode.WINDOWS || mode === DeviceMode.LINUX
                || mode === DeviceMode.MAC_OS  || mode === DeviceMode.WEB;
   ```
   ⚠️ 兜底要**失效安全**：查不到就按「非 PC」处理（退回 N+2）—— 与现状一致、不引入回归。
   想靠猜一个「通用值」同时满足两家，一定会在某一端炸。

   **通用教训**：跨端判据不要建立在「对端在协议里声明的身份字段」上，
   除非那段源码能证明它填的**就是它自己**；否则一律**回落到自己这边的观测**
   （发现表 / 心跳 / 连接来源 IP）。"""

# ── C. 排查口诀补一条
C_OLD = """- 「自己写的探针全过、真实客户端必挂」→ 让探针**复刻客户端的读取行为**再试一次。"""
C_NEW = """- 「自己写的探针全过、真实客户端必挂」→ 让探针**复刻客户端的读取行为**再试一次。
- 「分流的判据明明写对了，真机上却从没生效」→ **打印判据的输入值**（5.0.58 就是
  把 `announcedIp / myIp` 打进日志才一眼看出「宣告的是它自己」）。
  经验：**身份类判据上线时，必须把判据的每个输入都打进可读日志**，
  否则它失效了你只会看到「功能偶尔不好用」。
  ⚠️ 5.0.60 真机证伪：`makeDataEnc(*p1,…)` 的 `p1` 是**对端自己设备列表里同子网的某一台**，
  不是目标设备 ⇒ 宣告的 IP/名字/型号**全都不可靠**；要用同帧里的 `uniqueUuid` 反查本机发现表。"""

pairs = [(A_OLD, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW)]

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED')
    sys.exit(0)

for i, (old, new) in enumerate(pairs):
    assert s.count(old) == 1, '锚点#%d 命中 %d 次' % (i + 1, s.count(old))
    assert s.count(new) == 0, '新文本#%d 此前已存在' % (i + 1)
for old, new in pairs:
    s = s.replace(old, new)

assert 'PC 端宣告的是「目标设备」的地址' not in s, '旧判据仍在'
assert 'PC 端 makeDataEnc(*p1,…) 填的是**目标设备**的信息' not in s, '旧的错误依据仍在'
assert s.count('5.0.60 真机证伪') >= 1

io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
chk = io.open(P, encoding='utf-8', newline='').read()
print('OK: TCP skill 第九节判据已修正')
print('  len:', len(chk), '| CRLF:', '\r' in chk, '| uniqueUuid:', chk.count('uniqueUuid'))
