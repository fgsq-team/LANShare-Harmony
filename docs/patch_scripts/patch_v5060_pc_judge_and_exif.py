#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5.0.60 —— 修两个真机确诊问题（vivi 2026-10-02 日志 + 沙箱取证）。

════════════════════════════════════════════════════════════════════
【问题 1】PC 端连发多图，最后一项必然「60 秒超时」而失败（5.0.58 没修好）
════════════════════════════════════════════════════════════════════
证据（17:00:04 那批 5 张，第 5 张失败）：
    [17:00:15] v5 对端宣告：name=vivi ip=192.168.10.186 mode=2 ver=5
    [17:01:17] v5 "IMG_0097.JPG"：数据块 1869453 B 读取失败（已收 4194280/6063733）
    —— 正好 60 秒，且连接没断。

5.0.58 的判据是「**对端宣告的 IP == 本机 IP** ⇒ 是 PC」。实测本机 `.146`、
PC 宣告 `.186`（它**自己**），**判据从未命中** ⇒ `pcStyleAck` 一直是 false
⇒ 走 N+2 ⇒ PC 每文件多收 1 字节 ⇒ 块级节流失效一路狂发 ⇒ 接收窗口压满
⇒ PC 的裸 `::send()` 部分返回被当硬错误 ⇒ 中途改发 `FS_CLOSE` ⇒ 我方当数据体
吞掉 ⇒ 干等 60 秒。**5.0.58 改的是对的（只回 `2` = N+1），坏的是判据。**

判据为什么必然不可靠（PC 源码，`LANShare.cpp:467-474`）：
```cpp
std::vector<Device>::iterator p1;
std::vector<Device> mDevices = LANShare::getInstance()->getMDevices();
for (p1 = mDevices.begin(); p1 != mDevices.end(); p1++) {
    if (NetWorldUtils::subNet(..., p1->getDevIp(), device.getDevIp())) {
        makeDataEnc(*p1, &dataEnc);        // ← 序列化的是 p1！
```
`p1` = **PC 自己设备列表里「与目标同子网的某一台」** —— 可能是它自己，
也可能是别的设备。所以 `devIp / devName / devMode` 三个字段**天生不可靠**。

★ 唯一可靠的是**同一帧里的 `uniqueUuid`**：它取自 `config.uniqueUUid`
（`LANShare.cpp:117`），是**对端自己的 UUID**，与 `p1` 无关。
而本机发现表 `devices: Map<string, LanDevice>` 的 **key 正好就是它**（`trackPeer`）
⇒ 用握手带来的 UUID 反查发现表，拿到的是**真实**的 `devMode`。WINDOWS(2)/LINUX(3)/
MAC(4)/WEB(7) ⇒ 按 N+1 回收尾应答。

兜底刻意保守：**查不到就按「非 PC」**（退回 N+2，与现状完全一致）—— 不引入回归。

════════════════════════════════════════════════════════════════════
【问题 2】第 12 / 15 张照片「比例和方向都不对」（其余 13 张正常）
════════════════════════════════════════════════════════════════════
规律：本地 13 张对照图里**只有 `IMG_0069.JPG` 的 EXIF orientation = 8**，
其余全是 1 —— 与用户说的「第 12 张」**完全吻合**（第 12 项 = IMG_0069）。

沙箱取证：把 `album_thumbs/c12-…#0.jpg` 拉回来逐像素比对 ——
    缩略图 213x320（竖），但内容与「原图旋转 180°＋拉伸」最接近（MSE 5.1），
    与正确朝向（exif_transpose）差 **90°**。
即：**物理旋转转了错的方向，而校验没抓到。**

为什么校验没抓到：现有校验只看**横竖性**
```ts
const wantTall = Index.isQuarter(deg) ? !(srcH > srcW) : (srcH > srcW);
ok = (wantTall === (gh > gw));        // 只看「是不是变竖了」
```
而 **90° 和 270° 都会翻转横竖性** ⇒ 转反 90° 也能通过校验。

