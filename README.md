# LANShare · HarmonyOS

局域网文件传输工具 **LANShare** 的鸿蒙（HarmonyOS / ArkTS）实现。

> 原 Android 版（Java + Gradle）的鸿蒙化移植工程。协议与 Android 端保持兼容，
> 可与 Android 设备互发文件。

---

## 能力

| 能力 | 说明 |
|---|---|
| 设备发现 | UDP 广播发现（端口 4573）+ 设备列表带**版本徽章**（V3 / V4 / V5） |
| 文件传输 | 自研 V5 私有协议（TCP 5856），**定长帧**流控，支持分片并发 |
| 网页端 | 内置 HTTP + WebSocket 服务（5856），浏览器可直接访问 |
| 双向发送 | 设备 → 设备、设备 → 网页、网页 → 设备 |
| 消息页 | 双向文字消息 + 文件消息卡片 + 气泡宫格缩略图 |
| 文件管理 | 独立文件页：缩略图、大图预览、批量另存为、批量删除 |
| 自动存相册 | 可开关；相册资产删除探测（每张图一条索引） |
| 扩展名纠错 | 按文件头魔数纠正错后缀（**只纠正，不给无后缀文件硬加**） |
| 发送到网页 | 直推原文件，**零落盘**（连沙箱副本也不要） |

---

## 协议

| 项 | 值 |
|---|---|
| UDP 发现 | `4573` |
| TCP 传输 / 网页 | `5856` |
| 协议魔数 | `0x66677371` |
| 设备平台代号 | `HARMONY_OS = 6`（原协议已预留） |

TCP 上有**两套编码**，靠首 4 字节分流：

| | 旧协议（`dataVersion < 4`） | v4 协议 |
|---|---|---|
| 开头 | 魔数 → DataEnc 包（12B 头） | 魔数 → 裸 int `NEW_VERSION_4 = -2` |
| 混淆 | 全段 `0x45` | 无 |
| 结构 | 一个包一个命令 | 一条流顺序写多字段 |

**接收有三条平行路径**，新增逻辑必须三条都接入：

| 路径 | 实现 | 场景 |
|---|---|---|
| 单文件 | `V5Transfer.recvBody` | 协议侧大文件 |
| 分片 | `V5Transfer` 的 `SegPart` | 协议侧小文件 |
| 网页 | `MultipartStream.closePart` | 浏览器上传 |

---

## 工程结构

```
entry/src/main/ets/
├── core/        协议编解码、AES、CRC32、手写 JSON、类型与常量
├── net/         TCP 服务端/客户端、UDP 发现、HTTP、WebSocket
├── service/     V5 传输、v4 兼容、文件存储、相册导出、权限
├── store/       RDB 持久化
└── pages/       ArkUI 界面
```

各文件头部注释含**该模块的设计决策与踩坑记录**，改代码前建议先读。

---

## 构建

⚠️ **工程路径必须纯 ASCII** —— hvigor 有硬编码路径校验，中文目录会报
`00306003 Invalid project path`。

### 前置条件

| 依赖 | 版本 |
|---|---|
| DevEco command-line-tools | API 26（SDK 26.0.0） |
| JDK | 21 |
| Node.js | 22.x |
| hvigor | 6.x（工程自带 `hvigor/`） |

### 命令

```bash
node hvigor/bin/hvigorw.js assembleHap
```

产物（**未签名**）：
`entry/build/default/outputs/default/entry-default-unsigned.hap`

### Windows + Git Bash 注意

Git Bash 会破坏 PATH 与路径转换，构建前需：

```bash
unset MSYS_NO_PATHCONV MSYS2_ARG_CONV_EXCL
export JAVA_HOME=<jdk21>
export PATH="$JAVA_HOME/bin:<node>:$PATH"
```

否则会出现 `spawn java ENOENT`（00308018）—— **这通常不是没装 JDK**，
而是 Git Bash 把 PATH 里的 `C:` 当 POSIX 分隔符切坏了。

### 签名

产物默认**未签名**。签名需要华为调试证书，请自行配置 `signingConfigs`
或使用 DevEco Studio 的签名工具。**本仓库不提供任何证书或密码。**

---

## 平台能力限制

以下功能在鸿蒙上**平台不开放**，非实现问题：

| 原功能 | 限制 |
|---|---|
| 枚举已装应用 / 分享 APK | 三方应用无此权限 |
| 应用内自更新（装 APK） | 三方应用不能装 HAP |
| 全盘文件浏览 | 无全盘访问权限，改沙箱 + Picker 授权 |
| 开机自启 | 静态广播注册已废弃 |
| 系统级悬浮窗 | 无等价能力 |

---

## 许可

[Apache License 2.0](LICENSE)
