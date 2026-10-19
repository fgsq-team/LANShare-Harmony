/**
 * 沙箱删除接口的路径守卫 —— 离线对拍。
 *
 * 删除是**不可逆**操作，而且路径可能来自网络/剪贴板，
 * 守卫写错的代价是删到沙箱外（装成"同前缀的兄弟目录"最典型）。
 * 这里把 `ExportService.checkInRoot` 的逻辑原样复刻到 node 里，
 * 用一组边界路径验证「该放的放行、该拦的拦住」。
 *
 * 跑法：node tests/sandbox-delete-check/check.mjs
 */
'use strict';

const ROOT = '/data/storage/el2/base/haps/entry/files/LANShare';

/** 与 ExportService.checkInRoot 逐行对应 */
function checkInRoot(root, path) {
  if (root.length === 0) {
    return '共享未开启，无法删除';
  }
  if (path.indexOf('..') >= 0) {
    return '路径不合法，已拒绝';
  }
  const prefix = root.endsWith('/') ? root : `${root}/`;
  if (!path.startsWith(prefix)) {
    return '该文件不在接收目录内，已拒绝删除';
  }
  return null;
}

/** 与 ExportService.deleteFiles 的统计逻辑对应（unlink 抛错记为 failed） */
function deleteFiles(root, paths, failSet) {
  const r = { ok: 0, failed: 0, firstError: '' };
  for (const p of paths) {
    const guard = checkInRoot(root, p);
    if (guard !== null) {
      r.failed++;
      if (r.firstError.length === 0) { r.firstError = guard; }
      continue;
    }
    if (failSet.has(p)) {           // 模拟 unlink 抛错（占用 / 权限）
      r.failed++;
      if (r.firstError.length === 0) { r.firstError = '删除失败（13）'; }
      continue;
    }
    r.ok++;
  }
  return r;
}

let pass = 0;
let fail = 0;
function check(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    pass++;
    console.log(`  [OK]   ${name}`);
  } else {
    fail++;
    console.log(`  [FAIL] ${name}\n        期望 ${e}\n        实际 ${a}`);
  }
}

console.log('== 1. 路径守卫 ==');
check('正常子目录文件放行', checkInRoot(ROOT, `${ROOT}/文档/a.txt`), null);
check('根目录直接子文件放行', checkInRoot(ROOT, `${ROOT}/a.txt`), null);
check('嵌套分类目录放行', checkInRoot(ROOT, `${ROOT}/视频/x/y.mp4`), null);
check('中文+emoji 文件名放行', checkInRoot(ROOT, `${ROOT}/其他/测试 🎉.bin`), null);

console.log('== 2. 必须拦住的 ==');
check('含 .. 的穿越路径', checkInRoot(ROOT, `${ROOT}/../../system/a.txt`) !== null, true);
check('root 之外的绝对路径', checkInRoot(ROOT, '/data/storage/el2/base/haps/entry/files/other/a.txt') !== null, true);
check('同前缀兄弟目录（前缀欺骗）', checkInRoot(ROOT, `${ROOT}Backup/a.txt`) !== null, true);
check('root 为空（共享未开启）', checkInRoot('', `${ROOT}/a.txt`) !== null, true);
check('root 目录本身不该被删', checkInRoot(ROOT, ROOT) !== null, true);
check('root 带尾斜杠时兄弟目录仍被拦', checkInRoot(`${ROOT}/`, `${ROOT}Backup/a.txt`) !== null, true);

console.log('== 3. 批量删除的统计 ==');
const paths = [`${ROOT}/a.txt`, `${ROOT}/b.txt`, `${ROOT}/c.txt`, `${ROOT}/../outside.txt`];
let r = deleteFiles(ROOT, paths, new Set());
check('3 条放行 1 条被拦', [r.ok, r.failed], [3, 1]);
check('firstError 是被拦那条的原因', r.firstError, '路径不合法，已拒绝');

r = deleteFiles(ROOT, paths, new Set([`${ROOT}/b.txt`]));
check('其中一条 unlink 失败', [r.ok, r.failed], [2, 2]);
check('unlink 失败不影响其余条数', r.ok > 0, true);

r = deleteFiles(ROOT, [], new Set());
check('空列表不报错', [r.ok, r.failed], [0, 0]);

console.log('== 4. 一条真实场景串 ==');
// 用户点「清空」：列表里既有分类子目录文件，也有根目录散文件
const mixed = [`${ROOT}/probe.bin`, `${ROOT}/其他/probe(1).bin`, `${ROOT}/文档/note.txt`];
check('清空路径全放行', mixed.map((p) => checkInRoot(ROOT, p)), [null, null, null]);
check('清空统计', deleteFiles(ROOT, mixed, new Set()).ok, 3);

console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail === 0 ? 0 : 1);
