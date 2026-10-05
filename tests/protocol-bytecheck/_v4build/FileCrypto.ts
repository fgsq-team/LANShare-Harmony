/**
 * 文件数据块的流式变换 —— 平移自 utils/mUtil.java 的 encData / decData。
 *
 * ## 这不是 AES
 * 它跟 DataPacket 的 0x45 混淆是同一类东西：把明文特征打散，
 * 让同网段随手抓包看不到可读内容。**没有密钥**，任何人拿到实现都能还原。
 *
 * 真正的机密性由上层 AES（AesCodec.ets，用于文字消息）承担；
 * 文件体量大，Android 端为了吞吐只做了这一层。
 *
 * ## 算法（逐字节，index 是**本文件内**的累计字节偏移）
 * ```
 * 加密： out = ((b - 1) & 0xFF) ^ ((index + j) & 0xFF)
 * 解密： out = ((b ^ ((index + j) & 0xFF)) + 1) & 0xFF
 * ```
 * j 从 0 递增。Java 里 `buffer[i]` 是**有符号 byte**，但最后都强制转回 byte，
 * 等价于 8 位模运算，所以用无符号写法位级一致（已由字节级对拍验证）。
 *
 * ⚠️ index 必须与发送端严格同步：发送端用「本文件已发送字节数」，
 *    接收端用「本文件已接收字节数」。一旦错位，后面全部字节都会解错。
 *    这也是为什么解密必须**按收到多少算多少**，不能预先分配。
 */
export class FileCrypto {
  /**
   * 原地加密一段缓冲区。
   * @param buf   缓冲区
   * @param len   要处理的字节数
   * @param off   起始偏移
   * @param index 本文件内已发送的累计字节数
   */
  static encData(buf: Uint8Array, len: number, off: number, index: number): void {
    let j: number = 0;
    const end: number = off + len;
    for (let i = off; i < end; i++) {
      if (i < 0 || i >= buf.length) {
        break;
      }
      buf[i] = ((buf[i] - 1) & 0xFF) ^ ((index + j) & 0xFF);
      j += 1;
    }
  }

  /**
   * 原地解密一段缓冲区。参数含义与 encData 对称。
   * @param index 本文件内已接收的累计字节数
   */
  static decData(buf: Uint8Array, len: number, off: number, index: number): void {
    let j: number = 0;
    const end: number = off + len;
    for (let i = off; i < end; i++) {
      if (i < 0 || i >= buf.length) {
        break;
      }
      buf[i] = ((buf[i] ^ ((index + j) & 0xFF)) + 1) & 0xFF;
      j += 1;
    }
  }

  /**
   * 便捷形式：对整块做变换，等价于 off=0, len=buf.length。
   * 注意这会按「整块」而不是「按分片」计算 index，
   * 仅在确认收发双方分片一致时使用 —— 文件传输请用上面两个方法。
   */
  static encBlock(buf: Uint8Array, index: number): void {
    FileCrypto.encData(buf, buf.length, 0, index);
  }

  static decBlock(buf: Uint8Array, index: number): void {
    FileCrypto.decData(buf, buf.length, 0, index);
  }
}
