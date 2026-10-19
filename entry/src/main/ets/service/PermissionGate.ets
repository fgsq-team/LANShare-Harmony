/**
 * 运行期权限申请。
 *
 * ## 为什么之前"一个权限都没申请"—— 这不是 bug
 * 从 SDK 自带的 `PermissionDefinitions.json` 里读出来的真实授予模式：
 *
 * | 权限 | grantMode | 会不会弹窗 |
 * |---|---|---|
 * | `ohos.permission.INTERNET` | **system_grant** | ❌ 安装时静默授予 |
 * | `ohos.permission.GET_NETWORK_INFO` | system_grant | ❌ |
 * | `ohos.permission.READ_WRITE_DOWNLOAD_DIRECTORY` | **user_grant** | ✅ 要 `requestPermissionsFromUser` |
 *
 * ★ 5.3.4（合规）：CAMERA / NFC_TAG 两条**声明已从 module.json5 删除**
 *   （零引用 = 违规收集，会被驳回）。B2 接扫码/NFC 时随功能加回。
 * ★ 5.3.13：APPROXIMATELY_LOCATION / VIBRATE 两条声明也删了
 *   （零引用/零调用 = 死声明，同 CAMERA/NFC 性质）。
 * ★ 5.3.10：READ_WRITE_DOWNLOAD_DIRECTORY 声明也删了 —— 它依赖的 SysCap
 *   （FolderObtain）官方仅 PC/2in1/平板提供，**手机形态能力门禁就没过、
 *   申请代码从不执行**；平板/2in1 上只是「收到文件直存下载目录」的便利功能。
 *   相关 ensure* 方法与 DOWNLOAD_DIR 常量一并移除；FileStorage.tryDownloadDir
 *   保留（未授权时抛 201 已优雅降级到沙箱）。加回时随功能一起声明，
 *   并在发布 Profile 勾选对应受限权限。
 *
 * 也就是说：**核心的局域网收发全程不需要任何用户授权**，装完就能用 ——
 * 这跟 Android 那边"一进应用弹一堆权限"是完全不同的模型。
 * 真正会弹窗的只有「写下载目录」，而它只在**接收文件**时才需要，
 * 所以本类按需申请，而不是启动就弹。
 *
 * ## 申请时机
 * 不放在 onWindowStageCreate：用户还没表达任何意图，弹窗是骚扰，
 * 而且华为的接入规范也不建议"启动即申请无关权限"。
 * 一律放到**触发该能力的那一刻**（点开始共享 / 收到文件前）。
 */
import { abilityAccessCtrl, common, Permissions, PermissionRequestResult } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../core/Logger';

const TAG: string = 'PermissionGate';

/**
 * 一次授权尝试的结论。
 * `detail` 是给人看的（进 UI 日志），必须是**能指导下一步动作**的话，
 * 不能只说「未授权」—— 那等于没说。
 */
export class GrantOutcome {
  granted: boolean = false;
  detail: string = '';
}

export class PermissionGate {
  /** 权限名常量，避免各处手写字符串写错字母 */
  static readonly INTERNET: Permissions = 'ohos.permission.INTERNET';
  static readonly GET_NETWORK_INFO: Permissions = 'ohos.permission.GET_NETWORK_INFO';
  // ★★ 5.3.13：VIBRATE / LOCATION 常量随声明一并移除
  //   （零引用 = 死声明，与 CAMERA/NFC/READ_WRITE_DOWNLOAD_DIRECTORY 同性质）。
  //   加回时随 module.json5 声明一起恢复，别只加常量
  //   （声明没有时申请会拿到 authResult=2）。

