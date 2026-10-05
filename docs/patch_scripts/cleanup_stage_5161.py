#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.61：多文件「发送到网页端」改为 打包完即删沙箱副本

vivi 2026-10-03：「那就先复制到沙箱，再自动删除」

## 背景
5.1.60 只让**单文件**零落盘；多文件因`zlib.compressFiles` 只认真实路径，
仍走 `stageForWeb()` 整份复制到 `${saveRoot}/网页待下载/` 且**从不清理**。

## 本轮方案：打包成功 ⇒ 立刻删副本
删除时机选在 **`POST /compressFiles` 打包成功之后**（`zlib.compressFiles` 返回后），
理由：此刻字节已在 zip 里，浏览器随后取的是 zip，不再需要副本。
★ **不能拖到 `GET /downloadZipFile` 之后** —— 那时浏览器可能已断线/取消，
   副本会永久残留；且打包与取走是两次独立请求，跨请求关联容易漏。

## 安全要点（★ 绝不能误删用户原有文件）
副本**全部位于固定子目录 `${saveRoot}/网页待下载/` 下** ⇒ 删除时逐个校验
`p.startsWith(该目录 + '/')`，**只删这个目录下的文件**。
⚠️ 若误把「用户从文件页勾选的原有文件」也删了 = 数据丢失。
⇒ 因此只删「本次请求里、且落在该目录下」的路径，逐个 `unlinkSync`。

## 幂等/兜底
· 打包失败 ⇒ **不删**（保留副本供重试），并清掉本次登记。
· 删除失败只记日志，不影响打包结果。
· 另外加一条「启动/压缩前清陈旧副本」的兜底 `pruneWebStage()`：
  超过 30 分钟的删掉（进程被杀导致没走到删除的场景）。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
BK = os.path.join(ROOT, 'docs', 'backups')
F = {
    'router': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net', 'HttpRouter.ets'),
    'svc': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets'),
    'idx': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets'),
    'ap': os.path.join(ROOT, 'AppScope', 'app.json5'),
}
SENT = 'private pruneWebStageSafe(paths: string[]): void {'

# ======================================================================
# 1. LanService：导出暂存目录名 + 新增 prune 方法
# ======================================================================
OLD_SIG = """  async stageForWeb(files: OutgoingFile[]): Promise<string[]> {
    const dir: string = `${this.storage.saveRoot}/网页待下载`;
    FileStorage.mkdirs(dir);"""

NEW_SIG = """  async stageForWeb(files: OutgoingFile[]): Promise<string[]> {
    const dir: string = LanService.webStageDir(this.storage.saveRoot);
    FileStorage.mkdirs(dir);"""

# ★★★ 关键：复制成功后必须**登记**这份副本，否则打包后无从判断哪些能删。
#   （第一版漏了这行⇒ 登记簿永远是空的⇒ 副本永远删不掉。）
OLD_MARK = """      if (okc) {
        out.push(dst);
      } else {
        this.pushLog(`写入「${f.name}」失败，已跳过`);
      }"""
NEW_MARK = """      if (okc) {
        out.push(dst);
        // ★★ 5.1.61：登记「这份是本进程复制出来的副本」——
        //   打包成功后 HttpRouter 只删登记在册的，
        //   **绝不碰用户原有的接收文件**（`pushFilesToWeb` 也走这个函数）。
        HttpRouter.markWebStage([dst]);
      } else {
        this.pushLog(`写入「${f.name}」失败，已跳过`);
      }"""

OLD_PUSH_FWD = """  pushUrisToWeb(items: WebPushItem[]): number {"""

NEW_PUSH_FWD = """  /** ★ 5.1.61：「发送到网页端」的**副本目录**（唯一的、可安全整目录清理的地方） */
  static webStageDir(saveRoot: string): string {
    return `${saveRoot}/网页待下载`;
  }

  /**
   * ★★ 5.1.61 清理「发送到网页端」的沙箱副本。
   *
   * 只删 `${saveRoot}/网页待下载/` 下的文件 —— 这个目录**只由 stageForWeb 产生**，
   * 所以整目录清理不会碰到用户原有的接收文件（那是 `saveRoot/<分类>/`）。
   * ⚠️ **绝不能按「本次推送的路径列表」盲删** —— 那些路径里可能混着
   * 文件页勾选的原有文件（`pushFilesToWeb` 也走同一入口）。
   *
   * @param keep 需要保留的路径（一般为空）
   */
  pruneWebStage(keep: string[] = []): number {
    const dir: string = LanService.webStageDir(this.storage.saveRoot);
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(dir);
    } catch (e) {
      return 0;                    // 目录不存在 = 没有副本
    }
    let n: number = 0;
    for (let i = 0; i < names.length; i++) {
      const p: string = `${dir}/${names[i]}`;
      if (keep.indexOf(p) >= 0) {
        continue;
      }
      try {
        const st: fileIo.Stat = fileIo.statSync(p);
        if (st.isDirectory()) {        // 目录里不该有子目录，保险起见跳过
          continue;
        }
        fileIo.unlinkSync(p);
        n += 1;
      } catch (e) {
        // 删不掉就算了（可能正被占用），下次 prune 或下次启动再试
        Log.w(TAG, `网页待下载副本清理失败: ${p}`);
      }
    }
    if (n > 0) {
      this.pushLog(`已清理 ${n} 个网页待下载副本`);
      this.emit();
    }
    return n;
  }

  pushUrisToWeb(items: WebPushItem[]): number {"""

