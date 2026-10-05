# -*- coding: utf-8 -*-
"""
5.0.50 补丁：修「自动存相册弹窗又不见了」+ 撤掉偷存相册 + 修气泡文件名溢出。

哨兵：'5.0.50'（脚本幂等，重复执行直接 SKIP）

改动文件
  1. entry/src/main/ets/pages/Index.ets
  2. AppScope/app.json5

vivi 本轮反馈（2026-10-02 12:0x）：
  ① 「这次不闪退了」                 -> 5.0.49 的闪退修复有效，保留
  ② 「但这次不弹窗保存了」           -> 回归，必须修
  ③ 「文件删除后再点就不要把缩略图保存到相册了，提示相册里已删除就行」
  ④ 「气泡中文件名会溢出气泡」

②的根因（代码级）：
  5.0.49 为了接住 `ImageSource.release()` 的异步 rejection（闪退防护），
  把它写成了 `await src.release()`。但 `await` 引入了**新的挂起风险** ——
  `release()` 的 Promise 在异常态（重复释放/服务忙）可能**永不 settle**。
  一旦挂起：
    - `cacheThumbInner` 在 finally 里 `await gen.release()/srcRef.release()`
      永不返回 -> 它返回的 Promise 永挂；
    - `cacheThumb` 单飞表里把这个永挂的 Promise 钉住 -> 同 key 后续调用全卡；
    - `flushAutoSave` 里 `autoSaveAlbumBatch(...)` 卡在 `await cacheThumb` ->
      promise 不 settle -> `.then` 不执行 -> `autoSaveBusy` 永远为 true
      -> **之后再也不弹框**。
  另外 5.0.49 的 `flushAutoSave` 只挂了 `.then` 没挂 `.catch`：
  只要 batch reject（例如 finally 里 refreshReceived 抛异常），
  `autoSaveBusy` 同样永久停在 true。

修法：
  (a) 所有 `await x.release()` -> `x.release().catch(() => {})`
      —— 仍然接住异步 rejection（闪退防护不丢），但**不阻塞**流程。
  (b) `cacheThumb` 单飞 + **8 秒超时兜底**，绝不让永挂的 Promise 钉住 map。
  (c) `flushAutoSave` 补 `.catch`，并在**任何**路径都复位 autoSaveBusy。
  (d) `flushAutoSave` 加 **45 秒卡死看门狗**：busy 挂太久强制复位重试。
      —— 这条是"无论真因是什么都保证弹窗能回来"的兜底。

③：`onFileBubbleClick` 里去掉 `historyToAlbum()` 补存分支 -> 只提示 + 应用内预览。
   `historyToAlbum()` 方法本体一并删除（已无调用者）。

④：`chatFileBubble` 的 Row 是 wrapContent，测量子项时给的是"无限宽"，
   只把 `constraintSize` 挂在 Row 上**不会**约束到内部 Text ->
   长文件名单行摊开、画出气泡背景外。
   修法：把宽度约束**下沉**——外层 Column 给 `maxWidth:'92%'`，
   气泡内层 Column 与 Text 各给 `maxWidth:'100%'`，形成有限约束链。
"""

import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
F_IDX = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets')
F_APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.0.50'


def rd(p):
    return io.open(p, encoding='utf-8', newline='').read()


def wr(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s.replace('\r\n', '\n'))


# ----------------------------------------------------------------------
# Index.ets
# ----------------------------------------------------------------------
IDX_OLD = rd(F_IDX)
if SENTINEL in IDX_OLD:
    print('ALREADY APPLIED')
    sys.exit(0)

EDITS = []

# (1) 新增 autoSaveBusySince 字段
EDITS.append((
    'field autoSaveBusySince',
    """  /** 5.0.39：正在弹框 / 拷贝中，防重入 */
  private autoSaveBusy: boolean = false;
""",
    """  /** 5.0.39：正在弹框 / 拷贝中，防重入 */
  private autoSaveBusy: boolean = false;
  /** 5.0.50：`autoSaveBusy` 置位的时刻 —— 用于「卡死看门狗」（见 flushAutoSave） */
  private autoSaveBusySince: number = 0;
"""))

