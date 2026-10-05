/** 列出应用「已接收文件」目录，拿到探针落盘文件的确切名（走 GET /files）。 */
import http from 'node:http';

const HOST = process.argv[2] || '192.168.10.146';
const PORT = Number(process.argv[3] || 5856);
const DIR = process.argv[4] || '/data/storage/el2/base/haps/entry/files/LANShare/其他';

const url = `http://${HOST}:${PORT}/files?path=${encodeURIComponent(DIR)}`;
http.get(url, (res) => {
  const chunks = [];
  res.on('data', (c) => chunks.push(c));
  res.on('end', () => {
    console.log(`HTTP ${res.statusCode}`);
    const t = Buffer.concat(chunks).toString('utf8');
    try {
      const j = JSON.parse(t);
      console.log(`dir = ${j.path}`);
      for (const f of j.list || []) {
        console.log(`  ${f.isDirectory ? '[D]' : '   '} ${String(f.length).padStart(12)}  ${f.name}`);
      }
    } catch (e) {
      console.log(t.substring(0, 800));
    }
  });
}).on('error', (e) => console.log(`错误: ${e.message}`));
