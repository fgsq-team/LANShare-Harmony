/**
 * 日志门面 —— 替代原项目的 SLF4J + logback-android。
 *
 * 迁移说明：
 *   org.slf4j.Logger        -> Logger（本文件）
 *   ch.qos.logback          -> @kit.PerformanceAnalysisKit 的 hilog
 *   app/src/main/assets/logback.xml -> 删除，改由 hilog 的 DOMAIN/TAG 与
 *                                       DevEco Studio 的 HiLog 过滤器承担
 *
 * 保持原有 API 形状（d/i/w/e），这样从 Java 平移过来的调用点可以机械替换：
 *   LLog.d(TAG, "xxx")  ->  Log.d(TAG, 'xxx')
 */

const hilog = { debug(){}, info(){}, warn(){}, error(){} };

/** hilog 域号。0x0000-0xFFFF，业务域建议用 0x0 开头的自定义值 */
const DOMAIN: number = 0xF5F0;

export class Log {
  static d(tag: string, msg: string): void {
    hilog.debug(DOMAIN, tag, '%{public}s', msg);
  }

  static i(tag: string, msg: string): void {
    hilog.info(DOMAIN, tag, '%{public}s', msg);
  }

  static w(tag: string, msg: string): void {
    hilog.warn(DOMAIN, tag, '%{public}s', msg);
  }

  static e(tag: string, msg: string): void {
    hilog.error(DOMAIN, tag, '%{public}s', msg);
  }

  /** 带异常对象的错误日志，对应 Java 的 logger.error(msg, throwable) */
  static e2(tag: string, msg: string, err: Error): void {
    hilog.error(DOMAIN, tag, '%{public}s | %{public}s', msg, err.message);
  }
}
