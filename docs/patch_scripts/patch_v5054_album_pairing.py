# -*- coding: utf-8 -*-
"""
5.0.54（vivi 2026-10-02 反馈：多图拆成多条消息后**没有存相册弹窗**，
       退到后台再打开才弹，且「提示 4 张只成功了 2 张」）

日志证据（时间线）
  14:53:42  [相册] 准备弹存相册确认框：1 个文件      ← 第 1 张（screenshot_..._com.fgsqw.lanshare.jpg）
            …… 之后**再也没有** `确认框返回` 这一行   ← ★ Bug A：Promise 永不 settle
  14:54:10  [相册] 待存队列共 4 项 / 入队 3 条         ← 新收 3 张，但**一次弹窗都没有**
            （没有「准备弹」—— 闸门 autoSaveBusy 还被 14:53:42 那次钉着）
  14:55:31  [相册] 自动存相册疑似卡死 108642ms，强制复位重试   ← 45 秒看门狗终于生效
  14:55:31  [相册] 准备弹存相册确认框：4 个文件
  14:55:34  [相册] 确认框返回 2 个 URI（提交 4 个）   ← ★ Bug B：4 提交只回 2

── Bug A：`showAssetsCreationDialog` 会**永不返回** ──
  108 秒里闸门一直关着。只靠「45 秒看门狗 + 恰好有 UI 刷新」才恢复，
  用户把应用切后台再切回来触发了 refreshReceived 才转起来。
  修：① 给弹窗套 **20 秒超时**（超时按「本次失败、留队重试」，不当作取消）；
     ② 加**自驱定时重试**，不再依赖 UI 刷新；
     ③ 连续 3 次无响应就停止自动重试并提示用户手动存。

── Bug B：返回数量 < 提交数量时**按位置硬配** → 内容错位 + 原图被误删 ──
  提交顺序： [0]screenshot_…_com.fgsqw.lanshare  [1]IMG_20260929_201626
             [2]扫描全能王 2026-09-22 22.33      [3]IMG_20260907_092804
  回来的 2 个恰好是 **title 不带点**的那两个（[1] 和 [3]）。
  ⚠️ 旧 `safeAlbumTitle` 的非法字符表 `\\/:*?"'`<>|{}[]` **漏了 `.`** ——
     而 `title` 是「不含后缀的文件名」，带点就建不出资产。
  ⇒ 4 个挂了 2 个 = 两个 title 带点的，**逐个对得上**。
  更要命的是旧代码 `n = min(uris.length, paths.length)` 后**按位置配对**：
  `uris[0]`（实为 [1] 的资产）被写进 `paths[0]` 的字节、`uris[1]`（[3] 的）写进 `paths[1]`
  ⇒ 相册里两张内容**全错位**，而且 `paths[0]`/`paths[1]` 的**沙箱副本被当成"成功"删掉了**
  ⇒ **原图直接丢失**（paths[0] 是那张 screenshot）。
  修：① `safeAlbumTitle` 把 `.` 一并换掉；② 批内 title 去重；
     ③ **数量不符时一律不写、不删**，改「逐张提交」重试（每次只交 1 个 ⇒ 结果无歧义）。

幂等：哨兵 `autoSaveSingleShot`。写文件保持 LF。
"""
import io, sys

IX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
AJ = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'

SENTINEL = 'autoSaveSingleShot'

# ================================================================= 1. 成员变量
M_OLD = """  /** 5.0.50：`autoSaveBusy` 置位的时刻 —— 用于「卡死看门狗」（见 flushAutoSave） */
  private autoSaveBusySince: number = 0;
"""
M_NEW = """  /** 5.0.50：`autoSaveBusy` 置位的时刻 —— 用于「卡死看门狗」（见 flushAutoSave） */
  private autoSaveBusySince: number = 0;
  /**
   * ★ 5.0.54：确认框**返回数量 ≠ 提交数量**时翻成 true —— 之后一律「逐张提交」。
   *
   * ⚠️ 为什么必须这样：系统返回的 URI 数组只按「它接受的那几个」给出，
   *   既不告诉你跳过了哪些、也不保证位置能对上。真机 4 提交只回 2 个，
   *   旧代码按位置硬配 ⇒ 相册内容错位 + 沙箱原图被误删（见 autoSaveAlbumBatch 注释）。
   *   逐张提交时每次只交 1 个，返回只可能是 0 或 1 —— **没有歧义**。
   */
  private autoSaveSingleShot: boolean = false;
  /** ★ 5.0.54：连续「确认框无响应」次数；到 3 次停止自动重试，只提示用户手动存 */
  private autoSaveDialogFails: number = 0;
  /** ★ 5.0.54：自驱重试的定时器句柄（-1 = 没有） */
  private autoSaveTimer: number = -1;
"""

