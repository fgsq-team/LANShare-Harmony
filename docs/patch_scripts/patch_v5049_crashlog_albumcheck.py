# -*- coding: utf-8 -*-
"""
5.0.49 补丁
===========
两个目标：

A. 「接收图片（单张/多张都）概率性闪退 + 重启后日志全没了」—— 两件事一起做：
   1. **日志落盘**：`pushLog` 每行同步写 `filesDir/ui_log.txt`（句柄常开）；
      启动时根据 `run.lock` 判断上次是否异常退出，是就把上一次的日志尾巴
      挂到日志列表最前面 —— 用户点一次「复制日志」就能把崩溃现场完整带走。
   2. **未捕获异常捕获**：EntryAbility 注册 `errorManager.on('error')`，
      栈直接写进同一个日志文件。
   3. **修真实的崩溃源**：`index.ImageSource.release()` 返回的是 **Promise**，
      代码里三处 `try { src.release(); } catch {}` **catch 不到**异步 rejection
      （未处理的 Promise 异常在 ArkTS 上会终止应用）—— 这三处正是 5.0.48
      自动存相册打通后才被高频走过的路径。全部改 `await`。
   4. `cacheThumb` 单飞（同一 id 不并发解码）+ ImageSource 进 finally 释放
      + `pendingRot` 由实例字段改局部（并发时会串台）+ 极端尺寸保护。

B. 「在系统相册里删掉那张图后，再点气泡跳过去是空白、也没有提示」——
   跳转前用「写打开」探一下该资产还在不在（写授权一定有，只有真没了才失败），
   不在就给 toast 并把失效 URI 摘掉（自愈：下次点击走补存流程）。

幂等：哨兵 `5.0.49`。
"""
import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
SENTINEL = '5.0.49：日志落盘'

F_IDX = os.path.join(ROOT, 'entry/src/main/ets/pages/Index.ets')
F_SVC = os.path.join(ROOT, 'entry/src/main/ets/service/LanService.ets')
F_ABI = os.path.join(ROOT, 'entry/src/main/ets/entryability/EntryAbility.ets')
F_APP = os.path.join(ROOT, 'AppScope/app.json5')


def read(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read().replace('\r\n', '\n')


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)


# ======================================================================
# LanService.ets
# ======================================================================
SVC_FIELDS_OLD = """  private snapshot: ServiceSnapshot = new ServiceSnapshot();
  private listeners: Array<(s: ServiceSnapshot) => void> = [];
  private logRing: string[] = [];
"""
SVC_FIELDS_NEW = """  private snapshot: ServiceSnapshot = new ServiceSnapshot();
  private listeners: Array<(s: ServiceSnapshot) => void> = [];
  private logRing: string[] = [];
  // ---------------- 5.0.49：日志落盘（闪退取证） ----------------
  // 背景：vivi 真机「接收图片有概率闪退，重新打开后日志就消失了」——
  //       logRing 只在内存里，进程一崩证据就全没了，只能靠猜。
  /** 本次会话的日志文件（应用沙箱内），崩溃后依然留在磁盘上 */
  private logFile: string = '';
  /** 常开的追加写句柄；-1 = 还没初始化（此期间只进内存环形缓冲） */
  private logFd: number = -1;
  /** 已写入字节数，用于超限轮转 */
  private logBytes: number = 0;
  /** `run.lock`：启动时写、正常退出时删。下次启动还在 => 上次是崩的 */
  private lockFile: string = '';
  /** 上一次会话异常退出时保留下来的「崩溃前最后若干行」 */
  private crashTail: string[] = [];
  /** 上一次会话是否异常退出（UI 用来提示用户去复制日志） */
  prevCrashed: boolean = false;
"""

