/**
 * 文件传输（v4 协议）—— 平移自
 *   发送：service/version/four/FileSend.java          (send / handleFileTransfer / sendFileStream)
 *   接收：service/version/four/FileServer.java        (handleVersion1 / handleFileTransfer / startReceiveFile)
 *
 * ## 完整的字节序列（已与 Java 源码逐行对齐，未做任何猜测）
 *
 * ### 建链（LANService.makeSocket）
 * ```
 * [4B MAGIC_NUM 0x66677371]        未混淆，服务端靠它做协议分流
 * ```
 *
 * ### 发送方 -> 接收方：请求头
 * ```
 * int      NEW_VERSION_4 = -2
 * string   deviceJson               发送方设备信息（键名见 DeviceCodec.toJson）
 * int      FS_SHARE_FILE = 1101
 * boolean  encData                  文件体是否做了 FileCrypto 变换
 * string   transferJson             {"fromDevice":{...},"type":0,"groupId":0,"files":[...]}
 * ```
 *
 * ### 接收方 -> 发送方：应答
 * ```
 * int      FS_AGREE = 1102  或  FS_NOT_AGREE = 1103
 * ```
 *
 * ### 文件体（按 files 顺序，每个文件一段）
 * ```
 * loop {
 *   int    len                     本次分片字节数，1MB 上限
 *   byte[] data                    若 encData 则已做 ((b-1)&0xFF)^((subTotal+j)&0xFF)
 * }
 * ```
 * ⚠️ **没有结束标记**。接收方按 json 里声明的 length 精确收够就停，
 * 发送方读完文件自然结束。所以 length 字段错一个字节，两边就会错位。
 * 取消时发送方会写一个 `NEW_FS_BREAK = -2`，接收方读到 len <= 0 即中止。
 *
 * ### transferJson 里 files 元素
 * ```json
 * { "fileId":"<uuid>", "name":"a.jpg", "length":12345, "fileType":1, "toUser":"目标名" }
 * ```
 * fileType 取自 MsgFileType（1 图片 / 2 视频 / 5 普通文件 / 6 文件夹），
 * **不是** LCmd 的 3001~3004 —— 详见 core/FileTypes.ets 的说明。
 * 文件夹额外带 `fileCount` 与 `children[]`（每个 child 有 name/length/fileType）。
 *
 * ## 控制流备注
 * 接收方在**收到请求后立刻**回 FS_AGREE（原实现默认 NOT_RECV_DIALOG=true 即自动接收），
 * 不做用户确认弹窗。这与 Android 版默认行为一致。
 */
import { BusinessError } from '@kit.BasicServicesKit';
import { LCmd } from '../core/LCmd';
import { LanConfig } from '../core/LanConfig';
import { Log } from '../core/Logger';
import { JsonNode, JsonParseResult, MiniJson } from '../core/MiniJson';
import { FileCrypto } from '../core/FileCrypto';
import { MsgFileType } from '../core/FileTypes';
import { LanDevice, DeviceCodec } from '../core/DeviceCodec';
import { LanClient } from '../net/LanClient';
import { TcpChannel } from '../net/NativeSocket';
import { ProtoIO } from '../net/ProtoIO';
import { FileSink, FileSource, FileStorage, MagicType, OutgoingFile } from './FileStorage';

const TAG: string = 'FileTransfer';
/** 同步解密之间「让一帧给 UI」的时间预算（ms）。理由见 V5Transfer 的同名常量 */
const UI_YIELD_BUDGET: number = 16;
/** 解密切片大小。整块解会把主线程按住，见 V5Transfer 的同名常量 */
const DEC_SLICE: number = 512 * 1024;

/** 分片大小，与 Android 一致（1MB） */
const CHUNK: number = 1024 * 1024;

