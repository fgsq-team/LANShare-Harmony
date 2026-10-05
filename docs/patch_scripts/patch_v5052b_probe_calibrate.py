# -*- coding: utf-8 -*-
"""
5.0.52 补丁 B：「已从相册删除」这条判定加**现场自校准**。

背景（mem：5.0.49/5.0.50 两次实测）：
  媒体 URI 是 `showAssetsCreationDialog` 给的**写授权** —— 回头去读它（stat / 读打开）
  在本平台可能**一律失败**（≠ 文件不存在），也可能**一律成功**（删了也说还在）。
  两种失真都会骗人：
    · 一律失败 + 「都失败 ⇒ 已删除」 ⇒ **每一张图**都谎报「已从相册删除」（vivi 2026-10-02 报的）；
    · 一律成功 ⇒ 删掉的图仍跳进空白相册页、无提示（vivi 2026-10-02 前一版报的）。

思路：**用刚写进去的资产当场验探针**。这一秒字节刚写成功，资产必然存在 ——
  此刻探活若判「不存在」，那就是**探针不可信**，从此不再信它的「已删除」结论
  （退回 5.0.50 的保守行为：判定不出来就照常跳相册，绝不谎报）。
  只允许「可信 → 不可信」单向翻；可信度持久化，重启不必重试。
"""
import io
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
F_IDX = ROOT + r'\entry\src\main\ets\pages\Index.ets'
F_SVC = ROOT + r'\entry\src\main\ets\service\LanService.ets'

SENTINEL = 'albumProbeOk'


def load(p):
    return io.open(p, encoding='utf-8', newline='').read()


def save(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s.replace('\r\n', '\n'))


def rep(s, old, new, tag, count=1):
    got = s.count(old)
    assert got == count, '%s: 锚点命中 %d 次（期望 %d）\n---\n%s' % (tag, got, count, old[:200])
    return s.replace(old, new, count)


idx = load(F_IDX)
svc = load(F_SVC)

if SENTINEL in svc and SENTINEL in idx:
    print('ALREADY APPLIED')
    sys.exit(0)

# ======================================================================
# LanService：可信度标志 + 持久化
# ======================================================================
ANCHOR_SVC = """  /** 载入相册索引（幂等，只会真正读一次） */
  async loadAlbumIndex(ctx: common.UIAbilityContext): Promise<void> {"""

NEW_SVC = """  /**
   * ★ 5.0.52：「相册里那份已不存在」这条判定**可不可信**。
   *
   * 媒体 URI 是 `showAssetsCreationDialog` 给的**写授权**，回头去读它（stat / 读打开）
   * 在本平台可能一律失败（≠ 文件不存在）⇒ 「两个信号都失败就判已删除」会把
   * **每一张图**都谎报成「已从相册删除」；也可能一律成功 ⇒ 删了还照常跳空白页。
   * 判定方法见 `Index.albumProbeCalibrate()`：拿**刚写进去**的资产当场试一次。
   * 一次不可信以后就不再谎报；持久化，重启也不用重试。
   */
  private albumProbeOk: boolean = true;

  probeTrusted(): boolean {
    return this.albumProbeOk;
  }

  setProbeTrusted(v: boolean): void {
    if (this.albumProbeOk === v) {
      return;
    }
    this.albumProbeOk = v;
    this.persistAlbumProbe().catch((e: Error) => {
      Log.w(TAG, `保存探针可信度失败: ${e.message}`);
    });
  }

  private async persistAlbumProbe(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);
      await store.put('albumProbe', this.albumProbeOk ? 1 : 0);
      await store.flush();
    } catch (e) {
      Log.w(TAG, '保存探针可信度失败');
    }
  }

  private async loadAlbumProbe(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);
      const raw: Object = await store.get('albumProbe', 1);
      if (typeof raw === 'number') {
        this.albumProbeOk = (raw as number) !== 0;
      }
    } catch (e) {
      Log.w(TAG, '读取探针可信度失败');
    }
  }

  /** 载入相册索引（幂等，只会真正读一次） */
  async loadAlbumIndex(ctx: common.UIAbilityContext): Promise<void> {"""
svc = rep(svc, ANCHOR_SVC, NEW_SVC, 'LanService 插入可信度标志')