SVC_EMIT_OLD = """    this.snapshot.chat = this.chatRing;
    this.snapshot.logLines = this.logRing;
"""
SVC_EMIT_NEW = """    this.snapshot.chat = this.chatRing;
    // 5.0.49：上次异常退出的日志尾巴排在最前面 ——
    //         「复制日志」一次就能把崩溃现场带走（真机没有 hdc，这是唯一通路）。
    this.snapshot.logLines = this.crashTail.length > 0
      ? this.crashTail.concat(this.logRing) : this.logRing;
"""

SVC_PUSHLOG_OLD = """  private pushLog(line: string): void {
    const ts: string = new Date().toTimeString().substring(0, 8);
    this.logRing.push(`[${ts}] ${line}`);
    if (this.logRing.length > 200) {
      this.logRing.shift();
    }
  }
"""
SVC_PUSHLOG_NEW = r"""  private pushLog(line: string): void {
    const ts: string = new Date().toTimeString().substring(0, 8);
    const row: string = `[${ts}] ${line}`;
    this.logRing.push(row);
    if (this.logRing.length > 200) {
      this.logRing.shift();
    }
    // 5.0.49：每行**同步落盘**。闪退是进程直接消失，内存里的日志一条都留不下；
    //         只有已经 write 出去的还在 page cache 里，重启后能读回来。
    this.appendLogFile(row);
  }

  /**
   * 5.0.49：把一行日志追加到沙箱内的日志文件。
   *
   * ⚠️ 为什么必须落盘：vivi 真机反馈「接收图片有概率闪退，重新打开后日志就消失了」
   *    —— `logRing` 只在内存里，进程一崩就全没了，等于**没有任何证据**。
   *    现在句柄常开、每行一次 writeSync（纯 syscall，微秒级，不拖慢传输），
   *    崩溃时至少能保住最后一段。
   * ⚠️ 超过 512KB 轮转一次（旧内容挪到 `.1`），避免无限增长。
   */
  private appendLogFile(row: string): void {
    if (this.logFd < 0) {
      return;   // 还没 initLogFile（启动早期）—— 这些行走内存，稍后由 initLogFile 回灌
    }
    try {
      if (this.logBytes > 512 * 1024) {
        this.rotateLogFile();
      }
      fileIo.writeSync(this.logFd, `${row}\n`);
      this.logBytes += row.length + 1;
    } catch (e) {
      // 日志写不进去绝不能影响业务
    }
  }

  /** 日志轮转：当前文件留档成 `.1`，重开一个空的 */
  private rotateLogFile(): void {
    try {
      fileIo.closeSync(this.logFd);
    } catch (e) {
      // 忽略
    }
    this.logFd = -1;
    this.logBytes = 0;
    try {
      fileIo.unlinkSync(`${this.logFile}.1`);
    } catch (e) {
      // 还没有旧的备份
    }
    try {
      fileIo.copyFileSync(this.logFile, `${this.logFile}.1`);
    } catch (e) {
      // 复制失败就算了，下面直接清空重开
    }
    try {
      const f: fileIo.File = fileIo.openSync(this.logFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC | fileIo.OpenMode.WRITE_ONLY);
      this.logFd = f.fd;
    } catch (e) {
      this.logFd = -1;
    }
  }

  /**
   * 5.0.49：初始化日志文件，并判断上一次会话是不是**异常退出**（闪退）。
   *
   * 判据是一个 `run.lock`：启动时写、`onDestroy`（正常退出）时删。
   * 下次启动如果它还在，说明上次是被崩掉的 —— 这时把日志文件里最后 150 行
   * 读出来当「崩溃现场」，挂在日志列表最前面，
   * 用户点一次「复制日志」就能把现场完整发出来。
   */
  initLogFile(ctx: common.UIAbilityContext): void {
    if (this.logFd >= 0) {
      return;   // 幂等：重复调用直接返回
    }
    this.logFile = `${ctx.filesDir}/ui_log.txt`;
    this.lockFile = `${ctx.filesDir}/run.lock`;
    let lockExists: boolean = false;
    try {
      lockExists = fileIo.accessSync(this.lockFile);
    } catch (e) {
      lockExists = false;
    }
    if (lockExists) {
      this.prevCrashed = true;
      const tail: string[] = [];
      try {
        const old: string = fileIo.readTextSync(this.logFile);
        const rows: string[] = old.split('\n');
        const from: number = rows.length > 150 ? rows.length - 150 : 0;
        for (let i: number = from; i < rows.length; i++) {
          if (rows[i].length > 0) {
            tail.push(`[上次] ${rows[i]}`);
          }
        }
      } catch (e) {
        // 第一次跑 / 文件被清 —— 没有现场可留
      }
      this.crashTail = tail;
      // 现场也留一份档，避免下次启动把它覆盖掉
      try {
        fileIo.copyFileSync(this.logFile, `${this.logFile}.1`);
      } catch (e) {
        // 忽略
      }
    }
    // 新会话从空文件开始
    try {
      const f: fileIo.File = fileIo.openSync(this.logFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC | fileIo.OpenMode.WRITE_ONLY);
      this.logFd = f.fd;
      this.logBytes = 0;
    } catch (e) {
      this.logFd = -1;
    }
    // 把启动早期（句柄还没就绪时）攒下的日志回灌进去，别丢
    for (let i: number = 0; i < this.logRing.length; i++) {
      this.appendLogFile(this.logRing[i]);
    }
    // 打上「本次会话开始」标记 + 上次是否异常退出
    this.pushLog(this.prevCrashed
      ? '⚠️ 检测到上次异常退出（闪退），崩溃前日志已挂在列表最前面，请点「复制日志」'
      : '会话开始（上次为正常退出）');
    // 最后才写 run.lock —— 上面任何一步崩掉都不该被误判成「本次正常」
    try {
      const lf: fileIo.File = fileIo.openSync(this.lockFile,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      fileIo.writeSync(lf.fd, `${new Date().toString()}\n`);
      fileIo.closeSync(lf);
    } catch (e) {
      // 忽略
    }
  }

  /**
   * 5.0.49：正常退出 —— 删掉 `run.lock`，下次启动就不会误报「异常退出」。
   * 由 EntryAbility.onDestroy 调用。
   */
  markCleanExit(): void {
    if (this.lockFile.length > 0) {
      try {
        fileIo.unlinkSync(this.lockFile);
      } catch (e) {
        // 已经不在了
      }
    }
    if (this.logFd >= 0) {
      try {
        fileIo.closeSync(this.logFd);
      } catch (e) {
        // 忽略
      }
      this.logFd = -1;
    }
  }
"""

