/**
 * 应用入口 UIAbility
 *
 * 对应 Android 的 App.java（Application 子类）+ 启动 Activity。
 *
 * ## 生命周期策略（vivi 2026-09-30 决策后重写）
 * 决策是「不做后台保活，需要传输时手动打开软件」。这直接决定了这里怎么写：
 *
 * | 回调 | 旧方案（长时任务） | 现方案（纯前台） |
 * |---|---|---|
 * | onForeground | 什么都不做（靠长时任务续命） | **自动恢复上次的共享会话**（若之前被后台停掉） |
 * | onBackground | 什么都不做，会话继续跑 | **主动停服**：释放端口 + 关闭现有连接 + 关掉屏幕常亮 |
 * | onDestroy | 停服（释放长时任务） | 停服 + 兜底复位屏幕常亮 |
 *
 * ### 为什么退到后台要主动停服，而不是"不管它"
 * 鸿蒙对普通应用退到后台后会做**冻结**（进程挂起、socket 不再被调度）。
 * 如果不管它，结果是最坏的一种：端口还占着、TCP 连接既没关也没断，
 * 浏览器那边表现为"卡住直到超时"。主动停服后连接被干净关闭，
 * 对端立刻知道传输中断，用户重新打开应用即可重试。
 *
 * ### 为什么回前台要自动恢复
 * 恢复不需要任何权限、也不产生后台行为，纯粹是重新 bind 端口 + 起 UDP 发现。
 * 用户切出去接个电话再切回来，不用再点一次「开始共享」。
 */
import { AbilityConstant, UIAbility, Want, errorManager } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';
import { LanConfig } from '../core/LanConfig';
import { LanService } from '../service/LanService';

const TAG: string = 'EntryAbility';

/**
 * 5.0.49：构造「未捕获异常观察者」。
 *
 * ⚠️ 为什么写成对象字面量而不是 `extends ErrorObserver`：
 *    SDK 里 `ErrorObserver` 只以 `errorManager.ErrorObserver`（`export type`）的形式
 *    暴露，而 **AbilityKit 只导出 errorManager 的值、不导出这个类型** ——
 *    `class X extends errorManager.ErrorObserver` / `import ErrorObserver from
 *    '@ohos.app.ability.ErrorObserver'` 两条路都编不过（实测 10505001）。
 *    改成直接传一个「方法名/签名对齐」的对象字面量即可，运行时是按方法名回调的。
 *
 * 「接收图片概率性闪退」在真机上表现为**进程直接消失**，什么都抓不到。
 * 注册这个回调后，ArkTS 层任何未捕获异常（含未处理的 Promise rejection）
 * 都会先经过这里 —— 栈被写进应用内日志文件，重启后还能读回来，
 * 用户点一次「复制日志」就能把它发出来。
 */
function buildCrashObserver(): errorManager.ErrorObserver {
  return {
    onUnhandledException: (errMsg: string): void => {
      Log.e(TAG, `未捕获异常: ${errMsg}`);
      LanService.get().crashLog(`未捕获异常：${errMsg}`);
    },
    onException: (errObject: Error): void => {
      const stack: string = errObject.stack === undefined ? '' : errObject.stack;
      Log.e(TAG, `JS 异常: ${errObject.message}`);
      LanService.get().crashLog(`JS 异常：${errObject.message} @ ${stack}`);
    }
  };
}

export default class EntryAbility extends UIAbility {
  /**
   * 标记「这次的停服是退后台导致的」。
   * 只有它置位时才在回前台时自动恢复 —— 用户手动点过「停止共享」的，
   * 回前台不应该擅自又开起来。
   */
  private stoppedByBackground: boolean = false;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    Log.i(TAG, 'EntryAbility onCreate');
    // 5.0.49：注册未捕获异常回调（崩溃取证）。失败也不能影响启动。
    try {
      errorManager.on('error', buildCrashObserver());
      Log.i(TAG, '未捕获异常回调已注册');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `注册未捕获异常回调失败: ${err.code} ${err.message}`);
    }
  }

  onDestroy(): void {
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

  onWindowStageCreate(windowStage: window.WindowStage): void {
    // 沉浸式：内容延伸到状态栏底下，浅色主题用深色前景
    try {
      const win: window.Window = windowStage.getMainWindowSync();
      win.setWindowLayoutFullScreen(true);
      win.setWindowSystemBarProperties({
        statusBarContentColor: '#000000',
        navigationBarContentColor: '#000000'
      });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `设置窗口属性失败: ${err.code} ${err.message}`);
    }

    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code !== 0) {
        Log.e(TAG, `加载首页失败: ${err.code} ${err.message}`);
        return;
      }
      Log.i(TAG, '首页已加载');
    });
  }

  onWindowStageDestroy(): void {
    Log.i(TAG, 'EntryAbility onWindowStageDestroy');
  }

  /**
   * 回到前台：如果上次是被系统退后台打断的，这里自动恢复。
   * 恢复动作本身没有任何权限门槛，只是重新监听端口。
   */
  onForeground(): void {
    Log.i(TAG, `onForeground（上次是否被后台打断: ${this.stoppedByBackground}）`);
    if (!this.stoppedByBackground) {
      return;
    }
    this.stoppedByBackground = false;
    LanService.get().startSharing(this.context).then((ok: boolean) => {
      Log.i(TAG, `回前台自动恢复共享: ${ok}`);
    }).catch((e: Error) => {
      Log.w(TAG, `回前台自动恢复失败: ${e.message}`);
    });
  }

  /**
   * 退到后台：按决策停服。
   * 这样端口能被干净释放、已建立的连接正常关闭，对端立刻感知中断。
   */
  onBackground(): void {
    Log.i(TAG, 'onBackground');
    if (!LanConfig.AUTO_STOP_ON_BACKGROUND) {
      Log.i(TAG, 'AUTO_STOP_ON_BACKGROUND=false，保持会话（不推荐：进程很快会被冻结）');
      return;
    }
    if (!LanService.get().isRunning) {
      return;
    }
    this.stoppedByBackground = true;
    LanService.get().stopSharing().then(() => {
      Log.i(TAG, '已退后台，共享已暂停');
    }).catch((e: Error) => {
      Log.w(TAG, `退后台停服失败: ${e.message}`);
    });
  }
}
