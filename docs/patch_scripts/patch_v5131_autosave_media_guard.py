# -*- coding: utf-8 -*-
"""
5.1.31 —— 修「网页上传 .apk 完成后闪退」：入队相册漏判「是不是媒体」

## 真机证据（2026-10-03 13:44，5.1.30）
  [13:44:05] 网页上传完成：launchermap_3.9.151-20260925-02.apk（645.9 MB）  <- 传输成功
  [13:44:05] [相册] 新消息 0 -> 1，自动存相册开关=true
  [13:44:05] [相册] 入队待存相册：「launchermap_...apk」(id=c1-1791006245866)
  [13:44:05] [相册] 待存队列共 1 项
  [13:44:05] [相册] 队列 1 项暂未解析出沙箱路径（等文件落盘后再试）          <- 末条，随后进程消失
  ⇒ **传输成功后的「自动存相册」流程把进程拖死**，与传输/协议无关。

## 根因：「是不是媒体」这一维判据缺失
  `autoSaveNewMedia()` 的入队条件只判了「收进来的文件」：
      if (!m.incoming || m.kind !== 'file') { continue; }
  没有判「它是不是图片/视频」⇒ **.apk 也被入队**。
  之后 `flushAutoSave()` 用 `mediaNamesOf(m)` 解析媒体名，而它对 apk 返回**空数组**
  ⇒ 永远解析不出路径 ⇒ 每轮刷新都走 `noteAutoSaveWaiting()` 重试
  ⇒ 无限轮询（`flushAutoSave -> logAuto -> emit -> onSnapshot -> refreshReceived
     -> flushAutoSave`）把主线程/事件循环拖死。
  ★ 这不是新问题：LanService.ets:353-365 早就记录过同一条链路的同步重入
    （5.0.51 修过「同一秒刷 200 条日志」）；当时只加了 emit 重入保护，
    **没堵住「非媒体被入队」这个源头**，所以重入被压住后变成了「慢性拖死」。

## 修法：入队时补上「是否媒体」判据（与 UI 同一真源）
  复用页面已有的 `isMediaName()`（委托 `LanService.isMediaFileName`，唯一真源）。
  ⇒ 非媒体（apk/zip/pdf…）根本不进相册队列，重试链从源头消失。
  用 `mediaNamesOf(m).length === 0` 判定，与「解析路径」用的是同一个函数
  ⇒ **入队判据与消费判据对齐**，不会再出现「入了队却永远解析不出」。

## 幂等
  sentinel = `AUTOSAVE_MEDIA_GUARD`
"""
import io
import sys
import os
import shutil

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')
BAK = os.path.join(ROOT, 'docs', 'backups')

SENTINEL = 'AUTOSAVE_MEDIA_GUARD'

src = io.open(IDX, encoding='utf-8').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)


def check(s, old, new, tag):
    co = s.count(old)
    cn = s.count(new)
    if co != 1:
        raise AssertionError('%s: old 出现 %d 次（应为 1）' % (tag, co))
    if cn != 0:
        raise AssertionError('%s: new 已存在 %d 次（应为 0）' % (tag, cn))


# ---------------------------------------------------------------- 入队补媒体判据
OLD_1 = """      if (!m.incoming || m.kind !== 'file') {
        continue;
      }
      // 60 秒新鲜度：挡掉「启动恢复历史聊天」那一茬条数跳变
      if (now - m.timeMs > 60000) {
        continue;
      }"""
NEW_1 = """      if (!m.incoming || m.kind !== 'file') {
        continue;
      }
      // ★★ 5.1.31：AUTOSAVE_MEDIA_GUARD —— **必须判「是不是媒体」**。
      //
      // 【真机事故】网页上传 .apk（645.9MB）传完后进程闪退。日志：
      //   网页上传完成 -> 入队待存相册：「launchermap_...apk」
      //   -> 队列 1 项暂未解析出沙箱路径（等文件落盘后再试）  <- 末条
      //   根因：这里只判了 kind，没判媒体 ⇒ **apk 也入队**；
      //   而消费侧 `mediaNamesOf(m)` 对 apk 返回空数组 ⇒ 永远解析不出路径
      //   ⇒ 每轮刷新都重试（flushAutoSave -> logAuto -> emit -> onSnapshot
      //      -> refreshReceived -> flushAutoSave）⇒ 无限轮询拖死进程。
      //   ⚠️ LanService.ets:353 记录过同一条链路的同步重入（5.0.51 修过
      //      「同一秒刷 200 条」），但当时没堵住「非媒体入队」这个源头。
      //
      // 【判据对齐】用 `mediaNamesOf(m).length === 0` 而不是另写一套后缀判断：
      //   入队判据与消费判据**必须同一个函数**，否则又会出现
      //   「入了队却永远解析不出来」。
      if (this.mediaNamesOf(m).length === 0) {
        continue;
      }
      // 60 秒新鲜度：挡掉「启动恢复历史聊天」那一茬条数跳变
      if (now - m.timeMs > 60000) {
        continue;
      }"""
check(src, OLD_1, NEW_1, '入队判据')

# ---------------------------------------------------------------- 版本号
OLD_2 = '"versionCode": 5000130'
NEW_2 = '"versionCode": 5000131'
app_src = io.open(APP, encoding='utf-8').read()
check(app_src, OLD_2, NEW_2, 'versionCode')

OLD_3 = '"versionName": "5.1.30"'
NEW_3 = '"versionName": "5.1.31"'
check(app_src, OLD_3, NEW_3, 'versionName')

# ---------------------------------------------------------------- 备份 + 落盘
if not os.path.isdir(BAK):
    os.makedirs(BAK)
shutil.copyfile(IDX, os.path.join(BAK, 'Index.ets.v5131pre'))
shutil.copyfile(APP, os.path.join(BAK, 'app.json5.v5131pre'))

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(src.replace(OLD_1, NEW_1))
io.open(APP, 'w', encoding='utf-8', newline='\n').write(
    app_src.replace(OLD_2, NEW_2).replace(OLD_3, NEW_3))

# ---------------------------------------------------------------- 复核
chk = io.open(IDX, encoding='utf-8').read()
assert 'AUTOSAVE_MEDIA_GUARD' in chk, '守护未写入'
assert chk.count('this.mediaNamesOf(m).length === 0') >= 1, '判据未写入'
assert io.open(APP, encoding='utf-8').read().count('5000131') == 1, 'versionCode 未更新'
print('OK 5.1.31 applied')
