# -*- coding: utf-8 -*-
"""
5.0.62 —— 修「每文件多发 1 字节」→ PC 端接收缓冲逐项积压 → 块级流控失效。

真机现象（15 项批次，两次都命中同一条）：
    失败恒在**最后一项的最后一块**：已收 = n × 2097140，差的正是余数块；
    与文件大小无关、与**位置**强相关。伴随 TcpChannel「send 失败: 2303200
    Network is down」+ LanTcpServer「监听套接字错误 -1」。

根因链：
    ① 本文件 A 处（:1046）无条件发 1 字节；
    ② 同一函数 pcStyleAck 分支（:1068）又发 1 字节 ⇒ 每文件实发 N+2；
    ③ PC 端 baseSend 每文件只读 N+1（循环内 C 次 + 循环外 1 次）
       ⇒ **每文件在对端内核接收缓冲留下 1 字节**；
    ④ 积压线性增长：第 k 项开始时已积压 k-1 字节；
    ⑤ 当积压 ≥ 该项块数时，对端块级 `recvo(1)` 全部命中**过期字节**
       ⇒ 不再等我们 ack ⇒「一块一等」流控彻底失效 ⇒ 整项猛灌；
    ⑥ 对端大块（修改版 PC 实测 2 MB）`::send` 部分返回 ⇒ 对端判失败
       ⇒ 发 FS_CLOSE 放弃本项 ⇒ 我们的**余数块**永远读不满 ⇒ 60 s 超时。

修法：pcStyleAck 时不再发 A 处那一字节（只保留终态 2）⇒ 实发 N+1 = 对端读次数。
附带：让「应答发送失败」真的能被感知（原 send() 吞异常，告警形同虚设）。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
NATIVE = os.path.join(ROOT, r'entry\src\main\ets\net\NativeSocket.ets')
V5 = os.path.join(ROOT, r'entry\src\main\ets\service\V5Transfer.ets')
APP = os.path.join(ROOT, r'AppScope\app.json5')
BAK = os.path.join(ROOT, r'docs\backups')

SENTINEL = '5.0.62'


def read(p):
    with io.open(p, 'r', encoding='utf-8') as f:
        return f.read()


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)


def backup(p, tag):
    dst = os.path.join(BAK, os.path.basename(p) + '.' + tag)
    if not os.path.exists(dst):
        shutil.copy2(p, dst)
        print('  backup -> ' + dst)
    else:
        print('  backup 已存在，跳过: ' + dst)


# ---------------------------------------------------------------- P1
P1_OLD = """        const err: BusinessError = e as BusinessError;
        Log.w(TAG, `send 失败: ${err.code} ${err.message}`);
        this.closed = true;
      }
    };
    this.sendChain = this.sendChain.then(task, task);
    return this.sendChain;
  }
"""

P1_NEW = """        const err: BusinessError = e as BusinessError;
        Log.w(TAG, `send 失败: ${err.code} ${err.message}`);
        this.closed = true;
        // ★ 5.0.62：置 closed 之后必须唤醒所有等待者。
        //   否则 readExactly 会一直挂在 waitForData 上、干等自己的超时
        //   （表现成「等了 60 秒没数据」而不是「连接已断」），把真因藏起来。
        this.flushWake();
      }
    };
    this.sendChain = this.sendChain.then(task, task);
    return this.sendChain;
  }

  /**
   * 发送并**感知成败**。
   *
   * `send()` 为了不打断其它调用点，把写失败吞掉了（只置 closed、不抛）。
   * 但块级 / 文件级应答一旦没发出去，对端会一直阻塞在 recv 上等到超时 ——
   * 这是必须能被日志看见的失败，所以这里把 closed 翻成布尔返回值。
   */
  async sendChecked(data: Uint8Array): Promise<boolean> {
    await this.send(data);
    return !this.closed;
  }
