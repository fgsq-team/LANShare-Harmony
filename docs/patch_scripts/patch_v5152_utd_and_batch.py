# -*- coding: utf-8 -*-
"""
5.1.52 采纳 vivi 的两条建议：
  A. 魔数 → MIME → **UTD**（`@ohos.data.uniformTypeDescriptor`）→ 系统标准后缀
     ★ 关键改进：不再自己维护「媒体后缀白名单」来判断「要不要改」，
       改用 **UTD 的 `filenameExtensions`**（系统认定的标准后缀列表）作唯一判据。
     ★ 风险与对策：SDK 文档写 `getUniformDataTypeByMIMEType` 的 `belongsTo`
       「has no default value」⇒ 可能必须传、且传它需要先有 UTD（循环依赖）。
       **对策：try/catch 包裹，失败直接回落到自带的魔数表**，
       保证无论 UTD 在真机是否可用，功能都正确、只是少一层系统背书。
  B. 批量处理走 **TaskPool** + **信号量限流**；
       单文件纠正**仍留主线程**（µs 级 IO，搬 TaskPool 得不偿失，
       且 5.1.38 实测过「多一次 await ⇒ microtask 优先于 vsync ⇒ 渲染更难插入」）。
"""
import io, os, re, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
ET = os.path.join(ROOT, 'entry', 'src', 'main', 'ets')
FS = os.path.join(ET, 'service', 'FileStorage.ets')
APP = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL = '5.1.52'
fs = io.open(FS, encoding='utf-8', newline='').read()
app = io.open(APP, encoding='utf-8', newline='').read()
if SENTINEL in fs:
    print('ALREADY APPLIED'); sys.exit(0)

B = []
def rep(tag, old, new): B.append((tag, old, new))

# ══════════════════════════════════════════════════════════════════
# ① 顶部加 import（uniformTypeDescriptor + taskpool）
# ══════════════════════════════════════════════════════════════════
rep('imports',
    "import { fileIo, Environment } from '@kit.CoreFileKit';",
    "import { fileIo, Environment } from '@kit.CoreFileKit';\n"
    "// ★ 5.1.52：UTD 取系统标准后缀（唯一判据）+ taskpool 做批量纠正\n"
    "import { uniformTypeDescriptor } from '@kit.ArkData';\n"
    "import { taskpool } from '@kit.ArkTS';")

# ══════════════════════════════════════════════════════════════════
# ② probe 改造：返回 MIME，并在末尾加 UTD 解析 + 批量版
# ══════════════════════════════════════════════════════════════════
rep('probe->mime',
    """  static probe(path: string): string {
    const b: Uint8Array = MagicType.head(path, 16);
    if (b.length < 4) {
      return '';
    }""",
    """  static probe(path: string): string {
    return MagicType.probeMime(path);
  }

  /**
   * ★★ 5.1.52：探测**真实 MIME**（`image/jpeg` / `video/mp4` …）。
   *
   * ## 为什么要 MIME 而不是直接给扩展名
   *   扩展名是「怎么称呼它」，MIME 是「它是什么」。
   *   ★ 交给 UTD 去把「是什么」翻译成「标准后缀」，
   *     我就不必自己维护 `image/jpeg → jpg` 这类映射表。
   *
   * ★ 这一层（读文件头判断物理格式）是**事实**，与平台无关，
   *   所以魔数表仍然必须自己维护；UTD 替代的是「**叫什么**」那部分。
   */
  private static probeMime(path: string): string {
    const b: Uint8Array = MagicType.head(path, 16);
    if (b.length < 4) {
      return '';
    }""")

