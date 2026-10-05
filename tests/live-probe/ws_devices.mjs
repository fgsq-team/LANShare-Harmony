/**
 * 通过应用自带的 WebSocket 接口读**实时设备表**（WS_CMD_SYNC_DEVICE_LIST = 2）。
 *
 * 用途：设备表去重修复的「修复前 / 修复后」对照。
 *   修复前：同一台物理设备（同 IP）会出现多条。
 *   修复后：同 IP 只应剩一条。
 *
 * ⚠️ 该接口的字段只有 address/devName/devIP（见 wsDeviceListMessage），
 *    拿不到 uuid 与 dataVersion —— 那两项要看 hilog。
 *
 * 用法：node ws_devices.mjs [ip] [port] [listenMs]
 */
const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const LISTEN_MS = Number(process.argv[4] || 8000);

const url = `ws://${HOST}:${PORT}/wss`;
console.log(`连接 ${url} ，监听 ${LISTEN_MS} ms …`);

const seen = [];

function dump(tag) {
  if (seen.length === 0) {
    console.log(`[${tag}] （还没收到设备列表推送）`);
    return;
  }
  // 按 devIP 归并，统计同 IP 出现次数
  const byIp = new Map();
  for (const d of seen) {
    const k = d.devIP || '(空)';
    if (!byIp.has(k)) byIp.set(k, []);
    byIp.get(k).push(d);
  }
  console.log(`[${tag}] 设备表条目数 = ${seen.length}，不同 IP 数 = ${byIp.size}`);
  for (const [ip, list] of byIp) {
    const mark = list.length > 1 ? `  ★ 同 IP ${list.length} 条（重复！）` : '';
    console.log(`   ${ip.padEnd(16)} × ${list.length}${mark}`);
    for (const d of list) console.log(`       name=${d.devName}`);
  }
}

const ws = new WebSocket(url);

ws.addEventListener('open', () => {
  console.log('已连接，等待 SYNC_DEVICE_LIST …');
});

ws.addEventListener('message', (ev) => {
  const raw = typeof ev.data === 'string' ? ev.data : Buffer.from(ev.data).toString('utf8');
  console.log(`<< ${raw.length > 300 ? raw.slice(0, 300) + '…' : raw}`);
  let obj = null;
  try {
    obj = JSON.parse(raw);
  } catch (e) {
    return;
  }
  if (obj && obj.cmd === 2 && Array.isArray(obj.data)) {
    seen.length = 0;
    for (const d of obj.data) seen.push(d);
    dump('设备表');
  }
});

ws.addEventListener('error', (e) => {
  console.log(`✗ 连接错误: ${e.message || e}`);
});

ws.addEventListener('close', () => {
  console.log('连接已关闭');
});

setTimeout(() => {
  dump('最终');
  try { ws.close(); } catch (e) { /* ignore */ }
  setTimeout(() => process.exit(0), 200);
}, LISTEN_MS);