修法：不去猜 `createPixelMap({rotate})` 的语义（同一张图在不同实现下结论不同、
已经来回改过多轮），而是**绕开物理旋转** ——
只要 `deg !== 0`（自带 EXIF 方向）就**直接走「复制原图」缓存**（保留 EXIF），
让显示层 `AUTO` 交给 `Image` 自己转 —— 这条路与「弹窗那一刻显示沙箱原图」
**是同一条已被验证正确**的路（`_full` 兜底，5.0.42 就写好了）。
代价：仅对带方向的少数照片多存一份原图；绝大多数照片（deg=0）路径**完全不变**。
"""
import io
import sys

IX = r'entry/src/main/ets/pages/Index.ets'
LS = r'entry/src/main/ets/service/LanService.ets'
AJ = r'AppScope/app.json5'
SENTINEL = '5.0.60：判据改'

# ══════════════════════════════════ 1. LanService：可靠分流判据
LS_OLD = """    const announcedIp: string = peer.devIp;
    const announcedMode: number = peer.devMode;
    if (channel.remoteIp.length > 0) {
      peer.devIp = channel.remoteIp;
    }
    this.pushLog(`v5 对端宣告：name=${peer.devName} ip=${announcedIp}`
      + ` mode=${announcedMode} ver=${peer.dataVersion}`);
    const myIp: string = this.localNet.ip;
    const pcStyleAck: boolean = announcedIp.length > 0 && myIp.length > 0
      && announcedIp === myIp && announcedMode !== DeviceMode.ANDROID;
    if (pcStyleAck) {
      this.pushLog('对端宣告的是本机地址 ⇒ 判定为 PC 端发送器，文件收尾按它的 N+1 读取数回');
    }"""

LS_NEW = """    const announcedIp: string = peer.devIp;
    const announcedMode: number = peer.devMode;
    if (channel.remoteIp.length > 0) {
      peer.devIp = channel.remoteIp;
    }
    this.pushLog(`v5 对端宣告：name=${peer.devName} ip=${announcedIp}`
      + ` mode=${announcedMode} uuid=${peer.uniqueUuid} ver=${peer.dataVersion}`);
    // ★ 5.0.60：判据改「**用握手 UUID 反查发现表**」—— 5.0.58 那条判据（宣告 IP == 本机 IP）
    //   在真机上**从未命中**：实测 PC 宣告的是它**自己**（`.186`），本机是 `.146`。
    //   根因在 PC 源码（`LANShare.cpp:467-474`）：`makeDataEnc(*p1, …)` 里的 `p1` 是
    //   PC **自己设备列表里「与目标同子网的某一台」** —— 可能是它自己、也可能是别的设备。
    //   ⇒ 同帧里的 `devIp / devName / devMode` **三个字段天生不可靠**。
    //   ★ 唯一可靠的是 `uniqueUuid`：取自 `config.uniqueUUid`（`LANShare.cpp:117`），
    //     是**对端自己的 UUID**，与 `p1` 无关；而本机发现表的 key 正好就是它
    //     （`devices: Map<string, LanDevice>`，见 `trackPeer`）⇒ 反查得到**真实** devMode。
    //   ⚠️ 兜底刻意保守：**查不到就按「非 PC」**（退回 N+2）—— 与现状一致，不引入回归。
    let peerMode: number = DeviceMode.UNKNOWN;
    let modeFrom: string = '未命中';
    if (peer.uniqueUuid.length > 0) {
      const known: LanDevice | undefined = this.devices.get(peer.uniqueUuid);
      if (known !== undefined) {
        peerMode = known.devMode;
        modeFrom = '发现表(uuid)';
      }
    }
    if (peerMode === DeviceMode.UNKNOWN && channel.remoteIp.length > 0) {
      // 第二道：按 TCP 对端 IP 反查（发现表里有同 IP 的那台）。同样只信发现表。
      const byIp: LanDevice[] = [];
      this.devices.forEach((d: LanDevice) => {
        if (d.devIp === channel.remoteIp) {
          byIp.push(d);
        }
      });
      if (byIp.length > 0) {
        peerMode = byIp[0].devMode;
        modeFrom = '发现表(ip)';
      }
    }
    const pcStyleAck: boolean = peerMode === DeviceMode.WINDOWS || peerMode === DeviceMode.LINUX
      || peerMode === DeviceMode.MAC_OS || peerMode === DeviceMode.WEB;
    this.pushLog(`v5 ack 分流：对端 mode=${peerMode}（${modeFrom}）⇒ 文件收尾回 `
      + `${pcStyleAck ? 'N+1（PC 端只读 N+1）' : 'N+2（Android/1.35 需要 5+2）'}`);"""

# ══════════════════════════════════ 2. Index：绕开物理旋转
# 2a. 声明 preferFull
IX_A_OLD = """    // 5.0.49：原来是实例字段 `pendingRot`，并发调用时会互相串台（方向错乱）→ 改局部
    let pendRot: number = 0;"""
IX_A_NEW = """    // 5.0.49：原来是实例字段 `pendingRot`，并发调用时会互相串台（方向错乱）→ 改局部
    let pendRot: number = 0;
    // ★ 5.0.60：带 EXIF 方向（deg≠0）时**直接走原图缓存**，不做物理旋转。
    //   理由见下方校验块（物理旋转会转错方向，而校验只看横竖性、抓不到）。
    let preferFull: boolean = false;"""

# 2b. deg 定案后置位
IX_B_OLD = """        degRaw = Index.jpegExifDeg(srcPath);
        deg = degApi !== 0 ? degApi : degRaw;"""
IX_B_NEW = """        degRaw = Index.jpegExifDeg(srcPath);
        deg = degApi !== 0 ? degApi : degRaw;
        // ★ 5.0.60：只要带方向就改走原图缓存（见下方校验块的长注释）
        preferFull = (deg !== 0);"""

# 2c. 校验块：preferFull 也触发原图缓存
IX_C_OLD = """        if (!ok) {
          Log.w(TAG, `缩略图方向仍未修正 ${gw}x${gh}，改用原图缓存: ${srcPath}`);"""
IX_C_NEW = """        // ★ 5.0.60：**只要 deg≠0 就直接走原图缓存，不信任物理旋转。**
        //   真机根因（vivi 2026-10-02，日志 + 沙箱取证）：
        //   对 EXIF orientation=8 的照片，`createPixelMap({desiredSize, rotate})` 的结果
        //   被下面的校验判成「已转正」放行，但把缓存小图拉回来逐像素比对，它与原图的
        //   关系是「**旋转 180° ＋ 拉伸**」，与正确朝向差 90°、比例也被压过
        //   —— 用户看到的正是「比例和方向都不对」。
        //   校验为什么漏掉：它只看**横竖性**（`wantTall === gotTall`），
        //   而 **90° 与 270° 都会翻转横竖性** ⇒ 转反了 90° 照样通过。
        //   ⇒ 与其去猜 `rotate` 的语义（来回改过多轮、同一张图结论还不一致），
        //     不如**绕开物理旋转**：复制原图当缓存（**保留 EXIF**），
        //     显示层 `thumbOri` 对 `-1` 返回 AUTO，交给 `Image` 自己转 ——
        //     这与「弹窗那一刻显示沙箱原图」是**同一条已验证正确**的路。
        if (preferFull || !ok) {
          if (preferFull) {
            Log.i(TAG, `EXIF 方向 ${deg}° ⇒ 直接用原图缓存（不做物理旋转）: `
              + `${Index.baseName(srcPath)}`);
          } else {
            Log.w(TAG, `缩略图方向仍未修正 ${gw}x${gh}，改用原图缓存: ${srcPath}`);
          }"""

# ══════════════════════════════════ 3. 版本号
AJ_OLD = '''    "versionCode": 5000059,
    "versionName": "5.0.59"'''
AJ_NEW = '''    "versionCode": 5000060,
    "versionName": "5.0.60"'''


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        assert s.count(old) == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, s.count(old))
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src = io.open(IX, encoding='utf-8', newline='').read()
if SENTINEL in io.open(LS, encoding='utf-8', newline='').read():
    print('ALREADY APPLIED')
    sys.exit(0)

new_ls = apply(LS, [(LS_OLD, LS_NEW)], 'LanService')
new_ix = apply(IX, [(IX_A_OLD, IX_A_NEW), (IX_B_OLD, IX_B_NEW), (IX_C_OLD, IX_C_NEW)], 'Index')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

# ─────────────────────────────────── 三道保险
# ① 旧判据彻底清零（用精确串，避免被自己的注释误报）
assert "announcedIp === myIp && announcedMode !== DeviceMode.ANDROID" not in new_ls, \
    '5.0.58 那条失效判据仍在'
assert '对端宣告的是本机地址' not in new_ls, '5.0.58 的判据日志仍在'
# ② 新逻辑齐备
for sym, want in [('5.0.60：判据改', 1),
                  ('this.devices.get(peer.uniqueUuid)', 1),
                  ('let peerMode: number = DeviceMode.UNKNOWN;', 1),
                  ("modeFrom = '发现表(uuid)';", 1),
                  ("modeFrom = '发现表(ip)';", 1),
                  ('peerMode === DeviceMode.WINDOWS', 1),
                  ('v5 ack 分流：对端 mode=', 1)]:
    got = new_ls.count(sym)
    assert got == want, 'LS 符号校验失败 %r: 期望 %d 实为 %d' % (sym[:44], want, got)
    print('  OK %2d  %s' % (got, sym[:56]))

for sym, want in [('let preferFull: boolean = false;', 1),
                  ('preferFull = (deg !== 0);', 1),
                  ('if (preferFull || !ok) {', 1),
                  ('EXIF 方向 ${deg}° ⇒ 直接用原图缓存（不做物理旋转）', 1)]:
    got = new_ix.count(sym)
    assert got == want, 'IX 符号校验失败 %r: 期望 %d 实为 %d' % (sym[:44], want, got)
    print('  OK %2d  %s' % (got, sym[:56]))

# ③ 既有结构未被破坏
# ⚠️ `if (!ok) {` 在本文件里另有 6 处（无关分支），不能按 0 校验 ——
#    改为校验「新分支在 + 原日志行还在」（精确串）。
assert new_ix.count('if (preferFull || !ok) {') == 1, '新分支不在'
assert new_ix.count('缩略图方向仍未修正 ${gw}x${gh}，改用原图缓存') == 1, '原校验日志行丢了'
assert new_ix.count('-1 = 这份缓存**保留了 EXIF**') == 1, '原图缓存的 -1 语义注释被动过'
assert new_ix.count('this.service.albumRotMap.set(fullPath, -1);') == 1, '原图缓存的 rot=-1 丢了'
assert 'pcStyleAck' in new_ls and 'pcStyleAck);' in new_ls, 'pcStyleAck 未传到 receive'
assert '5000060' in new_aj and '"5.0.60"' in new_aj

# ─────────────────────────────────── 落盘
io.open(LS, 'w', encoding='utf-8', newline='\n').write(new_ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.60 已应用')