# probeMime 内部的 return 全部改成 MIME
_mime_map = {
    "return 'jpg';": "return 'image/jpeg';",
    "return 'png';": "return 'image/png';",
    "return 'gif';": "return 'image/gif';",
    "return 'bmp';": "return 'image/bmp';",
    "return 'webp';": "return 'image/webp';",
    "return 'avi';": "return 'video/x-msvideo';",
    "return 'wav';": "return 'audio/wav';",
    "return 'mkv';": "return 'video/x-matroska';",
    "return 'flv';": "return 'video/x-flv';",
    "return 'mp3';": "return 'audio/mpeg';",
    "return 'ogg';": "return 'audio/ogg';",
    "return 'flac';": "return 'audio/flac';",
    "return 'tiff';": "return 'image/tiff';",
    "return 'mov';": "return 'video/quicktime';",
    "return '3gp';": "return 'video/3gpp';",
    "return 'heic';": "return 'image/heic';",
    "return 'avif';": "return 'image/avif';",
    "return 'm4v';": "return 'video/x-m4v';",
    "return 'm4a';": "return 'audio/mp4';",
    "return 'mp4';": "return 'video/mp4';",
}
for a, bnew in _mime_map.items():
    rep('mime:%s' % a.strip("return '';"), '      ' + a, '      ' + bnew)

# ══════════════════════════════════════════════════════════════════
# ③ UTD 查询 + 标准后缀判定 + 批量版（插在 isMediaExt 之前）
# ══════════════════════════════════════════════════════════════════
rep('utd-block',
    """  static isMediaExt(ext: string): boolean {
    return MagicType.MEDIA_EXTS.indexOf(ext) >= 0;
  }""",
    """  static isMediaExt(ext: string): boolean {
    return MagicType.MEDIA_EXTS.indexOf(ext) >= 0;
  }

  /**
   * ★★ 5.1.52：**用 UTD 把 MIME 翻译成「系统认定的标准后缀列表」**。
   *
   * ## 链路（vivi 建议的方案）
   *   魔数 → MIME → `getUniformDataTypeByMIMEType` → `getTypeDescriptor`
   *        → `.filenameExtensions`（系统标准后缀列表）
   *
   * ## ⚠️ 为什么整段包在 try/catch 里（**必须**）
   *   SDK 文档对 `getUniformDataTypeByMIMEType` 的 `belongsTo` 参数写的是
   *   「**This parameter has no default value**」——
   *   它**可能不允许省略**，而传它需要先有一个 UTD id（循环依赖）。
   *   ⇒ 真机上到底能不能省略**未经验证**（写这份时设备离线），
   *     所以**必须**留回落路径：UTD 不可用时返回空数组，
   *     上层继续用自带的 `MAGIC_FALLBACK_EXT` 表判定。
   *   ★ 这样无论 UTD 是否可用，**功能都正确**，只是少一层系统背书。
   *
   * @returns 标准后缀列表（小写、无点）；不可用时返回空数组
   */
  static officialExtsOf(mime: string): string[] {
    try {
      // ★ 不传 belongsTo —— 若真机报 401 就走下面的 catch，行为不变
      const utd: string = uniformTypeDescriptor.getUniformDataTypeByMIMEType(mime);
      if (utd.length === 0) {
        return [];
      }
      const td = uniformTypeDescriptor.getTypeDescriptor(utd);
      if (td === null || td === undefined) {
        return [];
      }
      const raw: Array<string> = td.filenameExtensions;
      if (raw === null || raw === undefined || raw.length === 0) {
        return [];
      }
      const out: string[] = [];
      for (let i: number = 0; i < raw.length; i++) {
        const e: string = MagicType.rtrim(MagicType.stripDot(raw[i])).toLowerCase();
        if (e.length > 0) {
          out.push(e);
        }
      }
      return out;
    } catch (e) {
      // ★ 静默失败：真机上 401 属预期情况，不刷错误日志（每文件都会走这里）
      return [];
    }
  }

  private static stripDot(ext: string): string {
    return ext.startsWith('.') ? ext.substring(1) : ext;
  }

  /** MIME → 兜底扩展名（UTD 不可用时用；表在 Python 里用真实字节样本验过） */
  private static fallbackExtOf(mime: string): string {
    const m: string = mime.toLowerCase();
    const table: string[] = [
      'image/jpeg|jpg', 'image/png|png', 'image/gif|gif', 'image/bmp|bmp',
      'image/webp|webp', 'image/heic|heic', 'image/avif|avif', 'image/tiff|tiff',
      'video/mp4|mp4', 'video/quicktime|mov', 'video/x-m4v|m4v', 'video/3gpp|3gp',
      'video/x-matroska|mkv', 'video/x-msvideo|avi', 'video/x-flv|flv',
      'audio/mpeg|mp3', 'audio/mp4|m4a', 'audio/wav|wav', 'audio/ogg|ogg', 'audio/flac|flac',
    ];
    for (let i: number = 0; i < table.length; i++) {
      const kv: string[] = table[i].split('|');
      if (kv[0] === m) {
        return kv[1];
      }
    }
    return '';
  }

  /**
   * ★★ 5.1.52：判断「当前后缀是否需要改」——**以 UTD 为唯一判据**。
   *
   * ## 规则（vivi 选定的口径：只改「列表里没有的」）
   *   · 当前后缀**在** UTD 的 `filenameExtensions` 里 ⇒ **不动**
   *     （避免把用户熟悉的 `.jpeg` 统一改成 `.jpg`、`.m4v` 改成 `.mp4`）；
   *   · 当前后缀**不在**里，但标准列表里有一个扩展名可以替代 ⇒ 改成**第一个**；
   *   · UTD 不可用 ⇒ 回落：目标后缀 = 兜底表，且**仅当与当前不同**才改。
   *
   * @returns 需要改成的新扩展名；**不需要改返回空串**
   */
  static shouldRenameExt(currentExt: string, mime: string): string {
    const cur: string = MagicType.rtrim(currentExt).toLowerCase();
    const official: string[] = MagicType.officialExtsOf(mime);
    if (official.length > 0) {
      // ★ 当前后缀已被系统认定 ⇒ 不动
      if (official.indexOf(cur) >= 0) {
        return '';
      }
      return official[0];
    }
    // 回落：UTD 不可用
    const fb: string = MagicType.fallbackExtOf(mime);
    if (fb.length === 0 || fb === cur) {
      return '';
    }
    return fb;
  }""")

