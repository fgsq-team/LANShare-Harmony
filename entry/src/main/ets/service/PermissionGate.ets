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
 * | `ohos.permission.VIBRATE` | system_grant | ❌ |
 * | `ohos.permission.READ_WRITE_DOWNLOAD_DIRECTORY` | **user_grant** | ✅ 要 `requestPermissionsFromUser` |
 * | `ohos.permission.CAMERA` | user_grant | ✅（扫码时才需要） |
 * | `ohos.permission.APPROXIMATELY_LOCATION` | user_grant | ✅（部分系统版本校验 Wi-Fi 场景才需要） |
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
  static readonly VIBRATE: Permissions = 'ohos.permission.VIBRATE';
  static readonly DOWNLOAD_DIR: Permissions = 'ohos.permission.READ_WRITE_DOWNLOAD_DIRECTORY';
  static readonly CAMERA: Permissions = 'ohos.permission.CAMERA';
  static readonly LOCATION: Permissions = 'ohos.permission.APPROXIMATELY_LOCATION';

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
   * 确保「写下载目录」可用。接收文件前调用一次。
   * 拿到授权后调用方应刷新 FileStorage 的落盘根目录。
   */
  static async ensureDownloadDir(ctx: common.UIAbilityContext): Promise<boolean> {
    const r: GrantOutcome = await PermissionGate.ensureOne(ctx, PermissionGate.DOWNLOAD_DIR);
    return r.granted;
  }

  /** 同上，但把「为什么没拿到」一起带出来给 UI 看 */
  static async ensureDownloadDirDetailed(
    ctx: common.UIAbilityContext
  ): Promise<GrantOutcome> {
    return PermissionGate.ensureDownloadDirWithReason(ctx);
  }

  /**
   * ⚠️ **先查设备能力，再申请权限** —— 顺序不能反。
   *
   * `Environment.getUserDownloadDir()` 需要
   * `SystemCapability.FileManagement.File.Environment.FolderObtain`，
   * 而该能力官方**仅对 PC/2in1 与 Tablet 形态开放**（见 SDK
   * `@ohos.file.environment.d.ts` 与官方文档「Currently, only 2-in-1 devices are supported」）。
   *
   * 手机形态（例如 HUAWEI Mate 70 Pro 优享版）上这个能力根本不存在，
   * `getUserDownloadDir()` 必定抛 **801 Capability not supported**。
   * 此时若直接去申请 `READ_WRITE_DOWNLOAD_DIRECTORY`，拿回来的是
   * `authResult=2`（请求非法），现象是「**权限怎么申请都不通过**」——
   * 很容易被误判成「权限名写错 / module.json5 声明有问题」，其实与权限无关。
   *
   * 所以这里先 `canIUse` 判定，把结论一次性说到位。
   */
  static async ensureDownloadDirWithReason(
    ctx: common.UIAbilityContext
  ): Promise<GrantOutcome> {
    const out: GrantOutcome = new GrantOutcome();
    if (!PermissionGate.supportsUserDownloadDir()) {
      out.granted = false;
      out.detail = '本机不支持预授权「下载」目录（该能力官方仅 PC/2in1 与平板提供，手机形态无此系统能力）';
      Log.i(TAG, 'canIUse(FolderObtain) = false，跳过下载目录权限申请');
      return out;
    }
    return PermissionGate.ensureOne(ctx, PermissionGate.DOWNLOAD_DIR);
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