/** 传输进度 / 结果，直接喂给 UI */
export class TransferReport {
  /** 'send' | 'recv' */
  direction: string = 'send';
  /** 对端设备名 */
  peer: string = '';
  fileName: string = '';
  /**
   * 5.0.31：这一批的**全部文件名**（顺序 = 传输顺序）。
   * ⚠️ 只在**终态**那一次上报里带（进度上报给它是没意义的重复数据）。
   */
  fileNames: string[] = [];
  fileIndex: number = 1;
  fileCount: number = 1;
  /** 当前文件已传字节 */
  bytes: number = 0;
  /** 当前文件总字节 */
  fileSize: number = 0;
  /** 整批进度 0-100 */
  percent: number = 0;
  /**
   * ★ 5.1.44：这次上报是不是「**分片**」进度。
   *
   * 【为什么需要】分片上报的 `fileIndex/fileCount` 是**片数**
   *   （`part.done` / `total`，1.35 硬编码 16），而多文件上报的是
   *   「第 i 个 / 共 n 个文件」。**两者数值上无法区分**（都可能相等），
   *   所以只能由上报方显式声明。
   * ⇒ 分片时 UI 不显示 `i/n`（否则被误读成 16 个文件），多文件时显示。
   */
  isSeg: boolean = false;
  done: boolean = false;
  ok: boolean = false;
  message: string = '';
}

export type TransferCallback = (r: TransferReport) => void;

/** 接收方解析出来的一个待收条目 */
class IncomingItem {
  fileId: string = '';
  name: string = '';
  length: number = 0;
  fileType: number = MsgFileType.FILE;
  children: IncomingItem[] = [];
}

export class FileTransfer {
  // ==================================================================
  // 发送
  // ==================================================================

