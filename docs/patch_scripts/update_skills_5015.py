# -*- coding: utf-8 -*-
"""
技能更新（5.0.15）：
  1) harmonyos-tcp-socket-server
     · 修正「坑十七」——它的判死模型在真实对端上从未生效（标注 + 表格行改写）
     · 新增「坑十九」——用 TCP 连接复核判死
  2) harmonyos-arkui-ui-pitfalls
     · 第十九节补「高频但不上屏的字段也必须从签名里剔除」
     · 新增「第二十节」——onBackPress 返回键拦截

写法：行号替换 + 末尾追加；先全部构造再统一落盘；文件级 sentinel 判重。
"""
import sys

SK = r"C:\Users\vivi\.workbuddy\skills"
TCP = SK + r"\harmonyos-tcp-socket-server\SKILL.md"
ARK = SK + r"\harmonyos-arkui-ui-pitfalls\SKILL.md"


def load(p):
    raw = open(p, "r", encoding="utf-8", newline="").read()
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def save(p, text, crlf):
    open(p, "w", encoding="utf-8", newline="").write(
        text.replace("\n", "\r\n") if crlf else text)


def find_line(text, needle):
    """按内容定位一行，返回 (行首, 行尾不含换行的位置, 行文本)。要求唯一命中。"""
    i = text.find(needle)
    if i < 0:
        raise AssertionError("未找到锚点: %r" % needle)
    if text.count(needle) != 1:
        raise AssertionError("锚点不唯一(%d 次): %r" % (text.count(needle), needle))
    ls = text.rfind("\n", 0, i) + 1
    le = text.find("\n", i)
    if le < 0:
        le = len(text)
    return ls, le, text[ls:le]


def op_replace_line(text, needle, block):
    ls, le, old = find_line(text, needle)
    return text[:ls] + block + text[le:]


def op_insert_after_line(text, needle, block):
    ls, le, old = find_line(text, needle)
    return text[:le] + "\n\n" + block.strip("\n") + text[le:]


OPS = {"replace": op_replace_line, "after": op_insert_after_line}


def append(text, block):
    return text.rstrip("\n") + "\n\n" + block.strip("\n") + "\n"


# ===================== harmonyos-tcp-socket-server =====================
TCP_WARN = '''> 🔴 **先把坑十九读完再回来看这里 —— 本坑的「判死」部分已被它取代。**
>
> 下面那套「RTT 概率判别 + 攒信任分」在**真实对端上从未成立过**：
> 实测对端（另一台 LANShare）**根本不回 `GET_DEVICES`**，只按自己的周期广播心跳，
> 于是 RTT 判据永远命不中（偶尔命中的那次只是撞上它自己的周期广播），
> 「信任分」永远是 0 → 快速判死形同虚设 → 最终还是走 8s 超时兜底，
> 用户看到的下线时间依然是「十秒左右」。
>
> **结论**：
> - **UDP 探活只能当"加速"**（让愿意应答的设备顺手刷新在线时间），**不能用来判死**；
> - **判死改用 TCP 连接复核**（坑十九）——「连得上就是在」是确定性事实；
> - ① 层（下线报文 1003）与 ③ 层（超时兜底）**依然有效**，保留。
'''

TCP_ROW_NEW = '''| ② ~~**主动探活**：单播 ping + 短超时~~ | ~~安静 > QUIET 发出，DEADLINE 无回包~~ | ⚠️ **实测无效** | 对端根本不回这个报文 → 信任分永远是 0 → 实际仍走 ③。判死改用 **TCP 连接复核**（坑十九），UDP 探活降级为「加速」 |'''

