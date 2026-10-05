# -*- coding: utf-8 -*-
"""更新 tcp 技能 description（让 5.0.62 的新内容可被触发）+ 追加项目记忆。"""
import io
import os
import sys

SKILL = r'C:\Users\vivi\.workbuddy\skills\harmonyos-tcp-socket-server\SKILL.md'
DESC_TAIL = '当用户要"鸿蒙写 TCP 服务端"'
DESC_ADD = ('含「同一客户端 App、换不同 PC 端 exe 就成败不同」的二进制反汇编归因四步法'
            '（量函数尺寸/调用集合差分/新增子系统 caller 反查/读字节常量）与坑（符号值语义不一致、'
            '导入表有≠代码调、仓库源码≠发布 exe）；含「失败恒在最后一项最后一块、已收恒为块尺寸整数倍」'
            '的记账推理（多送 1 字节 ⇒ 积压数=项序号 ⇒ 整项流控失效）；含'
            '「send() 吞写异常导致告警永不触发」与「置 closed 不唤醒等待者把断开伪装成超时」两条防护失效教训。')

MEM = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
MEM_BLOCK = '''

## 5.0.62 —— 「换 PC exe 就成败不同」根因闭合（反汇编归因）

**现象**：手机端同一 App，修改版 PC exe 发 15 张必挂；失败**恒在最后一项的最后一块**，
已收恒为 `n × 2097140`（= 2MB-12 的整数倍），差的正是余数块。伴随
`TcpChannel: send 失败 2303200 Network is down` + `LanTcpServer: 监听套接字错误 -1`。

**根因链**（反汇编 + 源码 + hilog 三方对证）：
1. 手机端 `V5Transfer.ets:1046` 无条件发 1 字节；`:1068` pcStyleAck 分支**又**发终态 2 ⇒ 每文件实发 **N+2**
2. PC 端 `baseSend` 每文件只读 **N+1**（循环内 C 次 + 循环外 1 次）
   ⇒ **每文件在对端内核接收缓冲留下 1 字节**
3. 积压线性增长 ⇒ 第 k 项开始时积压 `k-1` 字节
4. 当 `k-1 ≥ 该项块数`（最后一项：14 ≥ 7）⇒ 对端块级 `recvo(1)` **全部命中过期字节**
   ⇒「一块一等」整项失效 ⇒ 猛灌
5. 对端大块（修改版块尺寸 **2MB**，`movl $2097152`；源码版 **1MB**，`movl $1048576`）
   `::send` 部分返回 ⇒ 判失败 ⇒ 发 `FS_CLOSE` ⇒ 我方余数块永远读不满 ⇒ 60s 超时

**修复（5.0.62，commit 70a19c2 / tag v5.0.62，已推手机）**：
- `V5Transfer`：pcStyleAck 时**不再**发 :1046 那 1 字节（只保留终态 2）⇒ 实发 N+1 == 对端读次数
- `NativeSocket` 新增 `sendChecked()`：`send()` 原把写失败**吞掉**（只置 closed 不抛）
  ⇒ 5.0.58 加的「块级/文件级应答失败」告警**从未打印**（一整版形同虚设）
- `NativeSocket.send()` 失败补 `flushWake()`：否则 `readExactly` 挂死在 `waitForData`
  ⇒ 断开被伪装成「60s 无数据」

**PC 端二进制归因结论**（无修改版源码）：
- 修改版 = 仓库那份的演进（`LANShare::sendFile` + `baseSend`/`baseSendEnc`），
  **`C:\Program Files\LANShare` 那个「源码版」反而是更新一代**（整套 `FileSend::*` 重写、
  块尺寸 1MB、`TCPClient::connect` 是 272B 的 `socket/inet_addr/connect` 原版）
- 修改版多出整套并行/分段子系统（`sendFileParallel`/`sendOneSeg`/`recvSegFile`/`fsSegShare`），
  但 `sendFileParallel` **零调用者**、并行门槛 `>134217727`(128MB) ⇒ 本次**从未执行**，已排除
- ⚠️ 坑：`-p` 导入表有 `setsockopt` ≠ 代码调了它（链接 libws2_32 就有两种符号形态）；
  曾据此误判「修改版在 connect 加了 2MB 缓冲」，实际那 3 个 `<fthunk>` 是 `connect` + `freeaddrinfo`
- 归因脚本：`LANShareV5/docs/patch_scripts/disasm_{diff2,caller_map,pc_correct,pc_compare}.py`

**验收要点**：15 项批次必须**全过**；且观察 PC 端是否还会出现 `send error` / `FS_CLOSE`。
'''

def main():
    ok = False
    s = io.open(SKILL, encoding='utf-8').read()
    if 'FAILMARK_5_0_62' in s:
        print('SKILL: ALREADY')
        ok = True
    elif DESC_ADD not in s:
        assert s.count(DESC_TAIL) == 1, 'desc anchor count=%d' % s.count(DESC_TAIL)
        s = s.replace(DESC_TAIL, DESC_ADD + DESC_TAIL, 1)
        io.open(SKILL, 'w', encoding='utf-8', newline='\n').write(s)
        print('SKILL: description updated')
    m = io.open(MEM, encoding='utf-8').read()
    if '## 5.0.62 —— 「换 PC exe 就成败不同」根因闭合' in m:
        print('MEMORY: ALREADY')
    else:
        io.open(MEM, 'a', encoding='utf-8', newline='\n').write(MEM_BLOCK)
        print('MEMORY: appended')

main()
