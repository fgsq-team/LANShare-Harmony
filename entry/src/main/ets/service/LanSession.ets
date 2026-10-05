/**
 * 前台会话管理 —— 替代 Android 的「前台 Service + WakeLock + MulticastLock」
 *
 * ## 决策（vivi 2026-09-30 拍板）
 * > 不上应用市场；文件浏览走用户授权目录；**暂不做后台保活，需要传输时手动打开软件**。
 *
 * 这条决策把整个迁移里最难的一块（后台常驻）直接摘掉了，代价是产品形态从
 * 「装了就待命」变成「打开才提供服务」。这是需求层面的选择，不是技术妥协。
 *
 * ## Android 侧的三件保活机制，在鸿蒙侧如何处置
 * | Android 机制 | 作用 | 鸿蒙侧处置 |
 * |---|---|---|
 * | `startForeground()` 前台 Service | 让进程不被杀 | ❌ 不做。改为「应用可见时才提供服务」 |
 * | `PowerManager.WakeLock` | 传输时不息屏 | ✅ **保留等价能力**：`Window.setWindowKeepScreenOn(true)` |
 * | `WifiManager.MulticastLock` | 让组播能收进来 | ✅ 不需要。鸿蒙 socket 无此限制 |
 * | `backgroundTaskManager` 长时任务 | 唯一合法后台通道 | ❌ 不申请（本项目不需要，也免去实况窗 10 分钟心跳的硬约束） |
 *
 * 为什么保留「屏幕常亮」：用户的实际使用姿势是**打开应用、把页面停在屏上、
 * 让别的设备连过来传文件**。这条路径上唯一真正的敌人是息屏 —— 息屏后系统
 * 会让应用进入后台/冻结，TCP 监听就断了。所以 `setWindowKeepScreenOn`
 * 是「不做后台保活」前提下性价比最高的一步，等价于原来 WakeLock 的作用。
 *
 * ## 权限影响（相比之前的方案，可以少要一个重量级权限）
 * 不再声明 `ohos.permission.KEEP_BACKGROUND_RUNNING`，`module.json5` 里的
 * `backgroundModes: ["dataTransfer"]` 也一并移除。用户首次运行不会看到
 * 「允许后台运行」的授权弹窗。
 */
import { common } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';
import { LanConfig } from '../core/LanConfig';

const TAG: string = 'LanSession';

/** 会话统计，喂给 UI（屏幕上的实时数据） */
export class SessionStats {
  /** 已连接的对端设备数 */
  connectedDevices: number = 0;
  /** 累计收发字节 */
  transferredBytes: number = 0;
  /** HTTP 网页端请求数 */
  webClients: number = 0;
  /** 会话启动时间（毫秒时间戳） */
  startedAtMs: number = 0;

  /** 已运行时长，格式 HH:MM */
  get uptimeText(): string {
    if (this.startedAtMs === 0) {
      return '00:00';
    }
    const totalSec: number = Math.floor((Date.now() - this.startedAtMs) / 1000);
    const h: number = Math.floor(totalSec / 3600);
    const m: number = Math.floor((totalSec % 3600) / 60);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
  }

  /** 累计传输量的人类可读形式 */
  get transferredText(): string {
    const b: number = this.transferredBytes;
    if (b < 1024) {
      return `${b} B`;
    }
    if (b < 1024 * 1024) {
      return `${(b / 1024).toFixed(1)} KB`;
    }
    if (b < 1024 * 1024 * 1024) {
      return `${(b / 1024 / 1024).toFixed(1)} MB`;
    }
    return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }
}

/**
 * 前台会话。生命周期与 UIAbility 的「可见」状态绑定：
 *   onForeground 起（或保持）-> onBackground 停。
 */
export class LanSession {
  private context: common.UIAbilityContext | null = null;
  private running: boolean = false;
  /** 屏幕常亮是否已置位，避免重复调用系统接口 */
  private screenOnSet: boolean = false;