  /** 是否已授予（不弹窗） */
  static isGranted(ctx: common.UIAbilityContext, perm: Permissions): boolean {
    try {
      const mgr: abilityAccessCtrl.AtManager = abilityAccessCtrl.createAtManager();
      const token: number = ctx.applicationInfo.accessTokenId;
      const status: abilityAccessCtrl.GrantStatus =
        mgr.checkAccessTokenSync(token, perm);
      return status === abilityAccessCtrl.GrantStatus.PERMISSION_GRANTED;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `查询权限失败 ${perm}: ${err.code} ${err.message}`);
      return false;
    }
  }

  /**
   * 申请一组权限。已授予的不会重复弹窗（系统自己会跳过）。
   * @returns 每一项的授予结果，key 是权限名
   */
  static async request(
    ctx: common.UIAbilityContext,
    perms: Permissions[]
  ): Promise<Map<string, boolean>> {
    const result: Map<string, boolean> = new Map<string, boolean>();
    const need: Permissions[] = [];
    for (let i = 0; i < perms.length; i++) {
      if (PermissionGate.isGranted(ctx, perms[i])) {
        result.set(perms[i], true);
      } else {
        need.push(perms[i]);
      }
    }
    if (need.length === 0) {
      return result;
    }
    try {
      const mgr: abilityAccessCtrl.AtManager = abilityAccessCtrl.createAtManager();
      const res: PermissionRequestResult = await mgr.requestPermissionsFromUser(ctx, need);
      for (let i = 0; i < res.permissions.length; i++) {
        // authResults: 0 = 已授权；-1 = 未授权；2 = 请求非法（权限名/声明/特殊条件不满足）
        const code: number = res.authResults[i];
        const shown: boolean | undefined = res.dialogShownResults !== undefined
          ? res.dialogShownResults[i] : undefined;
        Log.i(TAG, `权限 ${res.permissions[i]} authResult=${code} dialogShown=${shown}`);
        result.set(res.permissions[i], code === 0);
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `申请权限失败: ${err.code} ${err.message}`);
      for (let i = 0; i < need.length; i++) {
        result.set(need[i], false);
      }
    }
    return result;
  }

  /**
   * 申请单个权限并给出**可诊断的**结论。
   *
   * 光知道「没拿到」是没法排查的 —— 从 `authResults` / `dialogShownResults`
   * 能区分出三种完全不同的处置方式：
   *   0            -> 已授权
   *   -1 + 弹过窗   -> 用户这次点了拒绝，下次点「开始共享」会再弹
   *   -1 + 没弹窗   -> 系统当前不再走弹窗路径，只能引导用户去「设置 → 应用 → 权限」手动开
   *   2            -> 请求本身非法（权限没在 module.json5 里声明 / 名称写错 / 不满足特殊条件）
   */
  static async ensureOne(
    ctx: common.UIAbilityContext,
    perm: Permissions
  ): Promise<GrantOutcome> {
    const out: GrantOutcome = new GrantOutcome();
    if (PermissionGate.isGranted(ctx, perm)) {
      out.granted = true;
      out.detail = '已授权';
      return out;
    }
    try {
      const mgr: abilityAccessCtrl.AtManager = abilityAccessCtrl.createAtManager();
      const res: PermissionRequestResult = await mgr.requestPermissionsFromUser(ctx, [perm]);
      let idx: number = -1;
      for (let i = 0; i < res.permissions.length; i++) {
        if (res.permissions[i] === perm) {
          idx = i;
          break;
        }
      }
      if (idx < 0) {
        out.detail = '系统未返回该项的结果';
        return out;
      }
      const code: number = res.authResults[idx];
      const shown: boolean = res.dialogShownResults !== undefined
        ? res.dialogShownResults[idx] : true;
      Log.i(TAG, `${perm} authResult=${code} dialogShown=${shown}`);
      if (code === 0) {
        out.granted = true;
        out.detail = '已授权';
      } else if (code === 2) {
        out.detail = '请求非法（权限名或 module.json5 声明有问题）';
      } else if (shown) {
        out.detail = '用户本次拒绝，下次启动会再次申请';
      } else {
        out.detail = '系统当前不再弹窗，需到「设置 → 应用 → 权限」手动开启';
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `申请 ${perm} 异常: ${err.code} ${err.message}`);
      out.detail = `申请异常 ${err.code}`;
    }
    return out;
  }

  /**
   * 设备是否具备「获取预授权用户目录」的系统能力。
   * 这是调用 `Environment.getUserDownloadDir()` 的**前置条件**，
   * 与权限无关：能力不存在时，有权限也调不通。
   */
  static supportsUserDownloadDir(): boolean {
    try {
      return canIUse('SystemCapability.FileManagement.File.Environment.FolderObtain');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `canIUse 查询失败: ${err.code} ${err.message}`);
      return false;
    }
  }
}
