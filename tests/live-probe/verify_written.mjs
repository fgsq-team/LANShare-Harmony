/**
 * 取回落盘文件做内容校验。
 *
 * 走应用自带 HTTP 接口 `GET /file/<名>?path=<绝对路径>`（HttpRouter.downloadFile）。
 * 探针造的负载：每一块内、每 4096 字节开头写 'LANSHARE-SEG'。
 *   每块块内标记数 = floor((2097140-1)/4096) + 1 = 512
 *   文件总标记数   = 片数 × 每片块数 × 512
 * 零字节处应全为 0x00（Buffer.alloc 默认清零）—— 若 16 路随机写偏移错位，
 * 标记数与「非零但无标记」的字节会明显对不上。
 *
 * 用法：node verify_written.mjs <手机IP> <文件绝对路径> <期望标记数> [http端口]
 */

import http from 'node:http';

const HOST = process.argv[2] || '192.168.10.146';
const ABS = process.argv[3];
const EXPECT_MARKS = Number(process.argv[4] || 0);
const PORT = Number(process.argv[5] || 8080);
/** 标记串要与造数据的那支探针一致：push/seg 用 LANSHARE-PROBE/SEG，blockack 用 LANSHARE-BLOCKACK */
const MARK_STR = process.argv[6] || 'LANSHARE-SEG';

if (!ABS) {
  console.error('用法：node verify_written.mjs <ip> <绝对路径> <期望标记数> [端口]');
  process.exit(2);
}

const name = ABS.substring(ABS.lastIndexOf('/') + 1);
const url = `http://${HOST}:${PORT}/file/${encodeURIComponent(name)}?path=${encodeURIComponent(ABS)}`;
console.log(`GET ${url}\n`);

function get(u) {
  return new Promise((resolve, reject) => {
    const req = http.get(u, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        resolve(get(res.headers.location));
        return;
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on('error', reject);
    req.setTimeout(60000, () => { req.destroy(new Error('超时 60s')); });
  });
}

const r = await get(url);
console.log(`HTTP ${r.status}`);
console.log(`Content-Length = ${r.headers['content-length'] ?? '(无)'}`);
if (r.status !== 200) {
  console.log(`响应体（前 300 字节）：${r.body.subarray(0, 300).toString('utf8')}`);
  process.exit(1);
}

const buf = r.body;
const MARK = Buffer.from(MARK_STR, 'utf8');
let marks = 0;
let pos = buf.indexOf(MARK);
while (pos !== -1) { marks++; pos = buf.indexOf(MARK, pos + 1); }

// 统计非零字节（整文件 ~16MB，全扫也就毫秒级）
let nonzero = 0;
for (let i = 0; i < buf.length; i++) if (buf[i] !== 0) nonzero++;

console.log(`\n实际大小   = ${buf.length}`);
console.log(`标记串     = '${MARK_STR}'（${MARK.length} 字节）`);
console.log(`标记数     = ${marks}（期望 ${EXPECT_MARKS}）`);
console.log(`非零字节   = ${nonzero}（标记应占 ${marks * MARK.length}）`);
console.log(`零字节占比 = ${(100 * (buf.length - nonzero) / buf.length).toFixed(2)}%`);

const okSize = EXPECT_MARKS === 0 || buf.length > 0;
const okMarks = EXPECT_MARKS === 0 || marks === EXPECT_MARKS;
console.log(`\n${okMarks ? '✓' : '✗'} 内容标记核对：${marks} / ${EXPECT_MARKS}`);
process.exit(okSize && okMarks ? 0 : 1);