SVC_LOGAUTO_OLD = """  logAuto(msg: string): void {
    this.pushLog(`[相册] ${msg}`);
    this.emit();
  }
"""
SVC_LOGAUTO_NEW = """  logAuto(msg: string): void {
    this.pushLog(`[相册] ${msg}`);
    this.emit();
  }

  /**
   * 5.0.49：**未捕获异常**落盘入口 —— EntryAbility 的 errorManager 回调调它。
   * 这是「闪退」最直接的一份证据：栈顶通常就写明了崩在哪一行。
   * ⚠️ 全程 try 包裹：出错回调里再抛异常会把证据一起弄丢。
   */
  crashLog(msg: string): void {
    try {
      this.pushLog(`💥 ${msg}`);
      this.emit();
    } catch (e) {
      try {
        this.appendLogFile(`💥 ${msg}`);
      } catch (x) {
        // 实在写不进去就放弃
      }
    }
  }
"""

SVC_START_OLD = """    this.ctx = ctx;
    this.router.setContext(ctx);
"""
SVC_START_NEW = """    this.ctx = ctx;
    // 5.0.49：日志立刻开始落盘 —— 崩溃取证越早开始越好
    this.initLogFile(ctx);
    this.router.setContext(ctx);
"""

SVC_ALBUMIDX_OLD = """  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {
    this.albumLoaded = true;
    this.albumMap.set(id, `${uri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }
"""
SVC_ALBUMIDX_NEW = """  async setAlbumIndex(id: string, uri: string, thumb: string, rot: number = 0): Promise<void> {
    this.albumLoaded = true;
    this.albumMap.set(id, `${uri}|${thumb}`);
    this.albumRotMap.set(thumb, rot);
    await this.persistAlbumIndex();
    await this.persistAlbumRot();
  }

  /**
   * 5.0.49：把**已经失效**的相册 URI 从索引里摘掉，但**保留缩略图**。
   *
   * 场景（vivi 2026-10-02）：在系统相册里把那张图删了，我们记的 uri 就成了死链接 ——
   * 再点气泡会跳进一个空白相册页、还没有任何提示。
   * 只清 uri 不清缩略图：气泡还能显示小图，而且下一次点击会自然走到
   * 「补存进相册」（historyToAlbum）那条路，可以自愈。
   */
  clearAlbumUri(id: string): void {
    const row: string | undefined = this.albumMap.get(id);
    if (row === undefined) {
      return;
    }
    const segs: string[] = row.split('|');
    const thumb: string = segs.length >= 2 ? segs[1] : '';
    if (thumb.length === 0) {
      this.albumMap.delete(id);
    } else {
      this.albumMap.set(id, `|${thumb}`);
    }
    this.persistAlbumIndex().catch((e: Error) => {
      Log.w(TAG, `清理失效相册 URI 落盘异常: ${e.message}`);
    });
  }
"""

