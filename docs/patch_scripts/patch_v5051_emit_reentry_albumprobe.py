# -*- coding: utf-8 -*-
"""
5.0.51 补丁
  ① emit 同步重入保护（根治「同秒 200 条日志 + 传输突然不能传」）
  ② onSnapshot 里 lastHadTransferText 的赋值顺序（重入源头之一）
  ③ flushAutoSave：闸门提前关门 + 「等落盘」重试加硬边界（6 次 / 60 秒）+ 日志限频
  ④ albumAssetAlive：换成「stat + 只读读字节」多信号探活（5.0.49 的写打开探活无效）

幂等：哨兵 '5.0.51' 出现即跳过。
先全部校验、内存构造结果、末尾统一落盘；写回按原行尾（工程源文件 LF）。
"""
import io
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
F_SVC = ROOT + r'\entry\src\main\ets\service\LanService.ets'
F_IDX = ROOT + r'\entry\src\main\ets\pages\Index.ets'
F_APP = ROOT + r'\AppScope\app.json5'

SENTINEL = '5.0.51'


def rd(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        return f.read()


edits = []   # (path, old, new, 标签)


# ======================================================================
# LanService.ets
# ======================================================================

# --- ①-a 新增 emit 重入保护字段 ---
OLD = """  /** 已排队的合并刷新定时器句柄，-1 = 无 */
  private pendingEmitTimer: number = -1;
"""
NEW = """  /** 已排队的合并刷新定时器句柄，-1 = 无 */
  private pendingEmitTimer: number = -1;

  // ---------------- 5.0.51：emit 同步重入保护 ----------------
  /**
   * ★★ `emit()` 是**同步**把快照推给所有监听者，而监听者（Index.onSnapshot）
   *   里又可能调回页面层方法；页面的 `flushAutoSave()` 每步都 `logAuto()`，
   *   而 `logAuto()` 是**打完日志立刻 emit()** 的。于是一条完整的同步互相递归
   *   就成立了（vivi 2026-10-02 真机实测：同一秒刷出 200 条同一句
   *   「队列 1 项暂未解析出沙箱路径」，恰好把 200 条容量的日志环整个填满，
   *   紧接着传输就彻底不动了）：
   *
   *     flushAutoSave() -> logAuto() -> emit()
   *       -> onSnapshot() -> refreshReceived() -> flushAutoSave() -> logAuto() -> ...
   *
   *   驱动它的是 `onSnapshot` 里那句 `this.lastHadTransferText = hadTransfer;`
   *   写在 `refreshReceived()` **之后** —— 重入进来的那次看到的还是「刚才有传输」，
   *   于是又走一遍同一条分支，永远退不出来。（那处顺序也照修，见 Index.ets）
   *
   *   这里做**全局**兜底：正在 emit 时再进来的 emit 只登记一次「还要再刷」，
   *   等本次发完用 setTimeout 补一次。同步递归从此不可能发生。
   */
  private emitting: boolean = false;
  private emitQueued: boolean = false;
"""
edits.append((F_SVC, OLD, NEW, 'LanService 重入保护字段'))

# --- ①-b emit() 拆成「外壳 + emitInner」---
OLD = """  private emit(): void {
    // 刷新派生字段
    this.snapshot.state = this.state;"""
NEW = """  private emit(): void {
    // 5.0.51：★ 重入保护（见 `emitting` 字段的注释）。
    //   同步回调链里任何一环再次触发 emit，都只登记「补刷」一次，
    //   绝不在当前这一层里套进去 —— 那会变成无限递归 + 把日志环刷满。
    if (this.emitting) {
      this.emitQueued = true;
      return;
    }
    this.emitting = true;
    try {
      this.emitInner();
    } finally {
      this.emitting = false;
    }
    if (this.emitQueued) {
      this.emitQueued = false;
      // 延后一帧再补：此时监听者已经把「上次有没有传输」这类状态更新完了，
      // 不会再重走同一条分支（两帧内必定收敛）。
      setTimeout(() => {
        this.emit();
      }, 0);
    }
  }

  /** 真正下发快照（**只许 `emit()` 调**，外面别直接用它，绕开重入保护） */
  private emitInner(): void {
    // 刷新派生字段
    this.snapshot.state = this.state;"""
edits.append((F_SVC, OLD, NEW, 'emit 重入保护'))

# --- ①-c subscribe 去重（同一实例重复进页面时不叠加监听）---
OLD = """  subscribe(fn: (s: ServiceSnapshot) => void): void {
    this.listeners.push(fn);
    fn(this.snapshot);
  }"""
NEW = """  subscribe(fn: (s: ServiceSnapshot) => void): void {
    // 5.0.51：同一函数重复订阅只登记一次 —— 监听者被叠加 N 份时，
    //   一次 emit 会触发 N 次 onSnapshot（含 N 次 refreshReceived），
    //   是日志风暴的放大器。
    if (this.listeners.indexOf(fn) < 0) {
      this.listeners.push(fn);
    }
    fn(this.snapshot);
  }"""
edits.append((F_SVC, OLD, NEW, 'subscribe 去重'))


# ======================================================================
# Index.ets
# ======================================================================

# --- ③-a 新增重试边界字段 ---
OLD = """  /** 5.0.50：`autoSaveBusy` 置位的时刻 —— 用于「卡死看门狗」（见 flushAutoSave） */
  private autoSaveBusySince: number = 0;
"""
NEW = """  /** 5.0.50：`autoSaveBusy` 置位的时刻 —— 用于「卡死看门狗」（见 flushAutoSave） */
  private autoSaveBusySince: number = 0;

  // ---------------- 5.0.51：自动存相册「等落盘」重试的硬边界 ----------------
  /**
   * ★ 每个 id 已经「空手而归」试了几次 / 第一次进队列的时刻。
   *
   *   5.0.47 起 `flushAutoSave` 把解析不出路径的项**留在队列里**等下一次刷新 ——
   *   方向是对的（文件落盘确实要时间），但**没有上限**：
   *   一旦某个 id 的路径**永远**解析不出来（落盘名被加了 `(1)` 去重后缀、
   *   或消息 content 是「3 个文件」而 files 为空），这个队列就**永远是热的**：
   *   每次刷新都打一条日志 -> 每次都 emit -> 配合 emit 重入就是一场风暴。
   *
   *   给重试加**硬边界**：6 次 或 60 秒仍解析不出 -> 结案放弃、从队列移除。
   */
  private autoSaveTry: Map<string, number> = new Map<string, number>();
  private autoSaveFirstMs: Map<string, number> = new Map<string, number>();
  /** 上一条「暂未解析出沙箱路径」日志的原文与时刻 —— 同样内容 5 秒内只打一次 */
  private autoSaveWaitLog: string = '';
  private autoSaveWaitLogAt: number = 0;
"""
edits.append((F_IDX, OLD, NEW, 'Index 重试边界字段'))

# --- ② lastHadTransferText 赋值顺序 ---
OLD = """    if (this.lastHadTransferText && !hadTransfer) {
      this.refreshReceived();
    }
    this.lastHadTransferText = hadTransfer;"""
NEW = """    // ⚠️ 5.0.51：**先把标志落到新值，再去刷新**。反过来写（原来那样）会造成
    //   同步重入：refreshReceived 里打一条 UI 日志 -> logAuto 立刻 emit ->
    //   重入到本方法 -> 这时标志还是旧值「刚才有传输」-> 又走一次 refreshReceived
    //   -> ... 无限递归（真机表现：同一秒 200 条同句日志，之后传输再也起不来）。
    const wasTransfer: boolean = this.lastHadTransferText;
    this.lastHadTransferText = hadTransfer;
    if (wasTransfer && !hadTransfer) {
      this.refreshReceived();
    }"""
edits.append((F_IDX, OLD, NEW, 'onSnapshot 标志顺序'))

# --- ③-b flushAutoSave：重试边界 + 闸门提前关 + 日志限频 ---
OLD = """    const paths: string[] = [];
    const owners: string[] = [];
    const ready: string[] = [];
    for (let i: number = 0; i < this.autoSavePending.length; i++) {
      const id: string = this.autoSavePending[i];
      const m: ChatMessage | undefined = this.msgById(id);
      if (m === undefined) {
        this.autoSaveHandled.add(id);
        continue;
      }
      const ps: string[] = this.resolveMediaPaths(m);
      if (ps.length === 0) {
        // 文件还没进索引 —— 留在队列里，等下一次 refreshReceived
        continue;
      }
      for (let k: number = 0; k < ps.length; k++) {
        if (paths.indexOf(ps[k]) < 0) {
          paths.push(ps[k]);
          owners.push(id);
        }
      }
      ready.push(id);
    }
    if (paths.length === 0) {
      this.service.logAuto(`队列 ${this.autoSavePending.length} 项暂未解析出沙箱路径（等文件落盘后再试）`);
      return;
    }
    this.service.logAuto(`准备弹存相册确认框：${paths.length} 个文件`);
    this.autoSaveBusy = true;
    this.autoSaveBusySince = Date.now();"""
NEW = """    const paths: string[] = [];
    const owners: string[] = [];
    const ready: string[] = [];
    const now: number = Date.now();
    const expired: string[] = [];
    for (let i: number = 0; i < this.autoSavePending.length; i++) {
      const id: string = this.autoSavePending[i];
      const m: ChatMessage | undefined = this.msgById(id);
      if (m === undefined) {
        this.autoSaveHandled.add(id);
        continue;
      }
      const ps: string[] = this.resolveMediaPaths(m);
      if (ps.length === 0) {
        // 文件还没进索引 —— 留在队列里，等下一次 refreshReceived。
        // 5.0.51：但**不能无限等** —— 见 `autoSaveTry` 上的注释。
        const n: number = (this.autoSaveTry.get(id) ?? 0) + 1;
        this.autoSaveTry.set(id, n);
        if (!this.autoSaveFirstMs.has(id)) {
          this.autoSaveFirstMs.set(id, now);
        }
        const waited: number = now - (this.autoSaveFirstMs.get(id) ?? now);
        if (n >= 6 || waited > 60000) {
          expired.push(id);
        }
        continue;
      }
      for (let k: number = 0; k < ps.length; k++) {
        if (paths.indexOf(ps[k]) < 0) {
          paths.push(ps[k]);
          owners.push(id);
        }
      }
      ready.push(id);
    }
    if (expired.length > 0) {
      // 结案放弃：不再占着队列、不再刷日志（否则就是永久热循环）
      for (let i: number = 0; i < expired.length; i++) {
        this.autoSaveHandled.add(expired[i]);
        this.autoSaveTry.delete(expired[i]);
        this.autoSaveFirstMs.delete(expired[i]);
      }
      const rest0: string[] = [];
      for (let i: number = 0; i < this.autoSavePending.length; i++) {
        if (!this.autoSaveHandled.has(this.autoSavePending[i])) {
          rest0.push(this.autoSavePending[i]);
        }
      }
      this.autoSavePending = rest0;
      this.service.logAuto(`放弃等待落盘 ${expired.length} 项`
        + `（重试 6 次 / 60 秒仍未解析出路径），已从队列移除`);
    }
    if (paths.length === 0) {
      this.noteAutoSaveWaiting();
      return;
    }
    // 5.0.51：闸门必须在**打日志之前**关门 —— logAuto 会立刻 emit，
    //   重入进来的 flushAutoSave 若看到闸门还开着，就会再解析、再打日志。
    this.autoSaveBusy = true;
    this.autoSaveBusySince = Date.now();
    this.service.logAuto(`准备弹存相册确认框：${paths.length} 个文件`);"""
edits.append((F_IDX, OLD, NEW, 'flushAutoSave 边界与限频'))

# --- ③-c 新增 noteAutoSaveWaiting（放在 msgById 之前）---
OLD = """  /** 消息 id -> 消息（聊天条数不多，线性找即可） */
  private msgById(id: string): ChatMessage | undefined {"""
NEW = """  /**
   * 「队列里还有项、但路径还没解析出来」这条日志的**限频器**（5.0.51）。
   *
   * 真正的重试在 `flushAutoSave` 里（由刷新驱动）；这里只保证：
   * 同样的内容 5 秒内最多打一条。日志环只有 200 条，
   * 一条刷屏日志会把真正的线索全部挤掉 —— vivi 2026-10-02 就是这么丢掉现场的。
   */
  private noteAutoSaveWaiting(): void {
    const msg: string =
      `队列 ${this.autoSavePending.length} 项暂未解析出沙箱路径（等文件落盘后再试）`;
    const at: number = Date.now();
    if (msg === this.autoSaveWaitLog && at - this.autoSaveWaitLogAt < 5000) {
      return;
    }
    this.autoSaveWaitLog = msg;
    this.autoSaveWaitLogAt = at;
    this.service.logAuto(msg);
  }

  /** 消息 id -> 消息（聊天条数不多，线性找即可） */
  private msgById(id: string): ChatMessage | undefined {"""
edits.append((F_IDX, OLD, NEW, 'noteAutoSaveWaiting'))

# --- ③-d 成功后清理重试计数（放在 batch finally 的结案处）---
OLD = """      if (!failed) {
        for (let i: number = 0; i < ready.length; i++) {
          this.autoSaveHandled.add(ready[i]);
        }
      }"""
NEW = """      if (!failed) {
        for (let i: number = 0; i < ready.length; i++) {
          this.autoSaveHandled.add(ready[i]);
          // 5.0.51：结案了就清掉重试计数，避免表无限增长
          this.autoSaveTry.delete(ready[i]);
          this.autoSaveFirstMs.delete(ready[i]);
        }
      }"""
edits.append((F_IDX, OLD, NEW, '结案清理重试计数'))

# --- ④ albumAssetAlive 重写 ---
OLD = """  private albumAssetAlive(uri: string): boolean {
    if (uri.length === 0) {
      return false;
    }
    let f: fileIo.File | null = null;
    try {
      // \u26a0\ufe0f 用「**写**打开」探活，不是「读打开」：
      //    `showAssetsCreationDialog` 给回来的是**写授权** URI ——
      //    读它本来就可能被拒（权限拒绝 \u2260 文件不存在，会把「已删除」误判成「还在」）。
      //    写授权我们一定有，所以只有「文件真的没了」才会失败。
      // \u26a0\ufe0f 不带 TRUNC：只是打开探一下，绝不能改内容。
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
  }"""
NEW = """  private albumAssetAlive(uri: string): boolean {
    if (uri.length === 0) {
      return false;
    }
    const codes: string[] = [];
    // 信号\u2460：stat（首选。不写内容、不创建任何东西；size>0 就确定还在）
    let statSize: number = -1;
    try {
      const st: fileIo.Stat = fileIo.statSync(uri);
      statSize = st.size;
      if (st.size > 0) {
        return true;
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      codes.push(`stat=${err.code}`);
    }
    // 信号\u2461：只读打开，并且**真读几个字节**（读得到内容才算在）
    let f: fileIo.File | null = null;
    try {
      f = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      const buf: ArrayBuffer = new ArrayBuffer(16);
      const n: number = fileIo.readSync(f.fd, buf);
      if (n > 0) {
        return true;
      }
      codes.push('read=0');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      codes.push(`open=${err.code}`);
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
    // 两个信号**全都失败** -> 判定「已从相册删除」。原始错误码写进 UI 日志，
    //   下一次真机日志就能给出平台真相（写打开这条路已证伪，不再采信）。
    this.service.logAuto(`相册探活判定已删除（statSize=${statSize}，信号: ${codes.join(' ')}）：${uri}`);
    return false;
  }"""
edits.append((F_IDX, OLD, NEW, 'albumAssetAlive 多信号探活'))


# ======================================================================
# app.json5
# ======================================================================
APP_OLD = """    "versionCode": 5000050,
    "versionName": "5.0.50","""
APP_NEW = """    "versionCode": 5000051,
    "versionName": "5.0.51","""
edits.append((F_APP, APP_OLD, APP_NEW, 'app.json5 版本号'))


# ======================================================================
# 执行：先全部校验，再统一落盘
# ======================================================================
cache = {}
for path in (F_SVC, F_IDX, F_APP):
    cache[path] = rd(path)
    if SENTINEL in cache[path]:
        print('ALREADY APPLIED (哨兵 %s 已存在于 %s)' % (SENTINEL, path))
        sys.exit(0)

problems = []
for path, old, new, tag in edits:
    s = cache[path]
    if s.count(old) != 1:
        problems.append('[%s] 锚点命中 %d 次（应为 1）: %s' % (tag, s.count(old), old.splitlines()[0][:70]))
    if new in s:
        problems.append('[%s] 新文本已存在（重复插入风险）' % tag)
if problems:
    print('校验失败，未做任何改动：')
    for p in problems:
        print('  - ' + p)
    sys.exit(1)

for path, old, new, tag in edits:
    s = cache[path]
    cache[path] = s.replace(old, new, 1)
    print('  + %s' % tag)

for path in (F_SVC, F_IDX, F_APP):
    body = cache[path]
    crlf = body.count('\r\n')
    body = body.replace('\r\n', '\n')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    print('  写入 %s（原有 CRLF %d 处已归一为 LF）' % (path.split('\\')[-1], crlf))

print('OK: 5.0.51 已应用')