# ================================================================= 2. watchdog
W_OLD = """    // 5.0.50：**卡死看门狗**。正常一次「弹框 + 拷贝」几秒内结束；
    //   超过 45 秒还挂在 busy 上，说明某一步（弹框 / 解码）没回来。
    //   强制复位再试一次 —— 绝不接受「收图后再也不弹」这种永久失效。
    if (this.autoSaveBusy && this.autoSaveBusySince > 0
      && Date.now() - this.autoSaveBusySince > 45000) {"""
W_NEW = """    // 5.0.50：**卡死看门狗**（第二道防线）。
    // ★ 5.0.54：第一道防线改成 `awaitDialog` 的 20 秒超时了 —— 弹窗不会再
    //   无限制挂住。这里放宽到 60 秒，只兜「超时机制本身也没生效」的极端情况；
    //   放宽是为了避免在**正常的长拷贝**中途复位闸门、把同一批弹第二遍。
    //   （真机 2026-10-02：45 秒档曾让闸门被钉死 108 秒，期间新到 3 张图一次弹窗都没有。）
    if (this.autoSaveBusy && this.autoSaveBusySince > 0
      && Date.now() - this.autoSaveBusySince > 60000) {"""

# ================================================================= 3. 核心：弹窗与配对
C_OLD = """      const srcUris: string[] = [];
      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];
      for (let i: number = 0; i < paths.length; i++) {
        const name: string = Index.baseName(paths[i]);
        const dot: number = name.lastIndexOf('.');
        const isVideo: boolean = this.isVideoName(name);
        const cfg: photoAccessHelper.PhotoCreationConfig = {
          title: Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name),
          fileNameExtension: dot > 0 ? name.substring(dot + 1).toLowerCase()
            : (isVideo ? 'mp4' : 'jpg'),
          photoType: isVideo ? photoAccessHelper.PhotoType.VIDEO
            : photoAccessHelper.PhotoType.IMAGE
        };
        cfgs.push(cfg);
        srcUris.push(this.imageUri(paths[i]));
      }
      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);
      this.service.logAuto(`确认框返回 ${uris.length} 个 URI（提交 ${srcUris.length} 个）`);
      if (uris.length === 0) {
        // 用户在确认框上点了取消 —— 系统返回空数组，不是错误
        this.toast('已跳过存入相册');
        cancelled = true;
        return;
      }
      this.toast(`正在存入相册（${uris.length} 个）…`);
      await Index.yieldOnce();
      const n: number = uris.length < paths.length ? uris.length : paths.length;
      let ok: number = 0;
      for (let i: number = 0; i < n; i++) {
        // 5.0.47：单文件失败（copyTo/cacheThumb 抛异常）不再中断整批 ——
        //   之前一张图抛异常，后面的图片全部不处理、也不删沙箱副本。
        try {
          const msg: string = ExportService.copyTo(paths[i], uris[i], Index.baseName(paths[i]));
          if (msg.startsWith('已保存')) {
            ok += 1;
            // ★ 5.0.52：拿刚写进去的资产校准探针（见 albumProbeCalibrate）
            this.albumProbeCalibrate(uris[i]);
            // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
            const thumb: string = await this.cacheThumb(ctx, paths[i], keys[i]);
            const rot: number = this.service.rotOf(thumb) ?? 0;
            await this.service.setAlbumIndex(keys[i], uris[i], thumb, rot);
            const derr: string | null =
              ExportService.deleteFile(this.service.receiveRoot, paths[i]);
            if (derr !== null) {
              Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${paths[i]}`);
            }
          }
        } catch (x) {
          const xe: BusinessError = x as BusinessError;
          Log.w(TAG, `单文件存相册失败: ${paths[i]} ${xe.code} ${xe.message}`);
        }
      }
      this.toast(ok > 0 ? `已存入相册 ${ok} 个` : '存入相册失败');
      Log.i(TAG, `自动存相册：${ok}/${n}`);"""

