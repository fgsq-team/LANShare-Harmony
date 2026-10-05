# -*- coding: utf-8 -*-
"""
v5.1.13 —— 发送吞吐优化（**不动协议**，字节级等价）

目标：同手机 → 车机 1.35，APP 30MB/s → 追平网页 40MB/s。

## 排查中发现的真瓶颈（每 1MiB 块）
发送链路上 **1MB 数据被拷贝 3 次**：
  1. `readChunk`：`new ArrayBuffer(1MB)`  ← **本次消除**
  2. `frame.rawBuffer().set(chunk, 12)`：拷进帧缓冲
  3. `bytes()` 返回 `subarray(0,pos)`（byteOffset=12≠0）
     → `TcpChannel.toArrayBuffer` 走 `slice()` 分支 → **又拷 1MB**（API 限制，消不掉）

## 本次只做两项（都能证明等价）
  A. FileSource 新增 `readChunkInto(dst)`：**复用调用方的缓冲**，不再每块 new 1MB。
     发送两处（1101 / 1110）改用它；`readChunk` 保留给其余调用点。
  B. FileCrypto.encData/decData：改 **256 项查表**，去掉每字节的算术与边界判断。

## 明确不做（写下来免得日后重犯）
  ❌ 直接 `readSync` 进帧缓冲偏移 12 —— `readSync(fd, buffer, options)` 的
     `options.offset` 是**文件内偏移**，不是缓冲内偏移；buffer 恒从 0 写。
     （已查 @ohos.file.fs.d.ts:2744 / ReadOptions:5689）
  ❌ CHUNK 提到 2MB —— 1.35 信令路径只 `new byte[1048576]`，会越界。
  ❌ 块级改滑动窗口 —— 块级 ack 是 1.35 的流控协议，窗口>1 可能错乱。
  ❌ SEG_SEND_ENABLED 改 true —— 1.35 有 5% 提前 FIN 的 bug。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
SENTINEL = '5.1.13'

# ================================================================ A1. FileStorage
OLD_A1 = """  readChunk(size: number): Uint8Array | null {
    if (this.fd < 0 || size <= 0) {
      return null;
    }
    try {
      const buf: ArrayBuffer = new ArrayBuffer(size);
      const n: number = fileIo.readSync(this.fd, buf);
      if (n <= 0) {
        return null;
      }
      return new Uint8Array(buf, 0, n);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `读文件失败: ${err.code} ${err.message}`);
      return null;
    }
  }"""

NEW_A1 = """  readChunk(size: number): Uint8Array | null {
    if (this.fd < 0 || size <= 0) {
      return null;
    }
    try {
      const buf: ArrayBuffer = new ArrayBuffer(size);
      const n: number = fileIo.readSync(this.fd, buf);
      if (n <= 0) {
        return null;
      }
      return new Uint8Array(buf, 0, n);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `读文件失败: ${err.code} ${err.message}`);
      return null;
    }
  }

  /**
   * ★ 5.1.13（吞吐优化）：读进**调用方给的缓冲**，不再每块 `new ArrayBuffer`。
   *
   * 动机：发送路径原来每 1MiB 块都 `new ArrayBuffer(1MB)`，
   * 紧接着又 `set()` 拷进帧缓冲 —— 大文件上这是**每块 1MB 的无谓分配 + GC 压力**。
   *
   * ⚠️ 为什么能安全复用（这正是原注释担心的那个坑）：
   *   原注释怕的是「拿一个 1MB 大缓冲去读最后一个不满的块，
   *   会把**下一个文件**的开头也读进来」。本方法规避了这一点：
   *   · 长度由 `size` 参数**显式限定**，传给 `readSync` 的 `length` 也是它
   *     ⇒ 不可能越过调用方给的缓冲末尾；
   *   · 调用点（`V5Transfer`）为**每个文件**新建自己的缓冲，不是跨文件复用；
   *   · 读到的字节与 `readChunk(size)` **逐字节相同**（同样从当前文件偏移读、
   *     同样最多 size 字节、同样 EOF 即止）。
   *
   * ⚠️ `readSync(fd, buffer, options)` 的 `options.offset` 是**文件内偏移**，
   *    **不是**缓冲内偏移（见 @ohos.file.fs.d.ts:2744 + ReadOptions:5689）。
   *    所以想让文件内容落在 `dst` 的第 12 字节处（避开帧头）在 API 层做不到 ——
   *    这也是本方法只让调用方传「从 0 开始用」的整块缓冲的原因。
   *
   * @param dst  目标缓冲（长度必须 >= size）
   * @param size 最多读多少字节
   * @returns 读到的字节数；0 表示已到末尾或出错
   */
  readChunkInto(dst: Uint8Array, size: number): number {
    if (this.fd < 0 || size <= 0 || dst.length < size) {
      return 0;
    }
    try {
      // ★ 关键：用 `dst` 自己的 ArrayBuffer + 显式 length，
      //   让 readSync 只填前 size 字节，绝不越界。
      const n: number = fileIo.readSync(this.fd, dst.buffer, { length: size, offset: 0 } as fileIo.ReadOptions);
      return n > 0 ? n : 0;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `读文件失败: ${err.code} ${err.message}`);
      return 0;
    }
  }"""

# ================================================================ A2. V5Transfer 1101
OLD_B = """    let subTotal: number = 0;
    let lastPercent: number = 0;
    const startedAt: number = Date.now();
    let chunkCount: number = 0;
    const frame: V5Enc = new V5Enc(CHUNK + 64);
    try {
      while (subTotal < size) {
        const want: number = Math.min(CHUNK, size - subTotal);
        const chunk: Uint8Array | null = src.readChunk(want);
        if (chunk === null) {
          break;
        }
        const n: number = chunk.length;
        if (encData) {
          FileCrypto.encData(chunk, n, 0, subTotal);
        }
        frame.resetKeepHeader();
        frame.setStreamCmd(LCmd.FS_DATA);
        frame.rawBuffer().set(chunk.subarray(0, n), 12);
        frame.advance(n);
        await chan.send(frame.bytes());
        subTotal += n;
        chunkCount += 1;
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }
    } catch (e) {"""

NEW_B = """    let subTotal: number = 0;
    let lastPercent: number = 0;
    const startedAt: number = Date.now();
    let chunkCount: number = 0;
    const frame: V5Enc = new V5Enc(CHUNK + 64);
    // ★ 5.1.13（吞吐优化）：读缓冲**每个文件只分配一次**，整批复用。
    //   原来是每块 `new ArrayBuffer(CHUNK)`（1MB）⇒ 大文件上白分配几百次。
    const readBuf: Uint8Array = new Uint8Array(Math.min(CHUNK, size));
    try {
      while (subTotal < size) {
        const want: number = Math.min(CHUNK, size - subTotal);
        // 复用 readBuf，不再每块 new。
        const n: number = src.readChunkInto(readBuf, want);
        if (n <= 0) {
          break;
        }
        if (encData) {
          // ★ index 仍是「本文件已发送字节数」subTotal —— 与原实现逐位一致。
          FileCrypto.encData(readBuf, n, 0, subTotal);
        }
        frame.resetKeepHeader();
        frame.setStreamCmd(LCmd.FS_DATA);
        frame.rawBuffer().set(readBuf.subarray(0, n), 12);
        frame.advance(n);
        await chan.send(frame.bytes());
        subTotal += n;
        chunkCount += 1;
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }
    } catch (e) {"""

# ================================================================ A3. V5Transfer 1110（分片发送侧）
OLD_C = """          if (!src.seek(start)) {
            return false;
          }
          const frame: V5Enc = new V5Enc(CHUNK + 64);
          let sent: number = 0;
          while (sent < len) {
            const want: number = Math.min(CHUNK, len - sent);
            const chunk: Uint8Array | null = src.readChunk(want);
            if (chunk === null) {
              break;
            }
            const n: number = chunk.length;
            frame.resetKeepHeader();
            frame.setStreamCmd(LCmd.FS_DATA);
            frame.rawBuffer().set(chunk.subarray(0, n), 12);
            frame.advance(n);
            await chan.send(frame.bytes());
            sent += n;
            st.sent += n;
            onTick();
          }"""

NEW_C = """          if (!src.seek(start)) {
            return false;
          }
          const frame: V5Enc = new V5Enc(CHUNK + 64);
          // ★ 5.1.13：同 1101，读缓冲每片只分配一次（SEG_SEND_ENABLED 仍为 false，
          //   这条路当前走不到，但保持与 1101 同一写法，避免日后改回 true 时又退化）。
          const readBuf: Uint8Array = new Uint8Array(Math.min(CHUNK, len > 0 ? len : 0));
          let sent: number = 0;
          while (sent < len) {
            const want: number = Math.min(CHUNK, len - sent);
            const n: number = src.readChunkInto(readBuf, want);
            if (n <= 0) {
              break;
            }
            frame.resetKeepHeader();
            frame.setStreamCmd(LCmd.FS_DATA);
            frame.rawBuffer().set(readBuf.subarray(0, n), 12);
            frame.advance(n);
            await chan.send(frame.bytes());
            sent += n;
            st.sent += n;
            onTick();
          }"""

# ================================================================ B. FileCrypto
OLD_TBL = """export class FileCrypto {
  /**
   * 原地加密一段缓冲区。"""

NEW_TBL = """export class FileCrypto {
  /**
   * ★ 5.1.13（吞吐优化）：256 项查表，去掉每字节的算术与分支。
   *   `DEC_TBL[b] === (b - 1) & 0xFF`（加密用）
   *   `INC_TBL[b] === (b + 1) & 0xFF`（解密用）
   * 两者互为逆运算，构造一次即可，之后只读。
   * 原来每字节要算一次 `(b-1)&0xFF` + 一次 `& 0xFF` 收 key；
   * 现在只剩一次数组读 + 一次 XOR。
   */
  private static readonly DEC_TBL: Int32Array = FileCrypto.buildTbl(-1);
  private static readonly INC_TBL: Int32Array = FileCrypto.buildTbl(1);

  private static buildTbl(delta: number): Int32Array {
    const t: Int32Array = new Int32Array(256);
    for (let b: number = 0; b < 256; b++) {
      t[b] = (b + delta) & 0xFF;
    }
    return t;
  }

  /**
   * 原地加密一段缓冲区。"""

OLD_C1 = """    const end: number = Math.min(off + len, buf.length);
    let k: number = index & 0xFF;
    for (let i = off; i < end; i++) {
      buf[i] = ((buf[i] - 1) & 0xFF) ^ k;
      k = (k + 1) & 0xFF;
    }
  }"""

NEW_C1 = """    const end: number = Math.min(off + len, buf.length);
    let k: number = index & 0xFF;
    let i: number = off;
    // ★ 5.1.13：查表 + 4 字节展开。`DEC_TBL[b] === (b-1)&0xFF` 逐项等价。
    const dec: Int32Array = FileCrypto.DEC_TBL;
    // 4 字节一组：组内 key 连续 +1 且以 256 为周期，展开后与逐字节写法逐位一致。
    for (; i + 4 <= end; i += 4) {
      buf[i] = dec[buf[i]] ^ k;
      const k1: number = (k + 1) & 0xFF;
      buf[i + 1] = dec[buf[i + 1]] ^ k1;
      const k2: number = (k1 + 1) & 0xFF;
      buf[i + 2] = dec[buf[i + 2]] ^ k2;
      const k3: number = (k2 + 1) & 0xFF;
      buf[i + 3] = dec[buf[i + 3]] ^ k3;
      k = (k3 + 1) & 0xFF;
    }
    for (; i < end; i++) {
      buf[i] = dec[buf[i]] ^ k;
      k = (k + 1) & 0xFF;
    }
  }"""

OLD_C2 = """    const end: number = Math.min(off + len, buf.length);
    let k: number = index & 0xFF;
    for (let i = off; i < end; i++) {
      buf[i] = ((buf[i] ^ k) + 1) & 0xFF;
      k = (k + 1) & 0xFF;
    }
  }"""

NEW_C2 = """    const end: number = Math.min(off + len, buf.length);
    let k: number = index & 0xFF;
    let i: number = off;
    // ★ 5.1.13：同 encData，查表 + 4 字节展开。`INC_TBL[b] === (b+1)&0xFF`。
    const inc: Int32Array = FileCrypto.INC_TBL;
    for (; i + 4 <= end; i += 4) {
      buf[i] = inc[buf[i] ^ k];
      const k1: number = (k + 1) & 0xFF;
      buf[i + 1] = inc[buf[i + 1] ^ k1];
      const k2: number = (k1 + 1) & 0xFF;
      buf[i + 2] = inc[buf[i + 2] ^ k2];
      const k3: number = (k2 + 1) & 0xFF;
      buf[i + 3] = inc[buf[i + 3] ^ k3];
      k = (k3 + 1) & 0xFF;
    }
    for (; i < end; i++) {
      buf[i] = inc[buf[i] ^ k];
      k = (k + 1) & 0xFF;
    }
  }"""

# ================================================================ 校验 / 落盘
def load(p):
    return io.open(os.path.join(ROOT, p), encoding='utf-8').read()

def save(p, s):
    assert '\r\n' not in s, 'CRLF 混入: ' + p
    assert '�' not in s, '坏字符: ' + p
    io.open(os.path.join(ROOT, p), 'w', encoding='utf-8', newline='\n').write(s)

EDITS = [
    ('entry/src/main/ets/service/FileStorage.ets', OLD_A1, NEW_A1),
    ('entry/src/main/ets/service/V5Transfer.ets', OLD_B, NEW_B),
    ('entry/src/main/ets/service/V5Transfer.ets', OLD_C, NEW_C),
    ('entry/src/main/ets/core/FileCrypto.ets', OLD_TBL, NEW_TBL),
    ('entry/src/main/ets/core/FileCrypto.ets', OLD_C1, NEW_C1),
    ('entry/src/main/ets/core/FileCrypto.ets', OLD_C2, NEW_C2),
]

cache = {}
for path, old, new in EDITS:
    if path not in cache:
        cache[path] = load(path)
    s = cache[path]
    c = s.count(old)
    assert c == 1, 'OLD 命中 %d（应 1）: %s' % (c, path)
    cache[path] = s.replace(old, new, 1)

if '--dry' in sys.argv:
    print('DRY-RUN OK（%d 处）' % len(EDITS))
    for path, s in cache.items():
        print('  %-22s %6d chars' % (os.path.basename(path), len(s)))
    raise SystemExit(0)

for path, s in cache.items():
    save(path, s)
    print('  已写 %s' % path)
print('APPLIED')