# ══════════════════════════════════════════════════════════════════
# ④ fixExtByMagic 改用 shouldRenameExt
# ══════════════════════════════════════════════════════════════════
rep('fix-use-utd',
    """  static fixExtByMagic(path: string): string {
    try {
      const real: string = MagicType.probe(path);
      if (real.length === 0 || !MagicType.isMediaExt(real)) {
        return path;
      }
      const slash: number = path.lastIndexOf('/');
      const base: string = slash >= 0 ? path.substring(slash + 1) : path;
      const dir: string = slash >= 0 ? path.substring(0, slash) : '';
      const dot: number = base.lastIndexOf('.');
      // ★ 已有后缀且与探测一致 ⇒ 什么都不做（最常见路径，零开销）
      if (dot > 0 && base.substring(dot + 1).toLowerCase() === real) {
        return path;
      }
      // ★ 无后缀也要加：`a.jpg (1)` 剥完可能是 `无后缀` 的形态
      const stem: string = dot > 0 ? base.substring(0, dot) : base;
      const target: string = `${dir}/${stem}.${real}`;""",
    """  static fixExtByMagic(path: string): string {
    try {
      const mime: string = MagicType.probe(path);
      if (mime.length === 0) {
        return path;
      }
      const slash: number = path.lastIndexOf('/');
      const base: string = slash >= 0 ? path.substring(slash + 1) : path;
      const dir: string = slash >= 0 ? path.substring(0, slash) : '';
      const dot: number = base.lastIndexOf('.');
      const cur: string = dot > 0 ? base.substring(dot + 1).toLowerCase() : '';
      // ★★ 5.1.52：要不要改、改成什么，**交给 UTD 判**
      //   （内部：当前后缀已在系统标准列表里 ⇒ 返回空串 ⇒ 不动）
      const want: string = MagicType.shouldRenameExt(cur, mime);
      if (want.length === 0) {
        return path;
      }
      // ★ 无后缀也要加：`a.jpg (1)` 剥完可能是无后缀形态
      const stem: string = dot > 0 ? base.substring(0, dot) : base;
      const target: string = `${dir}/${stem}.${want}`;""")

