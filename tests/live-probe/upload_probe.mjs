/**
 * /uploadFile 与「页面 15 秒」的实测复现脚本。
 *
 * 目的（三个独立实验，互不干扰）：
 *   A. 小文件 multipart 上传 —— 看契约与响应
 *   B. 大文件 multipart 上传 —— 测服务端真实吞吐，验证 60s 超时
 *   C. 并发 8 个请求 —— 复现「打开页面 15 秒才显示内容」
 *
 * 用法：node upload_probe.mjs [ip] [port]
 */
import net from 'node:net';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const BOUNDARY = '----WebKitFormBoundaryProbeLanShare01';

/** 构造 multipart/form-data 的前后包壳，中间是文件体 */
function multipartHead(fileName, size) {
  return Buffer.from(
    `--${BOUNDARY}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="${fileName}"\r\n` +
    `Content-Type: application/octet-stream\r\n\r\n`, 'utf8');
}
function multipartTail() {
  return Buffer.from(`\r\n--${BOUNDARY}--\r\n`, 'utf8');
}

/** 走裸 socket 发一个带 body 的 POST，返回 {status, headers, body, ms} */
function post(path, bodyChunks, totalLen, extraHeaders = {}, label = '') {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const sock = net.connect(PORT, HOST);
    let raw = Buffer.alloc(0);
    let sentAll = false;
    let firstByteMs = -1;
    sock.setNoDelay(true);

    sock.on('connect', () => {
      const head =
        `POST ${path} HTTP/1.1\r\n` +
        `Host: ${HOST}:${PORT}\r\n` +
        `Content-Type: multipart/form-data; boundary=${BOUNDARY}\r\n` +
        `Content-Length: ${totalLen}\r\n` +
        `Connection: close\r\n` +
        Object.entries(extraHeaders).map(([k, v]) => `${k}: ${v}\r\n`).join('') +
        `\r\n`;
      sock.write(head);
      (async () => {
        for (const c of bodyChunks) {
          if (!sock.write(c)) {
            await new Promise((r) => sock.once('drain', r));
          }
        }
        sentAll = true;
      })();
    });

    sock.on('data', (d) => {
      if (firstByteMs < 0) firstByteMs = Date.now() - t0;
      raw = Buffer.concat([raw, d]);
    });
    sock.on('error', (e) => {
      resolve({ label, error: e.message, ms: Date.now() - t0, sentAll });
    });
    sock.on('close', () => {
      const ms = Date.now() - t0;
      const txt = raw.toString('utf8');
      const headEnd = txt.indexOf('\r\n\r\n');
      const headPart = headEnd >= 0 ? txt.slice(0, headEnd) : txt;
      const status = (headPart.match(/^HTTP\/1\.[01] (\d+)/) || [])[1] || '???';
      resolve({
        label, ms, status, firstByteMs, sentAll,
        bytesBack: raw.length,
        body: headEnd >= 0 ? txt.slice(headEnd + 4).slice(0, 300) : '(无响应体)',
      });
    });
  });
}

/** 造一个 size 字节的「文件体」，用可辨识内容便于核对 */
function makeBody(size) {
  const head = multipartHead('probe.bin', size);
  const tail = multipartTail();
  const file = Buffer.alloc(size);
  for (let i = 0; i < size; i += 4096) file.write('LANSHARE-PROBE', i, Math.min(14, size - i), 'utf8');
  return { chunks: [head, file, tail], total: head.length + size + tail.length };
}

async function expA() {
  console.log('\n================ A. 小文件 multipart 上传（1 MiB）================');
  const { chunks, total } = makeBody(1024 * 1024);
  const r = await post('/uploadFile', chunks, total, { token: 'probe' }, 'A');
  console.log(`状态 ${r.status}  耗时 ${r.ms}ms  首字节 ${r.firstByteMs}ms  回包 ${r.bytesBack}B`);
  console.log(`响应体: ${JSON.stringify(r.body)}`);
}

async function expB() {
  console.log('\n================ B. 大文件 multipart 上传（32 MiB）================');
  const MB = 32;
  const { chunks, total } = makeBody(MB * 1024 * 1024);
  const r = await post('/uploadFile', chunks, total, { token: 'probe' }, 'B');
  const mbps = (MB / (r.ms / 1000)).toFixed(2);
  console.log(`状态 ${r.status}  耗时 ${r.ms}ms  首字节 ${r.firstByteMs}ms`);
  console.log(`有效吞吐 ${mbps} MiB/s   （局域网千兆理论 ~110 MiB/s）`);
  console.log(`响应体: ${JSON.stringify(r.body)}`);
  if (r.ms > 55000 && r.ms < 65000) {
    console.log('⚠️  耗时落在 60s 附近 —— 命中 readExactly(bodyLen, 60000) 超时');
  }
}

async function expC() {
  console.log('\n================ C. 并发 8 个 GET（复现「页面 15 秒」）================');
  const t0 = Date.now();
  const jobs = [];
  for (let i = 0; i < 8; i++) {
    const p = ['/', '/js/jquery.min.js', '/js/lanshare.min.js', '/css/style.min.css', '/main.min.js', '/js/main.min.js', '/favicon.ico', '/'][i];
    jobs.push(new Promise((resolve) => {
      const sock = net.connect(PORT, HOST);
      let raw = Buffer.alloc(0);
      let first = -1;
      const s0 = Date.now();
      sock.on('connect', () => {
        sock.write(`GET ${p} HTTP/1.1\r\nHost: ${HOST}:${PORT}\r\nConnection: close\r\n\r\n`);
      });
      sock.on('data', (d) => {
        if (first < 0) first = Date.now() - s0;
        raw = Buffer.concat([raw, d]);
      });
      sock.on('close', () => resolve({
        i, path: p, ms: Date.now() - s0, first, bytes: raw.length,
        status: (raw.toString('utf8').match(/^HTTP\/1\.[01] (\d+)/) || [])[1] || '???',
      }));
      sock.on('error', () => resolve({ i, path: p, ms: Date.now() - s0, first, bytes: -1, status: 'ERR' }));
    }));
  }
  const rs = await Promise.all(jobs);
  console.log(`全部完成耗时 ${Date.now() - t0}ms`);
  console.log('  序号  状态   总耗时   首字节   字节数   路径');
  for (const r of rs) {
    console.log(`  ${String(r.i).padEnd(5)} ${r.status.padEnd(6)} ${String(r.ms).padStart(7)}ms ${String(r.first).padStart(7)}ms ${String(r.bytes).padStart(9)}  ${r.path}`);
  }
  const worst = Math.max(...rs.map((r) => r.ms));
  if (worst > 14000) {
    console.log(`⚠️  最慢请求 ${worst}ms —— 与 15s 空转超时吻合`);
  }
}

await expA();
await expB();
await expC();
console.log('\n探测结束。');