TCP_19 = '''## ★★ 坑十九：判「对端还在不在」—— 用 **TCP 连接**，不要用 UDP 探活

> **坑十七的判死部分已被本坑取代。** 见坑十七标题下的红色提示。

### 症状

「对方关掉 App，本机列表**十秒左右**才显示下线。」
超时值调了两轮（15s → 9s → 8s）都没明显改善 —— 因为**判死模型本身没生效**，
调的只是一个从未被用到的兜底值。

### 根因：UDP 探活的前提在真实对端上不成立

坑十七的模型是：

```
单播探活发出 → 对端回包 → RTT ≤ 500ms → 信任分 +1 → 攒够 3 次才允许「快速判死」
```

它悄悄依赖一件事：**对端会应答我们的 `GET_DEVICES`**。而真实对端（另一台 LANShare）**不理它**，
只按自己的周期广播心跳。于是整条链断在最前面：

- RTT 判据永远命不中（偶尔命中的那次只是**撞上它自己的周期广播**，间隔远大于 500ms）；
- 「信任分」永远是 0 → 快速判死**从未触发** → 一直走 `OFFLINE_MS` 的 8s 兜底；
- 加上巡检粒度与用户计时误差，观感就是「十秒左右」。

> **教训**：把「判死」挂在对端**愿不愿意回某个报文**上，等于把下线速度寄托在
> 对端的实现细节上。而**你的实现对端可能根本不是你的实现**。

### 换成 TCP 连接：连得上就是在，连不上就是不在

设备之间本来就有一条 TCP 通道（文件端口）。向它发起一次连接即可：

| 连接结果 | 含义 |
|---|---|
| 成功 | 设备活着（服务在监听） |
| 立即 RST | 主机活着但服务已停 → 等同于下线 |
| SYN 超时 / 不可达 | 设备不在 / 已关机 / 不在同网段 |

这是**应用层无法回避**的事实，不依赖对端实现任何额外报文。
局域网里 RST 常常几毫秒就回来，所以「两次复核失败」≈ 设备消失后 **2~3s** 判死。

```ts
private static async tcpPing(ip: string, port: number): Promise<boolean> {
  let s: socket.TCPSocket | null = null;
  try {
    s = socket.constructTCPSocketInstance();
    await s.connect({ address: { address: ip, port, family: 1 }, timeout: TCP_PROBE_TIMEOUT_MS });
    closeQuietly(s);
    return true;                      // 连得上 = 还在
  } catch (e) {
    closeQuietly(s);
    return false;                     // RST / 超时 / 不可达 = 不在
  }
}
```

### ⚠️ 只建连，**不要发任何字节**

发魔数（或任何握手字节）会被对端的协议分流逻辑引到「私有协议」分支上 ——
等于凭空给对方造一条半截握手，还可能触发它的业务逻辑。
什么都不发，对端读到 EOF 就会把这条连接正常收尾。

### ⚠️ 安全阀：必须有「曾经成功过」这个前提（否则列表会**持续闪烁**）

设想某台设备的文件端口本来就不可连（防火墙 / 未开共享 / 端口被改）。
如果直接用「复核失败」判死，它**在线时**也会被反复判死 → 消失 2s 又冒出来 → **持续闪烁**，
比「慢」更糟。

| 常量 | 建议值 | 作用 |
|---|---|---|
| `TCP_PROBE_TIMEOUT_MS` | 1000 | 单次连接超时（RST 是毫秒级，1s 已极大方） |
| `TCP_PROBE_COOLDOWN_MS` | 700 | 同一设备两次复核的最小间隔 |
| `TCP_PROBE_MISS_LIMIT` | 2 | 连续失败几次才判死（抗单次网络抖动） |
| `TCP_VERIFY_MAX_MISS` | 3 | 「验证不通」时最多试几次，之后放弃并退回超时兜底 |

```
· 设备「曾经成功过」   → 失败累计到 MISS_LIMIT(2) 就判死
· 设备「从未成功过」   → 只累计、**不判死**；累计到 VERIFY_MAX_MISS(3) 后不再 connect，退回超时兜底
· 任何一次成功、或收到它任意一个 UDP 包 → 失败计数**清零**
```

### 落地：巡检里的顺序

```ts
sweepDevices() {
  this.devices.forEach((d: LanDevice, key: string) => {          // ← 第二个参数才是 Map 的 key
    if (this.deviceGone(d, now)) { this.dropDevice(key, d); return; }      // 基础超时兜底
    if (now - d.lastSeenMs < QUIET_MS) { this.tcpProbeMiss.delete(ip); return; }
    if (now - lastProbeSent >= PROBE_RETRY_MS) { this.sendLivenessProbe(ip, now); }  // UDP 加速
    this.tcpProbeStep(key, d, now);                            // TCP 复核：判死发生在这里
  });
  // …再算「在线集合签名」，变了才 emit（每秒无脑 emit 会让整页每秒重渲染）
}
```

> ⚠️ `dropDevice` 用的是 **Map 的 key**（`uniqueUuid` 或 IP），而 `devices.forEach`
> 的第一个参数是 **value**。要拿到 key 必须用**第二个参数** ——
> 拿 `d.devIp` 去删如果对不上 key 就会「删不掉」，表现为设备明明被判死却仍留在列表里。

### 时间线（对端关掉 App 后）

| 时刻 | 动作 |
|---|---|
| t = 0 | 最后一次收到它的心跳 |
| t ≈ 1.2s | 安静超过 `QUIET_MS(1200)` → 发 UDP 单播探活 + **TCP 复核 #1** |
| t ≈ 1.2s | 端口已关 → 立刻回 RST → 复核失败 → miss = 1 |
| t ≈ 2.2s | 冷却（700ms）已过 → **TCP 复核 #2** → 失败 → miss = 2 → **判死并立即移除** |

### 换模型时别忘了清死代码

只改判据、留下旧模型的常量与字段，会误导下一个读代码的人。换完之后 `grep` 一遍这些符号，
**该删的全部删干净**：`probePendingAt` / `probeTrust` / `noteProbeAnswer` /
`DEADLINE_MS` / `MAX_RTT_MS` / `TRUST`。
'''

