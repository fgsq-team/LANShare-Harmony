/**
 * v4 协议「发送端」实机探测 —— 从 PC 模拟 Android 端，向真机上的鸿蒙 LANShare 发文件。
 *
 * 用途：独立验证「其他设备 -> 鸿蒙」这条链路，不依赖任何 Android 设备。
 *
 * 字节序完全照抄原项目 app/src/main/java/com/fgsqw/lanshare/service/version/four/FileSend.java:
 *   1. writeInt(Config.MAGIC_NUM = 0x66677371)
 *   2. writeInt(LCmd.NEW_VERSION_4 = -2)
 *   3. writeString(fromDevice.toJsonObject().toJSONString())
 *   4. writeInt(LCmd.FS_SHARE_FILE = 1101)
 *   5. writeBoolean(encData)
 *   6. writeString({fromDevice, type, groupId, files})
 *   7. readInt() 期望 LCmd.FS_AGREE = 1102
 *   8. 逐文件循环: writeInt(len) + write(bytes)
 *
 * 用法:
 *   node v4_send_probe.mjs <ip> [port] [size]
 */

import net from 'node:net';
import { randomUUID } from 'node:crypto';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const SIZE = Number(process.argv[4] || 4096);

const MAGIC_NUM = 0x66677371;
const NEW_VERSION_4 = -2;
const FS_SHARE_FILE = 1101;
const FS_AGREE = 1102;
const FS_NOT_AGREE = 1103;

// 原项目 CustomDataOutputStream：全部大端
function i32(n) {
  const b = Buffer.alloc(4);
  b.writeInt32BE(n | 0, 0);
  return b;
}
function str(s) {
  const u = Buffer.from(s, 'utf8');
  return Buffer.concat([i32(u.length), u]);
}
function bool(v) {
  return Buffer.from([v ? 1 : 0]);
}

const t0 = Date.now();
function log(msg) {
  console.log(`[+${String(Date.now() - t0).padStart(5)}ms] ${msg}`);
}

const device = {
  devName: 'AI-Probe(PC)',
  devIP: '192.168.10.186',
  devNetMask: '255.255.255.0',
  devBrotIP: '192.168.10.255',
  uniqueUUid: randomUUID(),
  devPort: 4573,
  devMode: 1,
  dataVersion: 4,
  isIPv4: true,
  batteryLevel: 100,
  chargeStatus: 0
};

const fileId = randomUUID();
const fileName = `probe_from_pc_${SIZE}.txt`;
const payload = Buffer.alloc(SIZE, 0x41); // 'A' * SIZE
payload.write('LANShare HarmonyOS v4 receive probe\n', 0, 'utf8');

const transfer = {
  fromDevice: device,
  type: 0,
  groupId: 0,
  files: [
    { fileId, name: fileName, length: payload.length, fileType: 5, toUser: 'HarmonyOS' }
  ]
};

const sock = net.connect({ host: HOST, port: PORT });
sock.setNoDelay(true);

let stage = 'connect';
let acc = Buffer.alloc(0);
let recvBytes = 0;

sock.on('connect', () => {
  log(`已连接 ${HOST}:${PORT}`);
  log(`-> MAGIC=0x${MAGIC_NUM.toString(16)} NEW_VERSION_4=${NEW_VERSION_4} deviceJson(${JSON.stringify(device).length}B)`);
  sock.write(i32(MAGIC_NUM));
  sock.write(Buffer.concat([i32(NEW_VERSION_4), str(JSON.stringify(device))]));
  log(`-> FS_SHARE_FILE=${FS_SHARE_FILE} encData=false transferJson(${JSON.stringify(transfer).length}B)`);
  sock.write(Buffer.concat([i32(FS_SHARE_FILE), bool(false), str(JSON.stringify(transfer))]));
  stage = 'wait-agree';
  log('等待 FS_AGREE…');
});

sock.on('data', (d) => {
  recvBytes += d.length;
  acc = Buffer.concat([acc, d]);

  if (stage === 'wait-agree') {
    if (acc.length < 4) {
      return;
    }
    const resp = acc.readInt32BE(0);
    acc = acc.subarray(4);
    if (resp === FS_AGREE) {
      log(`<- FS_AGREE(${FS_AGREE}) ✓ 对端同意接收`);
      stage = 'sending';
      const CH = 64 * 1024;
      let off = 0;
      while (off < payload.length) {
        const n = Math.min(CH, payload.length - off);
        sock.write(Buffer.concat([i32(n), payload.subarray(off, off + n)]));
        off += n;
      }
      log(`-> 已发送 payload ${off} 字节（分 ${Math.ceil(payload.length / CH)} 片）`);
      stage = 'sent';
      setTimeout(() => sock.end(), 2000);
    } else if (resp === FS_NOT_AGREE) {
      log(`<- FS_NOT_AGREE(${FS_NOT_AGREE}) ✗ 对端拒绝接收`);
      stage = 'rejected';
      sock.end();
    } else {
      log(`<- 未知应答 ${resp}（期望 ${FS_AGREE}）`);
      stage = 'bad-response';
      sock.end();
    }
  }
});

sock.on('error', (e) => {
  log(`socket error: ${e.code} ${e.message}`);
});
sock.on('close', (hadErr) => {
  log(`连接关闭（hadError=${hadErr}）stage=${stage} 共收到 ${recvBytes}B`);
  process.exit(stage === 'sent' ? 0 : 1);
});

setTimeout(() => {
  log(`总超时 20s，stage=${stage}`);
  sock.destroy();
  process.exit(2);
}, 20000);
