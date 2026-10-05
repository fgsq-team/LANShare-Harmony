/**
 * 局域网通讯命令码 —— 平移自 app/src/main/java/com/fgsqw/lanshare/constants/LCmd.java
 *
 * ⚠️ 数值一律不可改动，否则与 Android/Windows 端无法互通。
 */
export class LCmd {
  // ---------- UDP 局域网通讯 ----------
  /** 获取设备（广播探测） */
  static readonly UDP_GET_DEVICES: number = 1001;
  /** 设置设备（心跳上报） */
  static readonly UDP_SET_DEVICES: number = 1002;
  /** 设备下线 */
  static readonly UDP_DEVICES_OFF_LINE: number = 1003;
  /** 广播消息 */
  static readonly UDP_DEVICES_MESSAGE: number = 1004;
  /** 广播消息到剪切板 */
  static readonly UDP_DEVICES_MESSAGE_TO_CLIPBOARD: number = 1005;

  /** (媒体) 静音 */
  static readonly UDP_SEND_MEDIA_MUTE: number = 1006;
  /** (媒体) 恢复音量 */
  static readonly UDP_SEND_MEDIA_RESTORE: number = 1007;
  /** (媒体) 暂停 */
  static readonly UDP_SEND_MEDIA_PAUSE: number = 1008;
  /** (媒体) 下一曲 */
  static readonly UDP_SEND_MEDIA_NEXT: number = 1009;
  /** (媒体) 上一曲 */
  static readonly UDP_SEND_MEDIA_PREVIOUS: number = 1010;
  static readonly UDP_SEND_MAP: number = 1011;

  // ---------- 文件服务 ----------
  /** 发送文件（请求） */
  static readonly FS_SHARE_FILE: number = 1101;
  /** 同意接收 */
  static readonly FS_AGREE: number = 1102;
  /** 拒绝接收 */
  static readonly FS_NOT_AGREE: number = 1103;
  /** 添加设备 */
  static readonly FS_ADD_DEVICE: number = 1104;
  /** 文本消息 */
  static readonly FS_MESSAGE: number = 1105;
  /**
   * 分段文件（1.35 修改版的「16 分片并行传输」）。
   *
   * ⚠️ 这条命令是 1101 之外的**另一条完全独立的发文件路径**：
   * 修改版把文件按固定 16 片切开，**每片一个 TCP 连接**并发发送，
   * 帧 1 = [1110][1][1] + byte(encData)；帧 2 = 12 字节头 + payload
   * `[long 文件大小][str 名][str segId][int idx][int total][long start][long len]`；
   * 之后的数据帧与 1101 完全同构，接收端按 `start` 随机写（RandomAccessFile.seek+write）。
   *
   * 真机取证：`LANService.smali:3270`（发送 E()）/ `:15441`（接收 q() 的 0x456 分支）
   * / `:18693`（分片落盘 z()，用 RandomAccessFile）；日志串 `SEND-PARA-START segs=16`。
   */
  static readonly FS_SEG_FILE: number = 1110;
  /** 获取未同步媒体列表 */
  static readonly FS_GET_NO_SYNC_MEDIA: number = 1106;
  /** 同步媒体 */
  static readonly FS_SYNC_MEDIA: number = 1107;
  static readonly FS_UPDATE_APPS: number = 1108;
  static readonly FS_GET_APPS: number = 1109;

  // ---------- 文件流内嵌命令（单字节，避免大小端差异） ----------
  /** 文件数据块 */
  static readonly FS_DATA: number = 1;
  /** 发送结束 */
  static readonly FS_END: number = 2;
  /** 取消 */
  static readonly FS_CLOSE: number = 3;
  /** 数据接收完毕（ACK） */
  static readonly FS_DATA_RECEIVED: number = 4;
  /** 下一步 */
  static readonly FS_NEXT: number = 5;
  /** 跳出 */
  static readonly FS_BREAK: number = 6;

  /** 协议版本 4 的分隔标记。Android: LCmd.NEW_VERSION_4 = -2 */
  static readonly NEW_VERSION_4: number = -2;
  static readonly NEW_FS_BREAK: number = -2;

  /** 文件类型标记 */
  static readonly FILE_IMAGE: number = 3001;
  static readonly FILE_VIDEO: number = 3002;
  static readonly FILE_FILE: number = 3003;
  static readonly FILE_FOLDER: number = 3004;
  static readonly FILE_MESSAGE_TO_CLIP: number = 3006;
}

/**
 * WebSocket 命令码 —— 平移自 constants/WSCmd.java。
 *
 * ⚠️ 必须与 entry/src/main/resources/rawfile/web/js/WSCmd.js 内的定义完全一致，
 * 否则复用过来的 Web 前端无法与鸿蒙端通信。原文里有拼写错误
 * （SEND_MSSAGE），此处保留同样的数值契约，仅修正命名。
 */
export class WsCmd {
  /** 发送消息。JS 侧常量名 SEND_MSSAGE = 1 */
  static readonly SEND_MESSAGE: number = 1;
  /** 同步设备列表。JS 侧常量名 SYNC_DEVICE_LIST = 2 */
  static readonly SYNC_DEVICE_LIST: number = 2;
}