# ===================== harmonyos-arkui-ui-pitfalls =====================
ARK_SIG_NOTE = '''### ⚠️ 补充（实测）：高频字段**即使不上屏**，放进签名也会把界面拖死

上面那份签名里带了 `s.connections`（连接数）与 `s.webRequests`（请求数）。
**它们界面上根本没有被渲染**（全工程 `grep` 0 处引用），看着像"无害的稳定字段"。
但接收文件时 `connections` 会随 16 条分片连接的建立/关闭**高频变化** ——
签名一直在变，`this.snapshot = s` 一直在执行，**整页重建 ≈ 10 次/秒**，
刚拆出去的进度字段白拆了。

**规则：签名只放「会被渲染」且「变化不频繁」的字段。**

| 字段形态 | 放哪 |
|---|---|
| 高频 + 会被渲染 | 独立 `@State`（如进度） |
| **高频 + 不上屏** | **从签名里剔除**（如连接数、请求数） |
| 低频 + 会被渲染 | 放进签名 |
| 低频 + 不上屏 | 无所谓（放进去只是白刷几次） |

> 自查手法：把签名里每个字段都 `grep` 一次，问「**它在界面上出现过吗？**」
> 没出现、又可能高频变 → 立刻删掉。
'''

ARK_20 = '''## 二十、返回键（`onBackPress`）—— 不实现它，返回就是**退出应用**

### 症状

列表页长按进入多选，选到一半误触返回 —— **直接回桌面**，勾选全丢。

### 根因

`@Entry` 页面**不实现 `onBackPress()`** 时，系统返回的默认行为就是**退出应用**。
「返回」在用户心里是「退回上一层」，但这种单页面应用没有"上一层"可退，
框架就只能退出 —— 除非你显式告诉它该退什么。

### 修法：按优先级吞掉「临时状态」

```ts
@Entry
@Component
struct Index {
  @State fileSelectMode: boolean = false;
  @State showQr: boolean = false;
  @State pickStep: number = 0;

  /**
   * @returns true = 我已处理（不再往下传）；false = 交给系统默认行为
   */
  onBackPress(): boolean {
    if (this.fileSelectMode) { this.exitFileSelect(); return true; }   // 多选 → 取消多选
    if (this.showQr) { this.showQr = false; return true; }             // 弹窗 → 关弹窗
    if (this.pickStep > 0) { this.pickStep = 0; return true; }
    return false;                                                      // 都没有 → 正常退出
  }
}
```

### 要点

| 点 | 说明 |
|---|---|
| 语义 | **返回 = 先退掉最上层临时状态**（多选 / 弹窗 / 二级表单），都没了才退出应用 |
| 顺序 | `if` 的顺序就是优先级（多个临时状态可能叠加时按"越上层越靠前"排） |
| 返回值 | 返回 `true` 才是**拦截**；返回 `false` / `void` 表示不处理。别写成裸 `return;` |
| 自绘浮层也算 | 用 `Stack` + `@State` 自己画的弹窗（不是 `CustomDialogController`）**必须**在这里手动关，框架管不着它 |
| 位置 | 只能定义在 `@Entry` 装饰的组件上（页面级生命周期回调） |

> 顺带：同一个回调也是**拦截返回键做"二次确认"**的落点（例如"再按一次退出"），
> 手法同上 —— 只是把 `return true` 换成「弹个 toast + 记个时间戳，短时间内再按才返回 false」。
'''

PATCHES = [
    (TCP, "坑十九", [
        ("replace", "② **主动探活**", TCP_ROW_NEW),
        ("after", "## ★★ 坑十七：设备", TCP_WARN),
    ], TCP_19),
    (ARK, "二十、返回键", [
        ("replace", "别把「只读不渲染」的大数组塞进签名",
         "| **别把「只读不渲染」的大数组塞进签名** | 比如只是复制去剪贴板的日志数组：UI 读的是**同一个活数组**，不必参与签名，参与只会让刷新变频繁 |\n\n"
         + ARK_SIG_NOTE.rstrip("\n")),
    ], ARK_20),
]


def main():
    staged = []
    for path, sentinel, ops, tail in PATCHES:
        text, crlf = load(path)
        if sentinel in text:
            print("[SKIP] 已更新: %s" % path)
            continue
        for kind, needle, block in ops:
            text = OPS[kind](text, needle, block)
        text = append(text, tail)
        staged.append((path, text, crlf))
    if not staged:
        print("[NOTHING] 技能已是最新")
        return 0
    for path, text, crlf in staged:
        save(path, text, crlf)
        print("[OK] %s" % path)
    print("[DONE] 技能更新完成，共 %d 个文件" % len(staged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
