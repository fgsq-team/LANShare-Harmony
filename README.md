# LANShare · HarmonyOS

局域网文件传输工具的鸿蒙化实现。ArkTS 原生重写，与 Android 原版**协议字节级一致**，可直接互通。

| | |
|---|---|
| 包名 | `com.lanshare.hmos` |
| 最低 API | 26（HarmonyOS） |
| 申请权限 | 2 项，均为系统静默授予（`INTERNET` / `GET_NETWORK_INFO`） |
| 未签名产物体积 | 约 1.3 MB |
| 许可 | Apache License 2.0 |

## 功能

- **设备发现** —— UDP 广播，同网段自动列出可用设备
- **文件互传** —— 手机 ↔ 手机、手机 ↔ 电脑，支持多文件批量发送
- **多图归组** —— 批量收图自动聚合为九宫格，一键存入系统相册
- **文本消息** —— 文本与链接的局域网快传
- **网页端** —— 单端口同时承载文件互传与浏览器访问，浏览器可反向上传到手机
- **协议互通** —— 与官方 LANShare 1.2.x 的 V4 协议互通

## 架构：单端口三协议分流

TCP **5856** 一个端口上同时承载三套协议，按请求首 4 字节魔数分流；设备发现走 UDP **4573**。

| 协议 | 判别依据 | 用途 |
|---|---|---|
| V4 私有协议 | 魔数 `0x66677371` | 文件传输、设备心跳、文本消息 |
| HTTP/1.1 | 请求行形态 | 网页端、上传下载 |
| WebSocket | `Upgrade` 头 | 网页端实时通道 |

```
entry/src/main/ets/
├── core/                 协议内核（零平台依赖，可离线单测）
│   ├── LanConfig.ets     端口 / 魔数 / 业务参数
│   ├── LCmd.ets          命令码（数值不可改）
│   ├── ByteCodec.ets     大端读写（JS 原生小端，必须手写位移）
│   ├── DataPacket.ets    封包协议 + 混淆层
│   ├── DeviceCodec.ets   设备模型 + UDP 心跳报文
│   ├── AesCodec.ets      AES-256-ECB
│   ├── FileCrypto.ets    文件内容加密
│   ├── UdpHeartbeatCodec.ets  UDP 心跳编解码
│   ├── FileTypes.ets     扩展名 / UTD 推断
│   ├── MiniJson.ets      轻量 JSON 解析
│   └── Logger.ets        hilog 门面
├── net/                  网络层
│   ├── LanDiscovery.ets  UDP 广播发现（prefixLength → 掩码换算）
│   ├── LanTcpServer.ets  TCP 服务 + 单端口三协议分流
│   ├── LanClient.ets     客户端
│   ├── HttpProtocol.ets  HTTP/1.1 解析 / 响应 / MIME / Range
│   ├── HttpRouter.ets    路由表
│   ├── WsProtocol.ets    WebSocket 握手 + 帧编解码
│   ├── NativeSocket.ets  Socket 门面
│   └── ProtoIO.ets       读写辅助
├── service/              业务编排
│   ├── LanService.ets      服务编排主入口
│   ├── LanSession.ets      前台会话 + 屏幕常亮
│   ├── FileTransfer.ets    文件收发
│   ├── FileStorage.ets     沙箱存储
│   ├── ExportService.ets   导出到相册
│   ├── ShareInbox.ets      系统分享收件箱
│   ├── TextMessenger.ets   文本消息
│   ├── MultipartStream.ets multipart 流式解析
│   ├── WebSocketSession.ets
│   ├── WebClientStore.ets
│   ├── PermissionGate.ets  权限 / 系统能力探测
│   ├── thumbExif.ets       缩略图 EXIF 方向
│   └── thumbWorker.ets     缩略图任务
├── store/
│   └── DeviceStore.ets   设备持久化
├── entryability/
│   └── EntryAbility.ets  生命周期：退后台停服 / 回前台恢复
└── pages/
    └── Index.ets         主界面
```

## 网页端

