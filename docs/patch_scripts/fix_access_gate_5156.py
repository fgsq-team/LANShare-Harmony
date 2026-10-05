#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.56 补丁：修「魔数纠错从未真正改名」

真凶（vivi 2026-10-03 实测「加后缀没有成功、连存相册弹窗都没有」）：
  `fileIo.accessSync(path, mode?): boolean` —— **文件不存在时返回 false，不抛异常**。
  旧代码写成「try { accessSync(target) } catch { 不存在 } ⇒ 不抛异常 = 已存在 ⇒ 放弃改名」
  ⇒ `renameSync` 从 5.1.51 起**一次都没被调用过**。
  连招：`abc.1` 名字不变 → `isImageName` 判不出图片 → `mediaNamesOf()` 返回空
        → `autoSaveNewMedia` 第 4136 行 `continue` ⇒ **存相册弹窗压根不会出现**。

本脚本做三件事：
  1. FileStorage.fixExtByMagic：accessSync 判据改对；且「目标已存在」不再放弃改名，
     改为 `base (2).jpg` / `(3)` 递增去重 —— 保住「纠错后后缀必然正确」这个不变量。
  2. FileTransfer（v4 路径）：改名后回写 `item.name` + 同步 `names[]`（与 V5 同款）。
  3. 版本号 5.1.55 → 5.1.56。

纪律：全部校验通过才落盘；幂等（重跑直接 ALREADY 退出）；UTF-8 + LF。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
BK = os.path.join(ROOT, 'docs', 'backups')

FILES = {
    'fs': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'FileStorage.ets'),
    'ft': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'FileTransfer.ets'),
    'ap': os.path.join(ROOT, 'AppScope', 'app.json5'),
}

# 哨兵取「新代码里独有的标识串」，避开注释里的 markdown 强调标记
SENTINEL = "let finalName: string = `${base}.${real}`;"


