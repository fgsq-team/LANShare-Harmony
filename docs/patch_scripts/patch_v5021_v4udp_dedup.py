#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5.0.21 补丁：修两个真机复现过的缺陷。

【缺陷一】官方安卓版发文字 → 鸿蒙收不到
  `V5Udp.parse` **无条件**在设备头之后读一个「已知设备数」int。
  但「已知设备表」是 **v5（1.35 修改版）新增**的字段；官方 v4
  （`Config.DATA_VERSION = LVersion.DATA_VERSION_4`）8 字段之后**直接就是命令参数**。
  于是 readKnown 把 v4 的 `messageEnc` 长度前缀当计数、把整段消息吃穿，
  `extras` 全空 → "UDP 消息帧缺少密文字段" → 消息丢弃。
  真机证据（修复前）：`V5Codec: 字符串长度越界: 825255268 > 78` ×10
                      → `LanService: UDP 消息帧缺少密文字段，来自 192.168.10.186`
  修法：按**对端广播的 dataVersion**（uuid 后缀，V5Header.read 已解析）分流。

【缺陷二】鸿蒙发文字 → 官方安卓收到两次
  `devices` Map 的 key 是 uniqueUuid，而 `tcpProbeStep` 的 TCP 复核**只认 IP**：
  复核成功就把该条目的 `lastSeenMs` 刷新。于是同一台物理机换过 uuid
  （重装 App / 官方版与 1.35 双版本 / 清数据）之后，旧条目被新条目的存活"续命"，
  `DEVICE_OFFLINE_MS`(8s) 永远清不掉 → `onlineDeviceList()` 返回多条同 IP 记录 →
  群发时同一台设备收到多份。
  真机证据（修复前）：hilog 里同一秒三条
      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4）` ×2 + `协议 v5` ×1
  修法：① UDP 发现 / 入站连接两条写入路径都做「同 IP 去重」；
        ② `onlineDeviceList()` 按 IP 归并做兜底护栏。

约定（本工程铁律）：
  · 哨兵幂等：重跑直接逐文件 SKIP，不写不报错
  · 先全部校验 + 内存构造，最后统一落盘（任一失败则一个字都不写）
  · 双断言：new 此前不存在 + old 恰好一处
  · 花括号增量一致
"""
import io
import os
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
V5CODEC = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'core', 'V5Codec.ets')
LANSVC = os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets')
APPJSON = os.path.join(ROOT, 'AppScope', 'app.json5')

SENTINEL_V5CODEC = '★ v4 / v5 的分叉点（5.0.21 定案'
SENTINEL_LANSVC = 'private dropSameIpExcept('

# ---------------------------------------------------------------- 编辑定义

# ---- V5Codec.ets：known 表按版本分流 ----
# ⚠️ 必须**一次替换整段**（从 known 读取一直到方法收尾）：
#    「删掉末尾 frame.device 赋值」这种删除型编辑，其 new 是 old 的子串，
#    单独拆成一次编辑会触发双断言里的 "新文本已存在"（本工程踩过的坑）。
VC_OLD_1 = """    // 已知设备数在设备头之后（1.35 的顺序：设备头 8 字段 → 数量 → 表）
    const knownCount: number = dec.int();
    frame.known = V5Header.readKnown(dec, Math.min(knownCount, 64));
    // 剩下的都是命令专属参数（文本消息等）
    for (let i = 0; i < 8; i++) {
      if (dec.remaining < 4) {
        break;
      }
      frame.extras.push(dec.string());
    }
    frame.device = dev;
    return frame;
  }
}
"""

VC_NEW_1 = """    frame.device = dev;
    // ★ v4 / v5 的分叉点（5.0.21 定案，真机复现过）
    //   「已知设备表」是 **v5（1.35 修改版）新增**的字段：
    //     设备头 8 字段 → int 已知设备数 → N×(int port, String ip, String name) → 命令参数
    //   官方 v4（`Config.DATA_VERSION = LVersion.DATA_VERSION_4`）**没有这一段**，
    //   8 个字段之后直接就是命令参数。
    //   ⚠️ 无条件读这个计数会把 v4 的 `messageEnc` 长度前缀（例如 181）当成设备数，
    //      `readKnown` 于是把整段消息吃穿 → `extras` 全空 →
    //      收到 1004 时打 "UDP 消息帧缺少密文字段" → **官方安卓发来的文字一条都收不到**。
    //      （修复前真机日志：`字符串长度越界: 825255268 > 78` ×10，随后就是上面那句）
    //   判据取**对端广播的 dataVersion**（= uuid 后缀，`V5Header.read` 已解析并剥掉）：
    //     ≤4（官方 / 更老版本）无此段；≥5（v5）有此段。
    if (dev.dataVersion >= LanConfig.V5_MIN_DATA_VERSION) {
      const knownCount: number = dec.int();
      frame.known = V5Header.readKnown(dec, Math.min(knownCount, 64));
    }
    // 剩下的都是命令专属参数（文本消息等）
    for (let i = 0; i < 8; i++) {
      if (dec.remaining < 4) {
        break;
      }
      frame.extras.push(dec.string());
    }
    return frame;
  }
}
"""

# ---- LanService.ets：dropDevice 之后插入 dropSameIpExcept ----
LS_OLD_1 = """    Log.i(TAG, `设备下线：已移除 ${d.devName} @ ${d.devIp}`);
    this.pushLog(`${d.devName.length > 0 ? d.devName : d.devIp} 已下线`);
    this.broadcastDeviceList();
    this.syncStats();
    this.emit();
    return true;
  }
"""

LS_NEW_1 = """    Log.i(TAG, `设备下线：已移除 ${d.devName} @ ${d.devIp}`);
    this.pushLog(`${d.devName.length > 0 ? d.devName : d.devIp} 已下线`);
    this.broadcastDeviceList();
    this.syncStats();
    this.emit();
    return true;
  }

  /**
   * 同一 IP 只保留一个设备条目（5.0.21 定案，真机复现过）。
   *
   * ⚠️ 为什么必须做：`devices` 的 key 是 **uniqueUuid**，而 `tcpProbeStep` 的
   *    TCP 复核**只认 IP** —— 复核成功就把该条目的 `d.lastSeenMs` 刷新。
   *    于是同一台物理机只要换过 uuid（重装 App、官方版与 1.35 双版本共存、
   *    清数据），旧条目就会被新条目的存活**续命**，`DEVICE_OFFLINE_MS`(8s)
   *    永远清不掉。后果：`onlineDeviceList()` 返回多条同 IP 记录，
   *    群发消息时**同一台设备收到 N 份**。
   *    真机取证（修复前 hilog，同一秒三条）：
   *      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4，3 字）`
   *      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v4，3 字）`
   *      `已发送消息到 DBY-W09（192.168.10.100:5856，协议 v5，3 字）`
   *
   * 局域网内一个 IP 就是一台设备，按 IP 归并是安全的。
   * ⚠️ 注意**不要**清 per-IP 的探测状态（probeSentAt / tcpEverOk / tcpProbeMiss /
   *    lastTcpProbeAt）—— 那些键是 IP，跟着保留下来的条目继续有效；
   *    清理它们是 `dropDevice`（设备**真的**下线）才该做的事。
   */
  private dropSameIpExcept(ip: string, keepKey: string): void {
    if (ip.length === 0) {
      return;
    }
    const victims: string[] = [];
    this.devices.forEach((d: LanDevice, k: string) => {
      if (k !== keepKey && d.devIp === ip) {
        victims.push(k);
      }
    });
    for (let i = 0; i < victims.length; i++) {
      const old: LanDevice | undefined = this.devices.get(victims[i]);
      this.devices.delete(victims[i]);
      Log.i(TAG, `同 IP 去重：移除旧条目 ${old !== undefined ? old.devName : '?'}`
        + ` key=${victims[i]} @ ${ip}（保留 key=${keepKey}）`);
    }
  }
"""

# ---- onDeviceFound：入表前先去重 ----
LS_OLD_2 = """    const existing: LanDevice | undefined = this.devices.get(addKey);
    if (existing === undefined) {
      this.devices.set(addKey, d);
"""
LS_NEW_2 = """    // ★ 同一 IP 只保留一条（5.0.21）：见 dropSameIpExcept 的注释。
    //   必须放在 get 之前 —— 否则同一台设备换过 uuid 就会在表里留下僵尸条目，
    //   它会因 TCP 复核（按 IP）被持续续命，群发时多投一份。
    this.dropSameIpExcept(d.devIp, addKey);
    const existing: LanDevice | undefined = this.devices.get(addKey);
    if (existing === undefined) {
      this.devices.set(addKey, d);
"""

# ---- trackPeer：入表前同样去重 ----
LS_OLD_3 = """  private trackPeer(d: LanDevice): void {
    const key: string = d.uniqueUuid.length > 0 ? d.uniqueUuid : d.devIp;
    const existing: LanDevice | undefined = this.devices.get(key);
"""
LS_NEW_3 = """  private trackPeer(d: LanDevice): void {
    const key: string = d.uniqueUuid.length > 0 ? d.uniqueUuid : d.devIp;
    // ★ 同上（5.0.21）：入站连接带过来的 uuid 若与历史条目不同（重装 App），
    //   这里必须把同 IP 的旧条目清掉，否则设备列表里会出现两条同名设备。
    this.dropSameIpExcept(d.devIp, key);
    const existing: LanDevice | undefined = this.devices.get(key);
"""

# ---- onlineDeviceList：按 IP 归并兜底 ----
LS_OLD_4 = """  onlineDeviceList(): LanDevice[] {
    const now: number = Date.now();
    const out: LanDevice[] = [];
    this.devices.forEach((d: LanDevice) => {
      if (!this.deviceGone(d, now)) {
        out.push(d);
      }
    });
    return out;
  }
"""
LS_NEW_4 = """  onlineDeviceList(): LanDevice[] {
    const now: number = Date.now();
    const out: LanDevice[] = [];
    // ★ 同一 IP 只出一个（5.0.21 兜底护栏）：即使 devices 里因故残留了多条同 IP 记录，
    //   群发消息 / 网页下拉框也只会各投一份 —— 这是「同一条消息收到两次」的直接护栏。
    //   保留 `lastSeenMs` 最新的那条（有心跳、能连上的才是它）。
    //   空 IP 不参与合并（本来就不可用，但也不该被悄悄丢掉）。
    const slot: Map<string, number> = new Map<string, number>();
    this.devices.forEach((d: LanDevice) => {
      if (this.deviceGone(d, now)) {
        return;
      }
      if (d.devIp.length === 0) {
        out.push(d);
        return;
      }
      const at: number | undefined = slot.get(d.devIp);
      if (at === undefined) {
        slot.set(d.devIp, out.length);
        out.push(d);
      } else if (d.lastSeenMs > out[at].lastSeenMs) {
        out[at] = d;
      }
    });
    return out;
  }
"""

# ---- app.json5：版本号 ----
AJ_OLD_1 = '"versionCode": 5000020,'
AJ_NEW_1 = '"versionCode": 5000021,'
AJ_OLD_2 = '"versionName": "5.0.20",'
AJ_NEW_2 = '"versionName": "5.0.21",'


def read(p):
    return io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def brace_delta(s):
    return s.count('{') - s.count('}')


def apply_edits(name, path, sentinel, edits):
    """返回 (status, new_text)。status: 'applied' | 'already'

    ⚠️ sentinel 可能是 None（app.json5 没有注释可挂），那种情况按版本号判幂等。
    """
    src = read(path)
    if sentinel is not None and sentinel in src:
        print('  [SKIP] %s 已含哨兵，跳过' % name)
        return 'already', None
    out = src
    for i, (old, new, label) in enumerate(edits, 1):
        c_new = out.count(new)
        c_old = out.count(old)
        assert c_new == 0, '%s #%d (%s): 新文本已存在（count=%d）' % (name, i, label, c_new)
        assert c_old == 1, '%s #%d (%s): 旧文本命中 %d 次（应为 1）' % (name, i, label, c_old)
        out = out.replace(old, new, 1)
        print('  [OK]   %s #%d %s' % (name, i, label))
    assert out != src, '%s 结果与原文相同' % name
    return 'applied', out


def main():
    print('=== 5.0.21 补丁：官方 v4 UDP 消息接收 + 同 IP 条目去重 ===')
    results = {}
    plan = [
        ('V5Codec.ets', V5CODEC, SENTINEL_V5CODEC,
         [(VC_OLD_1, VC_NEW_1, 'known 表按 dataVersion 分流（整段一次替换）')]),
        ('LanService.ets', LANSVC, SENTINEL_LANSVC,
         [(LS_OLD_1, LS_NEW_1, '新增 dropSameIpExcept'),
          (LS_OLD_2, LS_NEW_2, 'onDeviceFound 入表前去重'),
          (LS_OLD_3, LS_NEW_3, 'trackPeer 入表前去重'),
          (LS_OLD_4, LS_NEW_4, 'onlineDeviceList 按 IP 归并')]),
        ('app.json5', APPJSON, None,
         [(AJ_OLD_1, AJ_NEW_1, 'versionCode -> 5000021'),
          (AJ_OLD_2, AJ_NEW_2, 'versionName -> 5.0.21')]),
    ]

    # ---- 第一阶段：全部校验 + 内存构造（一个字节都不落盘）----
    pending = []
    for name, path, sentinel, edits in plan:
        if sentinel is None:
            r = read(path)
            if '"versionCode": 5000021,' in r:
                print('  [SKIP] %s 已是 5.0.21' % name)
                results[name] = 'already'
                continue
        s, out = apply_edits(name, path, sentinel, edits)
        results[name] = s
        if s == 'applied':
            pending.append((name, path, out))

    if not pending:
        print('\nALREADY APPLIED（全部文件都命中哨兵，未做任何写入）')
        return

    # ---- 第二阶段：括号增量一致性总检（仅 .ets）----
    for name, path, out in pending:
        if not name.endswith('.ets'):
            continue
        src = read(path)
        d = brace_delta(out) - brace_delta(src)
        assert d == 0, '%s 花括号增量 %+d（应为 0）' % (name, d)
        print('  [OK]   %s 花括号增量 0' % name)

    # ---- 第三阶段：统一落盘 ----
    for name, path, out in pending:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(out)
        print('  [WRITE] %s' % path)
    print('\nAPPLIED OK')


if __name__ == '__main__':
    main()