svc = rep(svc,
          """      // 5.0.44：缩略图旋转角度也要恢复
      await this.loadAlbumRot(ctx);""",
          """      // 5.0.44：缩略图旋转角度也要恢复
      await this.loadAlbumRot(ctx);
      // 5.0.52：探针可信度也要恢复（不可信就别再谎报「已删除」）
      await this.loadAlbumProbe(ctx);""",
          'loadAlbumIndex 调用')

# ======================================================================
# Index：探针结论受可信度约束
# ======================================================================
OLD_VERDICT = """    const gone: boolean = codes.indexOf('stat=13900002') >= 0
      || codes.indexOf('open=13900002') >= 0;
    this.service.logAuto(`相册探活：${gone ? '已不存在' : '判定不出（按还在处理）'}`
      + `（statSize=${statSize}，信号: ${codes.join(' ')}）：${uri}`);
    return !gone;"""
NEW_VERDICT = """    const gone: boolean = codes.indexOf('stat=13900002') >= 0
      || codes.indexOf('open=13900002') >= 0;
    // ★ 5.0.52：结论还要受「探针可信度」约束 —— 见 `albumProbeCalibrate`。
    //   本机探针被证伪时，一律按「还在」处理（照常跳相册），**绝不谎报已删除**。
    const trusted: boolean = this.service.probeTrusted();
    this.service.logAuto(`相册探活：${gone ? '已不存在' : '判定不出（按还在处理）'}`
      + `（信任=${trusted ? 1 : 0}，statSize=${statSize}，信号: ${codes.join(' ')}）：${uri}`);
    return !(gone && trusted);"""
idx = rep(idx, OLD_VERDICT, NEW_VERDICT, '探针结论')

# ======================================================================
# Index：新增 albumProbeCalibrate（插在 albumAssetAlive 之后）
# ======================================================================
ANCHOR_CAL = """    return !(gone && trusted);
  }

  /**
   * 跳系统相册看这一个资产。"""
NEW_CAL = """    return !(gone && trusted);
  }

  /**
   * ★ 5.0.52：拿**刚写进相册的资产**当场校准「探活」可信度。
   *
   * 为什么需要：这一秒我们刚把字节写进去，资产**必然存在**。
   *   此刻 `albumAssetAlive(uri)` 若判「不存在」，那唯一解释就是**探针本身不可信**
   *   （媒体 URI 是写授权，读它可能一律失败）—— 从此不再采信它的「已删除」结论，
   *   否则会把**每一张图**都谎报成「已从相册删除」（vivi 2026-10-02 报的正是这个）。
   * ⚠️ 单向翻：只允许 可信 -> 不可信；绝不因为某次「说还在」就恢复 ——
   *   说还在也可能是错误兜底，不构成探针有效的证据。
   */
  private albumProbeCalibrate(uri: string): void {
    if (!this.service.probeTrusted()) {
      return;
    }
    if (this.albumAssetAlive(uri)) {
      return;
    }
    this.service.setProbeTrusted(false);
    this.service.logAuto('刚写入的相册资产被判「不存在」⇒ 本机探针不可信，已关闭「已删除」提示');
    this.toast('本机无法校验相册状态，已关闭「已删除」提示');
  }

  /**
   * 跳系统相册看这一个资产。"""
idx = rep(idx, ANCHOR_CAL, NEW_CAL, '插入校准方法')

# ======================================================================
# Index：两个保存路径各调一次校准
# ======================================================================
idx = rep(idx,
          """          if (msg.startsWith('已保存')) {
            ok += 1;
            // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反""",
          """          if (msg.startsWith('已保存')) {
            ok += 1;
            // ★ 5.0.52：拿刚写进去的资产校准探针（见 albumProbeCalibrate）
            this.albumProbeCalibrate(uris[i]);
            // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反""",
          'batch 校准调用')

idx = rep(idx,
          """      if (!msg.startsWith('已保存')) {
        return false;
      }""",
          """      if (!msg.startsWith('已保存')) {
        return false;
      }
      // ★ 5.0.52：同上 —— 手动保存也校准一次
      this.albumProbeCalibrate(uris[0]);""",
          '手动保存校准调用')

save(F_IDX, idx)
save(F_SVC, svc)
print('OK: 5.0.52b 已应用')