def read(p):
    return io.open(p, 'r', encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def backup(p, tag):
    if not os.path.isdir(BK):
        os.makedirs(BK)
    dst = os.path.join(BK, os.path.basename(p) + '.' + tag)
    if not os.path.exists(dst):
        shutil.copy2(p, dst)
        print('  备份 -> %s' % dst)


# ======================================================================
# 1. FileStorage.fixExtByMagic —— 核心修复
# ======================================================================
OLD_GATE = """      // 目标已存在 ⇒ 放弃（改名会覆盖别人的文件）
      try {
        fileIo.accessSync(target);
        Log.w(TAG, `魔数纠错：${base} → ${base}.${real} 但目标已存在，放弃`);
        return path;
      } catch (e) {
        // 不存在 = 正常，继续改名
      }
      fileIo.renameSync(path, target);
      Log.i(TAG, `魔数纠错：${base} → ${base}.${real}`);
      return target;"""

NEW_GATE = """      // ★★★★★ 5.1.56 真凶修复：`fileIo.accessSync` 的签名是 **返回 boolean**
      //   （`accessSync(path, mode?): boolean`，文件不存在时返回 false、**不抛异常**）。
      //   旧代码写成「try { accessSync } catch { 不存在 }」⇒ 不抛异常被当成「已存在」
      //   ⇒ **每一次都在这里 return，renameSync 从未执行过**（5.1.51~5.1.55 全白改）。
      //   ⚠️ 同一个 SDK 语义在别处（HttpRouter / LanService / dedupeName）都是用返回值判的，
      //      只有这一处反了 —— 这就是「换个 bug 还会撞上」的那类坑。
      //   ★ 5.1.56 目标已存在 ⇒ **递增去重**而不是放弃：
      //     「放弃」会让同名文件第二次接收时又变成非图片 ⇒ 又一次「不弹相册框」，
      //     等于把 bug 换个入口复现。要保住不变量：**纠错后后缀必然正确**。
      let finalName: string = `${base}.${real}`;
      let exists: boolean = false;
      try {
        exists = fileIo.accessSync(`${dir}/${finalName}`);
      } catch (e) {
        exists = false;   // 查不到就当作不存在，交给 renameSync 裁决
      }
      if (exists) {
        for (let k: number = 2; k < 50; k++) {
          const cand: string = `${base} (${k}).${real}`;
          let hit: boolean = false;
          try {
            hit = fileIo.accessSync(`${dir}/${cand}`);
          } catch (e2) {
            hit = false;
          }
          if (!hit) {
            finalName = cand;
            exists = false;
            break;
          }
        }
        if (exists) {
          Log.w(TAG, `魔数纠错：${base}.${real} 的候选名都被占用，保持原名`);
          return path;
        }
      }
      const finalPath: string = `${dir}/${finalName}`;
      fileIo.renameSync(path, finalPath);
      Log.i(TAG, `魔数纠错：${MagicType.baseNameOf(path)} → ${finalName}`);
      return finalPath;"""


# ======================================================================
# 2. FileTransfer（v4 接收路径）—— 补回写
# ======================================================================
OLD_FT = """    // ★★ 5.1.51：同 V5Transfer，收完按魔数纠正后缀并回写 path
    path = MagicType.fixExtByMagic(path);"""

NEW_FT = """    // ★★ 5.1.51：同 V5Transfer，收完按魔数纠正后缀并回写 path
    // ★★★ 5.1.56：与 V5 单文件路径同款——**必须回写 `item.name`**。
    //   `receiveOne` 上层（`receive` 的 report、以及收完汇总的 `names[]`）
    //   全部取自 `item.name`（协议原始名）⇒ 只改 `path` 等于改了个没人读的变量，
    //   磁盘上改了名、UI 与相册判定仍用旧名 ⇒ 「看起来完全没生效」。
    //   （这与 5.1.55 在 V5 侧踩的是同一个坑，v4 这条平行路径当时漏了。）
    const before: string = path;
    path = MagicType.fixExtByMagic(path);
    if (path !== before) {
      item.name = MagicType.baseNameOf(path);
      Log.i(TAG, `v4 改名回写：${before} → ${path}（item.name = ${item.name}）`);
    }"""

OLD_NAMES = """      FileTransfer.report(onReport, 'recv', from.devName,
        total === 1 ? items[0].name : `${total} 个文件`,"""

NEW_NAMES = """      // ★★★ 5.1.56：`names` 是**收文件之前** push 的副本（见上方 :395），
      //   `item.name` 被改名回写不会更新它 ⇒ 文件页列表仍显示旧名。
      //   与 V5Transfer 的 `names[i] = items[i].name` 完全同款。
      for (let i: number = 0; i < items.length; i++) {
        names[i] = items[i].name;
      }
      FileTransfer.report(onReport, 'recv', from.devName,
        total === 1 ? items[0].name : `${total} 个文件`,"""


def main():
    fs = read(FILES['fs'])
    ft = read(FILES['ft'])
    ap = read(FILES['ap'])

    if SENTINEL in fs:
        print('ALREADY APPLIED')
        return 0

    # ---- 校验（全部通过才落盘）----
    assert fs.count(OLD_GATE) == 1, 'FileStorage gate anchor count=%d' % fs.count(OLD_GATE)
    assert fs.count(NEW_GATE) == 0, 'FileStorage new already present'
    assert ft.count(OLD_FT) == 1, 'FileTransfer anchor count=%d' % ft.count(OLD_FT)
    assert ft.count(NEW_FT) == 0, 'FileTransfer new already present'
    assert ft.count(OLD_NAMES) == 1, 'FileTransfer names anchor count=%d' % ft.count(OLD_NAMES)
    assert ft.count(NEW_NAMES) == 0, 'FileTransfer names new already present'
    assert '"5.1.55"' in ap, 'versionName 5.1.55 not found'
    assert ap.count('"5.1.56"') == 0, 'versionName already bumped'

    # ---- 内存构造 ----
    fs2 = fs.replace(OLD_GATE, NEW_GATE)
    ft2 = ft.replace(OLD_FT, NEW_FT).replace(OLD_NAMES, NEW_NAMES)
    ap2 = ap.replace('"5.1.55"', '"5.1.56"')

    # ---- 二次校验 ----
    assert SENTINEL in fs2
    assert 'item.name = MagicType.baseNameOf(path);' in ft2
    assert 'names[i] = items[i].name;' in ft2
    # renameSync 现在真的会被调用
    assert fs2.count('fileIo.renameSync(path, finalPath);') == 1

    # ---- 统一落盘 ----
    backup(FILES['fs'], 'v5156pre')
    backup(FILES['ft'], 'v5156pre')
    backup(FILES['ap'], 'v5156pre')
    write(FILES['fs'], fs2)
    write(FILES['ft'], ft2)
    write(FILES['ap'], ap2)
    print('OK 5.1.56 patched: FileStorage.ets / FileTransfer.ets / app.json5')
    return 0


if __name__ == '__main__':
    sys.exit(main())