# ======================================================================
# EntryAbility.ets
# ======================================================================
ABI_IMPORT_OLD = """import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
"""
ABI_IMPORT_NEW = """import { AbilityConstant, UIAbility, Want, errorManager } from '@kit.AbilityKit';
import ErrorObserver from '@ohos.app.ability.ErrorObserver';
"""

ABI_CLASS_OLD = """export default class EntryAbility extends UIAbility {
"""
ABI_CLASS_NEW = """/**
 * 5.0.49：未捕获异常观察者。
 *
 * 「接收图片概率性闪退」在真机上表现为**进程直接消失**，什么都抓不到。
 * 注册这个回调后，ArkTS 层任何未捕获异常（含未处理的 Promise rejection）
 * 都会先经过这里 —— 栈被写进应用内的日志文件，重启后还能读回来，
 * 用户点一次「复制日志」就能把它发出来。
 */
class CrashObserver extends ErrorObserver {
  onUnhandledException(errMsg: string): void {
    Log.e(TAG, `未捕获异常: ${errMsg}`);
    LanService.get().crashLog(`未捕获异常：${errMsg}`);
  }

  onException(errObject: Error): void {
    const stack: string = errObject.stack === undefined ? '' : errObject.stack;
    Log.e(TAG, `JS 异常: ${errObject.message}`);
    LanService.get().crashLog(`JS 异常：${errObject.message}\n${stack}`);
  }
}

export default class EntryAbility extends UIAbility {
"""

ABI_CREATE_OLD = """  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    Log.i(TAG, 'EntryAbility onCreate');
  }
"""
ABI_CREATE_NEW = """  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    Log.i(TAG, 'EntryAbility onCreate');
    // 5.0.49：注册未捕获异常回调（崩溃取证）。失败也不能影响启动。
    try {
      errorManager.on('error', new CrashObserver());
      Log.i(TAG, '未捕获异常回调已注册');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `注册未捕获异常回调失败: ${err.code} ${err.message}`);
    }
  }
"""

ABI_DESTROY_OLD = """  onDestroy(): void {
    Log.i(TAG, 'EntryAbility onDestroy，释放共享会话');
    // onDestroy 是同步回调，这里只做触发（内部会兜底复位屏幕常亮）
    LanService.get().shutdown();
  }
"""
ABI_DESTROY_NEW = """  onDestroy(): void {
    Log.i(TAG, 'EntryAbility onDestroy，释放共享会话');
    // 5.0.49：正常退出 —— 清掉 run.lock，下次启动才不会误报「上次闪退」
    try {
      LanService.get().markCleanExit();
    } catch (e) {
      Log.w(TAG, '清理退出标记失败');
    }
    // onDestroy 是同步回调，这里只做触发（内部会兜底复位屏幕常亮）
    LanService.get().shutdown();
  }
"""