# (2) cacheThumb 单飞 + 8s 超时兜底
EDITS.append((
    'cacheThumb timeout guard',
    """    const p: Promise<string> = this.cacheThumbInner(ctx, srcPath, id);
    this.thumbInFlight.set(key, p);
    // \u26a0\ufe0f 这里必须挂 catch：这个「清理链路」不能自己变成未处理的 rejection
    p.then(() => {
      this.thumbInFlight.delete(key);
    }).catch(() => {
      this.thumbInFlight.delete(key);
    });
    return p;
  }
""",
    """    const raw: Promise<string> = this.cacheThumbInner(ctx, srcPath, id);
    // 5.0.50：**8 秒超时兜底**。单飞表里一旦留下一个永不 settle 的 Promise，
    //   同 key 的后续调用（含存相册链路）就会全部卡在它身上 ——
    //   真机表现就是「收过一次图之后，再也不弹存相册框」。
    //   解码是纯本地活，8 秒还没结果就按失败处理（返回空串 = 气泡退回占位块），
    //   绝不能让它把整条链拖死。
    const p: Promise<string> = new Promise<string>((resolve: (v: string) => void) => {
      let done: boolean = false;
      const finish: (v: string) => void = (v: string) => {
        if (!done) {
          done = true;
          resolve(v);
        }
      };
      raw.then((v: string) => {
        finish(v);
      }).catch(() => {
        finish('');
      });
      setTimeout(() => {
        if (!done) {
          Log.w(TAG, `缩略图解码超时 8s，放弃: ${srcPath}`);
        }
        finish('');
      }, 8000);
    });
    this.thumbInFlight.set(key, p);
    // \u26a0\ufe0f 这里必须挂 catch：这个「清理链路」不能自己变成未处理的 rejection
    p.then(() => {
      this.thumbInFlight.delete(key);
    }).catch(() => {
      this.thumbInFlight.delete(key);
    });
    return p;
  }
"""))

# (3) src.release() 改为非阻塞
EDITS.append((
    'src.release non-blocking',
    """        try {
          // \u26a0\ufe0f 5.0.49：必须 await（`release()` 返回 Promise）。
          //    原写法 `try { src.release(); } catch {}` **catch 不到**异步 rejection，
          //    未处理的 Promise 异常在 ArkTS 上会终止应用 —— 闪退元凶。
          await src.release();
          srcRef = null;
        } catch (x) {
          // 释放失败不影响缩略图
        }
""",
    """        // 5.0.50：**不能 await**。`release()` 的 Promise 在异常态（重复释放 /
        //   服务忙）可能**永不 settle**，一旦 await 就把它变成整条链的挂起点
        //   （配合单飞表 = 永久卡死，真机表现就是「之后再也不弹存相册框」）。
        //   改用 `.catch()`：同样接住异步 rejection（5.0.49 的闪退防护不丢），
        //   但绝不阻塞流程。
        src.release().catch(() => {
          // 释放失败 / 已经释放过，都不影响缩略图
        });
        srcRef = null;
"""))

# (3b) ensureMediaRatio 里的 src.release() 改为非阻塞
EDITS.append((
    'ensureMediaRatio src.release non-blocking',
    """      try {
        // \u26a0\ufe0f 5.0.49：`ImageSource.release()` 返回的是 **Promise**。
        //    不 await 的话它抛出的异常**不会**被这个 try/catch 接住，
        //    会变成「未处理的 Promise 异常」—— 在 ArkTS 上这会**终止应用**。
        //    这就是「接收图片概率性闪退」的元凶之一（只有走到这里才会中招）。
        await src.release();
      } catch (x) {
        // 释放失败不影响显示
      }
""",
    """      // 5.0.50：**不能 await** —— `release()` 的 Promise 在异常态可能永不 settle，
      //   await 会让本方法挂住、并钉死调用链。`.catch()` 同样接住异步 rejection
      //   （5.0.49 的闪退防护不丢），但不阻塞流程。
      src.release().catch(() => {
        // 释放失败不影响显示
      });
"""))

# (3c) 打包路径的 packer.release() / pm.release() 改为非阻塞
EDITS.append((
    'packer/pm release non-blocking',
    """      try {
        await packer.release();
      } catch (x) {
        // 忽略
      }
      try {
        await pm.release();
      } catch (x) {
        // 忽略
      }
""",
    """      // 5.0.50：两个 release 都不 await —— 结果不重要，绝不能阻塞编码路径
      packer.release().catch(() => {
        // 忽略
      });
      pm.release().catch(() => {
        // 忽略
      });
"""))