C_NEW = """      // ---- 准备 title / 后缀 / 类型（与源 URI 一一对应）----
      const srcUris: string[] = [];
      const rawTitles: string[] = [];
      const exts: string[] = [];
      const vids: boolean[] = [];
      for (let i: number = 0; i < paths.length; i++) {
        const name: string = Index.baseName(paths[i]);
        const dot: number = name.lastIndexOf('.');
        const isVideo: boolean = this.isVideoName(name);
        srcUris.push(this.imageUri(paths[i]));
        rawTitles.push(Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name));
        exts.push(dot > 0 ? name.substring(dot + 1).toLowerCase() : (isVideo ? 'mp4' : 'jpg'));
        vids.push(isVideo);
      }
      // ★ 5.0.54：批内 title 去重 —— 系统对同名同后缀会少建资产（见 uniqueAlbumTitles）
      const titles: string[] = Index.uniqueAlbumTitles(rawTitles);
      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];
      for (let i: number = 0; i < paths.length; i++) {
        const cfg: photoAccessHelper.PhotoCreationConfig = {
          title: titles[i],
          fileNameExtension: exts[i],
          photoType: vids[i] ? photoAccessHelper.PhotoType.VIDEO
            : photoAccessHelper.PhotoType.IMAGE
        };
        cfgs.push(cfg);
      }
      this.service.logAuto(`存相册提交 ${paths.length} 项，title：${titles.join(' | ')}`);

      // ---- 拿 URI：得到的是**确定能配对**的 (paths 下标, 相册 URI) ----
      const idxs: number[] = [];
      const gotUris: string[] = [];
      if (this.autoSaveSingleShot) {
        // ★ 5.0.54：逐张模式 —— 每次只提交 1 个，返回只可能是 0 或 1，**无歧义**
        for (let i: number = 0; i < paths.length; i++) {
          let one: string[] = [];
          try {
            one = await Index.awaitDialog(helper, [srcUris[i]], [cfgs[i]]);
          } catch (de) {
            this.service.logAuto(`逐张存相册：第 ${i + 1}/${paths.length} 项确认框无响应，跳过`);
            continue;
          }
          if (one.length === 1) {
            idxs.push(i);
            gotUris.push(one[0]);
          } else {
            this.service.logAuto(`逐张存相册：第 ${i + 1}/${paths.length} 项未获得 URI`
              + `（提交 1 个返回 ${one.length} 个），跳过`);
          }
        }
        this.service.logAuto(`逐张提交完成：${gotUris.length}/${paths.length} 项拿到 URI`);
      } else {
        let uris: string[] = [];
        let timedOut: boolean = false;
        try {
          uris = await Index.awaitDialog(helper, srcUris, cfgs);
        } catch (de) {
          timedOut = true;
        }
        if (timedOut) {
          // ★ 5.0.54 —— 修「没有弹窗 + 闸门卡死 108 秒」
          this.autoSaveDialogFails += 1;
          this.service.logAuto(`存相册确认框 ${Index.DIALOG_TIMEOUT_MS / 1000} 秒无响应`
            + `（第 ${this.autoSaveDialogFails} 次），本次放弃；文件留在沙箱，稍后自动重试`);
          if (this.autoSaveDialogFails >= 3) {
            if (this.autoSaveTimer >= 0) {
              clearTimeout(this.autoSaveTimer);
              this.autoSaveTimer = -1;
            }
            this.service.logAuto('自动存相册连续 3 次无响应，停止自动重试'
              + '（文件仍留在沙箱，可长按图片手动存相册）');
            this.toast('自动存相册无响应，已停止重试；可长按图片手动保存');
          } else {
            this.scheduleAutoSaveRetry(3000);
          }
          failed = true;
          return;
        }
        this.service.logAuto(`确认框返回 ${uris.length} 个 URI（提交 ${srcUris.length} 个）`);
        if (uris.length === 0) {
          // 用户在确认框上点了取消 —— 系统返回空数组，不是错误
          this.autoSaveDialogFails = 0;
          this.toast('已跳过存入相册');
          cancelled = true;
          return;
        }
        this.autoSaveDialogFails = 0;
        if (uris.length !== paths.length) {
          // ★★ 5.0.54 —— 修「4 张只成功 2 张」以及它背后的**内容错位 + 原图误删**。
          //   数量不符时**绝不能按位置配对**：返回的 URI 只对应系统接受的那几项，
          //   位置对不上。真机：提交 [screenshot, IMG_0929, 扫描全能王, IMG_0907]，
          //   回来的是 title 不带点的 [IMG_0929, IMG_0907]，旧代码却把
          //   paths[0]、paths[1] 写进它们 ⇒ 相册内容全错位，且 paths[0]/paths[1]
          //   的沙箱副本被当成"成功"删掉 ⇒ 原图丢失。
          //   现在：本次**不写任何字节、不删任何文件**，翻成逐张模式重试。
          for (let i: number = 0; i < uris.length; i++) {
            this.service.logAuto(`  返回 URI[${i}]：${Index.baseName(uris[i])}`);
          }
          this.autoSaveSingleShot = true;
          this.service.logAuto(`⚠️ 返回数量 ${uris.length} ≠ 提交数量 ${paths.length}，`
            + `无法确定对应关系 ⇒ 本次不写入（避免内容错位/误删），下一轮改「逐张提交」`);
          failed = true;
          return;
        }
        // 数量一致 ⇒ 按提交顺序一一对应（系统对该顺序有约定）
        for (let i: number = 0; i < uris.length; i++) {
          idxs.push(i);
          gotUris.push(uris[i]);
        }
      }
      if (gotUris.length === 0) {
        this.service.logAuto('未能获得任何相册 URI，文件留在沙箱，稍后重试');
        failed = true;
        return;
      }
      this.toast(`正在存入相册（${gotUris.length} 个）…`);
      await Index.yieldOnce();
      let ok: number = 0;
      const missed: string[] = [];
      for (let j: number = 0; j < gotUris.length; j++) {
        const i: number = idxs[j];
        // 5.0.47：单文件失败（copyTo/cacheThumb 抛异常）不再中断整批
        try {
          const msg: string = ExportService.copyTo(paths[i], gotUris[j], Index.baseName(paths[i]));
          if (!msg.startsWith('已保存')) {
            missed.push(Index.baseName(paths[i]));
            continue;
          }
          ok += 1;
          // ★ 5.0.52：拿刚写进去的资产校准探针（见 albumProbeCalibrate）
          this.albumProbeCalibrate(gotUris[j]);
          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反
          const thumb: string = await this.cacheThumb(ctx, paths[i], keys[i]);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(keys[i], gotUris[j], thumb, rot);
          const derr: string | null =
            ExportService.deleteFile(this.service.receiveRoot, paths[i]);
          if (derr !== null) {
            Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${paths[i]}`);
          }
        } catch (x) {
          const xe: BusinessError = x as BusinessError;
          missed.push(Index.baseName(paths[i]));
          Log.w(TAG, `单文件存相册失败: ${paths[i]} ${xe.code} ${xe.message}`);
        }
      }
      // ★ 5.0.54：把「没存进去的那些」如实报出来 —— 它们仍在沙箱里，可长按手动存。
      const extra: string = missed.length > 0
        ? `，${missed.length} 个未成功（文件仍在沙箱，可长按手动保存）` : '';
      this.toast(ok > 0 ? `已存入相册 ${ok} 个${extra}` : '存入相册失败');
      this.service.logAuto(`自动存相册完成：成功 ${ok}/${paths.length}`
        + (missed.length > 0 ? `，未成功：${missed.join('、')}` : ''));
      Log.i(TAG, `自动存相册：${ok}/${paths.length}`);"""

