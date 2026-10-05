# LANShare · HarmonyOS 7 (API 26)

LANShare 局域网文件传输工具的鸿蒙化工程。

> **工程位置**：`E:\lanshare-harmony\LANShare-HarmonyOS\`
> ⚠️ **不能放在含中文的路径下** —— hvigor 有硬编码的路径校验，中文目录会报 `00306003 Invalid project path`。
> 工作区里的 `E:\lanshare项目\鸿蒙工程位置说明.md` 有说明。
>
> **先读这个**：`鸿蒙7迁移技术决策报告.md`（迁移结论、风险、构建实况、分批计划）
> **开发执行看这个**：`docs/迁移对照表.md`（逐项依赖映射 + 能力缺失清单 + 验收标准）

---

## 当前状态

| 项 | 状态 |
|---|---|
| 命令行工具链构建 | ✅ **BUILD SUCCESSFUL**（hvigor 6.26.8 / SDK 26.0.0 / API 26） |
| 构建产物 | ✅ `entry/build/default/outputs/default/entry-default-unsigned.hap`（0.87 MB） |
| ArkTS 编译 | ✅ 通过（3 条非阻断告警，见决策报告 8.4） |
| 协议字节级对拍 | ✅ 8/8 通过 + 往返自洽校验通过 |
| 原 Web 前端复用 | ✅ 26 个文件零改动，已确认进包 |
| 真机运行 | ❌ 未做（未签名 HAP 只能装模拟器，见下） |

### 三条产品决策（vivi 2026-09-30）

1. **不上应用市场** → 不必过审
2. **不做后台保活**，需要传输时手动打开应用 → 长时任务 + 实况窗方案**整体删除**，改为纯前台运行（退后台即停服、回前台自动恢复、传输期间屏幕常亮）
3. **文件浏览走用户授权目录** → 不申请全盘存储权限

---

## 构建

```bat
build.cmd
```

脚本开头三行按本机情况改（工具链 / JDK / 工程路径）：

```bat
set "CL_TOOLS=D:\Downloads\commandline-tools-windows-x64-26.0.0.851\command-line-tools"
set "JAVA_HOME=C:\Users\vivi\.workbuddy\binaries\java\jdk-21.0.2"
set "PROJECT_PATH=E:\lanshare-harmony\LANShare-HarmonyOS"
```

常用参数：`build.cmd clean`、`build.cmd assembleHap --mode module -p product=default`

### 构建后自动推送到手机

`build.cmd` 构建成功后会调用 `push.cmd`，把 HAP 推到手机的**下载**目录：

```
/storage/media/100/local/files/Docs/Download/LANShare-HarmonyOS.hap
```

文件名固定、覆盖式 —— 手机上下载目录里永远是最新一版，不用翻时间戳。
手机没连（`hdc list targets` 为空）时只打印 `[WARN] no device connected`，
**不影响构建的成功状态**（构建成功就该算成功，没带手机不是构建的错）。

只推送、不重新构建：

```bat
push.cmd                        :: 推到默认下载目录
push.cmd MyBuild.hap            :: 换个文件名
push.cmd "" /data/local/tmp     :: 换个目标目录
```

前置条件：`push.cmd` 头部两行按本机改（`hdc` 路径 / 工程路径）。

> ⚠️ 推过去的是 **未签名 HAP**，真机直接安装会被验签拒绝 —— 见下面「装到设备」。

### 网页端（浏览器访问）

单端口 5856 上同时提供文件互传与网页端。网页端的三个接口契约与
`rawfile/web/js/lanshare.min.js` 严格对齐：

| 接口 | 请求 | 响应 |
|---|---|---|
| `POST /initConfig` | `{"test":1}` | `{rootPath, name, token, pass}` |
| `POST /checkPass` | `{}` | `{pass: bool}` |
| `POST /files` | `{path, isBack}` | `{path, list:[{name,path,isDirectory,time,...}]}` |
| `GET /wss` | WebSocket 升级（`?token=`） | 101 + 帧通道 |

> ⚠️ 网页端是**白名单授权**模型：`/initConfig` 先按 IP 查 token，
> `pass=false` 时网页会每 2 秒轮询 `/checkPass`，直到手机端点「允许」。
> 手机端没有确认入口时，网页会**永久停在「没有访问权限」**。

**「接收到的文件」**：手机形态拿不到「下载」目录能力（仅 PC/2in1/平板），
收到的文件落应用沙箱，系统文件管理器看不到。主页面的「接收到的文件」卡片
+ 「另存为」（系统保存对话框）是唯一的取件通道。

### 构建的三个前置条件（缺一个就报错）

| 条件 | 缺了会怎样 |
|---|---|
| 工程路径纯 ASCII | `00306003 Invalid project path`（中文目录被拒） |
| `DEVECO_SDK_HOME` 指向 SDK | 找不到 API 26 的 syscap |
| `JAVA_HOME` 指向 JDK | `PackageHap` 报 `spawn java ENOENT`（打包要跑 SDK 里的 `app_packing_tool.jar`） |

> 本机的 JDK 是**免安装版 OpenJDK 21**（解压在 `C:\Users\vivi\.workbuddy\binaries\java\jdk-21.0.2`，不写注册表、不改系统 PATH，只被 `build.cmd` 局部引用）。原安装包已删。
> 用真 JRE 目录之外的任何 JDK 17/21 都可以，改 `JAVA_HOME` 即可。

---

## 离线验证协议（不用鸿蒙 SDK，不用 JDK）

协议层可以完全脱离鸿蒙环境独立验证 —— 这是本工程能给出"字节级一致"结论的原因。

```bash
cd tests/protocol-bytecheck
python compare.py
```

预期输出：

```
[一致] udpEmpty(UDP_GET_DEVICES)                   16 bytes
[一致] udpString(UDP_SET_DEVICES, 中文设备名)           45 bytes
[一致] mixed fields                                58 bytes
[一致] payload all 0xFF                           272 bytes
[一致] payload all 0x00                           272 bytes
[一致] payload 0x00..0xFF                         272 bytes
[一致] negative cmd (-2)                           16 bytes
[一致] int boundary values                         24 bytes
往返自洽校验: Java 参考 / .ets 实测 均通过
结论: 通过。协议与 Android 端位级一致，可直接互通。
```

环境要求：Node ≥ 22.6、Python ≥ 3.9。

### 对拍的原理

不手写一份 JS 镜像 —— 手镜像会引入"两份代码同时写错"的风险。而是：

1. 直接读**交付的 `.ets` 源文件**
2. 只做 3 处无歧义的替换（`@kit.ArkTS` 导入 → 平台内置同名类；相对导入补 `.ts` 后缀），落到 `_build/*.ts`
3. 交给 Node 22 原生 TS 类型擦除执行（类型只是编译期注解，擦除后即 ArkTS 的真实运行语义）
4. 与 `ref.py`（原 Java 源码的逐行 Python 转写）逐字节比对

> 踩过的坑：不要用正则自己擦类型。三元表达式的 `:` 和类型注解的 `:` 形态相同，正则会吃掉 `a ? b : c` 里的 `: c`。用平台的类型擦除工具。

---

## 目录结构

```
LANShare-HarmonyOS/
├── build.cmd                     # 一键构建（ASCII-only，见文件头注释）
├── push.cmd                      # 构建后把 HAP 推到手机（由 build.cmd 自动调用）
├── 鸿蒙7迁移技术决策报告.md      # 主交付物：结论 / 决策 / 风险 / 构建实况
├── docs/
│   └── 迁移对照表.md             # 依赖映射 / 能力缺失 / B1-B3 验收标准 / 安全债
├── tests/protocol-bytecheck/     # 协议字节级对拍（无需 DevEco / Android SDK / Java）
│   ├── check.mjs                 #   读真实 .ets 源文件，降级为可执行 TS
│   ├── ref.py                    #   原 Java 实现的逐行 Python 转写（参考基准）
│   └── compare.py                #   对拍驱动
└── entry/src/main/
    ├── module.json5              # 权限声明（已移除 KEEP_BACKGROUND_RUNNING / backgroundModes）
    ├── resources/rawfile/web/    # 原 Web 前端，原样复用
    └── ets/
        ├── core/                 # 协议内核（零平台依赖，可离线测试）
        │   ├── ByteCodec.ets     #   大端读写（JS 原生小端，必须手写位移）
        │   ├── DataPacket.ets    #   封包协议 + 混淆层
        │   ├── DeviceCodec.ets   #   设备模型 + UDP 心跳报文
        │   ├── AesCodec.ets      #   AES-256-ECB（含安全债说明）
        │   ├── LCmd.ets          #   命令码（数值不可改）
        │   ├── LanConfig.ets     #   端口 / 魔数 / 业务参数 / 前台运行开关
        │   └── Logger.ets        #   hilog 门面
        ├── net/
        │   ├── LanTcpServer.ets  #   TCP 服务 + 单端口三协议分流
        │   ├── HttpProtocol.ets  #   HTTP/1.1 解析 / 响应 / MIME / Range
        │   ├── HttpRouter.ets    #   路由（与原 LHttpServer 路由表对应）
        │   ├── WsProtocol.ets    #   WebSocket 服务端握手 + 帧编解码
        │   └── LanDiscovery.ets  #   UDP 广播发现（含 prefixLength→掩码换算）
        ├── store/DeviceStore.ets #   relationalStore
        ├── service/
        │   ├── LanService.ets    #   服务编排（原 2571 行 LANService 的对应物）
        │   └── LanSession.ets    #   前台会话 + 屏幕常亮（替代原后台保活）
        ├── entryability/EntryAbility.ets   # 生命周期：退后台停服 / 回前台恢复
        └── pages/Index.ets       #   服务控制台
```

---

## 装到设备

| 目标 | 能否装当前产物 | 说明 |
|---|---|---|
| **模拟器** | ✅ | 未签名 HAP 可直接装 |
| **真机** | ❌ | HarmonyOS NEXT 起真机安装强制验签：需要**调试证书 + 含该设备 UDID 的调试 Profile（.p7b）** |

真机签名最省事的路径：DevEco Studio 连真机 → `File > Project Structure > Project > Signing Configs` → 勾选 `Automatically generate signature`（需登录华为开发者账号，IDE 会自动把设备 UDID 写进 Profile）。

> ⚠️ 「不上应用市场」省掉的是审核，**不是签名**。要给真机装，签名这一步绕不开。
> ⚠️ 用发布证书签的包不能 `hdc install` 到设备调试；Profile 里没有当前设备 UDID 也会被拒。取 UDID：`hdc shell bm get -u`。

---

## 剩余工作

1. **B1 收尾**：从原码提取 `FS_SHARE_FILE` / `FS_SYNC_MEDIA` 等文件传输命令的字段布局。
   *代码里对这几个命令显式返回"未实现"而不是猜 —— 猜错会静默丢文件。* 入口在 `docs/迁移对照表.md`。
2. **B2**：62 个 layout → ArkUI 声明式。
3. **B3**：ScanKit / AVPlayer / ArkWeb / NFC / Camera / 通知 / 振动。

---

## 许可

继承原项目 Apache License 2.0。
