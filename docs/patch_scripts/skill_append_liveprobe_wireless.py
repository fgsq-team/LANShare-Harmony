# -*- coding: utf-8 -*-
"""给 skill `harmonyos-live-device-probe` 追加「无线调试设备定位」一节（幂等：哨兵判重）。"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-live-device-probe\SKILL.md'
SENTINEL = '## 九、没有 USB 线时的无线调试'

ADD = '''

## 九、没有 USB 线时的无线调试：设备定位与重连

### 前提：鸿蒙的无线调试端口是**随机**的，不是 5555

`hdc tconn <ip>:<port>` 里的 port **每次开关无线调试都会变**，所以不能猜，只能扫。

### 标准流程

```bash
# ① 先确认手机当前 IP —— 换 SSID / DHCP 续租后 IP 会变，别信上一次的地址
for i in $(seq 1 254); do (ping -n 1 -w 300 192.168.10.$i >/dev/null 2>&1 && echo "192.168.10.$i") & done; wait
arp -a | grep 192.168.10      # 拿 MAC，顺便区分网关 / 路由器 / 手机

# ② 对可疑 IP 全端口扫（单机 ~32s @并发1500/超时700ms）
node tests/live-probe/hdc_portscan.mjs 192.168.10.167 1500 700

# ③ 逐个候选端口 tconn，成功者打印 Connect OK
hdc tconn 192.168.10.167:39417

# ④ ★ 无线通道极易掉：把 tconn 和 file send 放**同一条命令**，
#    判定成功一律以设备端 `ls -l` 为准（PowerShell 常吞 stdout）
```

### 关键判据（能省掉大量瞎试）

- 一台主机**全端口都扫不出任何开放端口** → 大概率就是手机，但**无线调试没开**；
- 开着 **23 / 80 / 1900** 的是路由器 / 网关 / IoT 设备，**不是手机**（telnet / http / SSDP）；
- **整个局域网所有存活主机都扫不出 hdc 端口** ⇒ 手机不在这个网里（或调试已关）。
  此时**别再逐台重试**，直接让用户去看手机：
  `设置 → 系统和更新 → 开发者选项 → 无线调试` —— 页面上**直接显示 IP 和端口**，比扫描快得多。

### 连接态的坑

- 连上了但 `list targets` 显示 `Unauthorized` ⇒ 手机上弹了授权框，**必须点「允许」**。
- 报 `need connect-key`（即便 `list targets` 已显示出 serial）⇒ 用 `hdc -t <serial> file send`
  **显式指定目标**，绕过路由失败。
- `hdc file send` 用 **PowerShell** 跑；**Git Bash 会被 MSYS 改写路径**导致发送失败。
- 多机全端口扫描脚本：`node tests/live-probe/hdc_portscan_all.mjs <ip,ip,...> [并发] [超时ms]`。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.endswith('\n'), '文件末尾不是换行'
assert s.count('## 一、找到 hdc') == 1, '找不到第一节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='').write(s2)
print('OK: 已追加第九节，%d -> %d' % (len(s), len(s2)))