# ================================================================= 4. 新方法
D_OLD = """      this.autoSavePending = rest;
      this.albumIndex = this.service.albumSnapshot();
      this.refreshReceived();
    }
  }"""
D_NEW = """      this.autoSavePending = rest;
      this.albumIndex = this.service.albumSnapshot();
      this.refreshReceived();
    }
  }

  /**
   * ★ 5.0.54：带**超时**的 `showAssetsCreationDialog`。
   *
   * ⚠️ 为什么必须包一层：真机上它**出现过永不 settle** ——
   *   vivi 2026-10-02 的日志里，14:53:42 提交后一句 `确认框返回` 都没有，
   *   直到 14:55:31 才被 45 秒看门狗强行复位（实际钉了 108642ms）；
   *   这期间 14:54:10 收到的 3 张图**一次弹窗都没有**（闸门还关着）。
   *   超时按「本次失败」处理（**不当作取消**）：文件留在沙箱、下一轮重试，
   *   绝不让一个不返回的 Promise 把整条自动存相册链路锁死。
   */
  private static DIALOG_TIMEOUT_MS: number = 20000;

  private static awaitDialog(helper: photoAccessHelper.PhotoAccessHelper,
                             srcUris: string[],
                             cfgs: photoAccessHelper.PhotoCreationConfig[]): Promise<string[]> {
    return new Promise<string[]>((resolve: (v: string[]) => void,
                                 reject: (e: Error) => void) => {
      let settled: boolean = false;
      const timer: number = setTimeout(() => {
        if (!settled) {
          settled = true;
          reject(new Error('showAssetsCreationDialog 超时未返回'));
        }
      }, Index.DIALOG_TIMEOUT_MS);
      helper.showAssetsCreationDialog(srcUris, cfgs).then((u: string[]) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        resolve(u);
      }).catch((e: Object) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        reject(e as Error);
      });
    });
  }

  /**
   * ★ 5.0.54：不依赖 UI 刷新的**自驱重试**。
   *
   * ⚠️ 为什么需要：`flushAutoSave` 只在「消息变化 / 文件列表刷新」时被调用。
   *   真机 14:53:42 那次确认框不返回之后，直到用户把应用切后台再切回来
   *   （触发 refreshReceived）才恢复 —— 中间 108 秒完全静默。
   *   有了它，超时后 3 秒自己再试一次。
   */
  private scheduleAutoSaveRetry(delayMs: number): void {
    if (this.autoSaveTimer >= 0) {
      clearTimeout(this.autoSaveTimer);
    }
    this.autoSaveTimer = setTimeout(() => {
      this.autoSaveTimer = -1;
      if (this.autoSaveBusy || this.autoSavePending.length === 0) {
        return;
      }
      this.service.logAuto(`定时重试存相册（队列 ${this.autoSavePending.length} 项）`);
      this.flushAutoSave();
    }, delayMs);
  }"""

