/**
 * UDP 单播定向探测 —— 区分「AP 不转发广播」与「主机防火墙拦截」。
 *
 * 直接向手机 IP 单播一份合法心跳，绕过广播路径。
 * 若手机日志出现「发现设备 PC-Probe(Windows)」→ 单播通、广播不通 = AP 抑制广播。
 * 若仍无反应 → 连单播都到不了 = 防火墙 / 路由问题。
 *
 * 用法: node --experimental-strip-types udp_unicast.mjs <手机IP> [端口]
 */
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import dgram from 'node:dgram';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BUILD = path.join(__dirname, '_probe_build');

const TARGET = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 4573);

const { DeviceCodec, LanDevice, DeviceMode } = await import(
  pathToFileURL(path.join(BUILD, 'DeviceCodec.ts')).href
);
const { LCmd } = await import(pathToFileURL(path.join(BUILD, 'LCmd.ts')).href);
const { LanConfig } = await import(pathToFileURL(path.join(BUILD, 'LanConfig.ts')).href);
const { DataDec } = await import(pathToFileURL(path.join(BUILD, 'DataPacket.ts')).href);

// 换一个 uuid，避免和广播实例混淆
const self = new LanDevice('PC-Unicast-Probe', '192.168.10.186', 5856);
self.devNetMask = '255.255.255.0';
self.devBroadcastIp = '192.168.10.255';
self.uniqueUuid = 'PC-UNICAST-PROBE-0002';
self.devMode = DeviceMode.WINDOWS;
self.dataVersion = LanConfig.DATA_VERSION;
self.batteryLevel = 88;
self.chargeStatus = -1;

const pkt = Buffer.from(DeviceCodec.buildHeartbeat(self, LCmd.UDP_SET_DEVICES));
console.log(`心跳包 ${pkt.length}B  hex=${pkt.toString('hex')}`);

const dg = dgram.createSocket({ type: 'udp4', reuseAddr: true });
dg.on('message', (msg, rinfo) => {
  const d = DataDec.fromUdp(new Uint8Array(msg));
  console.log(`<- 收到回包 ${msg.length}B 来自 ${rinfo.address}:${rinfo.port}` +
    (d ? ` cmd=${d.getCmd()}` : ' (非 LanShare 报文)'));
});
dg.on('error', (e) => console.log(`UDP error: ${e.code} ${e.message}`));

dg.bind(0, () => {
  let n = 0;
  const send = () => {
    n++;
    dg.send(pkt, PORT, TARGET, (err) => {
      console.log(err
        ? `-> 第 ${n} 次单播 -> ${TARGET}:${PORT} 失败: ${err.message}`
        : `-> 第 ${n} 次单播 -> ${TARGET}:${PORT} 已发出`);
    });
    if (n >= 3) {
      setTimeout(() => {
        console.log('发送完毕，等待 3s 看是否有回包…');
        setTimeout(() => { dg.close(); process.exit(0); }, 3000);
      }, 1000);
    }
  };
  send();
  setTimeout(send, 1000);
  setTimeout(send, 2000);
});