# (3d) 视频首帧路径 finally 里的 gen.release() 改为非阻塞
EDITS.append((
    'video gen.release non-blocking',
    """      if (gen !== null) {
        try {
          await gen.release();
        } catch (e) {
          // 忽略
        }
      }
""",
    """      if (gen !== null) {
        // 5.0.50：finally 里的 await 会让整个方法永不返回 —— 改成非阻塞
        gen.release().catch(() => {
          // 忽略
        });
      }
"""))

# (4) chk.release() 改为非阻塞
EDITS.append((
    'chk.release non-blocking',
    """          try {
            // \u26a0\ufe0f 5.0.49：同样是 Promise —— 必须 await（理由见上面 src.release 处）
            await chk.release();
          } catch (x) {
            // 忽略
          }
""",
    """          // 5.0.50：理由同 src.release() —— 不 await，只挂 catch
          chk.release().catch(() => {
            // 忽略
          });
"""))

# (5) finally: gen.release() 改为非阻塞
EDITS.append((
    'gen.release non-blocking',
    """      if (gen !== null) {
        try {
          await gen.release();
        } catch (x) {
          // 忽略
        }
      }
""",
    """      if (gen !== null) {
        // 5.0.50：**finally 里的 await 最危险** —— 它会让整个方法永不返回，
        //   进而把单飞表里这个 Promise 永久钉住。改成非阻塞。
        gen.release().catch(() => {
          // 忽略
        });
      }
"""))

# (6) finally: srcRef.release() 改为非阻塞
EDITS.append((
    'srcRef.release non-blocking',
    """      if (srcRef !== null) {
        // 5.0.49：异常路径下 ImageSource 的兜底释放（之前会漏）
        try {
          await srcRef.release();
        } catch (x) {
          // 已经释放过 / 释放失败都不影响
        }
      }
""",
    """      if (srcRef !== null) {
        // 5.0.49：异常路径下 ImageSource 的兜底释放（之前会漏）
        // 5.0.50：同样不能 await（理由见上面 src.release() 处）
        srcRef.release().catch(() => {
          // 已经释放过 / 释放失败都不影响
        });
      }
"""))

# (7) flushAutoSave 开头：45s 卡死看门狗
EDITS.append((
    'flushAutoSave watchdog',
    """  private flushAutoSave(): void {
    if (this.autoSaveBusy || this.autoSavePending.length === 0) {
      return;
    }
""",
    """  private flushAutoSave(): void {
    // 5.0.50：**卡死看门狗**。正常一次「弹框 + 拷贝」几秒内结束；
    //   超过 45 秒还挂在 busy 上，说明某一步（弹框 / 解码）没回来。
    //   强制复位再试一次 —— 绝不接受「收图后再也不弹」这种永久失效。
    if (this.autoSaveBusy && this.autoSaveBusySince > 0
      && Date.now() - this.autoSaveBusySince > 45000) {
      const stuck: number = Date.now() - this.autoSaveBusySince;
      this.service.logAuto(`自动存相册疑似卡死 ${stuck}ms，强制复位重试`);
      this.autoSaveBusy = false;
    }
    if (this.autoSaveBusy || this.autoSavePending.length === 0) {
      return;
    }
"""))

# (8) flushAutoSave 的 then -> then + catch，busy 必定复位
EDITS.append((
    'flushAutoSave catch + busy reset',
    """    this.service.logAuto(`准备弹存相册确认框：${paths.length} 个文件`);
    this.autoSaveBusy = true;
    this.autoSaveAlbumBatch(paths, owners, ready).then(() => {
      this.autoSaveBusy = false;
      // 5.0.47：batch 的 finally 里那次 flushAutoSave 发生在 busy 清零**之前**
      // （被 busy 挡掉），必须在这里补一次，否则弹框期间入队的后续图片
      // 永远没人再触发 -> 只有第一次有弹窗（真机复现）。
      this.flushAutoSave();
    });
  }
""",
    """    this.service.logAuto(`准备弹存相册确认框：${paths.length} 个文件`);
    this.autoSaveBusy = true;
    this.autoSaveBusySince = Date.now();
    this.autoSaveAlbumBatch(paths, owners, ready).then(() => {
      this.autoSaveBusy = false;
      this.autoSaveBusySince = 0;
      // 5.0.47：batch 的 finally 里那次 flushAutoSave 发生在 busy 清零**之前**
      // （被 busy 挡掉），必须在这里补一次，否则弹框期间入队的后续图片
      // 永远没人再触发 -> 只有第一次有弹窗（真机复现）。
      this.flushAutoSave();
    }).catch((e: Object) => {
      // 5.0.50：**必须兜住**。5.0.49 只挂了 then —— 一旦 batch reject
      //   （比如 finally 里那次 refreshReceived 抛异常），`autoSaveBusy`
      //   就永远停在 true，之后**再也不会弹框**。这是 5.0.49「不弹窗」的病灶之一。
      const err: BusinessError = e as BusinessError;
      this.service.logAuto(`自动存相册批处理异常：${err.code} ${err.message}`);
      this.autoSaveBusy = false;
      this.autoSaveBusySince = 0;
      this.flushAutoSave();
    });
  }
"""))