# ================================================================= 5. 外层 catch 也自驱重试
E_OLD = """      const err: BusinessError = e as BusinessError;
      this.service.logAuto(`自动存相册批处理异常：${err.code} ${err.message}`);"""
E_NEW = """      const err: BusinessError = e as BusinessError;
      this.service.logAuto(`自动存相册批处理异常：${err.code} ${err.message}`);
      // ★ 5.0.54：失败也自己排一次重试，不等 UI 刷新来救
      this.scheduleAutoSaveRetry(3000);"""

# ================================================================= 6. safeAlbumTitle
T_OLD = """  /** 把文件名压成系统允许的相册 title（非法字符统一换成下划线） */
  private static safeAlbumTitle(raw: string): string {
    const bad: string = '\\\\/:*?"\\'`<>|{}[]';
    let out: string = '';
    for (let i = 0; i < raw.length; i++) {
      const c: string = raw.substring(i, i + 1);
      out += bad.indexOf(c) >= 0 ? '_' : c;
    }
    if (out.length === 0) {
      out = 'image';
    }
    if (out.length > 200) {
      out = out.substring(0, 200);
    }
    return out;
  }"""

T_NEW = """  /**
   * 把文件名压成系统允许的相册 title（非法字符统一换成下划线）。
   *
   * ★★ 5.0.54：**`title` 里绝不能带 `.`** —— 它的语义是「不含后缀的文件名」，
   *   带点的 title 会让系统**建不出资产**。真机证据（vivi 2026-10-02）：
   *   一次提交 4 个只回来 2 个 URI，而挂掉的恰好就是两个 title 带点的
   *   （`screenshot_..._com.fgsqw.lanshare`、`扫描全能王 2026-09-22 22.33`），
   *   另两个不带点的正常 —— 4 个里挂 2 个，与「4 张只成功 2 张」**逐个对上**。
   *   旧实现的非法字符表漏了点，只换 `\\/:*?"'`<>|{}[]`。
   */
  private static safeAlbumTitle(raw: string): string {
    const bad: string = '\\\\/:*?"\\'`<>|{}[].';
    let out: string = '';
    for (let i = 0; i < raw.length; i++) {
      const c: string = raw.substring(i, i + 1);
      out += bad.indexOf(c) >= 0 ? '_' : c;
    }
    if (out.length === 0) {
      out = 'image';
    }
    if (out.length > 200) {
      out = out.substring(0, 200);
    }
    return out;
  }

  /**
   * ★ 5.0.54：把一批 title 去重（第 2 个起追加 `_2`、`_3`…）。
   *
   * ⚠️ 系统对**同名同后缀**的多个资产会少建 —— 一批里出现两个 `IMG_0001`
   *   （对端真发了两张同名图，或截断到 200 字后重名）时，就会重演
   *   「提交 N 个只回来 M 个」的错位。去重是零成本的防御。
   */
  private static uniqueAlbumTitles(raw: string[]): string[] {
    const out: string[] = [];
    const seen: Map<string, number> = new Map<string, number>();
    for (let i: number = 0; i < raw.length; i++) {
      const t: string = raw[i];
      const n: number = seen.get(t) ?? 0;
      seen.set(t, n + 1);
      out.push(n === 0 ? t : `${t}_${n + 1}`);
    }
    return out;
  }"""