# ======================================================================
# Index.ets
# ======================================================================
IDX_FIELD_OLD = """  /** `cacheThumb()` 内部传递「这次有没有物理转成功」的中转变量（0 = 转成功，否则 = 待补转的度数） */
  private pendingRot: number = 0;
"""
IDX_FIELD_NEW = """  /**
   * 5.0.49：缩略图解码**单飞表**（key = id|源路径）。
   *
   * 同一个 id 的缩略图有两路调用者：渲染驱动的 `syncChatMediaPaths()`
   * 和存相册驱动的 `autoSaveAlbumBatch()`。它们可能几乎同时给同一个 id
   * 解码、并写同一个 `<id>.jpg` —— 两路原生解码同时压内存，
   * 叠加一张 12MP 的解码峰值，正是「概率性闪退」最合理的解释之一。
   * 同一个 key 只跑一次，两路拿同一个 Promise。
   */
  private thumbInFlight: Map<string, Promise<string>> = new Map<string, Promise<string>>();
"""

IDX_AUTOSTART_OLD = """      const ok: boolean = await this.service.startSharing(ctx);
      if (!ok) {
        this.toast(`自动开启失败：${this.snapshot.message}`);
      }
"""
IDX_AUTOSTART_NEW = """      const ok: boolean = await this.service.startSharing(ctx);
      if (!ok) {
        this.toast(`自动开启失败：${this.snapshot.message}`);
      } else if (this.service.prevCrashed) {
        // 5.0.49：上次是闪退 —— 崩溃前的日志已经挂进日志列表最前面，
        //         明确引导用户去「复制日志」把它带出来（真机没有 hdc，这是唯一通路）
        this.toast('检测到上次闪退，请点「复制日志」把崩溃现场发出来');
      }
"""

IDX_RATIO_RELEASE_OLD = """      try {
        src.release();
      } catch (x) {
        // 释放失败不影响显示
      }
"""
IDX_RATIO_RELEASE_NEW = """      try {
        // ⚠️ 5.0.49：`ImageSource.release()` 返回的是 **Promise**。
        //    不 await 的话它抛出的异常**不会**被这个 try/catch 接住，
        //    会变成「未处理的 Promise 异常」—— 在 ArkTS 上这会**终止应用**。
        //    这就是「接收图片概率性闪退」的元凶之一（只有走到这里才会中招）。
        await src.release();
      } catch (x) {
        // 释放失败不影响显示
      }
"""

IDX_CACHETHUMB_SIG_OLD = """  private async cacheThumb(ctx: common.UIAbilityContext, srcPath: string,
                           id: string): Promise<string> {
    let pm: image.PixelMap | null = null;
    let gen: media.AVImageGenerator | null = null;
    let f: fileIo.File | null = null;
    // 这三项要带到方法末尾做「最终验证」，所以提到外层声明
    let srcW: number = 0;
    let srcH: number = 0;
    let deg: number = 0;
"""
IDX_CACHETHUMB_SIG_NEW = r"""  /**
   * 5.0.49：`cacheThumbInner` 的**单飞包装**（见 `thumbInFlight` 的注释）。
   */
  private cacheThumb(ctx: common.UIAbilityContext, srcPath: string,
                     id: string): Promise<string> {
    const key: string = `${id}|${srcPath}`;
    const running: Promise<string> | undefined = this.thumbInFlight.get(key);
    if (running !== undefined) {
      return running;
    }
    const p: Promise<string> = this.cacheThumbInner(ctx, srcPath, id);
    this.thumbInFlight.set(key, p);
    // ⚠️ 这里必须挂 catch：这个「清理链路」不能自己变成未处理的 rejection
    p.then(() => {
      this.thumbInFlight.delete(key);
    }).catch(() => {
      this.thumbInFlight.delete(key);
    });
    return p;
  }

  private async cacheThumbInner(ctx: common.UIAbilityContext, srcPath: string,
                                id: string): Promise<string> {
    let pm: image.PixelMap | null = null;
    let gen: media.AVImageGenerator | null = null;
    let f: fileIo.File | null = null;
    // 5.0.49：ImageSource 也提到外层 —— 之前只在**成功路径**里释放，
    //         中间任何一步抛异常就漏一个原生 ImageSource（累积就是闪退）。
    let srcRef: image.ImageSource | null = null;
    // 这三项要带到方法末尾做「最终验证」，所以提到外层声明
    let srcW: number = 0;
    let srcH: number = 0;
    let deg: number = 0;
    // 5.0.49：原来是实例字段 `pendingRot`，并发调用时会互相串台（方向错乱）→ 改局部
    let pendRot: number = 0;
"""