# ======================================================================
# 2. Index.ets：启动时清陈旧副本
# ======================================================================
OLD_IDX = """    this.toast('正在准备文件…');
    const paths: string[] = await this.service.stageForWeb(files);"""

NEW_IDX = """    this.toast('正在准备文件…');
    // ★ 5.1.61：多文件仍需复制（zip 只认真实路径），但**打包完会自动删**。
    //   这里先清一次陈旧副本 —— 覆盖「上次进程被杀、没走到删除」的残留。
    this.service.pruneWebStage();
    const paths: string[] = await this.service.stageForWeb(files);"""


def main():
    r = read_text(F['router']) if False else io.open(F['router'], encoding='utf-8', newline='').read()
    s = io.open(F['svc'], encoding='utf-8', newline='').read()
    i = io.open(F['idx'], encoding='utf-8', newline='').read()
    ap = io.open(F['ap'], encoding='utf-8', newline='').read()

    if SENT in r:
        print('ALREADY APPLIED')
        return 0

    # ---- 校验 ----
    assert s.count(OLD_SIG) == 1, 'svc stageForWeb dir anchor %d' % s.count(OLD_SIG)
    assert s.count(OLD_PUSH_FWD) == 1, 'svc pushUrisToWeb anchor %d' % s.count(OLD_PUSH_FWD)
    assert s.count(OLD_MARK) == 1, 'svc stageForWeb push anchor %d' % s.count(OLD_MARK)
    assert i.count(OLD_IDX) == 1, 'Index anchor %d' % i.count(OLD_IDX)
    assert '"5.1.60"' in ap
    assert 'fileIo' in s, 'LanService 未 import fileIo'

    # ---- HttpRouter：compressFiles 打包成功后删副本 ----
    OLD_ZIP = """    Log.i(TAG, `已打包 ${safe.length} 项 -> ${out}`);
    // 打包完先留一句「等网页来取」，浏览器紧接着的 GET /downloadZipFile 会把它覆盖成百分比
    if (packed) {
      this.notifyDownloadProgress(0, -1, '打包完成，等待网页下载…');
    }
    return HttpResponse.json(200, `{"tempFile":${HttpRouter.jsonStr(name)}}`);"""

    NEW_ZIP = """    Log.i(TAG, `已打包 ${safe.length} 项 -> ${out}`);
    // 打包完先留一句「等网页来取」，浏览器紧接着的 GET /downloadZipFile 会把它覆盖成百分比
    if (packed) {
      this.notifyDownloadProgress(0, -1, '打包完成，等待网页下载…');
    }
    // ★★ 5.1.61：**打包成功 ⇒ 立刻删掉「发送到网页端」的沙箱副本**。
    //   时机选在这里而不是 `GET /downloadZipFile` 之后：
    //     ① 此刻字节已在 zip 里，浏览器取的是 zip，不再需要副本；
    //     ② 取 zip 是**另一次请求**，可能断线/取消 ⇒ 副本会永久残留；
    //     ③ 跨请求关联两个阶段容易漏（进程被杀就再也不会有人来删）。
    //   ⚠️ 只删「网页待下载」目录下的文件（`pruneWebStage` 内部按目录前缀校验），
    //      绝不碰用户原有的接收文件。
    this.pruneWebStageSafe(safe);
    return HttpResponse.json(200, `{"tempFile":${HttpRouter.jsonStr(name)}}`);"""

    # 失败分支也要清登记（打包失败 ⇒ 保留副本供重试，但本次不算成功）
    OLD_FAIL = """      this.notifyDownloadEnd(false, '', 0, `打包失败：${err.message}`);
      return HttpResponse.text(500, `文件打包失败：${err.code} ${err.message}`);"""
    NEW_FAIL = """      this.notifyDownloadEnd(false, '', 0, `打包失败：${err.message}`);
      // ★ 5.1.61：**打包失败不删副本** —— 保留下来让用户能重试。
      //只清登记（本次没成功过，就不该有「待清理」的影子）。
      this.forgetWebStage(safe);
      return HttpResponse.text(500, `文件打包失败：${err.code} ${err.message}`);"""

    OLD_CM = """    this.pruneZipTemp(dir);
    const name: string = `LANShare-${Date.now().toString(36)}-${HttpRouter.randomName()}.zip`;"""
    NEW_CM = """    this.pruneZipTemp(dir);
    this.pruneWebStageSafe([]);   // ★ 5.1.61：每次打包前先清上一次的残留
    const name: string = `LANShare-${Date.now().toString(36)}-${HttpRouter.randomName()}.zip`;"""

    # 新增两个私有方法（挂在 compressFiles 之前）
    OLD_PRUNE_ANCHOR = """  /**
   * `POST /compressFiles` —— 打包下载的第一步。"""
    NEW_PRUNE_METHOD = """  /**
   * ★★ 5.1.61 暂存副本登记簿。
   *
   * 「发送到网页端」多文件时必须先把文件复制进沙箱（zip 只认真实路径），
   * 打包成功后要删掉。删除时**不能盲删 `safe`** ——
   * 那个数组里可能混着文件页勾选的**用户原有文件**（`pushFilesToWeb` 同一入口）。
   * ⇒ 用「本进程复制过的路径」做登记簿，只删登记在册的。
   */
  private static webStageSet: Set<string> = new Set<string>();

  /** 登记「这批路径是本进程复制出来的副本」 */
  static markWebStage(paths: string[]): void {
    for (let i = 0; i < paths.length; i++) {
      HttpRouter.webStageSet.add(paths[i]);
    }
  }

  /** 取消登记（打包失败、或用户改主意） */
  private forgetWebStage(paths: string[]): void {
    for (let i = 0; i < paths.length; i++) {
      HttpRouter.webStageSet.delete(paths[i]);
    }
  }

  /**
   * 打包成功后删副本：**只删在登记簿里的**那些。
   *
   * @param paths 本次涉及的路径（用来过滤出登记在册的）
   */
  private pruneWebStageSafe(paths: string[]): void {
    const doomed: string[] = [];
    for (let i = 0; i < paths.length; i++) {
      if (HttpRouter.webStageSet.has(paths[i])) {
        doomed.push(paths[i]);
      }
    }
    for (let i = 0; i < doomed.length; i++) {
      try {
        fileIo.unlinkSync(doomed[i]);
        HttpRouter.webStageSet.delete(doomed[i]);
        Log.i(TAG, `已删除网页待下载副本: ${doomed[i]}`);
      } catch (e) {
        // 删不掉不报错：下次打包前还会再清一次
        Log.w(TAG, `副本删除失败(保留登记): ${doomed[i]}`);
      }
    }
  }

  /**
   * `POST /compressFiles` —— 打包下载的第一步。"""

    assert r.count(OLD_ZIP) == 1, 'router zip anchor %d' % r.count(OLD_ZIP)
    assert r.count(OLD_FAIL) == 1, 'router fail anchor %d' % r.count(OLD_FAIL)
    assert r.count(OLD_CM) == 1, 'router pruneZipTemp anchor %d' % r.count(OLD_CM)
    assert r.count(OLD_PRUNE_ANCHOR) == 1, 'router prune anchor %d' % r.count(OLD_PRUNE_ANCHOR)

    # ---- 构造 ----
    r2 = r.replace(OLD_ZIP, NEW_ZIP).replace(OLD_FAIL, NEW_FAIL).replace(OLD_CM, NEW_CM)
    r2 = r2.replace(OLD_PRUNE_ANCHOR, NEW_PRUNE_METHOD)
    s2 = s.replace(OLD_SIG, NEW_SIG).replace(OLD_PUSH_FWD, NEW_PUSH_FWD)
    s2 = s2.replace(OLD_MARK, NEW_MARK)
    i2 = i.replace(OLD_IDX, NEW_IDX)
    ap2 = ap.replace('"versionCode": 5000160,', '"versionCode": 5000161,').replace('"5.1.60"', '"5.1.61"')

    # ---- 二次校验 ----
    assert SENT in r2 and r2.count(SENT) == 1
    assert 'static markWebStage(paths: string[])' in r2
    assert 'private pruneWebStageSafe(paths: string[])' in r2
    assert 'fileIo.unlinkSync(doomed[i])' in r2
    assert r2.count('this.pruneWebStageSafe(safe)') == 1
    assert 'static webStageDir(saveRoot: string)' in s2
    assert 'HttpRouter.markWebStage([dst]);' in s2
    assert 'pruneWebStage(keep: string[] = []): number' in s2
    assert 'this.service.pruneWebStage()' in i2
    assert '"versionCode": 5000161,' in ap2
    for a, b in ((r, r2), (s, s2), (i, i2)):
        assert a.count('\r\n') == b.count('\r\n'), '行尾被改动'

    # ---- 落盘 ----
    for k in ('router', 'svc', 'idx', 'ap'):
        dst = os.path.join(BK, os.path.basename(F[k]) + '.v5161pre')
        if not os.path.isdir(BK):
            os.makedirs(BK)
        if not os.path.exists(dst):
            shutil.copy2(F[k], dst)
            print('  备份 -> %s' % dst)
    for k in ('router', 'svc', 'idx', 'ap'):
        io.open(F[k], 'w', encoding='utf-8', newline='').write(
            {'router': r2, 'svc': s2, 'idx': i2, 'ap': ap2}[k])
    print('OK 5.1.61 patched: HttpRouter（打包后删副本）/ LanService（pruneWebStage）/ Index.ets / app.json5')
    return 0


if __name__ == '__main__':
    sys.exit(main())