# ================================================================= 8. 手动存相册也要超时
S_OLD = """      const uris: string[] = await helper.showAssetsCreationDialog([this.imageUri(path)], [cfg]);
"""
S_NEW = """      // ★ 5.0.54：手动保存同样套超时 —— 长按存相册走的是同一个系统接口，
      //   真机上它有永不返回的实例（见 awaitDialog 注释），裸 await 会把
      //   「长按保存」也变成永久无响应。
      let uris: string[] = [];
      try {
        uris = await Index.awaitDialog(helper, [this.imageUri(path)], [cfg]);
      } catch (de) {
        this.service.logAuto(`手动存相册：确认框 ${Index.DIALOG_TIMEOUT_MS / 1000} 秒无响应`);
        this.toast('存相册确认框无响应，请重试');
        return false;
      }
"""

# ================================================================= 9. 版本号
AJ_OLD = """    "versionCode": 5000053,
    "versionName": "5.0.53",
"""
AJ_NEW = """    "versionCode": 5000054,
    "versionName": "5.0.54",
"""


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        assert s.count(old) == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, s.count(old))
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src = io.open(IX, encoding='utf-8', newline='').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)

new_ix = apply(IX, [(M_OLD, M_NEW), (W_OLD, W_NEW), (C_OLD, C_NEW),
                    (D_OLD, D_NEW), (E_OLD, E_NEW), (T_OLD, T_NEW), (S_OLD, S_NEW)], 'Index')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

# ---- 三道保险：关键字残留 / 新符号齐备 / 旧模式清零 ----
assert 'const uris: string[] = await helper.showAssetsCreationDialog(' not in new_ix, '旧直连弹窗仍在'
assert new_ix.count('helper.showAssetsCreationDialog(') == 1, \
  '直连调用应只剩 awaitDialog 内那一处，实为 %d' % new_ix.count('helper.showAssetsCreationDialog(')
assert 'uris.length < paths.length ? uris.length : paths.length' not in new_ix, '旧硬配仍在'
for sym, want in [('private autoSaveSingleShot: boolean = false;', 1),
                  ('private autoSaveDialogFails: number = 0;', 1),
                  ('private autoSaveTimer: number = -1;', 1),
                  ('private static DIALOG_TIMEOUT_MS: number = 20000;', 1),
                  ('private static awaitDialog(', 1),
                  ('Index.awaitDialog(helper', 3),
                  ('private scheduleAutoSaveRetry(', 1),
                  ('this.scheduleAutoSaveRetry(', 2),
                  ('private static uniqueAlbumTitles(', 1),
                  ('Index.uniqueAlbumTitles(rawTitles)', 1),
                  ("const bad: string = '\\\\/:*?\"\\'`<>|{}[].';", 1),
                  ('Date.now() - this.autoSaveBusySince > 60000) {', 1),
                  ('自动存相册连续 3 次无响应', 1),
                  ('无法确定对应关系', 1),
                  ('逐张存相册：第 ', 2)]:
    got = new_ix.count(sym)
    assert got == want, '符号校验失败 %r: 期望 %d 实为 %d' % (sym, want, got)
    print('  OK %2d  %s' % (got, sym[:60]))
assert '5000054' in new_aj and '"5.0.54"' in new_aj

# ---- 括号增量 ----
for tag, before, after in [('Index', src, new_ix),
                           ('app.json5', io.open(AJ, encoding='utf-8', newline='').read(), new_aj)]:
    delta = {}
    for ch in '{}()[]':
        delta[ch] = after.count(ch) - before.count(ch)
    print('%s 括号增量: %s' % (tag, delta))

io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.54 已应用')