IDX_SRC_CREATE_OLD = """        const src: image.ImageSource = image.createImageSource(srcPath);
"""
IDX_SRC_CREATE_NEW = """        const src: image.ImageSource = image.createImageSource(srcPath);
        srcRef = src;   // 5.0.49：登记到外层，保证异常路径也能释放
"""

IDX_DIM_GUARD_OLD = """        const info: image.ImageInfo = src.getImageInfoSync(0);
        srcW = info.size.width;
        srcH = info.size.height;
        const w: number = srcW;
"""
IDX_DIM_GUARD_NEW = """        const info: image.ImageInfo = src.getImageInfoSync(0);
        srcW = info.size.width;
        srcH = info.size.height;
        // 5.0.49：极端尺寸保护 —— 有些全景图宽度上万，即使按 320 出缩略图，
        //         部分实现仍会先分配整张原图的缓冲，直接 OOM 闪退。
        //         宁可不出缩略图（气泡退回占位块），也不能把应用整个弄崩。
        if (srcW <= 0 || srcH <= 0 || srcW > 16384 || srcH > 16384) {
          Log.w(TAG, `原图尺寸异常 ${srcW}x${srcH}，跳过缩略图解码: ${srcPath}`);
          return '';
        }
        const w: number = srcW;
"""

IDX_THUMB_RELEASE_OLD = """        try {
          src.release();
        } catch (x) {
          // 释放失败不影响缩略图
        }
"""
IDX_THUMB_RELEASE_NEW = """        try {
          // ⚠️ 5.0.49：必须 await（`release()` 返回 Promise）。
          //    原写法 `try { src.release(); } catch {}` **catch 不到**异步 rejection，
          //    未处理的 Promise 异常在 ArkTS 上会终止应用 —— 闪退元凶。
          await src.release();
          srcRef = null;
        } catch (x) {
          // 释放失败不影响缩略图
        }
"""

IDX_PENDROT_SET_OLD = """          this.pendingRot = deg;
"""
IDX_PENDROT_SET_NEW = """          pendRot = deg;
"""

IDX_CHK_RELEASE_OLD = """          try {
            chk.release();
          } catch (x) {
            // 忽略
          }
"""
IDX_CHK_RELEASE_NEW = """          try {
            // ⚠️ 5.0.49：同样是 Promise —— 必须 await（理由见上面 src.release 处）
            await chk.release();
          } catch (x) {
            // 忽略
          }
"""

IDX_PENDROT_READ1_OLD = """        const swap: boolean = Index.isQuarter(this.pendingRot);
"""
IDX_PENDROT_READ1_NEW = """        const swap: boolean = Index.isQuarter(pendRot);
"""

IDX_PENDROT_READ2_OLD = """      this.service.albumRotMap.set(out, this.pendingRot);
      this.pendingRot = 0;
      return out;
"""
IDX_PENDROT_READ2_NEW = """      this.service.albumRotMap.set(out, pendRot);
      return out;
"""