  /**
   * 把一组文件发给对端设备。
   *
   * @param self      本机设备信息（会作为 fromDevice 发给对方）
   * @param target    目标设备（用 devIp / devPort）
   * @param files     待发文件（来自系统文件选择器的 URI）
   * @param encData   是否对文件体做 FileCrypto 变换。需与对端协商一致 ——
   *                  原 Android 端读的是本地偏好 PreConfig.ENC_DATA，
   *                  默认 false，所以鸿蒙侧默认也 false，保证互通。
   * @param onReport  进度回调
   */
  static async send(
    self: LanDevice,
    target: LanDevice,
    files: OutgoingFile[],
    encData: boolean,
    onReport: TransferCallback
  ): Promise<boolean> {
    const client: LanClient = new LanClient();
    const total: number = files.length;
    try {
      // ---- 0. 前置校验：大小未知的文件绝对不能发 ----
      // length 是 v4 协议里唯一决定「发多少 / 收多少」的字段。
      // 拿不到真实大小就发，只会换来一个「双方都以为成功」的空文件，
      // 所以这里宁可当场失败并把原因说清楚。
      for (let i = 0; i < files.length; i++) {
        const f: OutgoingFile = files[i];
        if (!f.sizeKnown) {
          FileTransfer.report(onReport, 'send', target.devName, f.name, i + 1, total,
            0, 0, 0, true, false,
            `无法读取「${f.name}」的大小，已中止发送（强行发送只会让对方收到 0 字节空文件）`);
          return false;
        }
      }

      const connected: boolean = await client.connect(target.devIp, target.devPort);
      if (!connected) {
        // 把系统错误码原样带出来。只说「连接失败」在真机上等于没说：
        // 2303120 是连不上，201 是权限，401 是参数，排查方向完全不同。
        const why: string = client.error.length > 0 ? `：${client.error}` : '';
        FileTransfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
          `无法连接 ${target.devName}（${target.devIp}:${target.devPort}）${why}`);
        return false;
      }
      const chan: TcpChannel | null = client.channel;
      if (chan === null) {
        return false;
      }

      // ---- 1. 建链头：NEW_VERSION_4 + 本机设备 JSON ----
      await chan.send(ProtoIO.join([
        ProtoIO.intBytes(LCmd.NEW_VERSION_4),
        ProtoIO.stringBytes(DeviceCodec.toJson(self))
      ]));

      // ---- 2. 文件清单 ----
      const listJson: string = FileTransfer.buildTransferJson(self, target, files);
      await chan.send(ProtoIO.join([
        ProtoIO.intBytes(LCmd.FS_SHARE_FILE),
        ProtoIO.boolBytes(encData),
        ProtoIO.stringBytes(listJson)
      ]));
      // 这条日志是刻意加的：它把「已经告诉对方要发什么」和「还在等对方点头」
      // 这两个状态分开。少了它，真机上就只能看到「已连接」，无法判断
      // 到底是没发出去、还是发出去了对方不理。
      Log.i(TAG, `已发出文件清单（${files.length} 项 / ${FileTransfer.sumSize(files)} B），等待 ${target.devName} 应答 FS_AGREE`);

      // ---- 3. 等应答 ----
      // 15s 内没等到 FS_AGREE 只有两种可能，日志里要说清是哪种，
      // 否则「对端未应答」这四个字在真机上没有任何排查价值：
      //   a) 对端连都没连上我们的请求（对端服务没开 / 被防火墙拦 / 端口不对）
      //   b) 请求到了但被丢弃（对端协议解析失败）
      const resp: number | null = await ProtoIO.readInt(chan, 15000);
      if (resp === null) {
        const stage: string = chan.isClosed
          ? '对端在应答前就断开了连接'
          : '15 秒内没有收到应答';
        FileTransfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
          `${stage}（${target.devName} ${target.devIp}:${target.devPort}）`);
        return false;
      }
      if (resp !== LCmd.FS_AGREE) {
        FileTransfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
          `对端拒绝接收（应答码 ${resp}）`);
        return false;
      }

      // ---- 4. 逐个文件传字节 ----
      const grandTotal: number = FileTransfer.sumSize(files);
      let sentBefore: number = 0;
      for (let i = 0; i < files.length; i++) {
        const item: OutgoingFile = files[i];
        const ok: boolean = await FileTransfer.sendOne(chan, item, encData,
          (sent: number, size: number) => {
            const percent: number = grandTotal > 0
              ? Math.floor((sentBefore + sent) * 100 / grandTotal) : 0;
            FileTransfer.report(onReport, 'send', target.devName, item.name, i + 1, total,
              sent, size, percent, false, true, '');
          });
        if (!ok) {
          FileTransfer.report(onReport, 'send', target.devName, item.name, i + 1, total,
            0, item.size, 0, true, false, `发送失败：${item.name}`);
          return false;
        }
        sentBefore += item.size > 0 ? item.size : 0;
      }

      // 5.0.31：终态带上整批文件名，UI 才能给「N 个文件」那条记录出缩略图
      const allNames: string[] = [];
      for (let i = 0; i < files.length; i++) {
        allNames.push(files[i].name);
      }
      FileTransfer.report(onReport, 'send', target.devName,
        files.length === 1 ? files[0].name : `${files.length} 个文件`,
        total, total, grandTotal, grandTotal, 100, true, true,
        `已发送 ${FileTransfer.human(grandTotal)} 到 ${target.devName}`, allNames);
      return true;
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `发送异常: ${err.message}`);
      FileTransfer.report(onReport, 'send', target.devName, '', 0, total, 0, 0, 0, true, false,
        `发送异常: ${err.message}`);
      return false;
    } finally {
      await client.close();
    }
  }

  /** 发一个文件的全部字节。对应 FileSend.sendFile + sendFileStream */
  private static async sendOne(
    chan: TcpChannel,
    item: OutgoingFile,
    encData: boolean,
    onChunk: (sent: number, size: number) => void
  ): Promise<boolean> {
    const src: FileSource | null = FileSource.open(item.uri);
    if (src === null) {
      return false;
    }
    const size: number = src.size > 0 ? src.size : item.size;
    item.size = size;
    if (size === 0) {
      // 0 字节文件：对端按 length=0 直接建空文件，不需要发任何分片
      src.close();
      return true;
    }
    let subTotal: number = 0;
    let lastPercent: number = 0;
    // 与接收侧同一套口径，实测时两侧速率可以直接对比
    const startedAt: number = Date.now();
    let chunkCount: number = 0;
    try {
      while (subTotal < size) {
        const want: number = Math.min(CHUNK, size - subTotal);
        const chunk: Uint8Array | null = src.readChunk(want);
        if (chunk === null) {
          break;
        }
        const n: number = chunk.length;
        if (encData) {
          // index 必须是「本文件已发送字节数」，与接收端的 subTotal 对齐
          FileCrypto.encData(chunk, n, 0, subTotal);
        }
        // 「4 字节长度 + 数据块」必须**一次**写出去。
        // 分成两次 send 时，那 4 字节会独立成一个 TCP 小包：
        // 即使 Nagle 关了，对端的 delayed ACK 也可能让它先被确认一次再发大块，
        // 等于每 1MB 多付一个 RTT；而且每次 send 都是一次 NAPI 往返 + 一次 Promise 链。
        // 合并后线上字节**完全一样**（接收端照样 readInt 再 readFully），只是少一次 syscall。
        const frame: Uint8Array = new Uint8Array(4 + n);
        frame.set(chunk.subarray(0, n), 4);
        FileTransfer.putInt(frame, 0, n);
        await chan.send(frame);
        subTotal += n;
        chunkCount += 1;
        // 进度回调节流：1MB 粒度上报，避免 UI 被刷爆
        const percent: number = Math.floor(subTotal * 100 / size);
        if (percent !== lastPercent || subTotal >= size) {
          lastPercent = percent;
          onChunk(subTotal, size);
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `发送文件块失败: ${err.code} ${err.message}`);
      return false;
    } finally {
      src.close();
    }
    if (subTotal !== size) {
      Log.w(TAG, `文件 ${item.name} 发送字节数不符: ${subTotal} != ${size}`);
      return false;
    }
    Log.i(TAG, `已发送 ${item.name} (${subTotal} B) ${FileTransfer.rateText(subTotal, startedAt, chunkCount)}`);
    return true;
  }

  /** 往 dst 的 off 处写 4 字节大端 int（避免为此再分配一个小数组） */
  private static putInt(dst: Uint8Array, off: number, v: number): void {
    dst[off] = (v >>> 24) & 0xFF;
    dst[off + 1] = (v >>> 16) & 0xFF;
    dst[off + 2] = (v >>> 8) & 0xFF;
    dst[off + 3] = v & 0xFF;
  }

  /** 构造 v4 的 transferJson。字段与 FileSend.send 完全一致 */
  private static buildTransferJson(self: LanDevice, target: LanDevice, files: OutgoingFile[]): string {
    const items: string[] = [];
    for (let i = 0; i < files.length; i++) {
      const f: OutgoingFile = files[i];
      const fileId: string = FileTransfer.uuid();
      let extra: string = '';
      // 图片/视频额外字段。Android 接收端会读 video/videoTime/gif，
      // 缺了不致命（getBooleanValue 给 false），但补上更接近原行为。
      if (f.fileType === MsgFileType.IMAGE || f.fileType === MsgFileType.VIDEO) {
        extra = `,"video":${f.fileType === MsgFileType.VIDEO ? 'true' : 'false'},`
          + `"videoTime":${MiniJson.quote('')},"gif":false`;
      }
      items.push('{'
        + `"fileId":${MiniJson.quote(fileId)},`
        + `"name":${MiniJson.quote(f.name)},`
        + `"length":${f.size},`
        + `"fileType":${f.fileType},`
        + `"toUser":${MiniJson.quote(target.devName)}`
        + extra
        + '}');
    }
    const filesJson: string = `[${items.join(',')}]`;
    return '{'
      + `"fromDevice":${DeviceCodec.toJson(self)},`
      + '"type":0,"groupId":0,'
      + `"files":${filesJson}`
      + '}';
  }

  // ==================================================================
  // 接收
  // ==================================================================

  /**
   * 处理对端发起的一次文件传输请求（v4）。
   *
   * 调用前提：channel 的前 4 字节魔数已被 LanTcpServer 分流时消费，
   * 且调用方已经读走了 NEW_VERSION_4 与对方设备 JSON。
   *
   * @param storage 落盘策略（下载目录 or 沙箱）
   */
  static async receive(
    chan: TcpChannel,
    from: LanDevice,
    storage: FileStorage,
    onReport: TransferCallback
  ): Promise<boolean> {
    try {
      // ---- 1. 读请求头 ----
      const encDataRaw: boolean | null = await ProtoIO.readBoolean(chan, 15000);
      if (encDataRaw === null) {
        return false;
      }
      const encData: boolean = encDataRaw;
      const json: string | null = await ProtoIO.readString(chan, 15000);
      if (json === null) {
        return false;
      }
      const items: IncomingItem[] = FileTransfer.parseTransferJson(json);
      if (items.length === 0) {
        Log.w(TAG, '文件清单为空或解析失败，拒绝');
        await chan.send(ProtoIO.intBytes(LCmd.FS_NOT_AGREE));
        return false;
      }

      // ---- 2. 立刻同意（与 Android 默认行为一致：不弹确认框）----
      await chan.send(ProtoIO.intBytes(LCmd.FS_AGREE));
      const names: string[] = [];
      for (let i = 0; i < items.length; i++) {
        names.push(items[i].name);
      }
      Log.i(TAG, `接收来自 ${from.devName} 的 ${items.length} 项: ${names.join(', ')}`);

      // ---- 3. 逐项接收 ----
      const total: number = items.length;
      let grand: number = 0;
      for (let i = 0; i < total; i++) {
        grand += items[i].length;
      }
      let done: number = 0;
      for (let i = 0; i < total; i++) {
        const item: IncomingItem = items[i];
        const ok: boolean = await FileTransfer.receiveOne(chan, item, encData, storage, i + 1, total,
          (got: number, size: number) => {
            const percent: number = grand > 0 ? Math.floor((done + got) * 100 / grand) : 0;
            FileTransfer.report(onReport, 'recv', from.devName, item.name, i + 1, total,
              got, size, percent, false, true, '');
          });
        if (!ok) {
          FileTransfer.report(onReport, 'recv', from.devName, item.name, i + 1, total,
            0, item.length, 0, true, false, `接收失败：${item.name}`);
          return false;
        }
        done += item.length;
      }

      // ★★★ 5.1.56：`names` 是**收文件之前** push 的副本（见上方 :395），
      //   `item.name` 被改名回写不会更新它 ⇒ 文件页列表仍显示旧名。
      //   与 V5Transfer 的 `names[i] = items[i].name` 完全同款。
      for (let i: number = 0; i < items.length; i++) {
        names[i] = items[i].name;
      }
      FileTransfer.report(onReport, 'recv', from.devName,
        total === 1 ? items[0].name : `${total} 个文件`,
        total, total, grand, grand, 100, true, true,
        `已接收 ${total} 项，保存到 ${storage.describe}`, names);
      return true;
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `接收异常: ${err.message}`);
      FileTransfer.report(onReport, 'recv', from.devName, '', 0, 1, 0, 0, 0, true, false,
        `接收异常: ${err.message}`);
      return false;
    }
  }

  /** 收一个条目（文件或文件夹） */
  private static async receiveOne(
    chan: TcpChannel,
    item: IncomingItem,
    encData: boolean,
    storage: FileStorage,
    index: number,
    count: number,
    onChunk: (got: number, size: number) => void
  ): Promise<boolean> {
    void index;
    void count;
    const dir: string = storage.categoryDir(item.name);

    if (item.fileType === MsgFileType.FOLDER) {
      const folderPath: string = storage.uniquePath(dir, item.name);
      FileStorage.mkdirs(folderPath);
      let acc: number = 0;
      for (let i = 0; i < item.children.length; i++) {
        const child: IncomingItem = item.children[i];
        const ok: boolean = await FileTransfer.receiveStreamTo(
          chan, child, encData, folderPath,
          (got: number, _size: number) => {
            onChunk(acc + got, item.length);
          });
        if (!ok) {
          return false;
        }
        acc += child.length;
      }
      return true;
    }

    return await FileTransfer.receiveStreamTo(chan, item, encData, dir,
      (got: number, size: number) => {
        onChunk(got, size);
      });
  }

  /** 把一个文件的字节流落到磁盘 */
  private static async receiveStreamTo(
    chan: TcpChannel,
    item: IncomingItem,
    encData: boolean,
    dir: string,
    onChunk: (got: number, size: number) => void
  ): Promise<boolean> {
    // ★ 5.1.51：改成 let —— 收完可能按魔数改名
    let path: string = FileStorage.uniquePathIn(dir, item.name);

    if (item.length <= 0) {
      // 0 字节条目（空文件）只需建文件，没有任何分片
      return FileSink.createEmpty(path);
    }

    const sink: FileSink | null = FileSink.create(path);
    if (sink === null) {
      return false;
    }
    // 收完要打一行速率：真机上「接收比发送慢」这类问题，
    // 没有这一行就只能靠猜（是网络慢、写盘慢、还是事件循环被空转吃掉了）。
    const startedAt: number = Date.now();
    let chunkCount: number = 0;
    let subTotal: number = 0;
    let lastPercent: number = 0;
    let lastYieldAt: number = Date.now();
    try {
      while (subTotal < item.length) {
        const len: number | null = await ProtoIO.readInt(chan, 60000);
        if (len === null) {
          return false;
        }
        if (len <= 0) {
          // 发送方主动中止（NEW_FS_BREAK = -2）或流已错位
          Log.w(TAG, `接收中止，len=${len}（已收 ${subTotal}/${item.length}）`);
          return false;
        }
        if (len > 8 * 1024 * 1024) {
          Log.e(TAG, `分片长度异常: ${len}`);
          return false;
        }
        const chunk: Uint8Array | null = await chan.readExactly(len, 60000);
        if (chunk === null) {
          return false;
        }
        if (encData) {
          // index 必须是「本文件已接收字节数」，与发送端的 subTotal 对齐。
          // 切片 + 让帧的理由见 V5Transfer：逐字节 JS 循环是同步的，
          // 整块解密会把 UI 线程按住，接收期间切 Tab 会卡好几秒。
          let off: number = 0;
          while (off < len) {
            const slice: number = Math.min(DEC_SLICE, len - off);
            FileCrypto.decData(chunk, slice, off, subTotal + off);
            off += slice;
            if (Date.now() - lastYieldAt >= UI_YIELD_BUDGET) {
              lastYieldAt = Date.now();
              await FileTransfer.yieldFrame();
            }
          }
        }
        if (!sink.append(chunk)) {
          return false;
        }
        chunkCount += 1;
        subTotal += len;
        const percent: number = Math.floor(subTotal * 100 / item.length);
        if (percent !== lastPercent || subTotal >= item.length) {
          lastPercent = percent;
          onChunk(subTotal, item.length);
        }
        if (Date.now() - lastYieldAt >= UI_YIELD_BUDGET) {
          lastYieldAt = Date.now();
          await FileTransfer.yieldFrame();
        }
      }
    } finally {
      sink.close();
    }
    // ★★ 5.1.51：同 V5Transfer，收完按魔数纠正后缀并回写 path
    // ★★★ 5.1.56：与 V5 单文件路径同款——**必须回写 `item.name`**。
    //   `receiveOne` 上层（`receive` 的 report、以及收完汇总的 `names[]`）
    //   全部取自 `item.name`（协议原始名）⇒ 只改 `path` 等于改了个没人读的变量，
    //   磁盘上改了名、UI 与相册判定仍用旧名 ⇒ 「看起来完全没生效」。
    //   （这与 5.1.55 在 V5 侧踩的是同一个坑，v4 这条平行路径当时漏了。）
    const before: string = path;
    path = MagicType.fixExtByMagic(path);
    if (path !== before) {
      item.name = MagicType.baseNameOf(path);
      Log.i(TAG, `v4 改名回写：${before} → ${path}（item.name = ${item.name}）`);
    }
    if (subTotal !== item.length) {
      Log.w(TAG, `接收字节数不符: ${subTotal} != ${item.length}`);
      return false;
    }
    Log.i(TAG, `已保存 ${path} (${subTotal} B) ${FileTransfer.rateText(subTotal, startedAt, chunkCount)}`);
    return true;
  }

  /** 让出一帧给 UI 线程。理由与写法见 V5Transfer.yieldFrame */
  private static yieldFrame(): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(resolve, 0);
    });
  }

  /**
   * 「字节数 + 耗时 + 平均速率 + 分片数」一行。
   * 收发两侧都用它，实测时可以直接对比同一台机器做发送方和做接收方的差异。
   */
  private static rateText(bytes: number, startedAt: number, chunks: number): string {
    const ms: number = Date.now() - startedAt;
    if (ms <= 0) {
      return `${chunks} 片`;
    }
    const mbps: number = (bytes / 1048576) / (ms / 1000);
    return `${chunks} 片 / ${ms}ms / ${mbps.toFixed(1)} MB/s`;
  }

  /** 解析 transferJson 的 files 数组 */
  private static parseTransferJson(json: string): IncomingItem[] {
    const out: IncomingItem[] = [];
    const res: JsonParseResult = MiniJson.parse(json);
    if (!res.ok) {
      Log.w(TAG, `transferJson 解析失败: ${res.error}`);
      return out;
    }
    const filesNode: JsonNode | null = res.root.field('files');
    if (filesNode === null || !filesNode.isArray()) {
      return out;
    }
    for (let i = 0; i < filesNode.count; i++) {
      const f: JsonNode | null = filesNode.at(i);
      if (f === null) {
        continue;
      }
      const item: IncomingItem = new IncomingItem();
      item.fileId = FileTransfer.str(f, 'fileId');
      item.name = FileTransfer.str(f, 'name');
      if (item.name.length === 0) {
        item.name = `unnamed_${i}`;
      }
      item.length = FileTransfer.num(f, 'length');
      item.fileType = FileTransfer.num(f, 'fileType', MsgFileType.FILE);
      const children: JsonNode | null = f.field('children');
      if (children !== null && children.isArray()) {
        for (let j = 0; j < children.count; j++) {
          const c: JsonNode | null = children.at(j);
          if (c === null) {
            continue;
          }
          const child: IncomingItem = new IncomingItem();
          child.name = FileTransfer.str(c, 'name');
          child.length = FileTransfer.num(c, 'length');
          child.fileType = FileTransfer.num(c, 'fileType', MsgFileType.FILE);
          if (child.name.length > 0) {
            item.children.push(child);
          }
        }
      }
      out.push(item);
    }
    return out;
  }

  private static str(n: JsonNode, key: string): string {
    const v: JsonNode | null = n.field(key);
    return v === null ? '' : v.asString('');
  }

  private static num(n: JsonNode, key: string, def: number = 0): number {
    const v: JsonNode | null = n.field(key);
    return v === null ? def : Math.floor(v.asNumber(def));
  }

  // ==================================================================
  // 工具
  // ==================================================================

  private static sumSize(files: OutgoingFile[]): number {
    let total: number = 0;
    for (let i = 0; i < files.length; i++) {
      total += files[i].size;
    }
    return total;
  }

  /** 不引入 crypto 依赖，用时间戳 + 随机数拼一个够用的 uuid */
  static uuid(): string {
    const rnd: number = Math.floor(Math.random() * 4294967296);
    return `${Date.now().toString(16)}-${rnd.toString(16).padStart(8, '0')}`;
  }

  static human(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    if (bytes < 1024 * 1024 * 1024) {
      return `${(bytes / 1048576).toFixed(1)} MB`;
    }
    return `${(bytes / 1073741824).toFixed(2)} GB`;
  }

  private static report(
    cb: TransferCallback,
    direction: string,
    peer: string,
    fileName: string,
    fileIndex: number,
    fileCount: number,
    bytes: number,
    fileSize: number,
    percent: number,
    done: boolean,
    ok: boolean,
    message: string,
    names: string[] = []
  ): void {
    const r: TransferReport = new TransferReport();
    r.direction = direction;
    r.peer = peer;
    r.fileName = fileName;
    r.fileIndex = fileIndex;
    r.fileCount = fileCount;
    r.bytes = bytes;
    r.fileSize = fileSize;
    r.percent = percent;
    r.done = done;
    r.ok = ok;
    r.message = message;
    r.fileNames = names;
    try {
      cb(r);
    } catch (e) {
      Log.w(TAG, '进度回调异常');
    }
  }
}

/** 供 LanConfig 之外的地方引用，避免外部直接依赖 LanConfig */
export const DEFAULT_TRANSFER_PORT: number = LanConfig.DEFAULT_FILE_SERVER_PORT;