浏览器访问 `http://<手机IP>:5856/`。

| 接口 | 说明 |
|---|---|
| `GET /` | 网页端首页 |
| `GET /files` | 列目录 |
| `GET /file/<path>` | 下载单个文件 |
| `GET /stagefile/<path>` | 下载沙箱内文件 |
| `GET /downloadZipFile` | 打包下载 |
| `GET /media` | 媒体列表 |
| `GET /wss` | WebSocket 通道 |
| `POST /initConfig` | 取配置与授权状态 |
| `POST /checkPass` | 轮询授权结果 |
| `POST /updateWebName` | 改网页端显示名 |
| `POST /uploadFile` | 浏览器上传文件到手机 |
| `POST /chatUploadFile` | 网页端聊天上传 |
| `POST /compressFiles` `/compressMedias` | 打包压缩 |

网页端是**白名单授权**模型：`/initConfig` 先按 IP 查 token，未授权时网页每 2 秒轮询
`/checkPass`，直到手机端点「允许」。手机端没有确认入口时，网页会永久停在「没有访问权限」。

> **手机形态的取件通道**：手机拿不到「下载」目录能力（该 SysCap 仅 PC/2in1/平板提供），
> 收到的文件落应用沙箱，系统文件管理器看不到。主页面的「接收到的文件」+「另存为」
> （系统保存对话框）是唯一取件通道。

## 离线验证协议

协议层可以完全脱离鸿蒙环境独立验证 —— 这是本工程能给出「字节级一致」结论的原因。

```bash
cd tests/protocol-bytecheck
python compare.py
```

**原理**：不手写一份 JS 镜像（手镜像会引入「两份代码同时写错」的风险），而是

1. 直接读**交付的 `.ets` 源文件**；
2. 只做 3 处无歧义的替换（`@kit.ArkTS` 导入 → 平台内置同名类；相对导入补 `.ts` 后缀）；
3. 交给 Node 原生 TS 类型擦除执行（类型只是编译期注解，擦除后即 ArkTS 的真实运行语义）；
4. 与 `ref.py`（原 Java 源码的逐行 Python 转写）逐字节比对。

环境要求：Node ≥ 22.6、Python ≥ 3.9。

> 踩过的坑：不要用正则自己擦类型。三元表达式的 `:` 和类型注解的 `:` 形态相同，
> 正则会吃掉 `a ? b : c` 里的 `: c`。用平台的类型擦除工具。

## 构建

需要 HarmonyOS SDK（API 26）与 JDK 17/21。**工程路径必须为纯 ASCII** —— hvigor 对非 ASCII
路径直接报 `00306003 Invalid project path`。

```bat
build.cmd
```

脚本头部三行按本机情况改（命令行工具链 / JDK / 工程路径）：

```bat
set "CL_TOOLS=<command-line-tools 目录>"
set "JAVA_HOME=<JDK 目录>"
set "PROJECT_PATH=<本工程绝对路径>"
```

常用参数：`build.cmd clean`、`build.cmd assembleHap --mode module -p product=default`

三个前置条件，缺一个就报错：

| 条件 | 缺了会怎样 |
|---|---|
| 工程路径纯 ASCII | `00306003 Invalid project path`（中文目录被拒） |
| `DEVECO_SDK_HOME` 指向 SDK | 找不到 API 26 的 syscap |
| `JAVA_HOME` 指向 JDK | `PackageHap` 报 `spawn java ENOENT`（打包要跑 SDK 里的 `app_packing_tool.jar`） |

产物：`entry/build/default/outputs/default/entry-default-unsigned.hap`（未签名）。

## 已知边界

- **后台保活受限** —— 退后台即停服、回前台自动恢复，传输期间屏幕常亮。需要传输时手动打开应用。
- **文件浏览走用户授权目录** —— 不申请全盘存储权限。
- **手机形态无直存通道** —— 保存到系统目录需经系统文件选择器或保存对话框，见「网页端」一节的说明。

## 许可

继承原项目 Apache License 2.0。