IDX_FINALLY_OLD = """    } finally {
      if (gen !== null) {
        try {
          await gen.release();
        } catch (x) {
          // 忽略
        }
      }
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  /** 相册索引的第 n 段：0 = 相册 URI，1 = 缩略图缓存路径 */
"""
IDX_FINALLY_NEW = """    } finally {
      if (gen !== null) {
        try {
          await gen.release();
        } catch (x) {
          // 忽略
        }
      }
      if (srcRef !== null) {
        // 5.0.49：异常路径下 ImageSource 的兜底释放（之前会漏）
        try {
          await srcRef.release();
        } catch (x) {
          // 已经释放过 / 释放失败都不影响
        }
      }
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  /** 相册索引的第 n 段：0 = 相册 URI，1 = 缩略图缓存路径 */
"""

IDX_CLICK_OLD = """  private onFileBubbleClick(m: ChatMessage): void {
    const album: string = this.albumPart(m.id, 0);
    if (album.length > 0) {
      this.openInGallery(album);
      return;
    }
"""
IDX_CLICK_NEW = """  private onFileBubbleClick(m: ChatMessage): void {
    const album: string = this.albumPart(m.id, 0);
    if (album.length > 0) {
      // 5.0.49：先确认相册里那份**还在**。
      //   用户可能已经在系统相册里把它删了 —— 那时直接 startAbility 会跳进
      //   一个**空白相册页**，而且没有任何提示（vivi 2026-10-02 反馈）。
      if (this.albumAssetAlive(album)) {
        this.openInGallery(album);
        return;
      }
      this.toast('该文件已从相册删除');
      this.service.logAuto(`相册资产已不存在（已从相册删除），摘掉失效 URI：${m.id}`);
      this.service.clearAlbumUri(m.id);
      this.albumIndex = this.service.albumSnapshot();
      // 降级：还有缓存的 320px 小图就打开它，至少让用户看到内容
      const gone: string = this.albumPart(m.id, 1);
      if (gone.length > 0 && this.isMediaName(gone)) {
        this.openMediaPreview(gone, m.content, m.id);
      }
      return;
    }
"""

IDX_ALIVE_OLD = """  private openInGallery(uri: string): void {
"""
IDX_ALIVE_NEW = """  private albumAssetAlive(uri: string): boolean {
    if (uri.length === 0) {
      return false;
    }
    let f: fileIo.File | null = null;
    try {
      // ⚠️ 用「**写**打开」探活，不是「读打开」：
      //    `showAssetsCreationDialog` 给回来的是**写授权** URI ——
      //    读它本来就可能被拒（权限拒绝 ≠ 文件不存在，会把「已删除」误判成「还在」）。
      //    写授权我们一定有，所以只有「文件真的没了」才会失败。
      // ⚠️ 不带 TRUNC：只是打开探一下，绝不能改内容。
      f = fileIo.openSync(uri, fileIo.OpenMode.WRITE_ONLY);
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `相册资产探测失败: ${err.code} ${uri}`);
      // 13900002 = No such file or directory（真的被删了）
      // 其它错误（权限 / 服务异常）分不清 —— 保守当「还在」，不去打扰用户
      return err.code !== 13900002;
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  private openInGallery(uri: string): void {
"""

APP_OLD = '''    "versionCode": 5000048,
    "versionName": "5.0.48",
'''
APP_NEW = '''    "versionCode": 5000049,
    "versionName": "5.0.49",
'''

