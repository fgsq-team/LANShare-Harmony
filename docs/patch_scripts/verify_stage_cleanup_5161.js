// 5.1.61 离线验证：暂存副本登记簿 + 删除安全性
// 核心断言：**只删「本进程复制出来的副本」，绝不删用户原有的接收文件**
const fs = require('fs');
const vm = require('vm');

const SRC = fs.readFileSync(
  __dirname + '/../../entry/src/main/ets/net/HttpRouter.ets', 'utf8');

console.log('=== 静态结构检查（ArkTS 源码层面）===');
let fail = 0;
function check(label, cond, extra) {
  console.log((cond ? 'OK   ' : 'FAIL ') + label + (extra ? '   ' + extra : ''));
  if (!cond) fail++;
}

// 1. 登记簿存在，且有 mark / forget / prune 三个动作
check('存在静态登记簿 webStageSet', /private static webStageSet: Set<string> = new Set<string>\(\);/.test(SRC));
check('有 markWebStage（登记）', /static markWebStage\(paths: string\[\]\): void/.test(SRC));
check('有 forgetWebStage（取消登记）', /private forgetWebStage\(paths: string\[\]\): void/.test(SRC));
check('有 pruneWebStageSafe（删除）', /private pruneWebStageSafe\(paths: string\[\]\): void/.test(SRC));

// 2. ★ 删除只针对「登记在册」的路径
const pruneBody = SRC.slice(SRC.indexOf('private pruneWebStageSafe'));
check('★ 删除前先查登记簿', /if \(HttpRouter\.webStageSet\.has\(paths\[i\]\)\)/.test(pruneBody));
check('★ 删除后清登记', /HttpRouter\.webStageSet\.delete\(doomed\[i\]\)/.test(pruneBody));

// 3. ★ 删除时机在「打包成功之后」
const zipAt = SRC.indexOf('已打包 ${safe.length} 项');
const pruneAt = SRC.indexOf('this.pruneWebStageSafe(safe);', zipAt);
check('★ 删除在「已打包」日志之后', zipAt > 0 && pruneAt > zipAt, `zip@${zipAt} prune@${pruneAt}`);

// 4. ★ 打包失败**不删**（保留供重试），只清登记
const failBranch = SRC.slice(SRC.indexOf('打包失败（${safe.length} 项）'));
const failSeg = failBranch.slice(0, failBranch.indexOf('return HttpResponse.text(500'));
check('★ 打包失败走 forgetWebStage（不删文件）', /this\.forgetWebStage\(safe\);/.test(failSeg));
check('★ 打包失败分支里没有 unlinkSync', !/unlinkSync/.test(failSeg));

// 5. 每次打包前先清上一次残留（兜底：进程被杀导致没走到删除）
const pruneZipAt = SRC.indexOf('this.pruneZipTemp(dir);');
check('打包前清陈旧残留', /this\.pruneZipTemp\(dir\);\s*\n\s*this\.pruneWebStageSafe\(\[\]\);/.test(SRC));

// 6. ★ stageForWeb 复制成功后必须登记
const svc = fs.readFileSync(
  __dirname + '/../../entry/src/main/ets/service/LanService.ets', 'utf8');
check('★ stageForWeb 复制后登记副本', /HttpRouter\.markWebStage\(\[dst\]\);/.test(svc));
const stageBody = svc.slice(svc.indexOf('async stageForWeb'));
check('★ 登记在「okc 成功分支」内',
  /if \(okc\) \{[\s\S]{0,400}?markWebStage/.test(stageBody));

// 7. LanService 侧整目录清理方法
check('有 pruneWebStage（整目录兜底清理）', /pruneWebStage\(keep: string\[\] = \[\]\): number/.test(svc));
check('★ 整目录清理会跳过 isDirectory', /st\.isDirectory\(\)/.test(svc));

console.log('-'.repeat(78));
if (fail) { console.log('FAILED: ' + fail + ' 项不符'); process.exit(1); }
console.log('ALL PASS: 只删登记在册的副本 / 打包后才删 / 失败不删 / 复制后必登记');