// 鸿蒙无线调试端口探测：手机端 hdc 端口是随机分配的（并非固定 5555），
// 所以只能对目标 IP 做全端口 TCP 扫描，再把开放端口逐个喂给 `hdc tconn`。
// 用法： node hdc_portscan.mjs 192.168.10.179 [并发] [超时ms]
import net from 'node:net';

const host = process.argv[2];
if (!host) { console.error('用法: node hdc_portscan.mjs <ip> [并发=1500] [超时ms=700]'); process.exit(1); }
const CONC = Number(process.argv[3] || 1500);
const TIMEOUT = Number(process.argv[4] || 700);
const MIN = Number(process.argv[5] || 1);
const MAX = Number(process.argv[6] || 65535);

function probe(port) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    let done = false;
    const fin = (ok) => {
      if (done) { return; }
      done = true;
      try { s.destroy(); } catch (_) { /* ignore */ }
      resolve(ok ? port : 0);
    };
    s.setTimeout(TIMEOUT);
    s.once('connect', () => fin(true));
    s.once('timeout', () => fin(false));
    s.once('error', () => fin(false));
    try { s.connect(port, host); } catch (_) { fin(false); }
  });
}

const t0 = Date.now();
const open = [];
let next = MIN;
let inflight = 0;

await new Promise((resolve) => {
  const pump = () => {
    while (inflight < CONC && next <= MAX) {
      const p = next++;
      inflight++;
      probe(p).then((r) => {
        inflight--;
        if (r) { open.push(r); console.log(`OPEN ${host}:${r}`); }
        if (next > MAX && inflight === 0) { resolve(); } else { pump(); }
      });
    }
  };
  pump();
});

console.log(`--- 扫描完成 ${host} ${MIN}-${MAX}，用时 ${((Date.now() - t0) / 1000).toFixed(1)}s`);
console.log('开放端口:', open.length ? open.join(', ') : '(无)');