EDITS = [
    (F_SVC, SVC_FIELDS_OLD, SVC_FIELDS_NEW, 'svc.fields'),
    (F_SVC, SVC_EMIT_OLD, SVC_EMIT_NEW, 'svc.emit'),
    (F_SVC, SVC_PUSHLOG_OLD, SVC_PUSHLOG_NEW, 'svc.pushLog+logfile'),
    (F_SVC, SVC_LOGAUTO_OLD, SVC_LOGAUTO_NEW, 'svc.crashLog'),
    (F_SVC, SVC_START_OLD, SVC_START_NEW, 'svc.startSharing'),
    (F_SVC, SVC_ALBUMIDX_OLD, SVC_ALBUMIDX_NEW, 'svc.clearAlbumUri'),
    (F_ABI, ABI_IMPORT_OLD, ABI_IMPORT_NEW, 'abi.import'),
    (F_ABI, ABI_CLASS_OLD, ABI_CLASS_NEW, 'abi.observerClass'),
    (F_ABI, ABI_CREATE_OLD, ABI_CREATE_NEW, 'abi.onCreate'),
    (F_ABI, ABI_DESTROY_OLD, ABI_DESTROY_NEW, 'abi.onDestroy'),
    (F_IDX, IDX_FIELD_OLD, IDX_FIELD_NEW, 'idx.thumbInFlight'),
    (F_IDX, IDX_AUTOSTART_OLD, IDX_AUTOSTART_NEW, 'idx.autoStart'),
    (F_IDX, IDX_RATIO_RELEASE_OLD, IDX_RATIO_RELEASE_NEW, 'idx.ensureRatioRelease'),
    (F_IDX, IDX_CACHETHUMB_SIG_OLD, IDX_CACHETHUMB_SIG_NEW, 'idx.cacheThumbWrap'),
    (F_IDX, IDX_SRC_CREATE_OLD, IDX_SRC_CREATE_NEW, 'idx.srcRef'),
    (F_IDX, IDX_DIM_GUARD_OLD, IDX_DIM_GUARD_NEW, 'idx.dimGuard'),
    (F_IDX, IDX_THUMB_RELEASE_OLD, IDX_THUMB_RELEASE_NEW, 'idx.thumbRelease'),
    (F_IDX, IDX_PENDROT_SET_OLD, IDX_PENDROT_SET_NEW, 'idx.pendRotSet'),
    (F_IDX, IDX_CHK_RELEASE_OLD, IDX_CHK_RELEASE_NEW, 'idx.chkRelease'),
    (F_IDX, IDX_PENDROT_READ1_OLD, IDX_PENDROT_READ1_NEW, 'idx.pendRotRead1'),
    (F_IDX, IDX_PENDROT_READ2_OLD, IDX_PENDROT_READ2_NEW, 'idx.pendRotRead2'),
    (F_IDX, IDX_FINALLY_OLD, IDX_FINALLY_NEW, 'idx.finallyRelease'),
    (F_IDX, IDX_CLICK_OLD, IDX_CLICK_NEW, 'idx.clickAlbumCheck'),
    (F_IDX, IDX_ALIVE_OLD, IDX_ALIVE_NEW, 'idx.albumAssetAlive'),
    (F_APP, APP_OLD, APP_NEW, 'app.version'),
]


def main():
    # ---- 哨兵：已打过就跳过（本脚本可能被执行两次）----
    svc = read(F_SVC)
    if SENTINEL in svc:
        print('ALREADY APPLIED')
        sys.exit(0)

    # ---- 第一步：全部校验（内存里改，一个文件都不落盘）----
    texts = {}
    for p in (F_SVC, F_ABI, F_IDX, F_APP):
        texts[p] = read(p)

    errors = []
    for path, old, new, name in EDITS:
        s = texts[path]
        n = s.count(old)
        if n != 1:
            errors.append(f'[{name}] 锚点出现 {n} 次（期望 1）: {old[:60]!r}')
            continue
        if s.count(new) > 0:
            errors.append(f'[{name}] 新文本已存在，疑似重复应用')
            continue
        texts[path] = s.replace(old, new, 1)

    if errors:
        print('校验失败，未做任何修改：')
        for e in errors:
            print('  - ' + e)
        sys.exit(1)

    # ---- 第二步：统一落盘 ----
    for path in (F_SVC, F_ABI, F_IDX, F_APP):
        write(path, texts[path])

    print('OK: 5.0.49 已应用（%d 处改动，4 个文件）' % len(EDITS))


if __name__ == '__main__':
    main()