rep('fix-log',
    """        Log.w(TAG, `魔数纠错：${base} → ${stem}.${real} 但目标已存在，放弃`);""",
    """        Log.w(TAG, `魔数纠错：${base} → ${stem}.${want} 但目标已存在，放弃`);""")

rep('fix-log2',
    """      fileIo.renameSync(path, target);
      Log.i(TAG, `魔数纠错：${base} → ${stem}.${real}`);""",
    """      fileIo.renameSync(path, target);
      // ★ 日志带上 MIME 与来源（UTD / 回落），真机排障时能一眼看出走的是哪条路
      const via: string = MagicType.officialExtsOf(mime).length > 0 ? 'UTD' : '回落表';
      Log.i(TAG, `魔数纠错：${base}(${mime}) → ${stem}.${want} [${via}]`);""")

# ══════════════════════════════════════════════════════════════════
# ⑤ 批量版：TaskPool + 信号量限流
# ══════════════════════════════════════════════════════════════════
rep('batch',
    """      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `魔数纠错失败（保持原名）: ${err.code} ${err.message}`);
      return path;
    }
  }
}""",
    """      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `魔数纠错失败（保持原名）: ${err.code} ${err.message}`);
      return path;
    }
  }

  /**
   * ★★ 5.1.52：**批量**纠正后缀（vivi 建议的 TaskPool + 信号量限流）。
   *
   * ## 为什么只在「批量」时才搬 TaskPool
   *   单文件纠正是「读 16 字节 + 一次 rename」，µs 级；
   *   搬到 taskpool 的**启动开销（序列化 + 线程调度）比 IO 本身还大**。
   *   ⇒ 接收路径的 `fixExtByMagic` **仍留主线程**。
   *   ⚠️ 与本项目 5.1.38 的教训一致：多一次 `await` ⇒ microtask 优先于
   *     宏任务（vsync/定时器）⇒ 反而更难让渲染插入。
   *
   * ## 并发为什么必须限
   *   taskpool 线程池是**共享**的（默认容量有限）；
   *   一次丢几百个任务进去会**挤占同池的其他业务**（本项目还有传输在跑），
   *   吞吐反而下降。⇒ 用**信号量**把并发压到 `BATCH_IO_CONCURRENCY`。
   *
   * @param paths 待处理路径数组
   * @param concurrency 最大并发 I/O 数（≤0 时用默认 4）
   * @returns 与入参**等长**的结果数组（每项是最终路径；失败项 = 原路径）
   */
  static async fixExtOfMany(paths: string[], concurrency: number = 0): Promise<string[]> {
    const n: number = paths.length;
    const out: string[] = new Array<string>(n);
    if (n === 0) {
      return out;
    }
    const limit: number = concurrency > 0 ? concurrency : MagicType.BATCH_IO_CONCURRENCY;
    // ★ 朴素信号量：只用「已启动任务数」这一个计数就够了
    //   （全部 await 完才进下一轮，不需要可重入的 acquire/release）
    let next: number = 0;
    let running: number = 0;
    let failed: number = 0;
    const worker: () => Promise<void> = async (): Promise<void> => {
      while (true) {
        const i: number = next;
        next += 1;
        if (i >= n) {
          return;
        }
        try {
          const fixed: string = await taskpool.execute(
            MagicType.renameWorker, 0, paths[i]);
          out[i] = fixed;
        } catch (e) {
          // 单个失败不影响整批
          out[i] = paths[i];
          failed += 1;
        }
        running -= 1;
        if (next >= n && running <= 0) {
          return;
        }
      }
    };
    const tasks: Array<Promise<void>> = [];
    for (let k: number = 0; k < limit && k < n; k++) {
      running += 1;
      tasks.push(worker());
    }
    await Promise.all(tasks);
    Log.i(TAG, `批量魔数纠错：共 ${n} 个，成功 ${n - failed} 个，失败 ${failed} 个（并发 ${limit}）`);
    return out;
  }

  /**
   * ★ 跑在 **taskpool worker 线程**里的重命名任务。
   *
   * ## 为什么它必须是**静态方法**且**只传原始类型**
   *   ArkTS 的 taskpool 只支持 `Function`（`@Concurrent` 函数或静态方法），
   *   **参数必须可序列化**（string / number / boolean）。
   *   ⇒ 传 `this` 或对象一律报错。
   * ⚠️ 编译要求：静态方法体里**不能**引用外部 import 之外的实例状态；
   *   这里的 `Log` / `fileIo` 都是模块级 import，允许。
   */
  private static async renameWorker(path: string): Promise<string> {
    return MagicType.fixExtByMagic(path);
  }

  /** ★ 批量 I/O 的默认并发上限（可被调用方覆盖） */
  static readonly BATCH_IO_CONCURRENCY: number = 4;
}""")

