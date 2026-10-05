/**
 * 文本消息发送—— **双栈**：按对端广播的 dataVersion 选协议。
 *   - >= 5（1.35 修改版 / 本机 LANShare） → v5 单帧
 *   - <= 4（官方 1.2.x）                    → v4 建链帧 + 消息帧
 *
 * 两边都平移自：
 *   service/version/four/FileSend.java#sendMessage()          （v4 建链 + 写帧）
 *   service/LANService.java#broadcastMessage(Device,...)      （消息体加密）
 *   以及 1.35 dex 的 1105 分支（v5 帧，无 isClip）
 *
 * ## 完整字节序列（与 Java 源码 / smali 逐字节对齐）
 * ```
 * [4B MAGIC_NUM 0x66677371]   未混淆，服务端靠它分流     —— LanClient.connect() 已写
 *
 * v4：
 * int      NEW_VERSION_4 = -2
 * string   deviceJson          发送方设备信息            —— FileSend.sendNewVersionFlag
 * int      FS_MESSAGE = 1105
 * boolean  isClip              对端是否把消息写入剪贴板
 * string   messageEnc          AES 密文的**十六进制**串（不是明文、不是 Base64）
 *
 * v5：
 * 帧头  [1105][0][len]
 * payload 设备头 + string(messageEnc)   ← **没有 isClip**，多写就错位
 * ```
 *
 * ⚠️ 早期这份注释写的是「v4」，但实现已改成 v5 帧——
 *    注释与代码脱节是这个文件历史上最容易误导的地方，已同步修正。
 *
 * ## ⚠️ 最容易踩的一点：消息体必须加密，且密钥要「再解一层」
 * 接收端 `FileServer.handleMessage()` 是这么写的：
 * ```
 * String messageEnc = inputStream.readString();
 * String message = AESUtils.decrypt(messageEnc, Config.MESSAGE_KEY);
 * ```
 * 而 `Config.MESSAGE_KEY` 并不是常量 `DEFAULT_MESSAGE_KEY`，它是在 `Config.initPrefs()`
 * 里被**又解了一次**得到的（见 core/LanConfig.ets 的注释）。
 * 所以这里必须用 `LanConfig.messageKey`（= 解出来的那个 32 字符），
 * 且必须传 hex 密文 —— 传明文的话对端 `hexToBytes` 直接抛 NumberFormatException，
 * 用户看到的是「消息解密失败」，而不是收到一条乱码。
 *
 * ## 为什么发完就关连接
 * 原实现同样是「一发一关」（`IOUtil.closeIO(socket)`），不要尝试复用：
 * 接收端在 handleMessage 的 finally 里也关了 socket。
 */
import { Log } from '../core/Logger';
import { LCmd } from '../core/LCmd';
import { LanConfig } from '../core/LanConfig';
import { AesCodec } from '../core/AesCodec';
import { LanDevice, DeviceCodec } from '../core/DeviceCodec';
import { LanClient } from '../net/LanClient';
import { TcpChannel } from '../net/NativeSocket';
import { ProtoIO } from '../net/ProtoIO';
import { V5Enc, V5Header } from '../core/V5Codec';

const TAG: string = 'TextMessenger';

/** 一条消息的发送结果（带失败原因，UI 直接展示） */
export class TextSendResult {
  ok: boolean = false;
  /** 目标设备名，用于日志/回执 */
  target: string = '';
  /** 失败原因（ok=false 时非空） */
  error: string = '';
}

export class TextMessenger {
  /**
   * 把一条文本消息发给指定设备。
   *
   * @param self    本机设备信息（对端靠它拿到发送方名字）
   * @param target  目标设备
   * @param text    明文消息
   * @param isClip  是否让对方写入剪贴板（长按发送 = true，与 Android 一致）
   */
  static async send(
    self: LanDevice,
    target: LanDevice,
    text: string,
    isClip: boolean
  ): Promise<TextSendResult> {
    const result: TextSendResult = new TextSendResult();
    result.target = target.devName;
    if (text.length === 0) {
      result.error = '消息内容为空';
      return result;
    }
    if (target.devIp.length === 0 || target.devPort <= 0) {
      result.error = '目标设备地址不完整';
      return result;
    }

    const client: LanClient = new LanClient();
    try {
      const connected: boolean = await client.connect(target.devIp, target.devPort);
      if (!connected) {
        result.error = client.error.length > 0
          ? `连接 ${target.devIp}:${target.devPort} 失败：${client.error}`
          : `连接 ${target.devIp}:${target.devPort} 失败`;
        Log.w(TAG, result.error);
        return result;
      }
      const chan: TcpChannel | null = client.channel;
      if (chan === null) {
        result.error = '通道未建立';
        return result;
      }

      // ---- 1. 消息体 AES 加密（两条协议路径共用；对端 handleMessage 会无条件解密）----
      let payload: string = text;
      try {
        payload = AesCodec.encrypt(text, LanConfig.messageKey);
      } catch (e) {
        // 加密失败**不放行明文**：明文发过去对端一定解不开，
        // 还不如当场失败让 UI 提示，避免「显示发送成功但对方没反应」。
        const err: Error = e as Error;
        result.error = `消息加密失败：${err.message}`;
        Log.e(TAG, result.error);
        return result;
      }

      // ---- 2. 出站协议分流：按**对端广播的** dataVersion 选协议栈 ----
      //   官方 handleVersion 对「cmd 不是 -2 且 dataVersion>=4」的包只会回「不支持的版本」并丢弃，
      //   所以给官方发 v5 帧必然失败。
      const peerVer: number = target.dataVersion ?? 0;
      if (peerVer >= LanConfig.V5_MIN_DATA_VERSION) {
        // v5（1.35 修改版）：单帧，payload = 设备头 + 密文字符串。
        // ⚠️ v5 去掉了 v4 的 `boolean isClip`（1.35 的 case 1105 第一条就是 readString），
        //    多写这一个字节，对端会把布尔当成字符串长度读，整帧直接错位。
        const enc: V5Enc = new V5Enc(512);
        enc.reset(LCmd.FS_MESSAGE, 0);
        V5Header.write(enc, self, []);
        enc.string(payload);
        await chan.send(enc.bytes());
      } else {
        // v4（官方 1.2.x）：建链帧（NEW_VERSION_4 + 设备 JSON）+ 消息帧。
        // 字节序列远程对齐 FileSend.sendMessage()，
        // 对端 FileServer.handleMessage() 读的是 isClip(boolean) + messageEnc(string)。
        await chan.send(ProtoIO.join([
          ProtoIO.intBytes(LCmd.NEW_VERSION_4),
          ProtoIO.stringBytes(DeviceCodec.toJson(self)),
          ProtoIO.intBytes(LCmd.FS_MESSAGE),
          ProtoIO.boolBytes(isClip),
          ProtoIO.stringBytes(payload)
        ]));
      }
      result.ok = true;
      Log.i(TAG, `已发送消息到 ${target.devName}（${target.devIp}:${target.devPort}，协议 ${peerVer >= LanConfig.V5_MIN_DATA_VERSION ? 'v5' : 'v4'}，${text.length} 字${isClip ? '，要求写入剪贴板' : ''}）`);
      return result;
    } catch (e) {
      const err: Error = e as Error;
      result.error = `发送异常：${err.message}`;
      Log.e(TAG, result.error);
      return result;
    } finally {
      await client.close();
    }
  }
}
