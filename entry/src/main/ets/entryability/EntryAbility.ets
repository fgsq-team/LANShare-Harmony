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
import { ShareInbox } from '../service/ShareInbox';
import { uniformTypeDescriptor as utd } from '@kit.ArkData';

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
    // ★ 5.1.79：冷启动（应用没开）时由系统分享拉起 —— 分享数据在 want 里。
    this.handleShareWant(want, 'onCreate');
  }

  /**
   * ★ 5.1.79：应用**已在后台运行时**，再次被分享拉起走 onNewWant 而不是 onCreate。
   *
   * ⚠️ 漏了这个回调的症状极具欺骗性：
   *   「从桌面图标进是好的，从分享面板点第二次就不弹了」——
   *   因为第一批文件把 ShareInbox 占住了（claim 取走），而第二批永远进不来。
   *   两个回调必须**都**接，且共用同一个处理函数。
   */
  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    Log.i(TAG, 'EntryAbility onNewWant');
    this.handleShareWant(want, 'onNewWant');
  }

  /**
   * 判断这个 want 是不是「系统分享投过来的文件」，是就交给 ShareInbox 落地成沙箱副本。
   *
   * ## 为什么要立刻落盘（而不是把 URI 直接丢给 UI）
   * 分享给本应用的是**临时授权 URI**（datashare:// 或 file://），
   * 只在分享方还活着的一小段时间里可读。
   * 若直接交给 UI，等用户在一堆设备里挑完再发，很可能已经读不到了
   * ⇒ `ShareInbox.accept` 里**同步拷进沙箱**，之后一律用沙箱路径。
   *
   * ## 为什么不在这里顺手 startSharing
   * `onCreate` 里 LanService 还没初始化完（`filesDir` 未知），
   * 此时落盘会失败。真正的 startSharing 由 Index 的 aboutToAppear 触发，
   * 它跑完之后会调 `ShareInbox.drain()` 补处理这一批 —— 这里只负责「收下」。
   */
  private handleShareWant(want: Want, from: string): void {
    if (want === undefined || want === null) {
      return;
    }
    // 只认分享动作。桌面图标点进来是 action.system.home，别把无关 want 也解析一遍
    const action: string | undefined = want.action;
    const uris: string | undefined = want.uri;
    const isShare: boolean = (action !== undefined && action.indexOf('send') >= 0)
      || uris !== undefined || this.hasShareParam(want);
    if (!isShare) {
      return;
    }
    Log.i(TAG, `${from} 收到分享：action=${action} uri=${uris}`);
    // ★★ 5.1.80：把 parameters 的 key 全打出来。
    //   5.1.79 的现象是「图库能弹、文件管理器不弹」，根因在 UTD 匹配；
    //   但**到底是哪个 key 承载了文件、UTD 是什么形态**，SDK 与文档都没给出处。
    //   ⇒ 下次再出问题，这行日志能直接指认，不用再猜。
    this.logWantShape(want);
    try {
      ShareInbox.accept(want);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `处理分享失败: ${err.code} ${err.message}`);
    }
  }

  /**
   * ★ 5.1.80 取证：把 want.parameters 的每个 key / 类型 / UTD 归属打进日志。
   *
   * 为什么要问 UTD 归属（`belongsTo`）：
   *   UTD 有三个互不包含的顶层根（object 92 / entity 5 / tar-archive 2），
   *   只声明 `general.object` 时，物理文件类型匹配不上 ⇒ **应用不出现**。
   *   拿到对方的 UTD 后逐根问一次，就知道它落在哪棵树里。
   *
   * ⚠️ `getTypeDescriptor()` 可能抛（UTD 被动态生成、已失效）⇒ 必须 try 包住，
   *   且**一个失败不能影响后面两根的询问**。
   */
  private logWantShape(want: Want): void {
    const params: Record<string, Object> | undefined = want.parameters;
    if (params === undefined) {
      Log.i(TAG, 'want.parameters 为空');
      return;
    }
    const keys: string[] = Object.keys(params);
    Log.i(TAG, `want.parameters 共 ${keys.length} 个 key: ${keys.join(',')}`);
    for (let i = 0; i < keys.length; i++) {
      const k: string = keys[i];
      const v: Object = params[k];
      if (typeof v === 'string') {
        Log.i(TAG, `  参数 ${k} = 字符串: ${v as string}`);
      } else if (Array.isArray(v)) {
        const arr: Object[] = v as Object[];
        const first: string = arr.length > 0 && typeof arr[0] === 'string' ? (arr[0] as string) : '?';
        Log.i(TAG, `  参数 ${k} = 数组[${arr.length}] 首项: ${first}`);
      } else {
        Log.i(TAG, `  参数 ${k} = 其他类型`);
      }
    }
    // 逐根问 UTD：先问「这个 key 的值像不像一个 utd id」，是才问归属
    for (let i = 0; i < keys.length; i++) {
      const v: Object = params[keys[i]];
      const cand: string = typeof v === 'string' ? (v as string)
        : (Array.isArray(v) && v.length > 0 && typeof v[0] === 'string' ? (v[0] as string) : '');
      if (cand.indexOf('general.') !== 0 && cand.indexOf('.') !== 0) {
        continue;
      }
      this.logUtdBelong(cand, keys[i]);
    }
  }

  /** 问一个 UTD 落在三棵树的哪一棵（每根独立 try，一根失败不影响别的） */
  private logUtdBelong(typeId: string, fromKey: string): void {
    let desc: string | null = null;
    try {
      desc = utd.getTypeDescriptor(typeId).description;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `取 UTD 描述失败 ${typeId}: ${err.code} ${err.message}`);
    }
    const roots: string[] = [
      utd.UniformDataType.OBJECT,
      utd.UniformDataType.ENTITY,
      utd.UniformDataType.FILE
    ];
    const hits: string[] = [];
    for (let i = 0; i < roots.length; i++) {
      try {
        if (utd.getTypeDescriptor(typeId).belongsTo(roots[i])) {
          hits.push(roots[i]);
        }
      } catch (e) {
        // 单根失败忽略，继续问下一根
      }
    }
    Log.i(TAG, `  UTD(${fromKey}) = ${typeId} 描述=${desc ?? '?'} 归属根=[${hits.join(',')}]`);
  }

  /** parameters 里是否有任何带 scheme 的值（多文件分享不带 want.uri） */
  private hasShareParam(want: Want): boolean {
    const params: Record<string, Object> | undefined = want.parameters;
    if (params === undefined) {
      return false;
    }
    const keys: string[] = Object.keys(params);
    for (let i: number = 0; i < keys.length; i++) {
      const v: Object = params[keys[i]];
      // ★ 5.1.80 放宽：原来只认含 `://` 的值。
      //   若某个分享方把 uri 放在别的形态里（例如只给了 UTD + fd），
      //   旧判据会整批漏掉 ⇒ 症状就是「收到了但什么都没发生」。
      //   现在：**只要 parameters 有任何非空 key** 就当分享处理。
      //   误判的代价只是「多跑一次 accept（内部自己会判定无 uri 而退出）」，
      //   漏判的代价是「用户的分享静默消失」⇒ 宁可误判。
      if (typeof v === 'string' && (v as string).length > 0) {
        return true;
      }
      if (Array.isArray(v) && (v as Object[]).length > 0) {
        return true;
      }
    }
    return false;
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