# ══════════════════════════════════════════════════════════════════
# ⑥ 版本号
# ══════════════════════════════════════════════════════════════════
rep('APP:ver',
    """    "versionCode": 5000151,
    "versionName": "5.1.51\"""",
    """    "versionCode": 5000152,
    "versionName": "5.1.52\"""")

# ══════════════════════════════════════════════════════════════════
cur = {'FS': fs, 'APP': app}
owner = {}
for t, _o, _n in B:
    owner[t] = ('APP' if t.startswith('APP:') else 'FS')

for tag, old, new in B:
    n = cur[owner[tag]].count(old)
    assert n == 1, '%s count=%d (期望 1)' % (tag, n)
for tag, old, new in B:
    f = owner[tag]
    cur[f] = cur[f].replace(old, new, 1)

fs, app = cur['FS'], cur['APP']

def code_only(x):
    x = re.sub(r'/\*.*?\*/', '', x, flags=re.S)
    return re.sub(r'//[^\n]*', '', x)
cf = code_only(fs)

assert 'uniformTypeDescriptor.getUniformDataTypeByMIMEType(mime)' in cf, 'UTD 查询缺失'
assert 'td.filenameExtensions' in cf, 'filenameExtensions 未用'
assert 'static shouldRenameExt(' in cf, 'shouldRenameExt 缺失'
assert 'official.indexOf(cur) >= 0' in cf, '「列表里没有才改」规则缺失'
assert 'static fallbackExtOf(' in cf, '回落表缺失'
assert 'static async fixExtOfMany(' in cf, '批量版缺失'
assert 'taskpool.execute(' in cf, 'taskpool 未用'
assert 'BATCH_IO_CONCURRENCY' in cf, '信号量并发上限缺失'
assert 'private static async renameWorker(' in cf, 'worker 缺失'
assert cf.count("return 'image/jpeg';") == 1, 'MIME 映射未改'
assert cf.count("return 'video/mp4';") == 1, 'MIME 映射未改全'
assert "'5.1.52'" in app, '版本未改'

for p_, s_ in ((FS, fs), (APP, app)):
    assert '\r' not in s_, '%s 含 CR' % p_
    io.open(p_, 'w', encoding='utf-8', newline='\n').write(s_)

print('改块数 :', len(B))
print('MIME 常量 : image/* %d, video/* %d, audio/* %d' % (
    cf.count("return 'image/"), cf.count("return 'video/"), cf.count("return 'audio/")))
print('UTD + 回落 + TaskPool 批量 : 全部到位')
print('OK 5.1.52 applied')