# (9) onFileBubbleClick：撤掉自动补存相册
EDITS.append((
    'onFileBubbleClick no re-save',
    """    // 5.0.45：旧消息沙箱原图已删、只剩缓存缩略图 -> 补存进相册再跳过去。
    //         历史图片本来就不在相册里，所以第一次点会弹一次系统确认框；
    //         存成之后索引里就有了 URI，以后点击直接跳相册，不再弹框。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.historyToAlbum(m, thumb).catch(() => {
        this.openMediaPreview(thumb, m.content, m.id);
      });
      return;
    }
    this.openFileTab();
""",
    """    // 5.0.50（vivi 要求）：**不再自动补存相册**。
    //   5.0.45 这里会把「只剩缓存缩略图」的图悄悄存回相册 ——
    //   用户在系统相册里删掉之后再点，它就被偷偷存回来了，等于删不掉。
    //   现在统一：只提示 + 用缓存小图在应用内看，绝不再写相册。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.toast('该文件已从相册删除');
      this.openMediaPreview(thumb, m.content, m.id);
      return;
    }
    this.openFileTab();
"""))

# (10) 删除 historyToAlbum 方法
EDITS.append((
    'remove historyToAlbum',
    """  /**
   * 5.0.45：点**历史图片**气泡 -> 补存进相册 -> 跳系统相册。
   *
   * 历史图片（5.0.38 之前收的，或当时自动存相册关着）索引里没有相册 URI，
   * 沙箱原图往往也已经删了，只剩下 `album_thumbs/<id>.jpg` 这份 320px 缓存图。
   * 这里把它补存进相册，拿到 URI 记回索引 —— **存过一次之后就永远能直接跳**，
   * 不用再弹第二次框。用户取消或保存失败则回退应用内预览，不阻断。
   */
  private async historyToAlbum(m: ChatMessage, thumb: string): Promise<void> {
    const ok: boolean = await this.saveImageToAlbum(thumb, m.content, m.id);
    if (ok) {
      const uri: string = this.albumPart(m.id, 0);
      if (uri.length > 0) {
        this.openInGallery(uri);
        return;
      }
    }
    // 没存成 / 没拿到 URI -> 还是用缓存图在应用内看，别把用户晾在那
    this.openMediaPreview(thumb, m.content, m.id);
  }

""",
    """  /*
   * 5.0.50：`historyToAlbum()` 已删除 —— vivi 要求「相册里删掉的就别再偷存回去」，
   *   现在点只剩缓存缩略图的气泡只提示「该文件已从相册删除」并做应用内预览，
   *   不再自动写相册。保留此注释说明去处，避免后人以为漏了实现。
   */

"""))

