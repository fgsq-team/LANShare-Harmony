// 多主机全端口扫描：鸿蒙无线调试端口随机，手机换了 IP 后只能扫出来再喂给 `hdc tconn`。
// 用法： node hdc_portscan_all.mjs 192.168.10.122,192.168.10.125,... [并发] [超时ms]
import net from 'node:net';

const hosts = (process.argv[2] || '').split(',').map((x) => x.trim()).filter(Boolean);
if (hosts.length === 0) { console.error('用法: node hdc_portscan_all.mjs <ip,ip,...> [并发=2000] [超时ms=600]'); process.exit(1); }
const CONC = Number(process.argv[3] || 2000);
const TIMEOUT = Number(process.argv[4] || 600);

function probe(host, port) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    let done = false;
    const fin = (ok) => {
      if (done) { return; }
      done = true;
      try { s.destroy(); } catch (_) { /* ignore */ }
      resolve(ok);
    };
    s.setTimeout(TIMEOUT);
    s.once('connect', () => fin(true));
    s.once('timeout', () => fin(false));
    s.once('error', () => fin(false));
    try { s.connect(port, host); } catch (_) { fin(false); }
  });
}

const t0 = Date.now();
const tasks = [];
for (const h of hosts) { for (let p = 1; p <= 65535; p++) { tasks.push([h, p]); } }
let idx = 0;
let inflight = 0;
const hits = new Map();

await new Promise((resolve) => {
  const pump = () => {
    while (inflight < CONC && idx < tasks.length) {
      const [h, p] = tasks[idx++];
      inflight++;
      probe(h, p).then((ok) => {
        inflight--;
        if (ok) {
          if (!hits.has(h)) { hits.set(h, []); }
          hits.get(h).push(p);
          console.log(`OPEN ${h}:${p}`);
        }
        if (idx >= tasks.length && inflight === 0) { resolve(); } else { pump(); }
      });
    }
  };
  pump();
});

console.log(`--- 完成 ${hosts.length} 台 ×65535 端口，用时 ${((Date.now() - t0) / 1000).toFixed(1)}s`);
for (const h of hosts) { console.log(`${h}: ${(hits.get(h) || []).join(', ') || '(无)'}`); }
