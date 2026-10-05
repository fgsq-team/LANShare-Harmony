# -*- coding: utf-8 -*-
"""给 harmonyos-tcp-socket-server 技能追加「第九节补」（5.0.62 二进制归因 + 精确定位）。"""
import io
import os
import sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-tcp-socket-server\SKILL.md'
SENTINEL = '### 九·补：反汇编归因 —— 「同一端 App，换个 PC exe 就成败不同」'

BLOCK = '''

### 九·补：反汇编归因 —— 「同一端 App，换个 PC exe 就成败不同」（5.0.62 实测）

#### 新的精确定位指纹

比「最后一项失败」更准一级：**失败项的最后一块，且已收字节数恒为 `n × 块尺寸`**。

```
第 15/15 项：数据块 338607 B 读取失败（已收 12582840/12921447）
12582840 = 6 × 2097140（= 2MB-12）          ← 整块全收完了
12921447 - 12582840 = 338607 = 余数块        ← 差的正好是最后那个余数块
```

推论：**与文件大小无关，与「项序号」强相关**（两次 15 项批次都死在第 15 项，
同一次会话里 21 项那轮反而全过）。凡是「失败位置 ∝ 项序号」的，
一律先怀疑**逐项累积的状态**（这里是每项多送的字节在对端接收缓冲里线性积压）。

#### ★★ 决定性的记账推理：积压字节数 = 项序号 ⇒ 流控失效

这是本节最有价值的一段，值得背下来：

```
每文件多送 1 字节（我方 N+2 vs 对端读 N+1）
  ⇒ 第 k 项开始时，对端接收缓冲里已积压 (k-1) 字节
  ⇒ 对端块级 recvo(1) 的前 (k-1) 次读到的是**过期字节**，压根没等我们
  ⇒ 当 (k-1) >= 该项块数时，「一块一等」在这**整项内 100% 失效**
  ⇒ 对端把整项猛灌进 socket ⇒ 大块 ::send 部分返回 ⇒ 对端发 FS_CLOSE 弃项
  ⇒ 我们的**余数块**永远读不满 ⇒ 60s 超时
```

核对本案例：最后一项积压 14 字节，该项 7 块（12921447 ÷ 2097140 = 7）⇒ 14 ≥ 7，
块级 ack 全部命中残留 ⇒ 完全失速。**而前 14 项各自「积压 (k-1) < 块数」，
只是部分失速，所以都没超时** —— 这正是「只死最后一项」的数学解释。

#### 块尺寸是分水岭：2MB vs 1MB

反汇编同一次会话里的两个对端 exe（同仓库、不同构建）拿到硬证据：

| | 数据块尺寸 | 反汇编 |
|---|---|---|
| 修改版 | **2 MB** | `movl $2097152, %ebp` |
| 源码版 | **1 MB** | `movl $1048576, %ecx` / `%r8d` |

块越大，`::send` 一次性写完的概率越低 ⇒ 部分返回的概率越高 ⇒
**只有 2MB 那版会踩到**。这也解释了「换个 exe 就成败不同」。

#### 反汇编取证的四个可复用动作

1. **量函数尺寸**：`llvm-objdump -t` 拿符号值，对比同名函数在两版里的
   相对大小。`TCPClient::connect` 源码版 272B vs 修改版 1056B ⇒
   一眼断定「`connect()` 被重写了」，不用读汇编。
2. **调「调用集合」差分**：按精确 mangled 名反汇编，
   把 `callq <...>` 的目标抽成集合，做 A/B 差集。
   本案例直接问出「源码版有整套 `FileSend::*`，修改版没有」+
   「修改版多出整套 `sendFileParallel*` / `sendOneSeg` / `recvSegFile`」。
3. **数新增子系统有没有被调用**：对每个新增函数做全量 caller 反查
   （`.text` 全 dump，记录 `caller -> callee`）。
   本案例：`sendFileParallel` **零调用者**、`fsSegShare` 只被 `handleTcp` 调
   ⇒ 整条新路径在本次传输里**从未执行**，直接排除，省掉大量无效追查。
4. **读字节常量**：`movl $N` / `cmpq $N` 找阈值与尺寸
   （128MB 并行门槛 `134217727`、块尺寸 `2097152`、块头 `12`）。

#### ⚠️ 三个把我带偏过的坑（务必避开）

1. **`llvm-objdump -t` 的符号值在不同 PE 上语义不一致**
   （有时是节内相对偏移，有时含 ImageBase 修正）。**别手算地址** ——
   一律用 `-d --disassemble-symbols=<精确 mangled 名>`，
   输出第一行会打印真实 VA，拿它当基准。
   本案例因此一度把 `sendFile` 的 4KB 邻区误读成它自己。
2. **`-p` 导入表里有 `setsockopt` ≠ 代码调了它**。
   只要链接了 `libws2_32`，`setsockopt`/`socket`/`send` 都会以
   「`__imp_xxx` 槽位 + `.text` 包装符号」两种形式出现。
   判定「有没有调」只能看**目标函数体内的 `callq` 目标**。
   （我曾据此误判「修改版在 connect 里加了缓冲区」，
   实际那三个 `<fthunk>` 是 `connect` 和 `freeaddrinfo`。）
3. **仓库里的源码 ≠ 发布 exe 的源码**。
   本案例仓库那份与「修改版」架构对齐、与「源码版」反而不一样
   （后者是更新一代、整套 `FileSend` 重写）。**符号表 + 函数尺寸 +
   `bool` 标志分支**才是二进制的可信证据，源码只做「哪条路径」的参考。

#### 判据：先分流「对端每文件读几次」，再决定我方发几次

与本书第九节同源，5.0.62 把修法收敛成一行**条件发送**：

```ts
// 块级 ack 已在循环内发够 N 次；这里只补「文件级终态」
// pcStyleAck（对端只读 N+1）⇒ 不发那个额外的 5，只发终态 2
// ⇒ 我方实发 N+1 == 对端读 N+1 ⇒ 缓冲不再积压 ⇒ 流控恢复
const needLevelAck: boolean = !ok || !pcStyleAck;
if (needLevelAck) {
  const ack = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);
  await chan.sendChecked(ack);       // ★ 必须能感知失败，见下
}
if (ok) {
  await chan.send(new Uint8Array([LCmd.FS_END]));   // 终态 2（两分支都发）
}
```

⚠️ **「多送 1 字节」是静默的** —— 它不会立刻报错，而是**逐项累积**成流控失效。
所以 ack 计数这种事，写完必须逐项核对：
**「我方发出的字节数」必须等于「对端读的次数」**，一次都不能多。

#### ★★ 附带的两个「防护失效」教训（比 bug 本身更值得记）

1. **`send()` 把写失败吞掉 ⇒ 你加的告警永远不触发。**
   本案例 `TcpChannel.send()` 的实现是：
   ```ts
   try { await this.sock.write(...); }
   catch (e) { Log.w(TAG, `send 失败: ${err.code} ${err.message}`);
               this.closed = true; }        // ← 吞掉，不抛
   ```
   于是上层 `try { await chan.send(ack) } catch {...}` 里那条
   「应答发送失败」**从未打印过**（5.0.58 加的，一整版形同虚设）。
   修法：加 `async sendChecked(): Promise<boolean> { await this.send(d); return !this.closed; }`。
   **通用规则：凡是「调用方以为会抛异常」的地方，都要回底层确认它到底抛不抛。**
2. **置了 `closed` 却不唤醒等待者 ⇒ 症状被伪装成超时。**
   `readExactly` 是 `while (available < need) { if (closed) return null; await waitForData(remain); }`。
   `send()` 失败只置 `closed` 不 `flushWake()` ⇒ 读侧仍挂在旧定时器上，
   要**干等满自己的超时**才发现断开。日志表现成「60 秒没数据」而不是
   「连接已断」，把真因藏起来。**凡是写失败导致连接终止的路径，
   必须顺手把读等待者唤醒。**
'''

def main():
    s = io.open(P, encoding='utf-8').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        sys.exit(0)
    assert s.count(BLOCK) == 0, 'new block already present'
    io.open(P, 'a', encoding='utf-8', newline='\n').write(BLOCK)
    print('OK appended, new size =', os.path.getsize(P))

main()