# (11) chatFileBubble：宽度约束下沉（文件名不再溢出）
EDITS.append((
    'chatFileBubble width constraints',
    """        Text(m.content)
          .fontSize(15)
          .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
          .maxLines(2)
          .wordBreak(WordBreak.BREAK_ALL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        if (m.incoming && !this.chatSelectMode) {
          // 只有「收到的」才给入口：收到的文件落在沙箱里，
          // 系统「文件管理」看不到，不指路用户就找不到。
          // 自己发出去的原文件还在用户自己手上，不需要跳。
          Text(this.bubbleHintOf(m, mediaPath))
            .fontSize(10)
            .fontColor(C_PRIMARY)
        }
      }
      // 5.0.36：不再 `layoutWeight(1)` 撑满 —— 气泡按文件名长度自适应收缩，
      // 长名字才长到 maxWidth 上限（88%），短名字就短短一条。
      .alignItems(HorizontalAlign.Start)
    }
""",
    """        // 5.0.50：文件名**必须**带宽度上限 —— wrapContent 的 Row 会用「无限宽」
        //   测量子项，长文件名单行摊开、直接画出气泡背景之外
        //   （vivi 反馈「气泡中文件名会溢出气泡」）。
        //   `maxLines(2)` 只有拿到有限宽度才会真的折行，所以把约束一路下沉到 Text。
        Text(m.content)
          .fontSize(15)
          .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
          .maxLines(2)
          .wordBreak(WordBreak.BREAK_ALL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .constraintSize({ maxWidth: '100%' })
        if (m.incoming && !this.chatSelectMode) {
          // 只有「收到的」才给入口：收到的文件落在沙箱里，
          // 系统「文件管理」看不到，不指路用户就找不到。
          // 自己发出去的原文件还在用户自己手上，不需要跳。
          Text(this.bubbleHintOf(m, mediaPath))
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
      }
      // 5.0.36：不再 `layoutWeight(1)` 撑满 —— 气泡按文件名长度自适应收缩，
      // 长名字才长到 maxWidth 上限（88%），短名字就短短一条。
      // 5.0.50：加 `maxWidth: '100%'` 把外层的 88% 上限**透传**给内部文本 ——
      //   这是「既自适应又不溢出」的关键（只靠 Row 上那一条约束不够）。
      .alignItems(HorizontalAlign.Start)
      .constraintSize({ maxWidth: '100%' })
    }
"""))

# (12) 气泡外层 Column 给有限宽度上限（让 88% 有参照物）
EDITS.append((
    'chatBubble column maxWidth',
    """      .alignItems(m.incoming ? HorizontalAlign.Start : HorizontalAlign.End)
      .onClick(() => {
        if (Date.now() < this.clickMuteUntil) {
""",
    """      .alignItems(m.incoming ? HorizontalAlign.Start : HorizontalAlign.End)
      // 5.0.50：给整列一个**有限的宽度上限**（相对外层满宽 Row）。
      //   没有它，内部所有百分比约束都会落到「无限宽」上而失效 ——
      //   这就是「文件名溢出气泡」的根因。
      .constraintSize({ maxWidth: '92%' })
      .onClick(() => {
        if (Date.now() < this.clickMuteUntil) {
"""))

# ---- 先全部校验，再统一应用 ----
IDX_NEW = IDX_OLD
for name, old, new in EDITS:
    c = IDX_NEW.count(old)
    if c != 1:
        print(f'FAIL: 锚点「{name}」出现 {c} 次（期望 1）')
        sys.exit(1)
    IDX_NEW = IDX_NEW.replace(old, new, 1)

# 语法自检：花括号/圆括号增量必须一致（这些改动全是"整块替换"，不应破坏配平）
for ch_open, ch_close, label in (('{', '}', '花括号'), ('(', ')', '圆括号')):
    d = IDX_NEW.count(ch_open) - IDX_NEW.count(ch_close)
    d0 = IDX_OLD.count(ch_open) - IDX_OLD.count(ch_close)
    if d != d0:
        print(f'FAIL: {label}配平变化 {d0} -> {d}')
        sys.exit(1)

# 残留检查
for bad in ('this.historyToAlbum(', 'this.pendingRot', 'await src.release()',
            'await chk.release()', 'await gen.release()', 'await srcRef.release()'):
    if bad in IDX_NEW:
        print(f'FAIL: 不应残留「{bad}」')
        sys.exit(1)

# ----------------------------------------------------------------------
# app.json5
# ----------------------------------------------------------------------
APP_OLD = rd(F_APP)
APP_OLD_S = """    "versionCode": 5000049,
    "versionName": "5.0.49","""
APP_NEW_S = """    "versionCode": 5000050,
    "versionName": "5.0.50","""
if APP_OLD.count(APP_OLD_S) != 1:
    print(f'FAIL: app.json5 版本锚点出现 {APP_OLD.count(APP_OLD_S)} 次')
    sys.exit(1)
APP_NEW = APP_OLD.replace(APP_OLD_S, APP_NEW_S, 1)

# ---- 落盘 ----
wr(F_IDX, IDX_NEW)
wr(F_APP, APP_NEW)

print('OK: 5.0.50 已应用')
print(f'  Index.ets   {len(IDX_OLD)} -> {len(IDX_NEW)} 字符')
print(f'  app.json5   versionCode=5000050 versionName=5.0.50')