"""

# ---------------------------------------------------------------- P2
P2_OLD = """  private static async sendByte(chan: TcpChannel, b: number): Promise<boolean> {
    try {
      await chan.send(new Uint8Array([b]));
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 块级应答失败(byte=${b}): ${err.code} ${err.message}`);
      return false;
    }
  }
"""

P2_NEW = """  private static async sendByte(chan: TcpChannel, b: number): Promise<boolean> {
    try {
      // ★ 5.0.62：必须走 sendChecked —— TcpChannel.send() 会把写失败吞掉
      //   （只置 closed、不抛），原来的 catch 因此**永远不会触发**，
      //   「块级应答失败」这条最关键的告警等于没写。
      const sent: boolean = await chan.sendChecked(new Uint8Array([b]));
      if (!sent) {
        Log.e(TAG, `v5 块级应答失败(byte=${b}): 通道已关`);
      }
      return sent;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `v5 块级应答失败(byte=${b}): ${err.code} ${err.message}`);
      return false;
    }
  }
"""

# ---------------------------------------------------------------- P3
P3_OLD = """        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时
        const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);
        // ★ 5.0.58：发送失败必须喊出来 —— 对端正阻塞等这一字节
        try {
          await chan.send(ack);
        } catch (se) {
          const sex: Error = se as Error;
          Log.e(TAG, `v5 文件级应答发送失败: ${sex.message}`);
          if (onLog) {
            onLog(`v5 "${item.name}" 文件级应答发送失败（对端会一直等）：${sex.message}`);
          }
        }
"""

P3_NEW = """        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时。
        // ★ 5.0.62 ★ 但 pcStyleAck（PC 端每文件只读 N+1 个字节）时**不能在这里发**：
        //   下面 pcStyleAck 分支还会再发一个终态 2，两者叠加就是「每文件多发 1 字节」。
        //   后果不是简单的多 1 字节，而是**对流控的连锁破坏**：
        //     多出的 1 字节留在对端内核接收缓冲 → 第 k 项开始时已积压 k-1 字节
        //     → 对端块级 recvo(1) 前 k-1 次读到的是**过期字节**，等于不再等我们 ack
        //     → 「一块一等」流控失效 → 对端把整个文件猛灌进 socket
        //     → 对端大块（修改版 PC 实测块尺寸 = 2 MB）::send 部分返回
        //     → 对端判失败 → 发 FS_CLOSE 放弃本项 → 我们的**余数块**永远读不满
        //     → 60 秒超时。
        //   ★ 真机铁证：失败恒在**最后一项的最后一块**（已收 = n × 2097140，
        //     差的正是余数块），与文件大小无关、与**位置**强相关 —— 因为积压字节数
        //     恰好等于项序号。
        //   ★ 计数核对：块级 ack C 次 + 终态 2 一次 = C+1，与对端
        //     「循环内 C 次 + 循环外 1 次」严格相等 ⇒ 流控恢复。
        const needLevelAck: boolean = !ok || !pcStyleAck;
        if (needLevelAck) {
          const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);
          // ★ 5.0.58：发送失败必须喊出来 —— 对端正阻塞等这一字节
          try {
            const ackSent: boolean = await chan.sendChecked(ack);
            if (!ackSent) {
              Log.e(TAG, 'v5 文件级应答发送失败: 通道已关');
              if (onLog) {
                onLog(`v5 "${item.name}" 文件级应答发送失败（对端会一直等）：通道已关`);
              }
            }
          } catch (se) {
            const sex: Error = se as Error;
            Log.e(TAG, `v5 文件级应答发送失败: ${sex.message}`);
            if (onLog) {
              onLog(`v5 "${item.name}" 文件级应答发送失败（对端会一直等）：${sex.message}`);
            }
          }
        }
"""


def main():
    nat = read(NATIVE)
    v5 = read(V5)
    app = read(APP)

    if SENTINEL in nat and 'sendChecked' in nat and SENTINEL in v5:
        print('ALREADY APPLIED (5.0.62) —— 跳过')
        sys.exit(0)

    # ---- 校验（全部通过才落盘）----
    errs = []
    for name, s, old, new in (
        ('P1 NativeSocket.send', nat, P1_OLD, P1_NEW),
        ('P2 V5Transfer.sendByte', v5, P2_OLD, P2_NEW),
        ('P3 V5Transfer 文件级应答', v5, P3_OLD, P3_NEW),
    ):
        c = s.count(old)
        if c != 1:
            errs.append('%s: 锚点 count=%d（期望 1）' % (name, c))
        if s.count(new) != 0:
            errs.append('%s: 新文本已存在（可能已打过）' % name)

    anchor = '"versionCode": 5000061'
    if app.count(anchor) != 1:
        errs.append('app.json5: versionCode 锚点 count=%d' % app.count(anchor))

    if errs:
        print('!! 校验失败，未做任何修改:')
        for e in errs:
            print('   - ' + e)
        sys.exit(1)

    # ---- 落盘 ----
    print('备份:')
    backup(NATIVE, 'v5062pre')
    backup(V5, 'v5062pre')
    backup(APP, 'v5062pre')

    nat2 = nat.replace(P1_OLD, P1_NEW, 1)
    v52 = v5.replace(P2_OLD, P2_NEW, 1).replace(P3_OLD, P3_NEW, 1)
    app2 = app.replace('"versionCode": 5000061', '"versionCode": 5000062', 1)
    app2 = app2.replace('"versionName": "5.0.61"', '"versionName": "5.0.62"', 1)

    write(NATIVE, nat2)
    write(V5, v52)
    write(APP, app2)

    print('OK 已应用 5.0.62:')
    print('  NativeSocket.ets : send() 失败唤醒等待者 + 新增 sendChecked()')
    print('  V5Transfer.ets   : sendByte 走 sendChecked；文件级应答 pcStyleAck 时不再多发 1 字节')
    print('  app.json5        : 5000062 / 5.0.62')


main()