  readonly stats: SessionStats = new SessionStats();

  /** 状态变化回调（供 UI 展示） */
  private onStateChange: ((running: boolean, message: string) => void) | null = null;

  setOnStateChange(cb: (running: boolean, message: string) => void): void {
    this.onStateChange = cb;
  }

  private notify(running: boolean, message: string): void {
    Log.i(TAG, `[session] running=${running} ${message}`);
    if (this.onStateChange !== null) {
      this.onStateChange(running, message);
    }
  }

  get isRunning(): boolean {
    return this.running;
  }

  /**
   * 开启共享会话。由 UI 的「开始共享」按钮触发（用户主动行为）。
   * 与之前的长时任务版本相比，这里**没有任何系统权限申请**，只是记账 + 屏幕常亮。
   */
  async startSession(ctx: common.UIAbilityContext): Promise<boolean> {
    if (this.running) {
      return true;
    }
    this.context = ctx;
    this.stats.startedAtMs = Date.now();
    this.running = true;

    await this.applyKeepScreenOn(true);

    this.notify(true, LanConfig.KEEP_SCREEN_ON_WHILE_SHARING
      ? '共享已开启（已开启屏幕常亮，请保持本页在前台）'
      : '共享已开启（请保持本页在前台）');
    return true;
  }

  /**
   * 结束会话。以下情形必须调用，否则会留下屏幕常亮和未释放的监听端口：
   *   - 用户点「停止共享」
   *   - 应用退到后台（见 EntryAbility.onBackground）
   *   - UIAbility 被销毁
   */
  async stopSession(): Promise<void> {
    if (!this.running) {
      return;
    }
    this.running = false;
    this.stats.startedAtMs = 0;

    await this.applyKeepScreenOn(false);

    this.notify(false, '共享会话已结束');
  }

  /** 会话统计刷新后由业务层调用 */
  updateStats(connected: number, bytes: number, webClients: number): void {
    this.stats.connectedDevices = connected;
    this.stats.transferredBytes = bytes;
    this.stats.webClients = webClients;
  }

  /** UI 上显示的一行状态文案 */
  statusLine(): string {
    return `前置运行 · ${this.stats.connectedDevices} 台设备 · ${this.stats.transferredText} · ${this.stats.uptimeText}`;
  }

  /**
   * 屏幕常亮开关。
   *
   * 等价于 Android 的 `PowerManager.WakeLock`（SCREEN_DIM_WAKE_LOCK）。
   * 用 `window.getLastWindow(ctx)` 拿当前窗口再置位；拿不到窗口不是致命错误，
   * 只是退化成「会息屏」，所以这里吞掉异常仅记日志。
   */
  private async applyKeepScreenOn(on: boolean): Promise<void> {
    if (!LanConfig.KEEP_SCREEN_ON_WHILE_SHARING) {
      return;
    }
    if (this.screenOnSet === on) {
      return;
    }
    if (this.context === null) {
      return;
    }
    try {
      const win: window.Window = await window.getLastWindow(this.context);
      await win.setWindowKeepScreenOn(on);
      this.screenOnSet = on;
      Log.i(TAG, `屏幕常亮 = ${on}`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // 常见于窗口尚未创建完成。不影响网络服务本身，只影响是否息屏
      Log.w(TAG, `设置屏幕常亮失败(${on}): ${err.code} ${err.message}`);
    }
  }

  /**
   * 释放时兜底：调用方即使漏了 stopSession，这里也要把屏幕常亮恢复，
   * 否则会留下「应用已退出但屏幕不灭」的脏状态。
   */
  async dispose(): Promise<void> {
    this.screenOnSet = false;
    this.running = false;
    if (this.context !== null) {
      try {
        const win: window.Window = await window.getLastWindow(this.context);
        await win.setWindowKeepScreenOn(false);
      } catch (e) {
        // 窗口可能已销毁，忽略
      }
    }
    this.context = null;
  }
}
