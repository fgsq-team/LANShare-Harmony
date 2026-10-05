/**
 * 主页面 —— 替代 Android 的 HelloActivity + MainActivity + FragmentFiles 那套 UI
 *
 * 原项目 62 个 layout + Fragment/Adapter 体系在鸿蒙侧统一改为 ArkUI 声明式组件。
 * 本页承载"服务控制台 + 设备列表 + 文件发送入口"这三块；
 * 文件浏览/聊天等页面仍按 B2 批次逐个补。
 *
 * ⚠️ 与 Android 版的形态差异（vivi 2026-09-30 决策）：
 * 本应用**不做后台保活**，退到后台即停服、回前台自动恢复。
 * 因此页面上的文案要明确告诉用户"保持本页在前台"，不能沿用"装了就能后台待命"的说法。
 *
 * ## 2026-09-30 界面改版（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 打开即共享，不要「开始共享」按钮 | `aboutToAppear` 自动 `startSharing`；仅失败时露出「重试」 |
 * | 删掉「在线设备/当前连接/网页访问」统计行 | 整行删除（数据仍在 snapshot 里，只是不上屏） |
 * | 访问地址模块做小 | 去说明文案 + 去「打开网页端」假按钮，网址与复制钮并排一行 |
 * | 标题和状态栏重叠 | 沉浸式下自取 `AvoidArea`，标题栏按状态栏高度让位（不写死数值） |
 * | 日志单独一个 tab | `Tabs` 底部多页：共享 / … / 日志 |
 *
 * ## 2026-09-30 第二轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 加「消息」tab，双方互发文字 | 页签 共享/消息/日志；消息页含目标设备胶囊 + 气泡列表 + 输入框；发送走 `LanService.sendTextMessage` |
 * | 底栏小白条位置与 tab 栏不同色 | 去掉 `Tabs` 的 bottom padding，改成一个与 tab 栏同色的显式底条（高度取避让区，不写死） |
 *
 * ## 2026-09-30 第四轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 接收文件单独一个 tab | 页签改为 共享 /「文件」/ 消息 / 日志；文件页含另存为 + 删除 + 清空，切到该页自动刷新列表 |
 *
 * ## 2026-09-30 第五轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 相册选择器与文件选择器并列 | 设备行两个按钮「相册」/「文件」；相册走 `PhotoViewPicker`（URI 永久授权：无需权限、无需先复制到沙箱） |
 * | 收/发进度在文件页也显示 | 文件页顶部复用 `snapshot.transferText` 的进度条 |
 * | 删掉日志 tab、消息放中间 | 页签改为 共享 / 消息 / 文件；日志改为共享页底部的「复制日志」按钮 |
 *
 * ## 2026-09-30 第三轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 沙箱里的文件删不掉 | 「接收到的文件」每项加「删除」、顶部加「清空」，删前弹确认框；删除走 `ExportService.deleteFile/deleteAll`，带路径守卫 |
 *
 * ## 2026-09-30 第六轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 设备名手动可改 | 共享页「运行模式」卡顶部加「本机名称」行：点「编辑」就地改，写入 preferences 并实时生效（下一轮 UDP 广播即带新名），重启沿用；编辑态「恢复默认」清除自定义名回到设备市场名 |
 * | 悬浮窗加大、长文件名显示全 | `transferFloat` 改为两行（文案最多 2 行，不再单行截断）+ 顶部 Linear 进度条，宽度 92%→96% |
 * | 传输完成自动刷新文件页 | `onSnapshot` 改用 `transferText` 由非空变空的跳变触发刷新，覆盖「接收侧」收完这类原本漏刷的场景 |
 * | 消息页发送入口收敛为加号 | 删除消息页独立的「相册/文件」行；在输入框右侧加「+」按钮，`bindMenu` 弹出「相册/文件」选择 |
 *
 * ## 2026-09-30 第九轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 消息页显示一条文件消息、点击跳文件页 | `ChatMessage` 新增 `kind`（`text`/`file`）；`LanService.onTransferReport` 在**传输成功**（`done && ok`）时插一条 `kind='file'` 的记录，内容为文件名（多发时为「N 个文件」）；气泡显示「收到文件/已发送文件 + 文件名 + 点击查看」，点击走 `openFileTab()` 刷新列表并切到文件页（index 2）。⚠️ 失败不插，否则会让人误以为传成了 |
 *
 * ## 2026-10-01（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 *
 * ## 2026-10-01 第五轮（vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 文件名自适应没生效 | 上一版在 `maxLines(2)` 之外又叠了 `lineHeight(19)` —— 它同时约束行高与组件高度，正是「两行没出来」的原因。本次**移除 `lineHeight`**，只留 `maxLines(2)`（Text 高度随实际行数走，天然自适应）+ `wordBreak(BREAK_ALL)`（无空格长英文名默认整词溢出、折不出第二行） |
 * | 去掉每行的「删除」按钮，改长按多选，多选后一次保存/删除 | 行内只剩「发到网页 / 另存为」；`LongPressGesture` 长按进多选，顶部条「已选 N / 全选 / 取消」，底部条「另存为(N) / 删除(N)」；批量另存走 `ExportService.saveMany`（一次弹窗、多文件名） |
 * | 设备关闭后列表里过一会才消失 | ① `DEVICE_OFFLINE_MS` 15s → **9s**；② 新增 `LanService` 1s 巡检 `sweepDevices()` —— 离线是「超时」判定的，那一刻**没有任何事件**，不主动巡检就只能等下一次别人发包才刷新 |
 * | 网页地址旁加二维码按钮 | 访问地址卡片「复制」旁新增「二维码」，弹窗用 ArkUI **内建 `QRCode` 组件**渲染 `webUrl`（无需三方库） |
 * | 消息历史记录退出应用就清空 | 新增 `LanService.restoreChat/scheduleChatSave/saveChatAsync`：落盘到 `${filesDir}/chat_history.json`（MiniJson 手写序列化），启动时恢复；「清空」连持久化一起清 |
 *
 * ## 2026-10-01 第七轮（5.0.15，vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 多选后返回不该回桌面 | 补 `onBackPress()`：多选态 → 取消多选；二维码 / 发文件弹窗 → 关弹窗；都不是才交还系统。**返回的语义是「先退掉最上层临时状态」** |
 * | 把文件页的删除按钮加回来 | 行内恢复「删除」（红字浅底，落在第二行右侧）；长按多选继续保留 —— 删一个点按钮、删一批用多选 |
 * | 接收还是不够流畅 | ① `snapshot` 签名**剔除** `connections` / `webRequests` / `onlineDevices` / `knownDevices` —— 前两个在接收期高频变化（16 条分片连接反复建立/关闭），而界面上根本不渲染它们，放签名里等于让每次「有分片连上」都触发**整页重建**；② 解密切片 512KB → **256KB**、让帧预算 16ms → 12ms |
 * | 对方关掉 App 十秒左右才显示下线 | **换掉判死模型**：UDP「信任分」在本机与 1.35 平板之间**从未攒够过**（对端不理 `UDP_GET_DEVICES`，偶尔命中的那次也只是撞上它自己的周期广播、RTT 超判据），实际一直走 8s 兜底。改成 **TCP 复核** —— 向对端文件端口 5856 建一次连接（**不发任何字节**就关，免得被引到私有协议分支），连不上连续 2 次即判死。预期 **2~3s** 消失（见 `LanConfig.DEVICE_TCP_*`） |
 *
 * ## 2026-10-01 第八轮（5.0.16，vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 删除确认弹窗的文件名字体过大、显示不全 | 系统 `showDialog` 的 **title 字号固定、且不按内容折行** —— 把「删除『<长文件名>』？」整句塞进 title，长名必然被截。**改为自绘弹窗**：标题固定 16fp 短文案，文件名单独一块 **13fp** 小字（`wordBreak(BREAK_ALL)` + `maxLines(5)`），多长的名字都能整段折行看全 |
 * | 收到的图片想要缩略图、点了能看大图 | ① 按扩展名识别图片 → 行内 **48×48 缩略图**（`fileUri.getUriFromPath()` 取沙箱 URI，配 `sourceSize(96)` 压解码尺寸 —— 不压的话 40 张原图会被整张解进内存）；② 普通态**点一下进全屏预览**（双指缩放 / 双击复位 / 放大后可拖动 / 返回键或「关闭」退出） |
 *
 * ## 2026-10-01 第六轮（5.0.14）
 * | 诉求 | 落法 |
 * |---|---|
 * | 首页的网址显示不全了 | 上一版把「复制 / 二维码」与网址放同一行，`layoutWeight(1)` 只拿到剩余宽度（约 200vp）放不下 26 字符的地址。改为按钮上移到标题行，**网址独占整行铺满** |
 * | 检测设备下线还是不够快 | ① 收到 `UDP_DEVICES_OFF_LINE(1003)` 立刻移除（原版 Android 就是这么做的，smali `LANService.smali:14116`；我们此前只发不收）；② 对安静 1.2s 的设备发 **UDP 单播探活**；③ `SCAN_TIME` 5s→3s |
 * | 接收文件时界面卡顿、切 Tab 卡好几秒 | ① 进度从 `snapshot` 拆成独立 `@State`（`tText`/`tPercent`），10Hz 的进度刷新不再触发**整页重建**；② `snapshot` 其余字段走签名比较，没变就不赋值；③ 接收循环里同步逐字节解密切片 + 预算**让帧给 UI**（`V5Transfer.yieldFrame`） |
 * | 多选后取消保存，不该退出多选 | `ExportService.saveMany` 改返回 `SaveOutcome`（带 `cancelled`）；取消时保留勾选与多选态，原样停住等用户再点一次 |
 *
 * ## 2026-10-01 第四轮（vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 进度条仍不线性，70% 左右一下跳到 100% | 两处：① `V5Transfer` 接收侧**每条连接独占一个 fd 复用**（原来每块 `openSync`+`closeSync`，1GB ≈ 1000 次同步系统调用压在 UI 线程上，落盘被拖慢 → 进度显不出来、末段猛涨）；② 上报节流状态由「每连接私有」改为「SegPart 共享」，原本全局百分比每变 1%，16 条连接会**各自上报一次**（≈1600 次，其中 15/16 是重复值）。另给进度条加 240ms 线性过渡动画，视觉上"追上去" |
 * | 接收文件过程中页面卡顿 | ① 同上：去掉了每块 open/close 与 16 倍冗余上报；② `onSnapshot` 原来**每次 emit 都无条件**重建 `this.devices` 数组（进度 10Hz → 每秒十几个同内容新数组，设备列表 ForEach 反复 diff），改为**签名比较**后才换引用 |
 * | 文件名一行放得下就一行、放不下才两行 | `maxLines(2)` 本身就是"内容自适应行数"（高度随内容走，不给固定 height 就不会撑成两行）；另补 `wordBreak(BREAK_ALL)` —— 无空格的长英文/哈希名默认被当整词溢出，第二行折不出来 |
 * | 设备列表显示传输协议版本（V3/V4/V5） | 设备行加**版本徽章**（取对端广播的 `dataVersion`：>=5→V5，4→V4，3→V3…），同时带进消息页胶囊与发文件弹窗 |
 * | 设备发现有点慢（官方版也慢） | ① 收到对方 `UDP_GET_DEVICES` 探测**立即单播应答**（原逻辑双方各等 5s 周期，最坏慢一整拍）；② 启动时 burst 补探（0.7s / 1.8s 各一轮），不再只发一次就干等 5s |
 *
 * ## 2026-10-01 第三轮（vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 接收进度条一直在 1%~2% 之间跳动、然后立马 100% | **根因在 `V5Transfer` 的 1110 分片接收**：进度上报的是 `part.received + got`，而 `received` 只在「整片收满」时才累加 —— 16 片并发推进时，每条连接报的都是「自己那一片的局部进度」，互相覆盖 → 低区间来回跳；16 片几乎同时收满后一次性跳到 100%。改为**每落地一块就累加到跨片共享的计数器**（与发送侧 `SegSend.sent` 同一模型），上报值必然单调递增 |
 * | 文件页「接收到的文件」文件名过长显示不全 | 原来文件名与三个按钮同在一个 `Row` 里，按钮横向占掉约 2/3 宽度，留给名字的只有 ~120vp（一行十几个字符）。改为 `Column` 两段式：**名字独占整行 + 最多 2 行**，按钮移到下一行右对齐 |
 *
 * ## 2026-10-01 第二轮（vivi 决策）
 * | 诉求 | 落法 |
 * |---|---|
 * | 传完文件后文件页大小不更新，刷新也无效，只能重启 App | **根因是 ForEach 的 keyGenerator 只用了 `f.path`**：传输中路径不变、只有 size 在长，key 恒定 → ArkUI 复用旧的 ListItem 与其 item 对象，`f.sizeText` 永久停在首次渲染时的「部分大小」。手动刷新只换了数组、key 没变故什么都不重建；重启 App 整树重建、首次生成 key，才拿到最新 stat 值。改为 `key = path\|size\|mtime`，三者任一变化即重建该行（`statSync` 本身是实时的，不走缓存，无需改数据层） |
 * | 多台设备在线时按「+」先选设备 | 「+」由 `bindMenu` 改为 `onClick` → `openPlus()`：已在胶囊选了设备 / 只有一台在线 → 直接进「相册或文件」；多台且选的是「所有设备」 → 先弹设备列表（`pickDialog`，两步：`pickStep` 1=选设备 2=选类型）。选完设备顺手把上方胶囊同步过去。⚠️ 菜单是静态的，做不到按设备数量分叉，所以必须换成自定义弹窗 |
 *
 * ## 2026-10-01 第八轮（vivi 真机诉求，5.0.17）
 * | 诉求 | 落法 |
 * |---|---|
 * | 消息页也要显示图片缩略图、可以点开 | `chatBubble` 里的「文件气泡」抽成 `chatFileBubble(m, mediaPath)`；收到的图片消息先渲染 128×128 缩略图（同样配 `sourceSize` 压解码尺寸），点一下进**同一个**全屏预览浮层。`openMediaPreview` 的入参从 `ReceivedFile` 改成 `(path, name)` —— 消息气泡手里只有一个路径，造不出「文件」页那个模型 |
 * | 图片能不能长按保存到相册 | 新增 `saveImageToAlbum()`：`photoAccessHelper.showAssetsCreationDialog`（**不需要任何权限声明**，弹系统确认框换一批带写权限的媒体 URI）+ 复用 `ExportService.copyTo` 写字节（「另存为」已在真机跑通的同一条路径）。入口两个：**长按图片气泡**、全屏预览顶栏「存相册」按钮 |
 * | ⚠️ 消息里只有文件名，路径从哪来 | `refreshReceived()` 时顺手建一张 **文件名 → 沙箱路径** 的表（`rebuildRecvIndex`）。⚠️ 必须额外登记一个「去掉重名后缀」的**别名键**：对端发来的图叫 `photo.jpg`，沙箱里已有同名时落盘会被 `FileKinds.dedupeName` 改成 `photo(1).jpg`，而气泡里存的永远是对端发来的**原名** —— 只登记真名的话，第二张同名的图就永远没有缩略图（`IMG_0001.jpg` 这种一发就是一批，太常见了） |
 *
 * ## 2026-10-01 第九轮（vivi 真机诉求，5.0.18）
 * | 诉求 | 落法 |
 * |---|---|
 * | 消息页点图片/视频别再跳文件页 | `msgImagePath` → `msgMediaPath`（图片 + **视频**都给路径）；气泡里图片走 `Image`、视频走**解出来的首帧** `PixelMap`；点击按类型分流 —— 图片进缩放预览、视频进 `Video` 播放器，**只有其它类型文件才 `openFileTab()`** |
 * | ⚠️ 视频怎么当缩略图 | `Image` 喂视频路径只会得到空白（图/视频解码器不是同一个）。用 `media.createAVImageGenerator()` + `fdSrc` + `fetchFrameByTime(0, AV_IMAGE_QUERY_CLOSEST_SYNC)` 解出首帧 `PixelMap`。⚠️ fd **必须活到 fetch 返回**；`release()` 要 await |
 * | 点开图片后长按就能存相册 | 图片预览的 `GestureGroup` 里加 `LongPressGesture`（与捏合/拖动/双击并列，Parallel 模式下不打架）。存相册本身扩到**视频**：`PhotoType.VIDEO`；⚠️ 视频几百 MB，`copyTo` 是同步逐块读写，先弹「正在保存」并**让出一帧**再拷，否则连提示都画不出来 |
 *
 * ## 2026-10-01 第十轮（5.0.31，vivi 真机诉求）
 * | 诉求 | 落法 |
 * |---|---|
 *   ③ `objectFit` 改 `Contain` —— 比例没量出来时宁可留边也不裁；④ `sourceSize` 按同一比例给 |
 * | 收到多个图片只显示第一张、点开左右滑动 | `TransferReport.fileNames` 带上整批名字 → `ChatMessage.files`（落盘也带）→ UI 逐个反查成路径 → 气泡出**第一张** + 「共 N 张」角标；点开进 `Swiper` 画廊，顶栏显示 `i/n`。⚠️ 非当前页的视频只出首帧（多个 Video 共用一个 controller 行为未定义） |
 * | ⚠️ 文件名里有换行怎么办 | `ChatMessage.files` 用 `\n` 分隔（`MiniJson.quote` 会转义成 `\n`），文件名本身不会出现换行 |
 *
 * ## 2026-10-01 第十一轮（5.0.35，vivi 真机诉求）
 * | 诉求 | 落法 |
 * |---|---|
 * | 消息页文件气泡做矮一点长一点，左缩略图右文件名 | `chatFileBubble` 由纵向 `Column` 改横排 `Row`：左 `mediaThumb(48)` + 右 `Column(状态+文件名+提示)`，`layoutWeight(1)` 撑满、`constraintSize maxWidth 78%→88%`、纵向内边距 8→6，整体更矮，像文件页那样但不那么长 |
 * | 多选后返回应取消多选、不是回桌面 | `onBackPress()` 此前只处理了 `fileSelectMode`，漏了 `chatSelectMode` → 补 `if (this.chatSelectMode) { this.exitChatSelect(); return true; }` |
 * | 删除提示应说明只删记录不删文件 | `batchDeleteChat` 确认文案 `删除后无法恢复` → `仅删除聊天记录，不会删除已接收的文件` |
 * | 复制文字消息别连用户名和时间 | `copyChat` 去掉 `[时间] 用户名: ` 前缀，只复制 `m.content`；多选态顶栏新增「复制」按钮（`copySelectedChat`，只复制选中正文）；新增通用 `copyText` |
 * | 关于页加 QQ 群与更新链接 | 新增 `ABOUT_UPDATE` 常量 + 关于弹窗「QQ 交流群 538809905」「更新地址 https://pan.quark.cn/s/04d4a2a1a13a」，各带「复制」按钮 |
 *
 * ## 2026-10-01 第十二轮（5.0.36，vivi 真机诉求）
 * | 诉求 | 落法 |
 * |---|---|
 * | 文件气泡长度别固定那么长，按文件名自适应 | 去掉 5.0.35 给右侧 `Column` 加的 `layoutWeight(1)`（它会把气泡撑到 `maxWidth` 上限）；现在 `Row` 按内容收缩 —— 短文件名就是短气泡，只有长名字才长到 `constraintSize maxWidth 88%` 上限后换行 / 省略。`alignItems(HorizontalAlign.Start)` 保留（左侧对齐，不随气泡变宽） |
 *
 * ## 2026-10-02 第十三轮（5.0.37，vivi 真机反馈：关于页只剩两个网址）
 * | 现象 | 根因 / 落法 |
 * |---|---|
 * | 「关于」弹窗背景变空白，只剩 QQ 群 + 更新地址两个网址 | 5.0.35 的补丁把这两个 `Column` **插到了主卡片 `Column({space:12})` 的收尾花括号之后**（在 `.width('86%')` 后面）。于是 `.padding(16) / .backgroundColor(C_CARD) / .borderRadius(14) / .shadow(...)` 这串**链式属性被挂到了最后一个子块（更新地址）上**，主卡片丢白底；而两个新块变成 `Stack` 的直接子节点，直接浮在半透明遮罩上 —— 于是只剩两个网址。修法：按行区间整体重写 `aboutDialog()`，两块挪回卡片 Column 内部，样式链挂回主 Column，并补 `constraintSize({maxHeight:'82%'})` 防止内容变高顶出屏幕。⚠️ **教训：往 `@Builder` 里追加子块，必须确认插入点在目标容器的花括号内；插错位置时 ArkTS 不报错，只是样式链被"顺延"到别的节点上** |
 *
 * ## 2026-10-02 第十四轮（5.0.38：收到图片/视频自动存相册）
 * | 诉求 | 落法 |
 * |---|---|
 * | 像捷传那样，收到的图片视频直接进相册 | 复用已有的 `showAssetsCreationDialog`（**免权限**），把它从「手动长按」接到**接收完成那一刻**：`onSnapshot` 聊天条数变化分支捕获 `oldCount` → `autoSaveNewMedia()` 挑出新增的「收到 + kind=file」记录里能解析出沙箱路径的图/视频 → `autoSaveAlbumBatch()` **整批一次弹框**逐个 `ExportService.copyTo`。⚠️ 用 `timeMs` 60 秒新鲜度挡掉「启动 restoreChat 灌历史」那次条数跳变，否则每次开 App 都会把历史图视频重弹一遍保存框 |
 * | 不想被自动打扰怎么办 | 设置区新增「收到图片/视频自动存相册」开关（默认开），持久化到 LanService 的 `PREF_CFG` |
 * | 为什么不用 WRITE_IMAGEVIDEO | 它是**受限权限**，普通应用申请不到。`showAssetsCreationDialog` 不需要任何权限声明，代价只是要弹一次系统确认框。前提：module.json5 的 abilities 必须配 label 和 icon，否则确认框显示不出应用名 |
 * | ⚠️ 已知边界 | 手机形态**没有**静默直写系统「下载」目录的通道 （`READ_WRITE_DOWNLOAD_DIRECTORY` 官方限定仅 2in1 / 平板；`Environment.getUserDownloadDir()` 依赖的 SysCap 也仅 2in1）。非图片视频的文件仍需走「另存为」Picker |
 *
 * ## 2026-10-02 第十五轮（5.0.39，vivi 真机反馈：发 1 张图不弹保存框）
 * | 现象 / 诉求 | 根因 / 落法 |
 * |---|---|
 * | **发 1 张图不弹保存框，发 2 张才弹**（重启也一样） | 路径靠 `recvIndex` 反查，而 `recvIndex` 只在 `refreshReceived()` 里重建，`refreshReceived()` 又只在「`transferText` 由非空变空」时触发 —— **小文件一次进度都没刷过**（transferText 全程空串）就永远不触发。1 张小图正好命中（索引是旧的 → 解析出 0 条路径 → 静默 return）；2 张耗时够长、刷过进度 → 索引是新的 → 才弹得出来。**修法不是调时序，而是不再依赖时序**：改成「待存队列 `autoSavePending` + 已处理集合 `autoSaveHandled`」，入队后无条件先 `refreshReceived()` 建索引，解析不出的留队里，并在 `refreshReceived()` 末尾再 `flushAutoSave()` 试一次 |
 * | 存进相册后把沙箱里的删掉（不留双份） | `autoSaveAlbumBatch` 里每个文件 `copyTo` 成功后 → **① 先 `cacheThumb()` 缓存 320px 小图 ② `setAlbumIndex()` 记相册 URI ③ 才 `ExportService.deleteFile()` 删沙箱副本**。顺序不能反（先出缩略图再删）。⚠️ 用户在确认框上点**取消**时不删 —— 那份是唯一的一份 |
 * | 点消息页的图/视频直接跳相册 | `onFileBubbleClick()` 分流：有相册 URI → `startAbility` 跳系统相册（`com.huawei.hmos.photos` 失败再试 `com.ohos.photos`）；没有 → 走原来的应用内预览；都不是 → 跳「文件」页 |
 * | 沙箱副本删了缩略图还会在吗 | 会。`cacheThumb()` 在删之前把小图写进 `filesDir/album_thumbs/<msgid>.jpg`，并记下真实宽高比；`bubbleMediaPath()` 优先用沙箱那份、没了就用缓存图。⚠️ 为什么不读相册 URI：那是个**写授权** URI，回头去读不一定读得到 |
 * | ★ 重启后缩略图全丢、点击又跳回文件 tab（5.0.43）| **索引持久化把 key 丢了**：落盘时只写了 value（`uri|thumb`）没写消息 id，读回来却用 `segs[0]`（相册 URI）当 key ⇒ 重启前 key 是 `m.id`（内存里，正常），重启后 key 变成 URI ⇒ `albumPart(m.id,n)` 永远查不到。修法：行格式改成 `id|uri|thumb`；旧的两段式行还原不出 id，直接丢弃。⚠️ 教训：**Map 持久化必须把 key 一起写进去**，而"读回来时用第 0 段当 key"这种写法编译期、运行期都不报错，只有重启才现形 |
 * | ★ 缩略图为什么从 cacheDir 挪到 filesDir | 鸿蒙**会在存储压力下清 `cacheDir`**（应用重启也可能丢）。缩略图是"沙箱副本删了之后唯一的一份"，不能放会被自动清的地方。顺带 `dropAlbumIndex()` 删记录时连缩略图文件一起删，否则会一直累积 |
 *
 * ## 2026-10-02 第十六轮（5.0.40，vivi 真机反馈：缩略图方向不对，纵向图显示成横向）
 * | 现象 / 诉求 | 根因 / 落法 |
 * |---|---|
 * | **纵向的照片缩略图是躺着的** | 三件事撞一起：① ArkUI `Image` **会自己读 EXIF 并旋转**（官方 FAQ 原文），所以直接显示沙箱原图那一路本来是对的；② 但 `cacheThumb()` 是「解码成 PixelMap → `packing()` 成 jpg」——**解码不应用 EXIF、pack 出的 jpg 也不带 orientation**，那张 320px 小图是**物理上躺着**的，又没有任何 EXIF 让 Image 转回来 → 躺着显示；③ `ensureMediaRatio()` 用 `getImageInfoSync()`，它返回的是**未旋转**的原始像素宽高 → 框的比例也反了（纵向图给了横向框）|
 * | 怎么修的 | **A** `cacheThumb()`：先读 `PropertyKey.ORIENTATION`，解码后 `pm.rotate(deg)` 把像素**物理转正**再 pack（缓存图本身变正，且不带 EXIF，Image 不会瞎转）；**B** `ensureMediaRatio()`：5/6/7/8（90°/270°）时**交换宽高**再算比例（因为 Image 会按 AUTO 把内容转过来，框要按"转完之后"给）；**C** 两处 `Image` 加 `.orientation(ImageRotateOrientation.AUTO)` |
 * | ⚠️ 为什么不给 Image 加 `.rotate({angle})` | `Image` 自己已经会按 EXIF 转，再转一次就是**转两遍**。AUTO 对没 EXIF 的缓存小图等价于 UP（不转），所以 A+B+C 这套组合不会双重旋转 |
 * | 镜像方向放弃了 | EXIF 的 2/4/5/7 带镜像。手机后摄几乎只出 1/3/6/8，为镜像引入翻转逻辑不值当 —— `exifDeg()` 只还原旋转那部分（5→270、7→90），且对任何非预期输入返回 0（不转），安全降级 |
 * | ⚠️ `ensureMediaRatio` 为什么改 async | 读 EXIF 的 `getImageProperty` **只有异步版**。这是它从同步改 async 的唯一原因。`ratioOf()` 里故意**不 await**（比例量到后 `thumbTick++` 会踢重绘，同步等反而卡渲染），用 `void` 明确丢弃 Promise |
 *
 * ## 2026-10-02 第十七轮（5.0.41，vivi 反馈：5.0.40 那版旋转**没修好**）
 * | 现象 / 诉求 | 根因 / 落法 |
 * |---|---|
 * | 5.0.40 改了但真机上还是躺着 | 两个各自独立、都足以让整件事**静默失效**的原因：**① `getImageProperty(ORIENTATION)` 返回值格式不统一** —— d.ts 只说「以字符串返回」，但华为官方 FAQ 示例代码比的是 `'Right-top'` 这类**语义串**（不是 `'6'`），5.0.40 的 `exifDeg()` 只认数字，命中语义串就返回 0（= 不转），表现跟 5.0.39 一模一样；**② `createPixelMap()` 没传 `editable: true`** —— SDK 原文「set to false ... operations such as writing pixels will fail」，`rotate()` 正属此类，失败又被 catch 掉只 Log.w，于是静默失效 |
 * | 三重保险（自动切换，绝不双重旋转） | **A** `exifDeg()` 同时认数字 `'6'`、兜底文本 `'Unknown Value 6'`、语义串 `'Right-top'`；**B** 解码时直接传 `rotate: deg` 一步到位 + 开 `editable: true`；**C** **运行时验证有没有真转** —— 90/270 时「横竖性」必须翻转，没翻就补一次 `pm.rotate(deg)` 再验一次，仍不生效才记进 `mediaRot` 交给 `Image.orientation()` 显示层补 |
 * | ⚠️ 显示层为什么不能一律显式给角度 | ArkUI `Image` **会自己读 EXIF 并旋转**（官方 FAQ 原文），沙箱原图再显式给就是转两遍。所以：沙箱原图（不在 `mediaRot` 表里）→ `AUTO`；缓存小图（自己 pack 的、不带 EXIF）→ 按 `mediaRot` 给，`0` 时强制 `UP`（防 pack 万一写回 EXIF 被二次旋转）|
 * | ⚠️ 补转时框的比例也要跟着换 | 物理没转成、靠显示层补时，`iw/ih` 还是躺着的比例 → 记比例必须按「转完之后」给（90/270 交换宽高），否则变成「竖图塞横框」|
 * | 留了排查入口 | `cacheThumb()` 里 `Log.i(TAG, "EXIF <名>: ori='<原值>' -> N度")` —— 再不对就抓这条日志，一眼看出设备上到底返回什么 |
 * | 5.0.41 也没修好（"弹窗时正常、保存完就变"）| 说明**旋转角度拿到的还是 0**。弹窗那一刻显示的是沙箱原图，Image 自己读 EXIF 转正，所以看着正常；保存后沙箱副本被删、改用我们 pack 的小图，那张图物理躺着又没 EXIF → 变横。⚠️ 反推：**"弹窗时正常"不能证明 EXIF 读到了** —— 那时即使 EXIF 没读到，Image 也能靠 AUTO 转对，只是框比例错（留白），用户不一定察觉 |
 * | ★ 不再靠系统 API 猜格式（5.0.42）| 三件事：① **自己读 JPEG 字节拿 EXIF**（`jpegExifDeg()`：SOI→APP1→"Exif\0\0"→TIFF IFD0→tag 0x0112，位置是标准规定的，与设备实现无关）；② pack 完**把小图再读回来验横竖性**（前面任一环出问题都会暴露）；③ 仍不对就**复制原文件兜底**（带 EXIF，Image 自己转正，方向必定正确，代价只是多占空间）。`mediaRot` 新增 `-1` = "这份缓存带 EXIF，显示层用 AUTO" |
 */
import { common, bundleManager, Want } from '@kit.AbilityKit';
import { pasteboard, BusinessError } from '@kit.BasicServicesKit';
import { picker, fileUri, fileIo } from '@kit.CoreFileKit';
import { window, KeyboardAvoidMode } from '@kit.ArkUI';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { media } from '@kit.MediaKit';
import { image } from '@kit.ImageKit';
import { Log } from '../core/Logger';
import { LanDevice } from '../core/DeviceCodec';
import { LanService, ServiceSnapshot, ServiceState, ChatMessage, ChatGroup, WebPushItem } from '../service/LanService';
import { OutgoingFile } from '../service/FileStorage';
import { WebClient } from '../service/WebClientStore';
import { ExportService, ReceivedFile, DeleteResult, SaveOutcome } from '../service/ExportService';
import { LanDiscovery, LocalNetInfo } from '../net/LanDiscovery';

const TAG: string = 'IndexPage';

/** 主题色，避免在多处重复字面量 */
const C_PRIMARY: string = '#0A59F7';
const C_TEXT: string = '#182431';
const C_SUB: string = '#8A8A8A';
const C_CARD: string = '#FFFFFF';
/** 页面内容区底色。⚠️ 底部安全区**不能**用它，否则会和白色的 tab 栏形成色差 */
const C_PAGE: string = '#F1F3F5';
/** ★ 5.1.41：传输完成态的浮层底色（绿）—— 与进行中的蓝区分 */
const C_DONE_OK: string = '#1E8E3E';

/** 上游开源仓库（梦醒了 大佬的 LANShare），「关于」里展示并可一键复制 */
const ABOUT_REPO: string = 'https://github.com/fgsq-team/LANShare';
const ABOUT_UPDATE: string = 'https://pan.quark.cn/s/04d4a2a1a13a';
/** 版本号兜底：运行时 bundleManager 取不到（或取到空串）时用这个，与 app.json5 同步 */
const ABOUT_FALLBACK_VER: string = '5.1.71';

/**
 * ★ 5.1.62（vivi 10-04「版本号 +1 并上传网盘」）：
 * **最后一个正式版**的版本号。
 *
 * ## 判据是「发布通道」，不是「新旧」
 * `5.1.62` 及更早 = 正式版；`5.1.62` 之后（如有） = 测试版。
 * 往后把某版定为正式版时，**只改这一个常量**即可，
 * 那一版立刻自动去掉「测试版」角标，界面代码一行都不用动。
 *
 * ⚠️ 比较方式必须是**逐段数字**比较，不能比字符串：
 *   `'5.1.9' > '5.1.12'` 在字符串比较下是**假的**（'9' > '1'），
 *   会把 5.1.9 误判成测试版。必须拆成数字数组逐段比。
 */
const LAST_STABLE_VER: string = '5.1.62';

/** 版本号 → 数字段数组。'5.1.13' → [5,1,13]；非数字段按 0 处理（宁当旧版，不误标测试） */
function verParts(ver: string): number[] {
  const out: number[] = [];
  const parts: string[] = ver.split('.');
  for (let i: number = 0; i < parts.length; i++) {
    const n: number = Number(parts[i]);
    out.push(isNaN(n) ? 0 : n);
  }
  return out;
}

/**
 * 逐段数字比较：a > b 返回 true，a <= b 返回 false。
 * 段数不同时按 0 补齐（'5.1' 与 '5.1.0' 视为相同）。
 */
function verGreater(a: string, b: string): boolean {
  const pa: number[] = verParts(a);
  const pb: number[] = verParts(b);
  const n: number = Math.max(pa.length, pb.length);
  for (let i: number = 0; i < n; i++) {
    const va: number = i < pa.length ? pa[i] : 0;
    const vb: number = i < pb.length ? pb[i] : 0;
    if (va > vb) {
      return true;
    }
    if (va < vb) {
      return false;
    }
  }
  return false;
}

/** 是否测试版：版本号 > LAST_STABLE_VER */
function isTestVersion(ver: string): boolean {
  if (ver.length === 0) {
    return false;
  }
  return verGreater(ver, LAST_STABLE_VER);
}

/** 毫秒 -> HH:MM，聊天气泡的时间戳 */
function fmtTime(ms: number): string {
  const d: Date = new Date(ms);
  const h: string = d.getHours().toString().padStart(2, '0');
  const m: string = d.getMinutes().toString().padStart(2, '0');
  return `${h}:${m}`;
}

@Entry
@Component
struct Index {
  @State snapshot: ServiceSnapshot = new ServiceSnapshot();
  @State busy: boolean = false;
  @State devices: LanDevice[] = [];
  /** 正在传输（发送或接收），用于禁用发送按钮 */
  @State transferring: boolean = false;
  /**
   * 传输进度文案 / 百分比 —— **从 `snapshot` 里拆出来的独立 @State**。
   *
   * ⚠️ 为什么必须拆（vivi 2026-10-01 真机：「接收文件过程中界面还是卡顿，
   *    切换一下 Tab 页能卡好几秒」）：
   *    进度是唯一**高频变化**的字段（接收侧约 10 次/秒）。
   *    以前它和其余字段共用 `this.snapshot`，于是每次进度刷新都要
   *    `this.snapshot = s` —— 而整页上几乎所有组件都在读 `this.snapshot`，
   *    一次赋值等于**整页重建**（三个 tab 的 Builder、设备列表、卡片全跑一遍）。
   *    10 次/秒的整页重建叠在接收线程上，Tab 切换那 300ms 动画就被拖成了好几秒。
   *    拆成独立 @State 后，进度只让那个浮层重新渲染，页面主体一动不动。
   */
  @State tText: string = '';
  @State tPercent: number = 0;
  /** ★ 5.1.41：实时速度（独立 @State ⇒ 10Hz 刷新只动这个浮层） */
  @State tSpeed: string = '';
  /** ★ 5.1.41：副信息（序号 / 已收-总量） */
  @State tSub: string = '';
  /**
   * ★ 5.1.50：浮层标题的**动词**（`接收`）。
   * 与文件名**分成两个组件**渲染 —— 5.1.49 拼成 `Text('接收 ' + 文件名)`
   * 一个字符串时，ArkUI **在空格处自动折行** ⇒「接收」独占第一行、
   * 文件名被挤到第二行且再次截断（vivi 截图）。
   */
  @State tVerb: string = '';
  /**
   * ★ 5.1.42：浮层是否处于「完成态」。
   *   ⚠️ 5.1.41 用 getter + 字符串前缀（`startsWith('\u2713')`）判定，实测失效
   *   不变色 / 地球不消失）—— 根因是「转义写法 + 依赖文案 + getter 读 @State
   *   在 @Builder 里追踪不可靠」三者叠加。
   *   ⇒ 改为**独立 @State**，由 `snapshot.transferDone` 显式驱动。
   */
  @State tDone: boolean = false;
  /** ★ 5.1.43：**预先算好的完成态底色**。
   *   ⚠️ 不要写成 `.backgroundColor(this.tDone ? A : B)` ——
   *   ArkUI 的**链式属性里读 @State 的三元表达式不可靠**（5.1.42 实测：
   *   `tDone` 已经变成 true，底色却仍是蓝色）。
   *   ⇒ 在 `onSnapshot` 里算好字符串，链式属性直接读这个 @State。 */
  @State tDoneBg: string = C_PRIMARY;
  /** ★ 5.1.44：完成 toast 只弹一次的去重标记（`transferDone` 会连续多次为 true） */
  // ★ 5.1.49：tDoneToastShown 已随「完成 Toast」一起删除。
  /** 自检进行中，防连点 */
  private diagBusy: boolean = false;
  /** 沙箱里已接收的文件（「另存为」的源） */
  @State receivedFiles: ReceivedFile[] = [];
  /** 当前页签：0=共享 1=消息 2=日志。⚠️ 不能叫 tabIndex —— 与 CustomComponent 基类的同名属性冲突 */
  @State curTab: number = 0;
  /** 沉浸式下需要自己让开的状态栏高度（vp） */
  @State topInset: number = 0;
  /** 底部导航条高度（vp） */
  @State bottomInset: number = 0;
  /** 软键盘当前高度（vp，未弹起为 0）：内容区按它让位，底栏不动（见 build()） */
  @State keyboardVp: number = 0;
  /** 主窗口引用：键盘高度监听要在 aboutToDisappear 里摘掉，否则回调悬空 */
  private mainWin: window.Window | null = null;
  /** 聊天记录镜像。⚠️ 必须**整体换引用**（slice），直接改原数组 ArkUI 检测不到 */
  @State chat: ChatMessage[] = [];
  /** 聊天输入框内容 */
  @State chatInput: string = '';
  /** 聊天目标设备的 IP；空串 = 所有在线设备（与网页端下拉框语义一致） */
  @State chatTargetIp: string = '';
  /** 设备名是否处于编辑态 */
  @State deviceNameEditing: boolean = false;
  /** 设备名编辑草稿 */
  @State deviceNameDraft: string = '';
  /**
   * 「发文件给谁」弹窗的步骤：0=不显示 1=选设备 2=选相册/文件。
   *
   * 拆两步是因为文件发送是**单连接模型**（一次只能发给一台设备），
   * 多台设备在线时必须先定设备，不能像文字消息那样群发。
   */
  @State pickStep: number = 0;
  /** 弹窗里选中的目标设备 IP */
  @State pickIp: string = '';
  /** 弹窗里选中的目标设备名（显示用） */
  @State pickName: string = '';
  /** 上一帧是否正在传输（用于检测"传输刚结束"触发文件页刷新） */
  private lastHadTransferText: boolean = false;
  /**
   * 上一次同步给 UI 的**设备列表签名**。
   * 用来判断「列表内容是否真的变了」，避免每次 emit 都换 @State 引用（见 syncDeviceList）。
   */
  private lastDeviceSig: string = '';
  /**
   * 上一次赋给 `this.snapshot` 时那批「稳定字段」的签名。
   * 签名没变就**不赋值** —— 见 onSnapshot 与 tText 的注释。
   */
  private lastSnapSig: string = '';

  // ---------------- 文件页多选 ----------------
  /**
   * 是否处于多选模式。**长按**文件列表里任意一行进入。
   *
   * 为什么要有它：长按进多选后可以一次另存 / 删除一批，比一个个点确认快得多。
   * ⚠️ 5.0.13 曾把行内「删除」按钮整个去掉，5.0.15 按 vivi 要求**加回来了** ——
   *    现在文件名独占一行、按钮都在第二行，三个按钮也不会再把它挤扁。
   *    两种删法并存：删一个点行内按钮，删一批长按多选。
   */
  @State fileSelectMode: boolean = false;
  /**
   * 多选态下已勾选的文件**路径**列表。
   * ⚠️ ArkUI 不观察数组元素变化，增删都必须**整体换引用**（见 toggleFileSelect）。
   */
  @State fileSelected: string[] = [];

  /** 消息页：多选态开关（长按气泡进入） */
  @State chatSelectMode: boolean = false;
  /**
   * 多选态下已勾选的消息 **id** 列表。
   * ⚠️ 同文件页：ArkUI 不观察数组元素变化，增删必须整体换引用（见 toggleChatSelect）。
   */
  @State chatSelected: string[] = [];

  /** 网页地址二维码弹窗是否可见 */
  /** 「关于」弹窗开关 */
  @State showAbout: boolean = false;
  /** 收到图片/视频后自动存进系统相册（持久化在 LanService，默认开） */
  @State autoAlbum: boolean = true;
  /**
   * 5.0.39：已存进相册的媒体 —— 消息 id -> `相册URI|缩略图缓存路径`。
   *
   * ⚠️ 为什么必须有这张表：存完相册后沙箱副本会**被删掉**（vivi 要求不留双份），
   *    `recvIndex` 立刻查不到它 —— 气泡缩略图和「点击打开」就都没了来源。
   *    所以删之前先缓存一张 320px 小图，URI 与缩略图路径一起记在这里。
   */
  @State albumIndex: Map<string, string> = new Map<string, string>();
  /**
   * ★ 5.1.5：非媒体文件「已存入本地/已删除」的**版本号** —— 纯计数器、无语义。
   *
   * ⚠️⚠️ **为什么需要它**（5.0.71 → 5.0.72 踩过同一个坑，我又踩了一次）：
   * `localMap` 是 `LanService` 的**普通 Map**，**不是 `@State`** ⇒ 依赖它的
   * `bubbleFooterText` **没有任何 @State 依赖** ⇒ 记账后那一格**不会重建**
   * ⇒ `Text(...)` 永远停留在 build 那一刻的值（＝「点击查看」）。
   * ★ 5.1.2 调的 `swapAlbumIndex()` 换的是 `albumIndex`，**与 `localMap` 毫无关系**，白调。
   *
   * ★ 与 5.0.63 对 `thumbTick` 的处理**完全一致**：`bubbleFooterText` 里
   *   **读它一次**（建立依赖 ⇒ 值更新后重建），但**不用它拼返回值**
   *   （拼进 key 就会因「改提示文案」而销毁重建那三态文本，得不偿失）。
   */
  @State localStateTick: number = 0;
  /** 运行时从 bundleManager 取到的版本号；取不到则用 ABOUT_FALLBACK_VER */
  @State aboutVer: string = '';
  @State showQr: boolean = false;

  // ---------------- 危险操作确认弹窗（自绘，替代系统 showDialog） ----------------
  /**
   * 确认弹窗是否可见。
   *
   * ⚠️ 为什么不用系统 `showDialog`（vivi 2026-10-01 真机：「删除弹窗的文件名字体过大、
   *    显示不全」）：系统对话框的 **title 字号是内部固定的，且不按内容折行**，
   *    把「删除『<长文件名>』？」整句塞进 title，长名必然被截。
   *    自绘之后文件名可以单列一块小字、按需折行 —— 想多长都能看全。
   */
  @State confirmVisible: boolean = false;
  /** 弹窗标题（**固定短文案**，如「删除文件」——长内容一律走 confirmDetail） */
  @State confirmTitle: string = '';
  /** 要重点展示全的内容（文件名 / 文件个数），小字、可折行 */
  @State confirmDetail: string = '';
  /** 副标题（风险提示之类的一句话） */
  @State confirmNote: string = '';
  /** 确认按钮文案 */
  @State confirmOkText: string = '删除';
  /** 等用户点击的那个 Promise 的 resolve —— null = 当前没有弹窗在等 */
  private confirmResolve: ((v: boolean) => void) | null = null;

  // ---------------- 图片预览 ----------------
  /** 正在全屏预览的图片路径；空串 = 没有预览 */
  @State imgPreview: string = '';
  /** 预览中的文件名（顶栏显示） */
  @State imgPreviewName: string = '';
  /** 当前缩放倍率 */
  @State imgScale: number = 1;
  /** 放大后用 translate 挪出来的位移（vp） */
  @State imgOffX: number = 0;
  @State imgOffY: number = 0;
  /** 一次捏合开始时的基准倍率（PinchGesture 给的是**相对**倍率） */
  private imgPinchBase: number = 1;
  /** 一次拖动开始时的基准位移 */
  private imgDragBaseX: number = 0;
  private imgDragBaseY: number = 0;

  // ---------------- 消息页图片缩略图 ----------------
  /**
   * 文件名 → 沙箱绝对路径。`refreshReceived()` 时重建（见 rebuildRecvIndex）。
   *
   * ⚠️ 为什么不把路径直接塞进 `ChatMessage`：那张表要落盘、要跨版本兼容，
   *    为一个纯「显示」用的字段去动持久化结构，收益不抵风险。
   *    用「消息里存的是对端发来的**原名**」这一点反查就够了。
   */
  private recvIndex: Map<string, string> = new Map<string, string>();
  /**
   * 长按之后的一小段时间里忽略 `onClick`。
   *
   * ArkUI 里长按命中后一般不会再补一个 click，但这个前提不值得赌：
   * 万一手势同时命中，用户「长按存相册」会连带弹出全屏预览。
   * 3 行的兜底，换掉一整类偶发怪象。
   */
  private clickMuteUntil: number = 0;

  // ---------------- 全屏预览：视频分支 ----------------
  /**
   * 全屏预览打开的是不是**视频**。
   * `imgPreview` 只存了一个路径 —— 图片走「缩放预览」、视频走「播放器」，
   * 靠这个标记在渲染时分流（同一个浮层，两套内容）。
   */
  @State imgPreviewVideo: boolean = false;
  /** 视频播放控制器（关闭预览时显式 stop，别让声音跟着页面跑） */
  private videoCtl: VideoController = new VideoController();

  // ---------------- 视频首帧缩略图 ----------------
  /**
   * 视频路径 → 首帧缩略图（PixelMap）。
   *
   * ⚠️ 视频**必须**先解码出首帧才能当缩略图：把视频路径直接喂给 `Image`
   *    只会得到一块空白（图/视频的解码器根本不是一个）。
   * ⚠️ 用普通字段而不是 `@State`：ArkUI 观察不到 `Map.set()` 这种「内容变化」，
   *    配下面的 `videoThumbTick` 计数器把重绘踢起来。
   */
  private videoThumbs: Map<string, image.PixelMap> = new Map<string, image.PixelMap>();
  /** 正在解码的路径，防同一条视频被重复提交 */
  private videoThumbBusy: Set<string> = new Set<string>();
  /** 每解出一张缩略图就 +1；@State 变化 → 重新 build → 缩略图出现 */
  @State videoThumbTick: number = 0;
  /**
   * 每条消息 id -> 其「收到的图片/视频」沙箱路径；空串 = 无缩略图。见 syncChatMediaPaths
   *
   * ★★ 5.0.69：**从 `@State` 降级为普通字段**（有日志证据，不是推断）。
   *
   * 5.0.68 诊断日志（存相册前后紧邻两行）：
   *   前  mediaPaths=n=8 空=0
   *   后  mediaPaths=n=8 **空=8**   ← 而 src 签名与 groups **完全没变**
   * 成因：存相册删掉沙箱副本 ⇒ recvPathFor 找不到 ⇒ 全部返回空串 ⇒ 换引用 ⇒ 闪。
   *
   * ⚠️ 降级的前提（本改动成立的全部依据）：
   *   **这张表在 UI 里一个读取点都没有**。穷举全文件引用后确认，只有
   *     - `syncChatMediaPaths` **自己**的签名比较（`.size` / `.get`）
   *     - 它自己的赋值
   *     - 5.0.68 的诊断日志
   *   真正给画廊用的是 `chatMediaGroups`（`mediaPathsOf`）；气泡缩略图从 5.0.61
   *   起走 `mediaThumbSrcOf()` 读相册索引，也不用它。
   *   ⇒ 它是一张**没有消费者的 @State**：内容变了没人看，
   *     但换引用照样触发**全组件重绘** —— 纯浪费，正是闪烁来源。
   *   ⇒ 去掉 `@State` 后 UI 读不到任何东西，行为零变化。
   *
   * ⚠️ 改前若新增了 UI 读取点，**必须把它改回 @State**，否则界面会停在旧值
   *   （普通字段的写不会触发重绘）—— 这是本改动唯一的维护成本。
   * ⚠️ 签名比较逻辑只依赖普通 Map 的读，不依赖可观察性 ⇒ 逻辑完全不变。
   */
  private chatMediaPaths: Map<string, string> = new Map<string, string>();
  /**
   * 每条消息 id -> 这一批媒体文件的沙箱路径（顺序 = 传输顺序）。
   *
   * ⚠️ 5.0.31：对端一次发来 N 张图时，聊天里只有**一条**「N 个文件」记录
   *    （`FileTransfer` 的终态上报就是一个合并文件名），老逻辑按名字反查不到任何媒体，
   *    于是只能显示一行干巴巴的文字。现在从 `ChatMessage.files` 拿到整批名字，
   *    逐个反查成路径 —— 气泡出第一张缩略图，点开进画廊左右滑。
   */
  /**
   * 每条消息 id -> 这一批媒体文件的沙箱路径（顺序 = 传输顺序）。
   *
   * ⚠️ 5.0.70：**从 `@State` 降级为普通字段**（依据见 `chatMediaPaths` 的注释
   *   —— 同一类问题：没有 UI 消费者的 `@State` 换引用照样触发全组件重绘）。
   *   唯一读取者是 `mediaPathsOf()`，而它 / `mediaCountOf` / `mediaPathAt`
   *   在整个 UI 里**零调用点**（全是历史遗留的死代码）。
   *   ⚠️ 若将来要在 UI 里用画廊的路径列表，**必须改回 @State**。
   */
  private chatMediaGroups: Map<string, string[]> = new Map<string, string[]>();
  /** 上一次算出来的分组签名，避免每次刷新都换引用（见 syncChatMediaPaths） */
  private chatMediaGroupsSig: string = '';
  /**
   * ★ 5.0.55：把消息按**批号**聚合成「气泡」后的列表 —— 同一次接收的多张图片/视频
   *   合成一个气泡（宫格多缩略图）。⚠️ 只是**显示**分组，组内每条仍各自独立记账
   *   （见 `ChatGroup` 与 `buildChatGroups` 的注释）。
   */
  @State chatGroups: ChatGroup[] = [];
  /** 分组签名 —— 没变就不换引用（避免每次刷新重建整个消息列表） */
  private chatGroupsSig: string = '';
  /**
   * 5.0.31：媒体路径 -> **原图宽高比**（w/h）。
   *
   * 缩略图以前是写死的 128×128 / 48×48 配 `objectFit(Cover)` —— 非正方形原图
   * 会被**裁成正方形**，再叠上 192×192 的解码请求（视频首帧）就是双重变形。
   * 现在按真实比例出框，解码尺寸也按同一个比例给，全程等比缩放。
   */
  private mediaRatio: Map<string, number> = new Map<string, number>();
  /**
   * 5.0.49：缩略图解码**单飞表**（key = id|源路径）。
   *
   * 同一个 id 的缩略图有两路调用者：渲染驱动的 `syncChatMediaPaths()`
   * 和存相册驱动的 `autoSaveAlbumBatch()`。它们可能几乎同时给同一个 id
   * 解码、并写同一个 `<id>.jpg` —— 两路原生解码同时压内存，
   * 叠加一张 12MP 的解码峰值，正是「概率性闪退」最合理的解释之一。
   * 同一个 key 只跑一次，两路拿同一个 Promise。
   */
  private thumbInFlight: Map<string, Promise<string>> = new Map<string, Promise<string>>();
  /** 正在量尺寸的路径（防重复提交） */
  private mediaRatioBusy: Set<string> = new Set<string>();
  /**
   * ★ 5.0.61：**已经提交过**缓存缩略图预生成的 key（`消息id#媒体序号`）。
   * 目的只有一个：让「渲染时按需补缩略图」不会每次重绘都重复提交。
   * ⚠️ 生成失败时会把记录撤掉（见 `prefetchThumbInner`），不会「一失手就永久没图」。
   */
  private thumbPrepare: Set<string> = new Set<string>();
  // ★★ 5.0.63：预生成结果的**批量提交缓冲**（消「闪一批」）
  private thumbBatch: Set<string> = new Set<string>();
  private thumbBatchDirty: boolean = false;
  private thumbBatchTimer: number = -1;
  /**
   * ★★ 5.1.66 C2b：待落盘的缩略图索引，格式 `${key}|${thumb}|${rot}`。
   * 只进数组，由 `flushThumbBatch()` 一次 `setThumbOnlyBatch` 落盘
   * ⇒ 400 张从 800 次全量写降到 1 次。
   */
  private thumbIndexBatch: string[] = [];

  /**
   * ★ 5.0.52：当前预览 / 画廊页对应的**相册索引 key**（`消息id#媒体序号`）。
   * 空串 = 不写相册索引（例如从「文件」页打开 —— 那里的图不属于任何消息）。
   * ⚠️ 原来存的是「消息 id」，而「文件」页打开画廊时**忘了复位**它 ⇒
   *   会把无关的图写到上一条消息的相册条目上（真机「点击打开的不是刚收到的那张」）。
   */
  @State imgPreviewKey: string = '';
  /** 每量出一个比例就 +1；@State 变化 -> 重新 build -> 缩略图换成等比框 */
  @State thumbTick: number = 0;
  /** 全屏预览的「一批」媒体路径（单张时长度为 1） */
  @State galleryPaths: string[] = [];
  /** 与 galleryPaths 一一对应的显示名（存相册 / 顶栏用） */
  @State galleryNames: string[] = [];
  /** 画廊当前页下标 */
  @State galleryIndex: number = 0;
  /**
   * ★ 5.0.52：与 `galleryPaths` 一一对应的**相册 key**（可能比它短 / 为空）。
   * 显式存下来而不是「用下标去推」—— 画廊里跳过没有源的项时下标会错位。
   */
  @State galleryKeys: string[] = [];
  private swiperCtl: SwiperController = new SwiperController();

  private service: LanService = LanService.get();
  private tabsController: TabsController = new TabsController();
  private chatScroller: Scroller = new Scroller();
  /** 上次渲染的聊天条数，用于判断"有新消息才滚到底 + 才刷新镜像" */
  private lastChatCount: number = 0;
  /** 5.0.39：待自动存相册的消息 id 队列（解析不出路径就留着，等下一次刷新再试） */
  private autoSavePending: string[] = [];
  /** 5.0.39：本次会话已弹过框的消息 id —— 存了、取消了、失败了都记，绝不再弹第二次 */
  private autoSaveHandled: Set<string> = new Set<string>();
  /** ★ 5.0.57：`chatAlbumCount()` 的缓存 —— 多选态底部条一次渲染会问它 4 遍 */
  private chatAlbumCountCache: number = -1;
  /** ★ 5.0.57：上面那个缓存对应的签名（选中项 / 消息数 / 相册索引任一变化都要重算） */
  private chatAlbumCountSig: string = '';
  /** 5.0.39：正在弹框 / 拷贝中，防重入 */
  private autoSaveBusy: boolean = false;
  /** 5.0.50：`autoSaveBusy` 置位的时刻 —— 用于「卡死看门狗」（见 flushAutoSave） */
  private autoSaveBusySince: number = 0;
  /**
   * ★ 5.0.54：确认框**返回数量 ≠ 提交数量**时翻成 true —— 之后一律「逐张提交」。
   *
   * ⚠️ 为什么必须这样：系统返回的 URI 数组只按「它接受的那几个」给出，
   *   既不告诉你跳过了哪些、也不保证位置能对上。真机 4 提交只回 2 个，
   *   旧代码按位置硬配 ⇒ 相册内容错位 + 沙箱原图被误删（见 autoSaveAlbumBatch 注释）。
   *   逐张提交时每次只交 1 个，返回只可能是 0 或 1 —— **没有歧义**。
   */
  private autoSaveSingleShot: boolean = false;
  /** ★ 5.0.54：连续「确认框无响应」次数；到 3 次停止自动重试，只提示用户手动存 */
  private autoSaveDialogFails: number = 0;
  /** ★ 5.0.54：自驱重试的定时器句柄（-1 = 没有） */
  private autoSaveTimer: number = -1;

  // ---------------- 5.0.51：自动存相册「等落盘」重试的硬边界 ----------------
  /**
   * ★ 每个 id 已经「空手而归」试了几次 / 第一次进队列的时刻。
   *
   *   5.0.47 起 `flushAutoSave` 把解析不出路径的项**留在队列里**等下一次刷新 ——
   *   方向是对的（文件落盘确实要时间），但**没有上限**：
   *   一旦某个 id 的路径**永远**解析不出来（落盘名被加了 `(1)` 去重后缀、
   *   或消息 content 是「3 个文件」而 files 为空），这个队列就**永远是热的**：
   *   每次刷新都打一条日志 -> 每次都 emit -> 配合 emit 重入就是一场风暴。
   *
   *   给重试加**硬边界**：6 次 或 60 秒仍解析不出 -> 结案放弃、从队列移除。
   */
  private autoSaveTry: Map<string, number> = new Map<string, number>();
  private autoSaveFirstMs: Map<string, number> = new Map<string, number>();
  /** 上一条「暂未解析出沙箱路径」日志的原文与时刻 —— 同样内容 5 秒内只打一次 */
  private autoSaveWaitLog: string = '';
  private autoSaveWaitLogAt: number = 0;

  private onSnapshot: (s: ServiceSnapshot) => void = (s: ServiceSnapshot) => {
    // ---- 1. 传输进度：只更新独立 @State，**不赋值 this.snapshot** ----
    // 这两行是「接收时不卡顿」的关键：10Hz 的进度刷新从此只重渲染那一个浮层。
    // ★ 5.0.65：进度浮层的三个 @State 也走闸门 —— 传输**结束**时 tText 由非空
    //   变空、tPercent 归 0、transferring 变 false，三个一起变；加上下面
    //   「条数变了」那批，一次接收完成原本要触发 6~7 次重渲染。
    //   ⚠️ 进度在传输期间是 10Hz 刷的，那属于**正常**刷新（浮层本就该动），
    //   合并它们不影响观感；这里只求「一次结束动作只重渲染一次」。
    //   ⚠️ `hadTransfer` 必须在开闸**之前**算出来：它只读 s，不依赖任何 @State。
    const hadTransfer: boolean = s.transferText.length > 0;
    this.beginStateSwap();
    if (s.transferText !== this.tText) {
      this.tText = s.transferText;
    }
    if (s.transferPercent !== this.tPercent) {
      this.tPercent = s.transferPercent;
    }
    if (s.transferSpeed !== this.tSpeed) {
      this.tSpeed = s.transferSpeed;
    }
    if (s.transferSub !== this.tSub) {
      this.tSub = s.transferSub;
    }
    // ★ 5.1.50：动词同步（与文件名分两个组件，见 tVerb 注释）
    if (s.verb !== this.tVerb) {
      this.tVerb = s.verb;
    }
    if (s.transferDone !== this.tDone) {
      this.tDone = s.transferDone;
    }
    // ★ 5.1.43：颜色在这里算好（见 tDoneBg 注释：链式属性里的三元表达式不可靠）
    this.tDoneBg = s.transferDone ? C_DONE_OK : C_PRIMARY;
    // ★★ 5.1.44：完成提示的**可靠通道** —— 浮层的颜色/图标连续两版不生效，
    //   而 toast 走系统组件，与 ArkUI 的 @State → 视图追踪**完全无关**。
    //   这条同时满足 vivi 的原始需求「完成后加完成提示、保留 3 秒」，
    //   并且**自带自证能力**：toast 出现 = 完成逻辑确实跑了。
    // ★ 5.1.49：**去掉「传输完成」的系统 Toast**（vivi 要求）。
    //   浮层现在能可靠显示完成态（绿底 + 静态 ✓ + 「接收完成 · 大小 · 速度」），
    //   Toast 属于重复信息，且会挡住底部设备列表 3 秒。
    //   ⚠️ 5.1.44 加它时是当作「状态是否到位的自证旁路」；
    //     5.1.48 证明真凶是代码 bug（状态被无条件清空），旁路已无价值。
    this.transferring = this.service.isTransferring;
    this.endStateSwap();
    // ---- 2. 设备列表：syncDeviceList 内部自带签名节流，成本极低 ----
    this.syncDeviceList();
    // 一次传输刚结束（transferText 由非空变空）—— 收发两侧都覆盖：
    // 发送侧在 sendUris 里置过 transferring，接收侧则没有，
    // 所以这里改用 transferText 的跳变判断，才能把「别人发给我、我刚收完」也刷出来。
    // 不在每帧刷新是因为这里要扫目录，传输期间会被调很多次。
    // ⚠️ 5.0.51：**先把标志落到新值，再去刷新**。反过来写（原来那样）会造成
    //   同步重入：refreshReceived 里打一条 UI 日志 -> logAuto 立刻 emit ->
    //   重入到本方法 -> 这时标志还是旧值「刚才有传输」-> 又走一次 refreshReceived
    //   -> ... 无限递归（真机表现：同一秒 200 条同句日志，之后传输再也起不来）。
    const wasTransfer: boolean = this.lastHadTransferText;
    this.lastHadTransferText = hadTransfer;
    // 聊天：只在条数真的变了时才 slice 一份新数组给 @State
    // （slice 换引用是让列表刷新的关键，见 chat 字段的注释）
    const chatCountChanged: boolean = s.chat.length !== this.lastChatCount;
    const oldCount: number = this.lastChatCount;
    // ★★ 5.0.65：闸门**上提到这里** —— 接收完成的这一次 onSnapshot 里，
    //   ①②（tText/tPercent 传输由非空变空）+ ③④⑤（chat / chatMediaPaths /
    //   chatGroups）**连续换了 5 个 @State**；5.0.64 的闸门只包住了
    //   `refreshReceived` 内部那部分，剩下这些仍在闸门之外 ⇒ 仍会重渲染多次。
    //   现在整段共用一次 `flushStateSwap()` ⇒ 一次重渲染。
    //   ⚠️ `lastChatCount` / `lastHadTransferText` 仍**立即**落值（它们是幂等标记，
    //   不是给 UI 看的；延迟落值会让下一次 emit 重复进这个分支）。
    let needScroll: boolean = false;
    this.beginStateSwap();
    try {
      if (wasTransfer && !hadTransfer) {
        this.refreshReceivedInner();
      }
      if (chatCountChanged) {
        this.lastChatCount = s.chat.length;
        this.swapChat(s.chat.slice());
        // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）
        this.syncChatMediaPaths();
        // ★ 5.0.55：条数变了也要重算「气泡分组」（同批的多条媒体要合成一个气泡）
        this.buildChatGroups();
        // 5.0.38：刚收到的图片/视频 -> 自动存相册（见 autoSaveNewMedia 注释）
        this.autoSaveNewMedia(oldCount);
        needScroll = this.curTab === 1;
      }
    } finally {
      this.endStateSwap();
    }
    // ⚠️ scrollEdge 必须在闸门**外**、也就是布局已更新之后再调 ——
    //   放在闸门内会滚到「旧布局」的位置（列表还没按新数据重排）。
    if (needScroll) {
      try {
        this.chatScroller.scrollEdge(Edge.Bottom);
      } catch (e) {
        // 列表还没挂载，忽略
      }
    }
    // ---- 3. 其余字段：**签名没变就不赋值** ----
    // `emit()` 是「就地改同一个 snapshot 对象」，赋值同一个引用也会让 ArkUI
    // 把整棵树重建一次。所以这里先把「界面上真的会显示」的那些字段拼成签名，
    // 只有它们变了才赋值 —— 进度类变化已在第 1 步被摘走，不会走到这里。
    // ⚠️ 新增「会被 UI 渲染」的快照字段时，必须同步加进这个签名，
    //    否则界面会停在旧值（这是这种做法唯一的维护成本）。
    // ⚠️ 刻意**不**把 connections / webRequests / onlineDevices / knownDevices 放进来：
    //    前两个在接收期间会高频变化（16 条分片连接反复建立/关闭！），
    //    而界面上根本没有渲染它们（连接数、请求数都不上屏）——
    //    放进来等于让每次「有分片连上 / 断开」都触发一次**整页重建**。
    //    设备数变化由 syncDeviceList 的独立签名负责，比这里精确得多。
    const sig: string =
      `${s.state}|${s.localIp}|${s.webUrl}|${s.deviceName}` +
      `|${s.webOpen ? 1 : 0}|${s.pendingWebClients.length}|${s.wsClients}` +
      `|${s.sessionActive ? 1 : 0}|${s.message}|${s.listenDetail}|${s.saveLocation}`;
    if (sig === this.lastSnapSig) {
      return;
    }
    this.lastSnapSig = sig;
    this.snapshot = s;
  };

  aboutToAppear(): void {
    // ⚠️ 键盘避让模式（SDK UIContext.d.ts:4826 定义了三种）：
    //     OFFSET=0 整页上移（默认）→ 顶栏和进度浮层被顶出屏幕；
    //     RESIZE=1 压缩页面高度 → 顶栏固定，但**底栏被挤到键盘上方**；
    //     NONE  =2 完全不避让  → 页面高度不变：顶栏固定、**底栏留在屏幕底部**。
    //   vivi 要的是「顶栏不动 + 底栏也不跟着上移」⇒ 只能取 NONE，
    //   再自己给 TabContent 加键盘高度的 bottom padding 让输入框上移
    //   （tab 栏是 Tabs 的 bar，不吃 TabContent 的 padding，所以原地不动）。
    try {
      this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.NONE);
    } catch (e) {
      Log.w(TAG, `设置键盘避让模式失败: ${JSON.stringify(e)}`);
    }
    this.loadVersion();
    this.autoAlbum = this.service.autoAlbumOn;
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.service.subscribe(this.onSnapshot);
    // 5.0.39：相册索引要先于气泡渲染就绪 —— 沙箱副本上一轮可能就删了，缩略图全靠它
    this.service.loadAlbumIndex(ctx).then(() => {
      this.albumIndex = this.service.albumSnapshot();
      // ★★ 5.1.70 C：**后台静默**探测「相册里的图还在不在」。
      //   原来挂在「切到消息 tab」（index === 1）⇒ 426 张时**切页必卡**
      //   （`probeAlbumOnEnterChat` 对 414 条 uri 逐个 statSync/openSync/readSync；
      //    5.1.66 C1 的「每 20 张让一帧」只缓解帧率，切页那一帧的等待仍在）。
      //   ⇒ 挂到页面出现时跑，与 tab 切换**完全解耦**。
      //   ⚠️ 必须在 `loadAlbumIndex` 完成**之后**：索引没加载就探会全部判「已删」
      //   （历史坑，见 probeAlbumOnEnterChat 的注释）。
      this.scheduleBackgroundAlbumProbe();
    });
    this.applyWindowInset(ctx);
    // 进页面时先把 IP 探出来，方便用户还没开共享就看到地址
    this.refreshLocalHint(ctx);
    this.refreshReceived();
    // 恢复本地聊天记录（服务层幂等，只会真正加载一次）。
    // 放在这里而不是等「开始共享」—— 用户不开共享也该能看到历史消息。
    this.service.restoreChat(ctx).catch((e: Error) => {
      Log.w(TAG, `恢复聊天记录异常: ${e.message}`);
    });
    // 打开即共享，界面上不再有「开始共享」按钮
    this.autoStart(ctx);
  }

  aboutToDisappear(): void {
    this.service.unsubscribe(this.onSnapshot);
    try {
      this.mainWin?.off('keyboardHeightChange');
    } catch (e) {
      // 窗口已销毁，忽略
    }
  }

  /**
   * 系统返回（返回键 / 侧滑手势）拦截。
   *
   * ⚠️ 不实现这个回调时，返回的默认行为是**退出应用** ——
   *    多选到一半误触返回就直接回桌面，勾选全丢（vivi 2026-10-01 真机反馈）。
   *    返回的语义应当是「先退掉最上层的临时状态」：
   *      确认弹窗 → 当「取消」结掉它；图片预览 → 关预览；多选态 → 取消多选；
   *      二维码弹窗 → 关弹窗；发文件弹窗 → 关弹窗；
   *      都不是 → 交还给系统（正常退出）。
   *
   * @returns true = 已经处理（不再往下传）；false = 交给系统默认行为
   */
  onBackPress(): boolean {
    // 确认弹窗在最上层 —— 必须**先把它结掉**：那个 await 还挂着，
    // 不结掉的话用户下一次点删除时，两次等待会串在同一个 Promise 上。
    if (this.confirmVisible) {
      this.settleConfirm(false);
      return true;
    }
    if (this.imgPreview.length > 0) {
      this.closeMediaPreview();
      return true;
    }
    if (this.fileSelectMode) {
      this.exitFileSelect();
      return true;
    }
    if (this.chatSelectMode) {
      this.exitChatSelect();
      return true;
    }
    if (this.showQr) {
      this.showQr = false;
      return true;
    }
    if (this.pickStep > 0) {
      this.pickStep = 0;
      return true;
    }
    // ★ 5.1.4（vivi 21:28）：「关于」弹窗也必须接住返回键。
    //   此前 `onBackPress` 处理了 6 个弹窗却**漏了它**（实测命中 0 次）
    //   ⇒ 落到末尾 `return false` 交还系统 ⇒ **按返回直接退出应用到桌面**。
    //   ⚠️ 自绘弹窗（`showXxx`）必须逐个登记到这里 —— 这是本项目的固有陷阱：
    //   **漏一个 = 用户按返回就退出应用**，而界面上弹窗还开着。
    if (this.showAbout) {
      this.showAbout = false;
      return true;
    }
    return false;
  }

  /**
   * 取系统的窗口避让区，把状态栏/导航条的高度换算成 vp。
   *
   * 为什么必须这么做：EntryAbility 里开了 `setWindowLayoutFullScreen(true)`，
   * 内容会铺到状态栏底下 —— 这是沉浸式想要的效果，但**组件不会自动让位**，
   * 所以标题栏必须自己按 topRect 下移。写死一个 38vp 在换机型/横屏时就会错。
   */
  private async applyWindowInset(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const win: window.Window = await window.getLastWindow(ctx);
      this.mainWin = win;
      // 键盘高度变化时联动：弹起 → 收掉底部安全条（它悬在键盘上方会留一条空档）
      win.on('keyboardHeightChange', (h: number) => {
        this.onKeyboardHeight(h);
      });
      const sys: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
      const nav: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR);
      this.topInset = this.getUIContext().px2vp(sys.topRect.height);
      this.bottomInset = this.getUIContext().px2vp(nav.bottomRect.height);
      Log.i(TAG, `窗口避让: 状态栏 ${this.topInset}vp / 导航条 ${this.bottomInset}vp`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `取窗口避让区失败: ${err.code} ${err.message}`);
    }
  }

  /**
   * 软键盘高度变化回调（px）。
   *
   * ⚠️ 避让模式是 NONE，系统不会替我们做任何让位 —— 这个高度就是
   *    内容区底部 padding 的唯一来源（`TabContent.padding(bottom)`）。
   *    换算成 vp 再存（px2vp 走 UIContext，全局 px2vp() 已废弃）。
   */
  private onKeyboardHeight(px: number): void {
    // KEYBOARD_PAD_EFFECTIVE_5030
    // 5.0.30：keyboardHeightChange 给的是「屏幕底→键盘顶」，但 padding 垫在 TabContent 上，
    // TabContent 底边本就在 tab 栏(50vp, 见 .barHeight(50)) + 底部安全条(bottomInset) 之上，
    // 不扣这两段输入框会被多抬高一条空白（vivi 2026-10-01 截图实测）。
    const totalVp: number = px > 0 ? this.getUIContext().px2vp(px) : 0;
    const reserved: number = 50 + this.bottomInset;
    const vp: number = px > 0 ? Math.max(0, totalVp - reserved) : 0;
    const wasUp: boolean = this.keyboardVp > 0;
    this.keyboardVp = vp;
    Log.i(TAG, `键盘: px=${px} total=${totalVp}vp 扣除=${reserved}vp 实垫=${vp}vp`);
    // 键盘刚弹起、且正停在消息页：把聊天列表拉到底（跟主流聊天软件一致）。
    // 延后一帧执行：此刻 padding 还没生效，立刻滚会停在旧的可视区底部。
    if (vp > 0 && !wasUp && this.curTab === 1) {
      setTimeout(() => {
        try {
          this.chatScroller.scrollEdge(Edge.Bottom);
        } catch (e) {
          // 列表还没挂载，忽略
        }
      }, 120);
    }
  }

  /** 未启动服务时也展示一下本机地址，降低"不知道填什么"的困惑 */
  private async refreshLocalHint(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const net: LocalNetInfo = await LanDiscovery.resolveLocalNet();
      if (net.valid && this.snapshot.localIp.length === 0) {
        this.snapshot.message = `检测到局域网地址 ${net.ip}`;
      }
    } catch (e) {
      Log.w(TAG, '预探测网络失败');
    }
  }

  /**
   * 进入页面即开启共享。
   * 幂等：服务已在跑（例如刚从后台切回来，EntryAbility 已恢复）就直接返回。
   */
  private async autoStart(ctx: common.UIAbilityContext): Promise<void> {
    if (this.busy || this.service.isRunning) {
      return;
    }
    this.busy = true;
    try {
      const ok: boolean = await this.service.startSharing(ctx);
      if (!ok) {
        this.toast(`自动开启失败：${this.snapshot.message}`);
      } else if (this.service.prevCrashed) {
        // ★★ 5.1.12（vivi 22:0x「把检测到闪退的提示删除了」）：**不弹 toast**。
        //
        // 【为什么删】`run.lock` / `crash.flag` 在 `filesDir` 里，**升级 HAP 时
        //   可能被系统清理/重建** ⇒ 用户**每次升级后首次启动**都会看到这条提示。
        //   而他什么都没做 ⇒ 纯噪声，且会让人以为「这软件一更新就崩」。
        //
        // 【⚠️ 只删 UI，检测与取证【全部保留】】
        //   `crashTail`（崩溃前 150 行挂到日志列表最前面）+ `ui_log.txt.1` 存档
        //   是**真机唯一的排障通路**（用户没 hdc，5.0.49 的原意）。
        //   删掉它 = 下次真闪退**完全无法取证**，只能盲修。
        //   ⇒ 这里改成**只打一行日志**：用户界面干净，我需要时仍能从日志看到。
        this.service.logAuto('检测到上次异常退出（闪退）：崩溃现场已挂在日志最前面');
      }
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `自动开启共享失败: ${err.message}`);
      this.toast('自动开启失败，请查看日志页');
    } finally {
      this.busy = false;
    }
  }

  /** 共享没起来时的兜底重试入口（正常路径下用户看不到它） */
  private async retryStart(): Promise<void> {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    await this.autoStart(ctx);
  }

  /**
   * ★ 5.1.44：加 `duration` 参数（默认 2000 保持既有调用行为不变）。
   *   完成提示要 3 秒（vivi 需求），而浮层那条链路连续两版不可靠
   *   （`tDoneBg` 不重绘、文件名被 ellipsis 吃光）⇒ 需要这条独立通道。
   */
  private toast(msg: string, duration: number = 2000): void {
    try {
      // 旧写法 promptAction.showToast 已标记 deprecated（工程器会告警），
      // 现在统一走 UIContext 拿到的 PromptAction 实例。
      this.getUIContext().getPromptAction().showToast({ message: msg, duration: duration });
    } catch (e) {
      Log.i(TAG, msg);
    }
  }

  /** 发送前置检查：正在传 / 服务没起来，都不该弹选择器 */
  private canSend(): boolean {
    if (this.transferring) {
      this.toast('已有传输在进行中');
      return false;
    }
    if (!this.service.isRunning) {
      this.toast('共享尚未就绪，请稍候');
      return false;
    }
    return true;
  }

  /**
   * 从**文件管理器**选文件（只选不发）。
   *
   * 走系统文件选择器（DocumentViewPicker）而不是直接扫盘：
   * 鸿蒙不给应用全盘读权限，用户选中的文件才授权给应用读 ——
   * 也正因如此，这一步**不需要申请任何存储权限**。
   *
   * 抽成独立方法是因为「发给设备」和「发给网页端」两个入口都要用它。
   */
  private async chooseDocuments(): Promise<string[]> {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    try {
      const opt: picker.DocumentSelectOptions = new picker.DocumentSelectOptions();
      // 单次最多 20 个：再多就该走文件夹传输了，而文件夹需要额外的 children 协议
      opt.maxSelectNumber = 20;
      const docPicker: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
      return await docPicker.select(opt);
    } catch (e) {
      const err: Error = e as Error;
      // 用户取消选择也会走到这里（错误码 13900020 等），不当成故障
      Log.i(TAG, `选择文件结束: ${err.message}`);
      return [];
    }
  }

  /**
   * 从**相册**选图片/视频（只选不发）。
   *
   * 用系统相册选择器（PhotoViewPicker）而不是自己扫媒体库，原因有两条：
   *   1. PhotoViewPicker 返回的 URI **带永久授权**，可以直接 `fileIo.openSync` 读，
   *      因此**不用申请** `ohos.permission.READ_IMAGEVIDEO`；
   *   2. 既然能直接 open，就**不需要先复制到沙箱** —— 拿到的 uri 直接喂给
   *      `OutgoingFile.fromUri`，后面整条发送链路与文件管理器选的完全一致。
   */
  private async chooseAlbum(): Promise<string[]> {
    try {
      const opt: photoAccessHelper.PhotoSelectOptions = new photoAccessHelper.PhotoSelectOptions();
      // 图片 + 视频都放开；只想发图的话换成 IMAGE_TYPE
      opt.MIMEType = photoAccessHelper.PhotoViewMIMETypes.IMAGE_VIDEO_TYPE;
      opt.maxSelectNumber = 20;
      const albumPicker: photoAccessHelper.PhotoViewPicker = new photoAccessHelper.PhotoViewPicker();
      const res: photoAccessHelper.PhotoSelectResult = await albumPicker.select(opt);
      return res.photoUris;
    } catch (e) {
      const err: Error = e as Error;
      // 用户取消同样走这里，不当成故障
      Log.i(TAG, `选择相册结束: ${err.message}`);
      return [];
    }
  }

  private async pickAndSend(d: LanDevice): Promise<void> {
    if (!this.canSend()) {
      return;
    }
    await this.sendUris(d, await this.chooseDocuments());
  }

  private async pickAlbumAndSend(d: LanDevice): Promise<void> {
    if (!this.canSend()) {
      return;
    }
    await this.sendUris(d, await this.chooseAlbum());
  }

  /**
   * 组装 OutgoingFile 并发送。相册与文件管理器两个入口共用这一段 ——
   * 差别只在选择器，发送链路完全一样，没必要写两遍。
   */
  private async sendUris(d: LanDevice, uris: string[]): Promise<void> {
    if (uris.length === 0) {
      return;
    }
    const files: OutgoingFile[] = [];
    let skipped: number = 0;
    for (let i = 0; i < uris.length; i++) {
      const f: OutgoingFile = OutgoingFile.fromUri(uris[i]);
      if (!f.sizeKnown) {
        // 读不到大小 = 打不开这个文件。相册里偶尔会碰到（云端图未下载、授权没生效），
        // 单张读不到不该拖垮整批 —— 记下来跳过，能发的照发。
        skipped++;
        Log.w(TAG, `无法读取已跳过: ${uris[i]}`);
        continue;
      }
      files.push(f);
    }
    if (files.length === 0) {
      this.toast(`所选 ${skipped} 个文件都读不到（相册里的云端图需先下载到本地）`);
      return;
    }
    if (skipped > 0) {
      this.toast(`${skipped} 个文件读不到，已跳过`);
    }
    this.transferring = true;
    this.toast(`开始发送 ${files.length} 个文件到 ${d.devName}`);
    try {
      const ok: boolean = await this.service.sendFiles(d, files);
      this.toast(ok ? '发送完成' : `发送失败：${this.snapshot.message}`);
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `发送异常: ${err.message}`);
      this.toast(`发送异常：${err.message}`);
    } finally {
      this.transferring = false;
    }
  }

  // ------------------------------------------------------------------
  // 主动推送给网页端（本机 -> 浏览器）
  // ------------------------------------------------------------------

  /**
   * 选文件（文件管理器 / 相册）并推给网页端。
   *
   * 官方网页端只会单向上传，手机上选个文件想发给浏览器是没有入口的。
   * HTTP 推不了字节，所以做法是：先把文件搬进沙箱，再用 WebSocket 通知
   * 浏览器「来取」，浏览器自己走 /compressFiles 两步把 zip 下走。
   */
  private async pickFileForWeb(): Promise<void> {
    await this.pushUrisToWeb(await this.chooseDocuments());
  }

  private async pickAlbumForWeb(): Promise<void> {
    await this.pushUrisToWeb(await this.chooseAlbum());
  }

  private async pushUrisToWeb(uris: string[]): Promise<void> {
    if (uris.length === 0) {
      return;
    }
    if (this.service.webClientCount === 0) {
      this.toast('没有网页端连接：请先用浏览器打开网页端页面并保持它开着');
      return;
    }
    const files: OutgoingFile[] = [];
    for (let i = 0; i < uris.length; i++) {
      const f: OutgoingFile = OutgoingFile.fromUri(uris[i]);
      if (f.sizeKnown) {
        files.push(f);
      }
    }
    if (files.length === 0) {
      this.toast('所选文件都读不到（相册里的云端图需先下载到本地）');
      return;
    }
    // ★★ 5.1.60 零落盘：单文件直接推授权 URI，**不再复制进沙箱**。
    //   原实现 `stageForWeb()` 会把整份文件复制到 `saveRoot/网页待下载/`
    //   且从不清理 ⇒ 沙箱永久留一份（vivi 明确不接受）。
    //   ⚠️ 多个文件仍必须复制：zip 打包（`zlib.compressFiles`）只认真实路径。
    if (files.length === 1) {
      const one: WebPushItem = new WebPushItem(files[0].uri, files[0].name);
      const n1: number = this.service.pushUrisToWeb([one]);
      if (n1 > 0) {
        this.toast('已通知网页端下载（不落盘）');
      } else if (n1 === 0) {
        this.toast('没有网页端连接：请先用浏览器打开网页端页面');
      } else {
        this.toast('推送失败，请重试');
      }
      return;
    }
    this.toast('正在准备文件…');
    // ★ 5.1.61：多文件仍需复制（zip 只认真实路径），但**打包完会自动删**。
    //   这里先清一次陈旧副本 —— 覆盖「上次进程被杀、没走到删除」的残留。
    this.service.pruneWebStage();
    const paths: string[] = await this.service.stageForWeb(files);
    if (paths.length === 0) {
      this.toast('文件准备失败，请查看日志');
      return;
    }
    const n: number = this.service.pushFilesToWeb(paths);
    this.toast(n > 0 ? `已通知网页端下载 ${paths.length} 个文件` : '通知发送失败，请重试');
  }

  /** 文件页单条：已在沙箱里，不用复制，直接通知网页端来取 */
  private pushOneToWeb(f: ReceivedFile): void {
    const n: number = this.service.pushFilesToWeb([f.path]);
    if (n < 0) {
      this.toast('这个文件不在沙箱内，无法推送（可先「另存为」再试）');
      return;
    }
    if (n === 0) {
      this.toast('没有网页端连接：请先用浏览器打开网页端页面');
      return;
    }
    this.toast(`已通知网页端下载「${f.name}」`);
  }

  /**
   * 手动跑一次网络自检。
   *
   * 为什么要有这个：真机排障最缺的就是「服务到底有没有真的在服务人」这个事实。
   * 自检做的是**真 HTTP 往返**（连上去、发 GET、要收到响应字节），
   * 而不是只看端口开没开 —— 端口开着但应用层是死的，是这两天真机上踩到的坑。
   */
  private async runDiag(): Promise<void> {
    if (this.diagBusy) {
      return;
    }
    this.diagBusy = true;
    this.toast('正在自检…');
    try {
      const msg: string = await this.service.runDiagnostics();
      this.toast(msg);
    } catch (e) {
      const err: Error = e as Error;
      Log.e(TAG, `自检异常: ${err.message}`);
      this.toast(`自检异常：${err.message}`);
    } finally {
      this.diagBusy = false;
    }
  }

  // ---------------- 网页访问授权 ----------------
  // 原 Android 版对网页访问实行「新客户端需手机端确认」：
  // 浏览器会停在「没有访问权限，请在手机上同意之后刷新页面」，
  // 手机端弹 SERVICE_HTTP_NEW_CLIENT 让用户点头。鸿蒙侧这里就是那个「点头」的地方。

  /** 允许某设备访问网页。对方页面会在 2 秒内自动刷新 */
  private async approveWeb(token: string): Promise<void> {
    await this.service.approveWebClient(token);
    this.toast('已允许，对方页面会自动刷新');
  }

  private async denyWeb(token: string): Promise<void> {
    await this.service.denyWebClient(token);
    this.toast('已拒绝该设备');
  }

  /** 切换「网页免确认」（对应原 Config.WEB_OPEN） */
  private async switchWebOpen(on: boolean): Promise<void> {
    await this.service.setWebOpen(on);
  }

  /** 切换「收到图片/视频自动存相册」 */
  private async switchAutoAlbum(on: boolean): Promise<void> {
    this.autoAlbum = on;
    await this.service.setAutoAlbum(on);
  }

  /**
   * 取当前应用版本号。
   *
   * 走 `bundleManager.getBundleInfoForSelfSync`，而不是把版本号再抄一份字面量 ——
   * 否则每次发版都要记得同步改，抄漏了「关于」里就是错的。
   * ⚠️ 仍保留兜底常量：个别机型/时机下该 API 可能抛异常或返回空串，
   *    总不能让「关于」里显示一个空白。
   */
  private loadVersion(): void {
    try {
      const info: bundleManager.BundleInfo = bundleManager.getBundleInfoForSelfSync(
        bundleManager.BundleFlag.GET_BUNDLE_INFO_WITH_APPLICATION);
      const v: string = info.versionName;
      this.aboutVer = v.length > 0 ? v : ABOUT_FALLBACK_VER;
    } catch (e) {
      this.aboutVer = ABOUT_FALLBACK_VER;
    }
  }

  /** 复制上游开源仓库地址（长按/点错都好过让用户手打 URL） */
  private copyRepo(): void {
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, ABOUT_REPO);
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast('仓库地址已复制');
    } catch (e) {
      this.toast('复制失败');
    }
  }

  private copyUrl(): void {
    if (this.snapshot.webUrl.length === 0) {
      this.toast('尚未获取到访问地址');
      return;
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, this.snapshot.webUrl);
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast('访问地址已复制');
    } catch (e) {
      this.toast('复制失败');
    }
  }

  /** 把全部运行日志一次性复制走（排障时直接粘给别人，比截图强） */
  private copyLogs(): void {
    const lines: string[] = this.snapshot.logLines;
    if (lines.length === 0) {
      this.toast('暂无日志');
      return;
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, lines.join('\n'));
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast(`已复制 ${lines.length} 条日志`);
    } catch (e) {
      this.toast('复制失败');
    }
  }

  // ---------------- 文本消息 ----------------

  /** 当前聊天目标设备；返回 null 表示"所有在线设备" */
  private chatTarget(): LanDevice | null {
    if (this.chatTargetIp.length === 0) {
      return null;
    }
    for (let i = 0; i < this.devices.length; i++) {
      if (this.devices[i].devIp === this.chatTargetIp) {
        return this.devices[i];
      }
    }
    // 目标设备已下线：退回"所有设备"，避免消息发到一个不存在的地址
    return null;
  }

  /**
   * 消息 tab 的「+」：先定「发给谁」，再定「发什么」。
   *
   * 走弹窗而不是原来的 bindMenu，是因为菜单只能静态列「相册/文件」，
   * 没法在运行时按在线设备数量决定要不要先问设备 ——
   * 多台在线时用户会收到一句「请先选目标设备」，却不知道去哪选。
   *
   * 分支：
   * | 情况 | 行为 |
   * |---|---|
   * | 已在上方胶囊选了具体设备 | 直接进「相册/文件」 |
   * | 只有一台在线 | 直接进「相册/文件」（目标就是它） |
   * | 多台在线且选的是「所有设备」 | 先弹设备列表 |
   * | 没有在线设备 | 提示，不弹（发不出去） |
   */
  private openPlus(): void {
    if (!this.canSend()) {
      return;
    }
    if (this.devices.length === 0) {
      this.toast('当前没有在线设备，无法发送文件');
      return;
    }
    const cur: LanDevice | null = this.chatTarget();
    if (cur !== null) {
      this.beginPickType(cur);
      return;
    }
    if (this.devices.length === 1) {
      this.beginPickType(this.devices[0]);
      return;
    }
    this.pickStep = 1;
  }

  /** 目标已定，进入「相册 / 文件」这一层；顺手把上方胶囊同步过去 */
  private beginPickType(d: LanDevice): void {
    this.pickIp = d.devIp;
    this.pickName = d.devName.length > 0 ? d.devName : d.devIp;
    this.chatTargetIp = d.devIp;
    this.pickStep = 2;
  }

  private closePick(): void {
    this.pickStep = 0;
  }

  /** 关掉弹窗并真正调起选择器。设备可能在这一步之前下线，所以要重新查一遍 */
  private async doPick(album: boolean): Promise<void> {
    const ip: string = this.pickIp;
    this.pickStep = 0;
    let d: LanDevice | null = null;
    for (let i = 0; i < this.devices.length; i++) {
      if (this.devices[i].devIp === ip) {
        d = this.devices[i];
        break;
      }
    }
    if (d === null) {
      this.toast('目标设备已离线，请重新选择');
      return;
    }
    if (album) {
      await this.pickAlbumAndSend(d);
    } else {
      await this.pickAndSend(d);
    }
  }

  /**
   * 发一条文本消息。
   *
   * 先清空输入框再 await —— 发送要建 TCP 连接（最长 5s），
   * 期间输入框里还留着字会让人以为没发出去而重复点。
   */
  private async sendChat(): Promise<void> {
    const text: string = this.chatInput.trim();
    if (text.length === 0) {
      this.toast('请输入消息内容');
      return;
    }
    this.chatInput = '';
    const msg: string = await this.service.sendTextMessage(this.chatTarget(), text, false);
    this.toast(msg);
  }

  /** 进入设备名编辑态，用当前名称预填草稿 */
  private startEditDeviceName(): void {
    this.deviceNameDraft = this.snapshot.deviceName;
    this.deviceNameEditing = true;
  }

  /** 保存设备名（调用服务层持久化 + 实时生效）。
   *  留空 = 恢复默认（设备市场名）：用户清掉输入框再点保存即回到市场名。 */
  private async saveDeviceName(): Promise<void> {
    const name: string = this.deviceNameDraft.trim();
    if (name.length === 0) {
      await this.resetDeviceName();
      return;
    }
    await this.service.setDeviceName(name);
    this.deviceNameEditing = false;
    this.toast('设备名已更新');
  }

  /** 恢复默认设备名（设备市场名）：清除已持久化的自定义名，实时生效 */
  private async resetDeviceName(): Promise<void> {
    await this.service.resetDeviceName();
    this.deviceNameEditing = false;
    this.toast('已恢复为默认设备名');
  }

  private copyChat(): void {
    // 5.0.35：只复制消息正文，不再带用户名和时间（vivi：只需要复制消息本身）
    if (this.chat.length === 0) {
      this.toast('暂无聊天记录');
      return;
    }
    const lines: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      lines.push(this.chat[i].content);
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, lines.join('\n'));
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast(`已复制 ${lines.length} 条消息`);
    } catch (e) {
      this.toast('复制失败');
    }
  }

  /** 多选态复制：只复制选中消息的正文，不含用户名和时间 */
  private copySelectedChat(): void {
    const ids: string[] = this.chatSelected.slice();
    if (ids.length === 0) {
      this.toast('请先选择要复制的消息');
      return;
    }
    const want: Set<string> = new Set(ids);
    const lines: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      if (want.has(this.chat[i].id)) {
        lines.push(this.chat[i].content);
      }
    }
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, lines.join('\n'));
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast(`已复制 ${lines.length} 条消息`);
    } catch (e) {
      this.toast('复制失败');
    }
  }

  /** 复制任意一段文本到剪贴板（关于页的群号 / 更新地址等） */
  private copyText(t: string): void {
    try {
      const data: pasteboard.PasteData = pasteboard.createData(
        pasteboard.MIMETYPE_TEXT_PLAIN, t);
      pasteboard.getSystemPasteboard().setDataSync(data);
      this.toast('已复制');
    } catch (e) {
      this.toast('复制失败');
    }
  }

  /**
   * 刷新「接收到的文件」列表。
   *
   * 源目录就是服务端的落盘根目录：手机形态下是应用沙箱，
   * 在系统「文件管理」里看不到 —— 所以这个列表 + 另存为是用户唯一的取文件通道。
   */
  /**
   * 只在设备列表**真的变了**时才换 @State 引用。
   *
   * ⚠️ 原来这里是**无条件** `this.devices = this.service.onlineDeviceList()`，
   *    而 `onSnapshot` 是「每次 emit 都调」的（进度上报 10Hz、TCP 日志、连接事件…）。
   *    于是传输期间每秒会新建十几个「内容一模一样」的数组，每次换引用都让
   *    设备列表的 ForEach 走一遍 diff + 重建 —— 这是「传输时界面卡顿」的一大来源。
   *    改成先比签名（uuid|ip|名字|协议版本|电量），内容没变就一个字节都不动。
   */
  private syncDeviceList(): void {
    const list: LanDevice[] = this.service.onlineDeviceList();
    let sig: string = '';
    for (let i = 0; i < list.length; i++) {
      const d: LanDevice = list[i];
      sig += `${d.uniqueUuid}|${d.devIp}|${d.devName}|${d.dataVersion}|${d.batteryLevel};`;
    }
    if (sig === this.lastDeviceSig) {
      return;
    }
    this.lastDeviceSig = sig;
    this.devices = list;
  }

  /**
   * 设备行上的**协议版本徽章**文案。
   *
   * 取对端**广播出来的** `dataVersion`（UDP 心跳里带的那个）：
   *   >=5 → V5（1.35 修改版 / 本机 LANShare）
   *   4   → V4（官方 LANShare 1.2.x）
   *   3   → V3
   *   1/2 → V1 / V2
   *   其它 → V?
   *
   * ⚠️ 它表示的是「**对端宣告**的版本」，不代表我们一定用那套帧发它 ——
   *    出站协议由 `LanConfig.V5_MIN_DATA_VERSION` 判定（>=5 才走 v5 帧）。
   *    之所以要在界面上显示：真机上「同一个 App 两个版本共存却连不上」时，
   *    第一步就是确认对端到底是谁、能不能走 16 分片 —— 以前只能翻日志。
   */
  private protoLabel(d: LanDevice): string {
    if (d.dataVersion >= 5) {
      return 'V5';
    }
    if (d.dataVersion === 4) {
      return 'V4';
    }
    if (d.dataVersion === 3) {
      return 'V3';
    }
    if (d.dataVersion === 2) {
      return 'V2';
    }
    if (d.dataVersion === 1) {
      return 'V1';
    }
    return 'V?';
  }

  /** 徽章底色：V5 = 主色，V4 = 蓝，V3 及更早 = 灰 */
  private protoColor(d: LanDevice): string {
    if (d.dataVersion >= 5) {
      return C_PRIMARY;
    }
    if (d.dataVersion === 4) {
      return '#3D7EFF';
    }
    if (d.dataVersion === 3) {
      return '#8A9099';
    }
    return '#B0B6BF';
  }

  /**
   * ★ 5.0.64：一次刷新里的**换引用闸门**。
   *
   * ArkTS 的 `@State` 每换一次引用就触发一次独立重渲染，**连续赋值不会合并**。
   * 存相册那条链路上一次操作要换 4 个（albumIndex / receivedFiles /
   * chatMediaPaths / chatGroups）⇒ 4 次重渲染 ⇒ 观感是「闪几下」。
   *
   * 做法：**先全部算完，最后统一换**。开关开着时，`syncChatMediaPaths` /
   * `buildChatGroups` / 存相册收尾都只把新值记到 xxxNext，**不碰 @State**；
   * 由 `flushStateSwap()` 在最末尾一次性换完 ⇒ 4 次重渲染变 1 次。
   *
   * ⚠️ 只改「什么时候通知 UI」，**不改变任何数据语义**。
   * ⚠️ 绝不能「干脆不换引用」来消闪 —— 数据真的变了（沙箱副本已删、缩略图已存），
   *    不换 = 界面不更新。只能合并，不能跳过。
   */
  private stateSwapDepth: number = 0;
  private chatMediaPathsNext: Map<string, string> | null = null;
  private chatMediaGroupsNext: Map<string, string[]> | null = null;
  private chatGroupsNext: ChatGroup[] | null = null;
  private albumIndexNext: Map<string, string> | null = null;
  /** ★ 5.1.5：闸门缓冲用的 tick 增量（`localStateTick` 自身的缓冲位） */
  private localStateTickNext: number = 0;
  // ★ 5.0.75：切消息页探测时**刚清过**的相册 key，避免每次切 tab 重复做同步 IO
  private albumClearedIds: Set<string> = new Set<string>();
  /**
   * ★★ 5.1.70：相册资产探测的**重入闸门**。
   * 切页（已停用）与 （后台静默）两路都可能触发，
   * 426 张时并发 = 白干一遍全量探活。
   */
  private albumProbeRunning: boolean = false;

  /** 打开闸门（可重入 ⇒ 用计数器，不用 boolean） */
  private beginStateSwap(): void {
    this.stateSwapDepth += 1;
  }

  /** 关闭闸门；归零时统一换引用 */
  private endStateSwap(): void {
    if (this.stateSwapDepth > 0) {
      this.stateSwapDepth -= 1;
    }
    if (this.stateSwapDepth > 0) {
      return;
    }
    this.flushStateSwap();
  }

  /**
   * ★ 5.0.64：把闸门期间攒下的新值**一次性**交给 UI。
   *
   * 逐个「换引用」而不是整体替换，是为了让每一处原有的
   * 「内容没变就不换引用」判断继续有效（避免无谓重绘）。
   */
  private flushStateSwap(): void {
    // ⚠️ 5.0.66：`receivedFiles` 与 `chat` 改为**立即落地**（见 swapChat 的注释），
    //   这里不再需要它们的缓冲字段。
    // ★★ 5.0.68（诊断）：逐项记录「换了哪些」，让下一次复现能一锤定音。
    // ⚠️ 5.0.69：`chatMediaPaths` 已降级为普通字段 ⇒ **不需要通知**，
    //   缓冲里那份直接落地即可（换引用不再触发重绘）。
    if (this.chatMediaPathsNext !== null) {
      this.chatMediaPaths = this.chatMediaPathsNext as Map<string, string>;
      this.chatMediaPathsNext = null;
    }
    const swP: boolean = false;   // 5.0.69：不再触发 UI，诊断口径固定为 N
    const swG: boolean = this.chatMediaGroupsNext !== null;
    const swC: boolean = this.chatGroupsNext !== null;
    if (this.localStateTickNext > 0) {
      this.localStateTick += this.localStateTickNext;
      this.localStateTickNext = 0;
    }
    const swA: boolean = this.albumIndexNext !== null;
    if (swG) {
      this.chatMediaGroups = this.chatMediaGroupsNext as Map<string, string[]>;
      this.chatMediaGroupsNext = null;
    }
    if (swC) {
      this.chatGroups = this.chatGroupsNext as ChatGroup[];
      this.chatGroupsNext = null;
    }
    if (swA) {
      this.albumIndex = this.albumIndexNext as Map<string, string>;
      this.albumIndexNext = null;
    }
    // ★ 5.1.0：5.0.68 的临时诊断打点已移除（真凶早已查明：外层气泡 key 的
    //   `groupAlbumSig` ⇒ 整颗气泡销毁重建，见 v5.0.71 的 commit）。
    //   `swP` 现在只用于「chatMediaPaths 落地」那一步的判断，保留以免动到逻辑。
  }

  /**
   * ★ 5.0.65：`chat` 换引用的统一入口（经闸门）。
   *
   * ⚠️ 为什么要专门一个方法：`chat` 是在 `onSnapshot` 里换的，而 `onSnapshot`
   *   一次会换好几个 @State；闸门开着时只记缓冲，由 `flushStateSwap()` 一次落地。
   */
  private swapChat(v: ChatMessage[]): void {
    // ★★★ 5.0.66：**这里必须立即落地，不能进闸门缓冲。**
    //
    // 5.0.65 的回归根因：`chat` 进了 `chatNext`，于是闸门段里
    //   syncChatMediaPaths() / buildChatGroups() / autoSaveNewMedia()
    // 这三个方法读到的 `this.chat` 仍是**旧数组** ——
    //   - autoSaveNewMedia 第一行 `if (oldCount >= this.chat.length) return;`
    //     直接 return ⇒ **自动存相册整个不执行**；
    //   - 另两个遍历旧数组 ⇒ 新消息的路径/分组没建 ⇒ **消息页不显示**
    //     （切 TAB 触发新一轮 refresh 才补上，故 vivi 看到「要切一下才对」）。
    //
    // ⚠️ 闸门缓冲的前提是这个值「**只给 UI 读**、没有别的代码在同一条链上读它」。
    //   一旦有别的代码读它，就必须立即落地 —— 它是**数据源**，不是通知。
    //   闸门该合并的是**派生表**（chatMediaPaths/chatGroups/...）这类通知型状态。
    this.chat = v;
  }

  /** `albumIndex` 的统一入口：闸门开着就记到缓冲，否则直接换 */
  private swapAlbumIndex(): void {
    const snap: Map<string, string> = this.service.albumSnapshot();
    if (this.stateSwapDepth > 0) {
      this.albumIndexNext = snap;
      return;
    }
    this.albumIndex = snap;
  }

  private refreshReceived(): void {
    this.beginStateSwap();
    // ⚠️ 5.0.64：必须 try/finally —— `refreshReceivedInner` 内部有
    //   `ExportService.listReceived`（磁盘 IO）等可能抛异常的调用。
    //   一旦抛出而闸门没关，`stateSwapDepth` 永久卡在 >0 ⇒
    //   之后**所有** @State 更新都只进缓冲不再落地 ⇒ 界面再也不更新，
    //   而且没有任何报错，只是「点了没反应」。这个坑比闪一次严重得多。
    try {
      this.refreshReceivedInner();
    } finally {
      this.endStateSwap();
    }
  }

  /** ★ 5.0.64：原 `refreshReceived` 的真身，包在换引用闸门里跑 */
  private refreshReceivedInner(): void {
    const list: ReceivedFile[] = ExportService.listReceived(this.service.receiveRoot);
    // ⚠️ 5.0.66：同理**必须立即落地**。`rebuildRecvIndex(list)` 与
    //   `syncChatMediaPaths()` 都要读 `this.receivedFiles`（经 recvPathFor），
    //   进缓冲就会让它们读到旧列表 ⇒ 路径解析不出来。5.0.64 引入闸门时就带着
    //   这个隐患，只是当时「条数变了」分支恰好在闸门外把它掩盖了。
    this.receivedFiles = list;
    // 消息页的图片缩略图靠它把「文件名」翻回「沙箱路径」（保留：气泡长按存图仍要用）
    this.rebuildRecvIndex(list);
    // 5.0.33：文件页回退「一行一个 + 48vp 小缩略图」，媒体不再单独拆宫格。⚠️ 仍**不**预热视频首帧 / 量图片比例 ——
    //   那两套都是「刷新就把全部文件同步算一遍」，文件一多主线程被卡住（vivi 实测卡顿）。
    //   视频首帧由文件页列表项的 mediaThumb 按需解（不再整批预热），图片交给框架按需解码。
    // 气泡长按存图依赖「文件名->沙箱路径」反查；文件一变就重算（见 syncChatMediaPaths）
    this.syncChatMediaPaths();
    // ★ 5.0.55：文件列表一变，缩略图的可用来源可能变（沙箱副本被删 -> 改用缓存小图）
    this.buildChatGroups();
    // 打一条汇总：真机上「列表里的 size」和「文件实际大小」对不上时，
    // 这一行能立刻区分是「stat 取到了旧值」还是「UI 没重建」。
    let total: number = 0;
    for (let i = 0; i < list.length; i++) {
      total += list[i].size;
    }
    Log.i(TAG, `文件列表刷新：${list.length} 条，共 ${ExportService.humanSize(total)}`);

    // 5.0.39：待存相册的那一批 —— 文件这时才刚落盘、索引刚建好，再试一次
    this.flushAutoSave();
  }

  /**
   * 从「消息」页的文件气泡跳到「文件」页。
   *
   * 这里显式刷一次列表再切页：`Tabs.onChange` 里的刷新只在 index 变化时触发，
   * 而 `Tabs` 的 index 又绑在 `curTab` 上，先赋值再 `changeIndex` 有可能被判成
   * 「没变化」而不回调 —— 不刷的话用户跳过去看到的是上一次的列表。
   */
  private openFileTab(): void {
    this.refreshReceived();
    this.curTab = 2;
    this.tabsController.changeIndex(2);
  }

  /**
   * 当前落盘位置说明，直接给用户看。
   *
   * ★ 5.1.1（vivi 21:02）：追加「可点击『另存为』保存到本地」。
   *   原因：那个沙箱路径在系统「文件管理」里**根本看不到**（沙箱隔离），
   *   只报路径对普通用户等于「拿不出来」。而「另存为」是本项目**唯一的取文件通道**
   *   （文件页注释已写明），顶部说明却一个字都没提。
   *   ⚠️ 仅在**有文件时**追加 —— 空列表提「另存为」是噪声。
   *   ⚠️ 判据与文案必须**在同一处**判定：拆开会出现「文案说有、实际没有」的不一致
   *   （5.0.75 刚踩过「判据与展示不同源」）。
   */
  private saveLocationHint(): string {
    const loc: string = this.snapshot.saveLocation;
    const where: string = `落盘位置：${loc.length > 0 ? loc : '共享未开启'}`;
    if (this.receivedFiles.length === 0) {
      return where;
    }
    return `${where} · 可点击「另存为」保存到本地`;
  }

  /**
   * 弹系统保存对话框，把沙箱里的文件另存到用户选定的位置。
   *
   * 不用「预授权目录」是因为手机拿不到该能力（见迁移对照表第十三节）；
   * 用户显式选一次位置的模型在手机上是可用的。
   */
  private async saveAsFile(f: ReceivedFile): Promise<void> {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const msg: string = await ExportService.saveAs(ctx, f.path, f.name);
    if (!msg.startsWith('已保存')) {
      // 取消 / 失败一律**不动**沙箱 —— 那份是唯一的一份（见 deleteOne 的注释）
      this.toast(msg);
      return;
    }
    // ★ 5.0.53（vivi 要求）：另存成功后**删掉沙箱副本**，不再留双份。
    //   与「存相册后删沙箱副本」同一口径：内容已经落到应用之外了。
    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `${msg}，沙箱副本已删除` : `${msg}（沙箱副本删除失败：${err}）`);
    // ★ 5.1.2：记账「已存本地」—— 气泡底部据此把「点击查看」改成「已存入本地」。
    //   ⚠️ 必须在**删除沙箱副本之后**记：删失败时内容还在沙箱里，不该显示「已存入本地」。
    //   ⚠️ 用 `f.name` 反查而不是拿消息对象：文件页的按钮拿到的是 `ReceivedFile`，
    //   与消息没有直接引用（5.0.55 的「显示聚合 ≠ 记账聚合」决定了不能顺着 UI 传）。
    this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);
    this.refreshReceived();
  }

  /**
   * 删除沙箱里的一个文件。
   *
   * 删除前必须确认：沙箱里的文件在**系统「文件管理」里看不到**，
   * 一旦删掉，用户没有任何别的途径能找回，误删代价远高于多一步确认。
   */
  private async deleteOne(f: ReceivedFile): Promise<void> {
    const ok: boolean = await this.confirmDialog('删除文件', '删除后无法恢复', '删除', f.name);
    if (!ok) {
      return;
    }
    const err: string | null = ExportService.deleteFile(this.service.receiveRoot, f.path);
    this.toast(err === null ? `已删除 ${f.name}` : err);
    // ★ 5.1.2：删除**成功**才记账（err !== null 说明文件可能还在）。
    if (err === null) {
      this.markMessagesLocal(f.name, Index.HINT_LOCAL_DELETED);
    }
    this.refreshReceived();
  }

  /**
   * 清空沙箱里所有已接收的文件。
   *
   * ⚠️ 这里刻意**不用** `receivedFiles`（列表有 40 条上限）来算要删什么，
   * 而是重新全量扫一遍目录 —— 否则用户点「清空」只会删掉看得见的前 40 条，
   * 剩下的继续占空间，表现得像"清空没生效"。
   */
  private async deleteAllFiles(): Promise<void> {
    const all: string[] = ExportService.allPaths(this.service.receiveRoot);
    if (all.length === 0) {
      this.toast('没有可删除的文件');
      return;
    }
    const ok: boolean =
      await this.confirmDialog('清空接收到的文件', '删除后无法恢复', '全部删除', `共 ${all.length} 个文件`);
    if (!ok) {
      return;
    }
    // ★ 5.1.11：先把**路径 → 文件名**记下来（此刻 receivedFiles 还是旧值），
    //   删完并 refreshReceived 之后就查不到了。
    const gonePaths: string[] = ExportService.allPaths(this.service.receiveRoot).slice();
    const r: DeleteResult = ExportService.deleteAll(this.service.receiveRoot);
    this.toast(r.failed === 0
      ? `已删除 ${r.ok} 个文件`
      : `已删除 ${r.ok} 个，失败 ${r.failed} 个（${r.firstError}）`);
    // ★ 5.1.11：清空也要记账 —— 否则消息页气泡永远停在「点击查看」
    //   （vivi 22:0x 反馈：单条删除会同步，清空不会）。
    if (r.ok > 0) {
      this.markMessagesLocalByPaths(gonePaths, Index.HINT_LOCAL_DELETED);
    }
    this.refreshReceived();
  }

  // ------------------------------------------------------------------
  // 文件页：长按多选
  // ------------------------------------------------------------------

  /**
   * 进入多选模式并选中给定文件（**长按**某一行触发）。
   * 已经在多选态时，长按等价于切换该行的勾选 —— 这样用户继续长按别的行
   * 也不会意外退出多选。
   */
  private enterFileSelect(path: string): void {
    if (!this.fileSelectMode) {
      this.fileSelectMode = true;
      this.fileSelected = [path];
      return;
    }
    this.toggleFileSelect(path);
  }

  /** 切换一行的勾选态。取消掉最后一个勾选时自动退出多选（少点一次「取消」） */
  private toggleFileSelect(path: string): void {
    const out: string[] = [];
    let removed: boolean = false;
    for (let i = 0; i < this.fileSelected.length; i++) {
      if (this.fileSelected[i] === path) {
        removed = true;
      } else {
        out.push(this.fileSelected[i]);
      }
    }
    if (!removed) {
      out.push(path);
    }
    // ⚠️ 必须整体换引用：ArkUI 不会因为数组 push/splice 就重渲染
    this.fileSelected = out;
    if (out.length === 0) {
      this.fileSelectMode = false;
    }
  }

  /** 全选 / 取消全选（再点一次） */
  private toggleSelectAllFiles(): void {
    if (this.receivedFiles.length === 0) {
      return;
    }
    if (this.fileSelected.length === this.receivedFiles.length) {
      this.exitFileSelect();
      return;
    }
    const out: string[] = [];
    for (let i = 0; i < this.receivedFiles.length; i++) {
      out.push(this.receivedFiles[i].path);
    }
    this.fileSelected = out;
  }

  /** 退出多选并清空勾选 */
  private exitFileSelect(): void {
    this.fileSelectMode = false;
    this.fileSelected = [];
  }

  /** 勾选态里是否包含某路径 */
  private isFileSelected(path: string): boolean {
    return this.fileSelected.indexOf(path) >= 0;
  }

  /** 多选批量另存为：一次弹窗选好目标目录，把勾选的文件都复制过去 */
  private async batchSaveSelected(): Promise<void> {
    const picked: ReceivedFile[] = [];
    for (let i = 0; i < this.receivedFiles.length; i++) {
      const f: ReceivedFile = this.receivedFiles[i];
      if (this.isFileSelected(f.path)) {
        picked.push(f);
      }
    }
    if (picked.length === 0) {
      this.toast('请先选择要保存的文件');
      return;
    }
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const r: SaveOutcome = await ExportService.saveMany(ctx, picked);
    // ⚠️ 用户**取消**保存对话框时不能退出多选：
    //    他刚才勾了 N 个文件，一按取消就把勾选全清掉，等于白勾一遍。
    //    取消 ⇒ 原样停在多选界面（勾选、模式都保留），用户可以再点一次。
    if (r.cancelled) {
      this.toast(r.msg);
      return;
    }
    // ★ 5.0.53（vivi 要求）：已保存成功的那些**删掉沙箱副本**（不再留双份）。
    //   ⚠️ 只删 `r.savedPaths` 里的 —— 失败的那几个还没落到应用之外，删了就真没了。
    // ★ 5.1.11：批量另存也要记「已存本地」（与单条 saveAsFile 口径一致）。
    //   ⚠️ 只记**删除成功**的那些（`deleteFile` 返回 null）——
    //   删失败说明内容还在沙箱里，不该显示「已存本地」（5.1.2 定的口径）。
    //   ⚠️ 在**同一个循环里**收集，不要另起一轮 deleteFile（会删两次）。
    let cleaned: number = 0;
    const savedOk: string[] = [];
    for (let i: number = 0; i < r.savedPaths.length; i++) {
      if (ExportService.deleteFile(this.service.receiveRoot, r.savedPaths[i]) === null) {
        cleaned += 1;
        savedOk.push(r.savedPaths[i]);
      }
    }
    if (savedOk.length > 0) {
      this.markMessagesLocalByPaths(savedOk, Index.HINT_LOCAL_SAVED);
    }
    this.toast(cleaned > 0 ? `${r.msg}；已清理 ${cleaned} 个沙箱副本` : r.msg);
    // 真正保存过（哪怕部分失败）才收起多选；失败也刷新一下，让大小/条数同步
    this.exitFileSelect();
    this.refreshReceived();
  }

  /** 多选批量删除：一次确认、逐个删（一条失败不影响其余） */
  private async batchDeleteSelected(): Promise<void> {
    const paths: string[] = this.fileSelected.slice();
    if (paths.length === 0) {
      this.toast('请先选择要删除的文件');
      return;
    }
    const ok: boolean = await this.confirmDialog(
      '删除选中的文件', '删除后无法恢复', '删除', `共 ${paths.length} 个文件`);
    if (!ok) {
      return;
    }
    const r: DeleteResult = ExportService.deleteFiles(this.service.receiveRoot, paths);
    this.toast(r.failed === 0
      ? `已删除 ${r.ok} 个文件`
      : `已删除 ${r.ok} 个，失败 ${r.failed} 个（${r.firstError}）`);
    // ★ 5.1.11：批量删除同样要记账（与单条 deleteOne 口径一致）。
    //   ⚠️ 必须在 exitFileSelect / refreshReceived **之前**——
    //   后者会清掉 receivedFiles，「路径 → 文件名」的映射就没了。
    if (r.ok > 0) {
      this.markMessagesLocalByPaths(paths, Index.HINT_LOCAL_DELETED);
    }
    this.exitFileSelect();
    this.refreshReceived();
  }


  /**
   * ★ 5.0.55：把消息列表按**批号**聚合成「气泡」列表。
   *
   *   同一次接收的多张图片/视频（5.0.53 拆成了 N 条消息、共享同一个 `batchId`）
   *   在这里合成**一个**气泡 → UI 渲染成宫格多缩略图。
   *
   * ⚠️⚠️ 只是**显示**聚合，**绝不**合并消息本身：
   *   `ChatGroup.msgs` 里的每个元素都是 `this.chat` 里的真实对象（同一引用），
   *   所以「点第 k 张打开第 k 张」「删第 k 条不影响其余」「每张各有自己的相册条目」
   *   全部照旧 —— 5.0.53 修的东西一个都没丢。
   *   如果为了「一个气泡」去把消息合并成一条，等于把 5.0.53 的修复废掉
   *   （回退到「删一张整批失效 + 点不到第 2 张」），千万别那么干。
   *
   * 空 `batchId`（单发 / 发送方向 / 文本 / 5.0.55 之前的历史数据）→ 各自一个气泡，
   * 与改动前行为完全一致。
   */
  private buildChatGroups(): void {
    const src: ChatMessage[] = this.chat;
    const out: ChatGroup[] = [];
    let i: number = 0;
    while (i < src.length) {
      const m: ChatMessage = src[i];
      const g: ChatGroup = new ChatGroup();
      g.msgs.push(m);
      let j: number = i + 1;
      // 同批消息一定是**连续**落进去的（`appendFileChat` 一个循环里连续 append），
      // 所以只往右扫、不跨消息找。
      if (m.batchId.length > 0 && m.kind === 'file') {
        while (j < src.length) {
          const n: ChatMessage = src[j];
          if (n.batchId !== m.batchId || n.kind !== 'file') {
            break;
          }
          g.msgs.push(n);
          j += 1;
        }
      }
      i = j;
      g.isFiles = m.kind === 'file';
      g.incoming = m.incoming;
      g.timeMs = m.timeMs;
      g.isMedia = this.groupAllMedia(g);
      // ★ 5.0.56：按 3 个一行切好（只有宫格才需要 rows，非媒体组不用浪费）
      if (g.isMedia) {
        for (let k: number = 0; k < g.msgs.length; k += Index.GRID_COLS) {
          const row: ChatMessage[] = [];
          for (let t: number = k; t < k + Index.GRID_COLS && t < g.msgs.length; t++) {
            row.push(g.msgs[t]);
          }
          g.rows.push(row);
        }
      }
      let ids: string = '';
      for (let k: number = 0; k < g.msgs.length; k++) {
        ids += `${g.msgs[k].id},`;
      }
      g.key = ids;
      out.push(g);
    }
    // 签名没变就不换引用 —— 这个方法在每次 refreshReceived 里都会跑，
    // 无条件换引用等于每次刷新都把整个消息列表重建一遍。
    let sig: string = '';
    for (let k: number = 0; k < out.length; k++) {
      sig += `${out[k].key}|${out[k].isMedia ? 1 : 0};`;
    }
    if (sig !== this.chatGroupsSig) {
      this.chatGroupsSig = sig;
      if (this.stateSwapDepth > 0) {
        this.chatGroupsNext = out;
      } else {
        this.chatGroups = out;
      }
    }
  }

  /**
   * 这一组是不是「**不止一张**、全是图片/视频、且是**收到**的」——
   * 只有这种才渲染成宫格气泡。
   *
   * ⚠️ 三个条件缺一不可：
   *   - 「不止一张」：单张走原来的文件名气泡（观感不变，风险最小）；
   *   - 「全是媒体」：混批（1 张图 + 1 个 zip）在 5.0.53 就没拆，这里也不会成组；
   *   - 「收到的」：用户要的是「**接受的**图片和视频」（vivi 2026-10-02）。
   *     自己发出去的那批点气泡只是跳文件页，没有相册语义，改成宫格没意义。
   *
   * ⚠️ 判据只看**消息本身**（`mediaNamesOf` 读 `m.files` / `m.content`），
   *   不看沙箱里还剩几个文件 —— 否则「自动存相册后删掉沙箱副本」会让它
   *   中途从宫格塌回文件名气泡（5.0.52 那个「下标塌缩」的同款病因）。
   */
  private groupAllMedia(g: ChatGroup): boolean {
    // ★★ 5.0.77（vivi 20:43「单张不就相当于单个的宫格」）：去掉 `length < 2` 限制。
    //
    // 【为什么要合】单张与多张是**同构**的（发送方名+时间 / 缩略图 / N张·提示），
    //   之前是两条独立代码路径，导致同一个问题要**分别修两遍**，而我接连漏掉：
    //     - 5.0.72 单张缩略图忘了改成 88 固定方框
    //     - 5.0.73 单张忘了改 `Cover` 铺满
    //     - 5.0.77 单张**漏了「已删」角标**（vivi 20:36 反馈）
    //     - 单张顶部还多一句「收到文件」（宫格那边是「发送方名 + 时间」）
    //   ⇒ 从**源头**合并，比继续在两条路上打补丁可靠。
    //
    // 【★ 长按逻辑天然统一，零新增代码】
    //   两条路的长按**本来就已经都是「进多选」**：
    //     `chatBubble`      → `enterChatSelect(m.id)`
    //     `chatMediaBubble` → `enterChatGroupSelect(g)`
    //   而「存相册」在**多选态底部**（`batchSaveChatToAlbum`，5.0.57 加的
    //   「存相册 (N)」）。⇒ 单张并入后，「长按 → 多选 → 底部点存相册」这条链
    //   自动就有 —— 正是 vivi 要求的「统一」（20:43）。
    //
    // ⚠️ **仍然只放开「收到的」**（`incoming` 保留）：自己发出去的图**沙箱里没有**
    //   （它在对方手机上）⇒ 走宫格会显示空白；而存相册对发出方也没有意义。
    //   要放开自己发的需单独确认，不在本轮擅自扩大范围。
    if (g.msgs[0].kind !== 'file' || !g.msgs[0].incoming) {
      return false;
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.mediaNamesOf(g.msgs[i]).length === 0) {
        return false;
      }
    }
    return true;
  }

  /**
   * 组内**每条**消息的缩略图签名（ForEach key 用，见调用点注释）。
   *
   * ★ 5.0.61：从这里**去掉全局 `thumbTick`**（原来挂在 ListItem 的 key 上）——
   *   那个计数器每生成一张缩略图就 +1，于是「一张图存进相册」会把**整屏**气泡的
   *   key 全部改掉、全部销毁重建（「保存完相册又刷一遍」的第三层成因）。
   *   现在签名下移到**这一组自己**的显示要素（显示源 + 比例 + 补转角度）：
   *   只有真正变了的那一组会重建，其余行的 key 完全不动。
   */
  private groupMediaSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      s += `${this.thumbSigOf(g.msgs[i])};`;
    }
    return s;
  }

  /** 组内**每条**消息的相册条目签名（ForEach key 用） */
  /**
   * ★ 5.0.71：组内**每条**消息的「已删」角标签名（**消息页外层气泡 key 用**）。
   *
   * ★★★ 为什么不能用 `groupAlbumSig` 当外层 key（这是「闪」的真正结构性原因）：
   *   `groupAlbumSig` 逐条读 `albumPartOf(mid, 0, 0).length > 0`，
   *   而「存相册」这个动作**恰好就是**把 uri 从空变成有 ⇒ 该位 `0 -> 1`
   *   ⇒ **外层 ForEach key 变** ⇒ **整颗气泡（`ListItem`）销毁重建** ⇒ 闪。
   *   5.0.63 已把**内层** `thumbSigOf` 改成不含 albumPart 的 `id:src:rot`，
   *   但**外层这一处一直还在读 albumPart** —— 前九轮都在内层打转，漏了它。
   *
   * 【为什么不能干脆删掉】
   *   `mediaGoneFromAlbum`（已删角标的唯一判据，:3439）第一行就是
   *   「有相册 uri ⇒ 返回 false」，所以存相册时它会 **`true -> false`**：
   *       存相册前：有 thumb + 沙箱已删 + 无 uri ⇒ true  （显示「已删」）
   *       存相册后：有 uri                        ⇒ false （角标要消失）
   *   这个翻转**只能靠重建刷新**，删掉 key 分量会让「已删」角标一直挂着。
   *
   * 【所以只保留「已删」这一半】
   *   - 「已删」翻转 ⇒ 保留触发（角标是唯一提示途径，必须刷）；
   *   - 「已存入」 ⇒ **不触发**：提示由 `bubbleHintOf` 的文案承载，
   *     而 5.0.70 已把那条文案**等宽化** ⇒ 文案能变而宽度不变 ⇒ 无需重建。
   */
  private groupGoneSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      // ★ 5.0.72 把「**已存入相册**」这一维**并回来**（5.0.71 拿掉后
      // 「已存入相册 · 点击打开」那行小蓝字**一直没出现**，见方法注释的完整说明）。
      //
      // ★★ 关键教训：5.0.71 我以为「提示由 `bubbleHintOf` 的等宽文案承载、
      //   不必重建」—— **前提漏了**：ArkTS 只在 **build 时**求值表达式，
      //   key 不变 ⇒ 不重建 ⇒ **那行 `Text` 永远停留在 build 那一刻的值**
      //   （存相册之前 = 「点击查看」），哪怕 `bubbleHintOf` 此刻返回的
      //   已经是「已存入相册 …」。
      //   ⇒ **凡是「靠表达式（文案/颜色/长度）承载的显示」，就必须让那一层真的重建。**
      //   这与 5.0.70 的「等宽化」不冲突：等宽化解决**宽度重排**，
      //   重建解决**值更新**，是**两个不同的问题**。
      s += this.mediaGoneFromAlbum(g.msgs[i], 0) ? '1' : '0';
      s += this.albumPartOf(g.msgs[i].id, 0, 0).length > 0 ? '1' : '0';
    }
    return s;
  }

  private groupAlbumSig(g: ChatGroup): string {
    let s: string = '';
    for (let i: number = 0; i < g.msgs.length; i++) {
      const mid: string = g.msgs[i].id;
      s += `${this.albumPartOf(mid, 0, 0).length > 0 ? 1 : 0}` +
        `${this.albumPartOf(mid, 0, 1).length > 0 ? 1 : 0}`;
    }
    return s;
  }

  /** 组内**全部**消息都被勾选 */
  private isGroupFullySelected(g: ChatGroup): boolean {
    if (g.msgs.length === 0) {
      return false;
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.chatSelected.indexOf(g.msgs[i].id) < 0) {
        return false;
      }
    }
    return true;
  }

  /** 组内**部分**消息被勾选（勾选圆显示成中间态） */
  private isGroupPartlySelected(g: ChatGroup): boolean {
    if (this.isGroupFullySelected(g)) {
      return false;
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.chatSelected.indexOf(g.msgs[i].id) >= 0) {
        return true;
      }
    }
    return false;
  }

  /**
   * ★ 5.0.55：长按一个**宫格气泡** → 整组进多选（已在多选态则整组切换）。
   *
   * 为什么按组：用户视觉上看到的就是「一个气泡」，长按它却只选中其中一张会很怪。
   * 想只删某一张时，在多选态下**点那一张缩略图**即可单独切换（见 chatMediaGrid）。
   * ⇒ 整组删 / 单张删，两条路都通。
   */
  private enterChatGroupSelect(g: ChatGroup): void {
    const ids: string[] = [];
    for (let i: number = 0; i < g.msgs.length; i++) {
      ids.push(g.msgs[i].id);
    }
    if (!this.chatSelectMode) {
      this.chatSelectMode = true;
      this.chatSelected = ids;
      return;
    }
    const all: boolean = this.isGroupFullySelected(g);
    let out: string[] = this.chatSelected.slice();
    if (all) {
      for (let i: number = 0; i < ids.length; i++) {
        out = Index.removeStr(out, ids[i]);
      }
    } else {
      for (let i: number = 0; i < ids.length; i++) {
        if (out.indexOf(ids[i]) < 0) {
          out.push(ids[i]);
        }
      }
    }
    // ⚠️ 必须整体换引用：ArkUI 不会因为数组 push/splice 就重渲染
    this.chatSelected = out;
    if (out.length === 0) {
      this.chatSelectMode = false;
    }
  }

  /** 从字符串数组里去掉一个值（整体换引用） */
  private static removeStr(list: string[], v: string): string[] {
    const out: string[] = [];
    for (let i: number = 0; i < list.length; i++) {
      if (list[i] !== v) {
        out.push(list[i]);
      }
    }
    return out;
  }

  // ------------------------------------------------------------------
  // 消息页：长按多选删除
  // ------------------------------------------------------------------

  /** 进入消息多选并选中给定消息（长按气泡触发） */
  private enterChatSelect(id: string): void {
    if (!this.chatSelectMode) {
      this.chatSelectMode = true;
      this.chatSelected = [id];
      return;
    }
    this.toggleChatSelect(id);
  }

  /** 切换一条消息的勾选态；取消最后一个勾选时自动退出多选 */
  private toggleChatSelect(id: string): void {
    const out: string[] = [];
    let removed: boolean = false;
    for (let i = 0; i < this.chatSelected.length; i++) {
      if (this.chatSelected[i] === id) {
        removed = true;
      } else {
        out.push(this.chatSelected[i]);
      }
    }
    if (!removed) {
      out.push(id);
    }
    // ⚠️ 必须整体换引用：ArkUI 不会因为数组 push/splice 就重渲染
    this.chatSelected = out;
    if (out.length === 0) {
      this.chatSelectMode = false;
    }
  }

  /** 全选 / 取消全选（再点一次） */
  private toggleSelectAllChat(): void {
    if (this.chat.length === 0) {
      return;
    }
    if (this.chatSelected.length === this.chat.length) {
      this.exitChatSelect();
      return;
    }
    const out: string[] = [];
    for (let i = 0; i < this.chat.length; i++) {
      out.push(this.chat[i].id);
    }
    this.chatSelected = out;
  }

  /** 退出消息多选并清空勾选 */
  private exitChatSelect(): void {
    this.chatSelectMode = false;
    this.chatSelected = [];
  }

  /** 勾选态里是否包含某消息 id */
  private isChatSelected(id: string): boolean {
    return this.chatSelected.indexOf(id) >= 0;
  }

  /** 多选批量删除消息：一次确认、逐个从聊天记录移除并落盘 */
  private async batchDeleteChat(): Promise<void> {
    const ids: string[] = this.chatSelected.slice();
    if (ids.length === 0) {
      this.toast('请先选择要删除的消息');
      return;
    }
    const ok: boolean = await this.confirmDialog(
      '删除选中的消息', '仅删除聊天记录，不会删除已接收的文件', '删除', `共 ${ids.length} 条消息`);
    if (!ok) {
      return;
    }
    this.service.deleteChatMessages(ids);
    this.exitChatSelect();
  }

  /**
   * 这条消息能不能「存相册」：是**收到**的文件消息、有媒体名、**且还没有相册条目**。
   *
   * ⚠️ 已有相册条目的要排除 —— 否则用户会看到「存了但相册里多出一张重复的」。
   *   真在系统相册里被删掉的那种，`clearAlbumUri` 已经把 uri 摘掉了（只剩缩略图），
   *   所以这里也会重新放行，符合预期。
   */
  private albumPickable(m: ChatMessage): boolean {
    if (m.kind !== 'file' || !m.incoming) {
      return false;
    }
    if (this.mediaNamesOf(m).length === 0) {
      return false;
    }
    return this.albumPartOf(m.id, 0, 0).length === 0;
  }

  /**
   * ★ 5.0.57（vivi 2026-10-02）：多选态里**可存相册**的条数 —— 底部按钮上的数字。
   *
   * ⚠️ 带缓存：多选态底部条一次渲染会问它 4 遍（按钮文案 + 配色 + enabled 各一次），
   *   每次都全量扫 `chat × chatSelected` 是 O(N²)。签名一变就重算，其余时候直接返回。
   */
  private chatAlbumCount(): number {
    if (this.chatSelected.length === 0) {
      return 0;
    }
    const sig: string =
      `${this.chatSelected.join(',')}|${this.chat.length}|${this.albumIndex.size}`;
    if (sig === this.chatAlbumCountSig) {
      return this.chatAlbumCountCache;
    }
    const sel: Set<string> = new Set<string>();
    for (let k: number = 0; k < this.chatSelected.length; k++) {
      sel.add(this.chatSelected[k]);
    }
    let n: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (sel.has(m.id) && this.albumPickable(m)) {
        n += 1;
      }
    }
    this.chatAlbumCountSig = sig;
    this.chatAlbumCountCache = n;
    return n;
  }

  /**
   * ★ 5.0.57（vivi 2026-10-02 要求）：多选态 -> 把选中的图片/视频**存进相册**。
   *
   * 典型用途：自动存相册被取消过、或在系统相册里删掉过之后补存。
   *
   * ⚠️ 复用 `autoSaveAlbumBatch` —— 那条链路已经在真机上跑通并修过三轮坑：
   *   `title` 去点号 + 批内去重、20 秒超时（`awaitDialog`）、
   *   **数量不符不按位置硬配**（改逐张）、写字节 + 缓存缩略图 + 记相册索引。
   *   自己另写一份批量存相册等于把这几个坑再踩一遍。
   *   `ready` 传空数组：那是「自动存队列」的结案清单，手动存不碰它。
   * ⚠️ 提交前把这些消息标进 `autoSaveHandled` —— 否则自动存相册那一队
   *   （`autoSavePending`）稍后可能又对它们弹一次框。
   * ⚠️ 与自动存相册**同口径**：内容落到相册后**删掉沙箱副本**（5.0.53 定的）。
   *   所以手动存完之后，文件页里那几条会消失 —— 它们是同一份内容，不是丢失。
   */
  private async batchSaveChatToAlbum(): Promise<void> {
    if (this.chatSelected.length === 0) {
      this.toast('请先选择要保存的图片或视频');
      return;
    }
    const paths: string[] = [];
    const keys: string[] = [];
    let skippedAlbum: number = 0;
    let skippedNone: number = 0;
    let thumbOnly: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (this.chatSelected.indexOf(m.id) < 0) {
        continue;
      }
      if (m.kind !== 'file' || !m.incoming) {
        skippedNone += 1;
        continue;
      }
      const medias: string[] = this.mediaNamesOf(m);
      if (medias.length === 0) {
        skippedNone += 1;
        continue;
      }
      if (this.albumPartOf(m.id, 0, 0).length > 0) {
        skippedAlbum += 1;
        continue;
      }
      // ★ 优先沙箱**原图**；沙箱副本已被删（只剩缓存缩略图）时也能存，但只能存小图
      const raw: string = this.recvPathFor(medias[0], 0, m.timeMs);
      const src: string = raw.length > 0 ? raw : this.mediaSrcOf(m, 0);
      if (src.length === 0) {
        skippedNone += 1;
        continue;
      }
      if (raw.length === 0) {
        thumbOnly += 1;
      }
      // 去重按路径：同一份内容被两条消息指到时只提交一次（重复 title 会让系统少建资产）
      if (paths.indexOf(src) >= 0) {
        continue;
      }
      paths.push(src);
      keys.push(Index.albumKeyOf(m.id, 0));
      this.autoSaveHandled.add(m.id);
    }
    if (paths.length === 0) {
      const why: string = skippedAlbum > 0 ? `（${skippedAlbum} 张已在相册里）` : '';
      this.toast(`选中的消息里没有可存相册的图片/视频${why}`);
      return;
    }
    this.service.logAuto(`手动存相册：提交 ${paths.length} 张`
      + (skippedAlbum > 0 ? `，跳过已在相册的 ${skippedAlbum} 张` : '')
      + (thumbOnly > 0 ? `，其中 ${thumbOnly} 张只剩缓存缩略图（沙箱原图已删）` : '')
      + (skippedNone > 0 ? `，${skippedNone} 条不是可存的媒体` : ''));
    await this.autoSaveAlbumBatch(paths, keys, []);
    this.albumIndex = this.service.albumSnapshot();
    this.exitChatSelect();
  }

  /**
   * 清空聊天记录。
   *
   * ⚠️ 必须连**本地持久化**一起清 —— 否则用户点了「清空」、看着列表空了，
   * 下次启动历史记录又全回来了（vivi 2026-10-01 要求历史记录能保存，
   * 那么「清空」就必须是真正的清空）。
   */
  private async clearChatHistory(): Promise<void> {
    if (this.chat.length === 0) {
      this.toast('暂无聊天记录');
      return;
    }
    const ok: boolean = await this.confirmDialog('清空聊天记录', '删除后无法恢复');
    if (!ok) {
      return;
    }
    this.service.clearChat();
    this.toast('聊天记录已清空');
  }

  /** 打开网页地址二维码（扫一下就能在手机上打开网页端） */
  private openQr(): void {
    if (this.snapshot.webUrl.length === 0) {
      this.toast('地址还没就绪，请先开始共享');
      return;
    }
    this.showQr = true;
  }

  /** 网页地址二维码弹窗 */
  @Builder
  qrDialog() {
    if (this.showQr) {
      Column() {
        Column({ space: 14 }) {
          Text('扫码打开网页端')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor(C_TEXT)
          // ⚠️ `QRCode` 是 ArkUI **内建组件**，不需要 import 也不需要三方库
          //   （`component/qrcode.d.ts`，随 SDK 提供）。
          QRCode(this.snapshot.webUrl)
            .width(220)
            .height(220)
            .color('#111111')
            .backgroundColor(Color.White)
          Text(this.snapshot.webUrl)
            .fontSize(12)
            .fontColor(C_SUB)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.Center)
            .width('100%')
          Button('关闭')
            .fontSize(14)
            .height(38)
            .width('100%')
            .backgroundColor(C_PRIMARY)
            .fontColor(Color.White)
            .onClick(() => {
              this.showQr = false;
            })
        }
        .width('84%')
        .padding(20)
        .backgroundColor(C_CARD)
        .borderRadius(16)
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      .backgroundColor('rgba(0,0,0,0.45)')
      .onClick(() => {
        this.showQr = false;
      })
    }
  }

  /**
   * 危险操作确认框（**自绘**，不是系统 `showDialog`）。
   *
   * 调用写法与 Promise 版完全一致：`const ok = await this.confirmDialog(...)`，
   * 内部把 resolve 存起来，等用户点按钮时再兑现（见 settleConfirm）。
   *
   * @param title  标题 —— **保持短**，长内容一律走 detail
   * @param note   副标题：风险提示之类的一句话
   * @param okText 确认按钮文案
   * @param detail 需要**完整展示**的内容（文件名 / 个数）：单独一块小字，可折行
   * @returns true = 用户点了确认按钮
   */
  private confirmDialog(title: string, note: string,
    okText: string = '删除', detail: string = ''): Promise<boolean> {
    // 上一次还没收尾（用户没点按钮就切走了）：先当「取消」结掉，避免 await 悬挂
    this.settleConfirm(false);
    this.confirmTitle = title;
    this.confirmDetail = detail;
    this.confirmNote = note;
    this.confirmOkText = okText;
    this.confirmVisible = true;
    return new Promise<boolean>((resolve: (v: boolean) => void) => {
      this.confirmResolve = resolve;
    });
  }

  /** 兑现并关闭确认弹窗（按钮 / 点遮罩 / 返回键，三条路都走它） */
  private settleConfirm(ok: boolean): void {
    const r: ((v: boolean) => void) | null = this.confirmResolve;
    this.confirmResolve = null;
    this.confirmVisible = false;
    if (r !== null) {
      r(ok);
    }
  }

  /**
   * 确认弹窗本体。
   *
   * 版式就是冲着「文件名字体过大显示不全」设计的：
   *   - 标题 16fp 固定短文案；
   *   - 文件名单独一块 **13fp**（比标题小一档）小字，浅底圆角与标题分层，
   *     `wordBreak(BREAK_ALL)` + `maxLines(5)` —— 无空格的长英文名 / 哈希名也能折行，
   *     5 行按 13fp 算≈110 个字符，正常文件名不可能再被截；
   *   - 遮罩点击 = 取消（危险操作默认落在安全侧）。
   */
  @Builder
  confirmDialogView() {
    if (this.confirmVisible) {
      Column() {
        Column({ space: 12 }) {
          Text(this.confirmTitle)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor(C_TEXT)
            .width('100%')

          if (this.confirmDetail.length > 0) {
            Text(this.confirmDetail)
              .fontSize(13)
              .fontColor(C_TEXT)
              .width('100%')
              .wordBreak(WordBreak.BREAK_ALL)
              .maxLines(5)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .textAlign(TextAlign.Start)
              .padding(10)
              .backgroundColor('#F5F6F8')
              .borderRadius(8)
          }

          if (this.confirmNote.length > 0) {
            Text(this.confirmNote)
              .fontSize(12)
              .fontColor(C_SUB)
              .width('100%')
          }

          Row({ space: 10 }) {
            Button('取消')
              .fontSize(14)
              .height(38)
              .layoutWeight(1)
              .backgroundColor('#F2F2F2')
              .fontColor('#666666')
              .onClick(() => this.settleConfirm(false))
            Button(this.confirmOkText)
              .fontSize(14)
              .height(38)
              .layoutWeight(1)
              .backgroundColor('#FDECEA')
              .fontColor('#E84026')
              .onClick(() => this.settleConfirm(true))
          }
          .width('100%')
          .margin({ top: 2 })
        }
        .width('84%')
        .padding(20)
        .backgroundColor(C_CARD)
        .borderRadius(16)
        // 空 onClick：把落在卡片空白处的点击「吃掉」，免得冒泡到遮罩变成取消
        .onClick(() => {
        })
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      .backgroundColor('rgba(0,0,0,0.45)')
      .onClick(() => this.settleConfirm(false))
    }
  }

  // ------------------------------------------------------------------
  // 接收到的图片：缩略图 + 全屏预览
  // ------------------------------------------------------------------

  /**
   * 文件名是不是 `Image` 能直接渲染的图片（按扩展名判断）。
   *
   * 为什么按扩展名而不是按内容嗅探：接收链路**保留了原始文件名**，
   * 而按内容嗅探要么先读文件头（40 行 = 40 次 IO），要么引入解码失败路径，
   * 收益不抵成本。后缀对不上顶多是不显示缩略图，不会出错。
   */
  private isImageName(name: string): boolean {
    // ★ 5.1.48：统一走 LanService.extOf —— 它会先剥掉 ` (n)` 复制后缀，
    //   否则 `扫描全能王 2026-10-01 09.47.jpg (1)` 取到 `jpg (1)` 判不出图片。
    const ext: string = LanService.extOf(name);
    if (ext.length === 0) {
      return false;
    }
    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'
      || ext === 'webp' || ext === 'bmp' || ext === 'heic' || ext === 'heif'
      || ext === 'avif' || ext === 'ico' || ext === 'tif' || ext === 'tiff';
  }

  /**
   * 文件名是不是**视频**（按扩展名判断，理由同 `isImageName`）。
   * 这张表管两件事：① 要不要解首帧缩略图；② 点击时进播放器还是进图片预览。
   * 解不出首帧（编码不支持）不影响播放 —— 缩略图那步失败只是留个灰色占位。
   */
  private isVideoName(name: string): boolean {
    const ext: string = LanService.extOf(name);   // ★ 5.1.48 同 isImageName
    if (ext.length === 0) {
      return false;
    }
    return ext === 'mp4' || ext === 'mov' || ext === 'mkv' || ext === 'webm'
      || ext === 'avi' || ext === '3gp' || ext === 'm4v' || ext === 'ts'
      || ext === 'flv' || ext === 'wmv' || ext === 'rmvb' || ext === 'mpg'
      || ext === 'mpeg' || ext === 'ogv';
  }

  /**
   * 图片 or 视频 —— 「能在 App 内直接打开」的那一类。
   *
   * ★ 5.0.53：改为**委托** `LanService.isMediaFileName`（唯一真源）——
   *   它决定「接收时拆不拆成每张一条消息」，这里决定「显不显示缩略图」，
   *   两边一旦不一致就会出现「拆了却没缩略图」或「没拆却有缩略图」的错位。
   */
  private isMediaName(name: string): boolean {
    return LanService.isMediaFileName(name);
  }

  /**
   * 沙箱路径 → 可直接喂给 `Image` 的 `file://` URI。
   *
   * ⚠️ **不能自己拼 `'file://' + path`**：沙箱 URI 的规范形态是
   *    `file://<bundleName>/<绝对路径>`，中间那段 bundleName 只有
   *    `fileUri.getUriFromPath()` 知道怎么补。手拼的地址 `Image` 认不出来，
   *    症状是缩略图恒定空白、也不报错。
   *    取不到时才退回手拼（老形态），聊胜于无。
   */
  private imageUri(path: string): string {
    try {
      return fileUri.getUriFromPath(path);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `取图片 URI 失败: ${err.code} ${path}`);
      return `file://${path}`;
    }
  }

  /**
   * 点开一个**媒体**文件（图片 / 视频）：进全屏预览。
   *
   * ⚠️ 入参是 `(path, name)` 而不是 `ReceivedFile`：消息页的气泡手里只有一个路径，
   *    造不出 `ReceivedFile`（那是「文件」页列表的模型）。
   * ⚠️ 由**扩展名**决定进哪套渲染（`imgPreviewVideo`），不靠调用方传类型 ——
   *    消息页和文件页两个调用点都不用改。
   */
  private openMediaPreview(path: string, name: string, key: string = ''): void {
    this.openMediaGallery([path], [name], 0, [key]);
  }

  /**
   * 5.0.31：打开一批媒体（>=1 个），从第 `index` 张开始看。
   *
   * ⚠️ 单张时也走这里 —— 只是长度为 1，画廊不启用 Swiper，行为与 5.0.30 完全一致，
   *    已验证过的「单图缩放预览」那条路径一个字都没动。
   * ⚠️ 视频也要顺手预热首帧：画廊里非当前页是靠首帧当占位图的。
   */
  private openMediaGallery(paths: string[], names: string[], index: number,
                           keys: string[] = []): void {
    if (paths.length === 0) {
      return;
    }
    this.galleryPaths = paths;
    this.galleryNames = names;
    this.galleryKeys = keys;
    let at: number = index < 0 ? 0 : index;
    if (at >= paths.length) {
      at = paths.length - 1;
    }
    this.galleryIndex = at;
    this.imgPreviewKey = this.galleryKeyAt(at);
    for (let i = 0; i < paths.length; i++) {
      if (this.isVideoName(this.galleryNameAt(i))) {
        this.ensureVideoThumb(paths[i]);
      }
    }
    this.imgPreview = paths[at];
    this.imgPreviewName = this.galleryNameAt(at);
    // 一个路径，两套渲染 —— 靠这个标记分流
    this.imgPreviewVideo = this.isVideoName(this.imgPreviewName);
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
  }

  /** 画廊翻页：停掉上一个视频、换当前项、复位缩放 */
  private onGalleryPageChanged(idx: number): void {
    if (idx === this.galleryIndex || idx < 0 || idx >= this.galleryPaths.length) {
      return;
    }
    try {
      this.videoCtl.stop();
    } catch (e) {
      // 没在播放时 stop 会抛，忽略
    }
    this.galleryIndex = idx;
    this.imgPreviewKey = this.galleryKeyAt(idx);
    this.imgPreview = this.galleryPaths[idx];
    this.imgPreviewName = this.galleryNameAt(idx);
    this.imgPreviewVideo = this.isVideoName(this.imgPreviewName);
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
  }

  /**
   * ★ 5.0.52：画廊第 i 页对应的**相册 key**。
   * 越界 / 来自「文件」页（没有 key）时给空串 = 该页不写相册索引。
   */
  private galleryKeyAt(i: number): string {
    return i >= 0 && i < this.galleryKeys.length ? this.galleryKeys[i] : '';
  }

  /** 画廊第 i 项的显示名（越界时退回当前项） */
  private galleryNameAt(i: number): string {
    if (i >= 0 && i < this.galleryNames.length && this.galleryNames[i].length > 0) {
      return this.galleryNames[i];
    }
    if (i >= 0 && i < this.galleryPaths.length) {
      return Index.baseName(this.galleryPaths[i]);
    }
    return this.imgPreviewName;
  }

  /**
   * 消息气泡：打开这一批（从第 index 张看起）。
   *
   * ★ 5.0.52：改两处 ——
   *  ① 源的顺序按**消息里的媒体序号**取（`mediaSrcOf`），沙箱副本被删的那些
   *     自动换成**这一张自己的**缓存缩略图，下标不再塌缩；
   *  ② 每页带上自己的相册 key，于是画廊里「存相册」永远写的是当前这一张。
   *
   * @returns true = 真的打开了（有至少一个可显示的源）
   */
  private openChatGallery(id: string, index: number): boolean {
    const m: ChatMessage | undefined = this.msgById(id);
    if (m === undefined) {
      return false;
    }
    const medias: string[] = this.mediaNamesOf(m);
    const srcs: string[] = [];
    const keys: string[] = [];
    const disp: string[] = [];
    for (let k: number = 0; k < medias.length; k++) {
      const s: string = this.mediaSrcOf(m, k);
      if (s.length === 0) {
        continue;
      }
      srcs.push(s);
      keys.push(Index.albumKeyOf(id, k));
      disp.push(medias[k]);
    }
    if (srcs.length === 0) {
      return false;
    }
    this.openMediaGallery(srcs, disp, index, keys);
    return true;
  }

  /**
   * 「文件」页：点一张图/视频时，把**整个列表里的媒体**都装进画廊，
   * 从点中那一项开始看 —— 收到一批图时同样是左右滑。
   */
  private openFileGallery(f: ReceivedFile): void {
    const paths: string[] = [];
    const names: string[] = [];
    let at: number = 0;
    for (let i = 0; i < this.receivedFiles.length; i++) {
      const g: ReceivedFile = this.receivedFiles[i];
      if (!this.isMediaName(g.name)) {
        continue;
      }
      if (g.path === f.path) {
        at = paths.length;
      }
      paths.push(g.path);
      names.push(g.name);
    }
    if (paths.length === 0) {
      this.openMediaPreview(f.path, f.name);
      return;
    }
    // ★ 5.0.52：这里**不传** keys —— 文件页的图不属于任何消息，绝不能写相册索引。
    //   （5.0.51 之前「当前预览对应的消息 id」在文件页不会被复位，于是文件页
    //    「存相册」会把无关的图写到上一条消息的相册条目上。）
    this.openMediaGallery(paths, names, at);
  }

  /**
   * 量一张图的真实宽高比（**只读头信息，不解码**）。
   *
   * ⚠️ 视频不走这里：它的比例从解出来的首帧 PixelMap 上取（见 decodeVideoThumb），
   *    `createImageSource` 喂 mp4 只会抛错。
   */
  private async ensureMediaRatio(path: string): Promise<void> {
    if (path.length === 0 || this.mediaRatio.has(path) || this.mediaRatioBusy.has(path)) {
      return;
    }
    if (this.isVideoName(path)) {
      return;
    }
    this.mediaRatioBusy.add(path);
    try {
      const src: image.ImageSource = image.createImageSource(path);
      // 5.0.40：先问 EXIF 要不要转。`getImageProperty` 只有异步版，
      //         这也是本方法从同步改成 async 的唯一原因。
      let deg: number = 0;
      try {
        const ori: string = await src.getImageProperty(image.PropertyKey.ORIENTATION);
        deg = Index.exifDeg(ori);
      } catch (x) {
        // 没 EXIF / 这个格式不支持读 EXIF —— 按"不转"处理，退回老行为
        deg = 0;
      }
      const info: image.ImageInfo = src.getImageInfoSync(0);
      let w: number = info.size.width;
      let h: number = info.size.height;
      // ⚠️ 框按「Image 转完之后」的宽高算：Image 会自己按 EXIF 把内容转正，
      //    但 getImageInfoSync 给的是**没转**的原始像素尺寸 -> 90/270 时必须交换
      if (Index.isQuarter(deg)) {
        const t: number = w;
        w = h;
        h = t;
      }
      if (w > 0 && h > 0) {
        this.mediaRatio.set(path, Index.clampRatio(w / h));
        this.thumbTick++;
      }
      // 5.0.50：**不能 await** —— `release()` 的 Promise 在异常态可能永不 settle，
      //   await 会让本方法挂住、并钉死调用链。`.catch()` 同样接住异步 rejection
      //   （5.0.49 的闪退防护不丢），但不阻塞流程。
      src.release().catch(() => {
        // 释放失败不影响显示
      });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `读图片尺寸失败: ${err.code} ${path}`);
    } finally {
      this.mediaRatioBusy.delete(path);
    }
  }

  /** 缩略图框宽：最长边 = maxSide，按原图比例算 */
  private thumbW(path: string, maxSide: number): number {
    const r: number = this.ratioOf(path);
    return r >= 1 ? maxSide : Math.round(maxSide * r);
  }

  /** 缩略图框高：最长边 = maxSide，按原图比例算 */
  private thumbH(path: string, maxSide: number): number {
    const r: number = this.ratioOf(path);
    return r >= 1 ? Math.round(maxSide / r) : maxSide;
  }

  /**
   * 5.0.41：这张图该用什么显示方向。
   *
   * - 表里**没有**记录 -> `AUTO`：交给 Image 按 EXIF 自己转（沙箱原图走这条）；
   * - 记录为 0 -> `UP`：缓存小图的像素**已经物理转正**了，这里强制不转，
   *   防止 pack 万一写回 EXIF 时 Image 又转一遍；
   * - 记录为 90/180/270 -> `RIGHT/DOWN/LEFT`：物理旋转没生效，显示层补一刀。
   *
   * ⚠️ 两条路互斥，`cacheThumb()` 里用「宽高有没有真的翻转」判定走哪条，
   *    绝不叠加。
   */
  private thumbOri(path: string): ImageRotateOrientation {
    // 5.0.44：先从 service 持久化的 rot 表里查；没有才按「沙箱原图 / 旧缓存」老规则走 AUTO。
    const v: number | undefined = this.service.rotOf(path);
    // undefined = 沙箱原图；-1 = 原图拷贝兜底（5.0.42，见 cacheThumb）—— 两者**都带 EXIF**，
    // 让 Image 自己读 EXIF 转，我们再显式给角度就是转两遍。
    if (v === undefined || v === -1) {
      return ImageRotateOrientation.AUTO;
    }
    if (v === 90) {
      return ImageRotateOrientation.RIGHT;
    }
    if (v === 180) {
      return ImageRotateOrientation.DOWN;
    }
    if (v === 270) {
      return ImageRotateOrientation.LEFT;
    }
    return ImageRotateOrientation.UP;
  }

  /**
   * 这条路径的宽高比（量不到就按 1 = 正方形）。
   *
   * ⚠️ 读一下 `thumbTick` 是为了**建立 @State 依赖**：比例是异步量出来的，
   *    不建立依赖的话框尺寸永远停在首次渲染的正方形。
   */
  private ratioOf(path: string): number {
    if (this.thumbTick < 0) {
      return 1;
    }
    // 5.0.34：渲染时按原图比例算框，比例还没量到就**按需**触发一次测量
    // （只读头信息，不解码，很轻；busy/Map 去重保证只触发一次）。放在这里是因为
    // `ratioOf` 是表达式上下文调用，合法；而 @Builder 顶层不能直接写方法调用语句。
    if (!this.mediaRatio.has(path) && !this.isVideoName(path)) {
      // 5.0.40：`ensureMediaRatio` 改 async 了（要 await 读 EXIF）。
      //         这里故意**不 await** —— 比例是异步量出来的，量到之后 `thumbTick++`
      //         会把重绘踢起来；同步等反而会卡住渲染。内部已全 try/catch，不会抛。
      void this.ensureMediaRatio(path);
    }
    const v: number | undefined = this.mediaRatio.get(path);
    return v === undefined ? 1 : v;
  }

  /** 极端长图 / 全景图别把框拉成一条线；夹到 [0.45, 2.2]（约 9:20 ~ 22:10） */
  private static clampRatio(r: number): number {
    if (r > 2.2) {
      return 2.2;
    }
    if (r < 0.45) {
      return 0.45;
    }
    return r;
  }

  /**
   * EXIF orientation -> 需要**顺时针**旋转的角度（度）。
   *
   * 相机拍的照片像素是"躺着"存的，靠 EXIF 的 Orientation 标记告诉观看者转多少度：
   *   1 不转 / 2 水平镜像 / 3 转 180° / 4 垂直镜像
   *   5 镜像后顺时针 270° / 6 顺时针 90° / 7 镜像后顺时针 90° / 8 顺时针 270°
   *
   * ⚠️ 镜像（2/4/5/7 里的镜像那一步）**放弃还原**：手机拍出来的照片几乎只会用到
   *    1/3/6/8，前置摄像头自拍偶有镜像，为它引入翻转逻辑不值当；
   *    这里只还原"旋转"那一部分（5 -> 270、7 -> 90）。
   *
   * ⚠️ `getImageProperty` 拿不到 EXIF 时会抛错（62980123 不支持 EXIF 解码）或返回
   *    `Unknown Value x`，本函数对任何非预期输入都返回 0（= 不转），安全降级。
   */
  private static exifDeg(ori: string): number {
    if (ori.length === 0) {
      return 0;
    }
    // ① 语义串：部分版本/设备返回 'Right-top' 这种（华为官方 FAQ 示例就是比这个）
    if (ori === 'Bottom-right') {
      return 180;
    }
    if (ori === 'Right-top' || ori === 'Right-bottom') {
      return 90;
    }
    if (ori === 'Left-top' || ori === 'Left-bottom') {
      return 270;
    }
    if (ori === 'Top-left' || ori === 'Top-right' || ori === 'Bottom-left') {
      return 0;
    }
    // ② 数字：'6'，以及读不到时官方返回的 'Unknown Value 6' —— 一律取串里第一个数字
    return Index.exifDegFromText(ori);
  }

  /** 从 `'6'` / `'Unknown Value 6'` 这类文本里取出方向数字再换算角度 */
  private static exifDegFromText(ori: string): number {
    let n: number = -1;
    for (let i: number = 0; i < ori.length; i++) {
      const code: number = ori.charCodeAt(i);
      if (code >= 48 && code <= 57) {
        n = code - 48;
        break;
      }
    }
    if (n === 3) {
      return 180;
    }
    if (n === 6 || n === 7) {
      return 90;
    }
    if (n === 5 || n === 8) {
      return 270;
    }
    return 0;
  }
  /**
   * 5.0.42：自己从 JPEG 的字节里读 EXIF Orientation。
   *
   * 为什么不再只信系统 `getImageProperty(ORIENTATION)`：它返回的东西各版本/各设备不统一
   * （'6' / 'Unknown Value 6' / 'Right-top' 都见过），一旦对不上就退化成 0（= 不转），
   * 5.0.40 / 5.0.41 两版都栽在这上面。而 EXIF 放在 JPEG 的哪个段里是**标准规定的**，
   * 直接读字节跟设备实现无关。
   *
   * @returns 需要顺时针旋转的度数（0 / 90 / 180 / 270）；不是 JPEG 或没 EXIF 一律返回 0。
   */
  private static jpegExifDeg(path: string): number {
    let f: fileIo.File | null = null;
    try {
      f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
      // EXIF 一定在 JPEG 头部的 APP1 段里，读 128K 足够（有些机器把缩略图也塞进来）
      const head: ArrayBuffer = new ArrayBuffer(131072);
      const n: number = fileIo.readSync(f.fd, head);
      if (n < 4) {
        return 0;
      }
      const b: Uint8Array = new Uint8Array(head, 0, n);
      if (b[0] !== 0xFF || b[1] !== 0xD8) {
        return 0; // 不是 JPEG（HEIC / PNG 之类）—— 交给系统 API 那一路
      }
      let i: number = 2;
      while (i + 4 <= n) {
        if (b[i] !== 0xFF) {
          i = i + 1;
          continue;
        }
        const mk: number = b[i + 1];
        if (mk === 0xD8 || mk === 0x01 || (mk >= 0xD0 && mk <= 0xD7)) {
          i = i + 2; // 这些标记不带长度字段
          continue;
        }
        if (mk === 0xDA) {
          break; // SOS：图像数据开始了，EXIF 只可能在它之前
        }
        const segLen: number = (b[i + 2] << 8) | b[i + 3];
        if (mk === 0xE1) {
          // APP1：payload 以 "Exif\0\0" 开头的才是 EXIF（别的 APP1 比如 XMP 不是）
          const p: number = i + 4;
          if (p + 12 <= n && b[p] === 0x45 && b[p + 1] === 0x78 && b[p + 2] === 0x69 &&
              b[p + 3] === 0x66 && b[p + 4] === 0x00 && b[p + 5] === 0x00) {
            return Index.tiffDeg(b, p + 6, n);
          }
        }
        if (segLen < 2) {
          break;
        }
        i = i + 2 + segLen;
      }
      return 0;
    } catch (e) {
      return 0;
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  /** 从 EXIF 的 TIFF 头里找出 IFD0 的 Orientation（tag 0x0112） */
  private static tiffDeg(b: Uint8Array, tiff: number, n: number): number {
    if (tiff + 8 > n) {
      return 0;
    }
    const le: boolean = (b[tiff] === 0x49 && b[tiff + 1] === 0x49); // 'II' 小端
    const be: boolean = (b[tiff] === 0x4D && b[tiff + 1] === 0x4D); // 'MM' 大端
    if (!le && !be) {
      return 0;
    }
    const ifd: number = tiff + Index.u32(b, tiff + 4, le);
    if (ifd < 0 || ifd + 2 > n) {
      return 0;
    }
    const cnt: number = Index.u16(b, ifd, le);
    for (let k: number = 0; k < cnt; k++) {
      const e: number = ifd + 2 + k * 12;
      if (e + 12 > n) {
        break;
      }
      if (Index.u16(b, e, le) === 0x0112) {
        // tag = Orientation。type 是 SHORT 时值就塞在 value 字段里，取低 16 位即可
        return Index.degOfOri(Index.u16(b, e + 8, le));
      }
    }
    return 0;
  }

  /** 按字节序读 16 位无符号 */
  private static u16(b: Uint8Array, o: number, le: boolean): number {
    return le ? (b[o] | (b[o + 1] << 8)) : ((b[o] << 8) | b[o + 1]);
  }

  /** 按字节序读 32 位无符号 */
  private static u32(b: Uint8Array, o: number, le: boolean): number {
    return le ? ((b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0)
      : (((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0);
  }

  /** EXIF Orientation -> 需要顺时针转多少度（2/4/5/7 带镜像，这里只还原旋转那部分） */
  private static degOfOri(v: number): number {
    if (v === 3 || v === 4) {
      return 180;
    }
    if (v === 6 || v === 7) {
      return 90;
    }
    if (v === 5 || v === 8) {
      return 270;
    }
    return 0;
  }


  /** 这个角度会不会让宽高互换（只有 90°/270° 会，180° 不会） */
  private static isQuarter(deg: number): boolean {
    return deg === 90 || deg === 270;
  }

  /** 绝对路径 -> 文件名 */
  private static baseName(path: string): string {
    const s: number = path.lastIndexOf('/');
    return s >= 0 ? path.substring(s + 1) : path;
  }

  /** 绝对路径 -> 文件 URI（图片/视频预览都吃这个，手拼 file:// 播不出来） */
  static fileUriOf(path: string): string {
    try {
      return fileUri.getUriFromPath(path);
    } catch (e) {
      return `file://${path}`;
    }
  }

  /** `ChatMessage.files` 的 '
' 分隔还原成数组（文件名里不会有换行） */
  private static splitFileNames(s: string): string[] {
    const out: string[] = [];
    let cur: string = '';
    for (let i = 0; i < s.length; i++) {
      const c: string = s.charAt(i);
      if (c === '\n') {
        if (cur.length > 0) {
          out.push(cur);
        }
        cur = '';
      } else {
        cur += c;
      }
    }
    if (cur.length > 0) {
      out.push(cur);
    }
    return out;
  }

  /** 这条消息那一批媒体的路径（空数组 = 不是媒体 / 还没落盘） */
  private mediaPathsOf(id: string): string[] {
    const v: string[] | undefined = this.chatMediaGroups.get(id);
    return v === undefined ? [] : v;
  }

  private mediaCountOf(id: string): number {
    return this.mediaPathsOf(id).length;
  }

  /** 第 i 个媒体的路径（越界给空串，调用方按「没有缩略图」处理） */
  private mediaPathAt(id: string, i: number): string {
    const v: string[] = this.mediaPathsOf(id);
    return i >= 0 && i < v.length ? v[i] : '';
  }

  /** 气泡底部那行提示：消息页只显示文件名、点击跳「文件」页，统一成「点击查看 ›」 */
  /**
   * 气泡底部的提示文案（**两个分支等宽**，见 5.0.70 的说明）。
   *
   * ★★★ 5.0.70：这里返回的字符串**长度必须相同**。
   *
   * 【为什么】存相册会让 `albumPartOf(m.id,0,0)` 从空变成有 uri ⇒ 本方法返回
   *   '点击查看' -> '已存入相册，点击查看'（5.0.74 改成用户指定口径）。
   *   它被渲染在**两处**消息页 UI（宫格气泡底部、单张气泡底部），两处容器都是
   *   `constraintSize({ maxWidth: '92%' })` —— **是上限、不是固定宽**
   *   ⇒ 宽度由内容决定 ⇒ **文案变长 ⇒ 整行重排 ⇒ 视觉上「闪一下」**。
   *
   * 【为什么不能只改措辞】中文字形宽度不同、字体渲染有像素差 ⇒ 改措辞只能
   *   「减小概率」，治不干净。5.0.63/64/67/69 连着四轮都改在**缩略图层**
   *   （key / 预生成 / TRUNC / @State 降级），而 5.0.68 诊断日志证明缩略图
   *   `src` 签名**从存相册前到后一字未变** ⇒ 全都不对症。
   *   ⇒ 只有**结构上等宽**才是一次性的根治。
   *
   * 【为什么不能跳过 `albumIndex` 的换引用】`albumIndex` 是**有真消费者的**
   *   `@State`（气泡文案 / 缩略图源 / 已删角标都经 `albumPartOf` 读它），
   *   换引用躲不掉；既然躲不掉，就让**被它驱动的内容宽度恒定**。
   *
   * ⚠️ 用**半角空格**（U+0020）补齐：全角空格（U+3000）宽度是全角的，会补过头；
   *   也不用零宽字符（U+200B）—— 部分渲染引擎处理不一致，反而引入新的不确定性。
   * ⚠️ 补齐发生在**文案尾部**，视觉上就是「后面多个空格」，看不出差别。
   */
  /**
   * ★ 5.0.75：宫格气泡用的提示文案 —— 判据是「**整组任一张已存入相册**」。
   *
   * 【为什么不能用 `bubbleHintOf(g.msgs[0])`】（5.0.75 修的真 bug）
   *   存相册是**逐张**进行的（`autoSaveAlbumBatch` 循环里一张一张 `setAlbumIndex`），
   *   **很可能第 3 张、第 7 张先被存上，而 `msgs[0]` 那一批还没存**
   *   ⇒ 只看第 1 张的话，判据恒为「未存」⇒ 文案永远停在「点击查看」，
   *   用户反馈「已存入相册也没有」就是这个。
   *   ⚠️ 与「已删」角标必须**逐张**判定（`mediaGoneFromAlbum(m, k)`）是同一个道理，
   *   我却在文案上偷懒只看 `msgs[0]`。
   *
   * 【判据】
   *   任一张 `albumPartOf(msg.id, 0, 0)` 非空 ⇒ 整组按「已存」处理。
   *   这样只要用户存了其中一张，提示就切到「已存入相册」，与用户直觉一致。
   */
  private bubbleHintOfGroup(g: ChatGroup): string {
    // ★ 5.0.76（vivi 20:30 定稿）：三个分支，且**判据按优先级**
    //   1) 任一张**已删除**（存过又被删）  => `已删除`
    //   2) 任一张**已存**（有 uri）      => `已存入相册`
    //   3) 否则（都没存过）               => `长按存入相册`
    // ⚠️ 「已删除」必须**排在最前**：存过又被删之后 uri 已被清掉（5.0.75 的
    //   `probeAlbumOnEnterChat`），此时 part 0 为空，与「从没存过」**无法区分**
    //   ⇒ 只看 uri 会把「全删了」误报成「长按保存到相册」（vivi 20:30 反馈）。
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.mediaGoneFromAlbum(g.msgs[i], 0)) {
        return this.padHint(Index.HINT_GONE);
      }
    }
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (this.albumPartOf(g.msgs[i].id, 0, 0).length > 0) {
        return this.padHint(Index.HINT_IN_ALBUM);
      }
    }
    return this.padHint(Index.HINT_NOT_YET);
  }

  /**
   * ★ 5.1.11：按**路径**批量记账（批量删除 / 清空 / 批量另存用）。
   *
   * ⚠️ **必须在 `refreshReceived()` 之前调用** —— 那些入口删完文件才调 refresh，
   *   而 `receivedFiles` 是**刷新前**的旧值，**恰好还留着「路径 → 文件名」的映射**。
   *   刷新之后映射就没了 ⇒ 拿不到名字 ⇒ 记不上账。
   *
   * ⚠️ 与 `markMessagesLocal` 的区别：那个按**文件名**查（单条入口手里是 `ReceivedFile`），
   *   这个按**路径**查（批量入口手里只有路径数组）。
   *   两者最终都走同一条消息匹配逻辑（`msgCarriesFileName`）。
   */
  private markMessagesLocalByPaths(paths: string[], state: string): void {
    if (paths.length === 0 || state.length === 0) {
      return;
    }
    for (let i: number = 0; i < paths.length; i++) {
      const p: string = paths[i];
      let name: string = Index.baseName(p);
      if (name.length === 0) {
        continue;
      }
      // 优先用 receivedFiles 里的原始名（可能带去重后缀，与消息里的完全一致）
      for (let k: number = 0; k < this.receivedFiles.length; k++) {
        if (this.receivedFiles[k].path === p) {
          name = this.receivedFiles[k].name;
          break;
        }
      }
      this.markMessagesLocal(name, state);
    }
  }

  /**
   * ★ 5.1.2：按**文件名**反查消息 id 并批量写本地落地状态。
   *
   * ⚠️ **为什么只能按名字反查、不能拿消息对象**：文件页的按钮拿到的是
   *   `ReceivedFile`，与 `ChatMessage` **没有共享引用**（5.0.55 的
   *   「显示聚合 ≠ 记账聚合」决定了不能顺着 UI 把消息传下去）。
   *
   * ⚠️ **同名多份怎么办**：本项目的既有口径是「**时间就近**」
   *   （`recvPathFor` 对多候选按 `|f.time - msg.timeMs|` 排序取最近的那个）——
   *   记账必须与它**保持一致**，否则会出现「气泡 A 显示已存、实际存的是气泡 B 那份」。
   *   所以这里对每个同名消息各记一笔（而不是只记一个），
   *   保证「凡是同名的那批，状态都对得上」。
   *
   * ⚠️ **一次可能记多条**：一个文件名可能对应多条消息（重名 / 去重后缀），
   *   全部记上才不会漏。
   */
  private markMessagesLocal(fileName: string, state: string): void {
    if (fileName.length === 0 || state.length === 0) {
      return;
    }
    const bare: string = Index.stripDedupeSuffix(fileName);
    let hit: number = 0;
    for (let i: number = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (m.kind !== 'file' || !m.incoming) {
        continue;
      }
      // ★★ 5.1.3 修：文件名在 **`m.files`** 里，不在 `m.content`。
      //   `appendFileChat` 的非媒体分支（LanService.ets:2234）是
      //   `appendChat(..., label, ..., names.join('\n'))`  —— label 是「N 个文件」那句文案
      //   ⇒ `content` 里根本没有文件名，只有 `files` 才有（换行分隔）。
      //   v5.1.2 误用 `content` ⇒ 多发 zip 时**永远匹配不上**、状态永远不写，
      //   而**编译完全通过、单发 zip 还能对上** ⇒ 极难发现（「1 个不触发、多个才触发」）。
      //   ⚠️ 必须**逐行**比：多发时 `files` 里有多行，`content` 只是那句 label。
      if (this.msgCarriesFileName(m, fileName, bare)) {
        this.service.markLocalState(m.id, state);
        hit += 1;
      }
    }
    if (hit > 0) {
      // ★ 5.1.5：换掉 5.1.2 那句 `swapAlbumIndex()` —— **它换的是 `albumIndex`，
      //   与 `localMap` 毫无依赖关系** ⇒ 那一格照样不重建 ⇒ 状态写了看不见。
      //   现在改为 `localStateTick++`：它是 `bubbleFooterText` **真正在读的** @State
      //   ⇒ ++ 之后那一格重建 ⇒ 提示重新求值。
      //   ⚠️ 走换引用闸门：与其它 @State 落地合并成**一次**重渲染，
      //   否则「记 N 条消息」会触发 N 次重渲染。
      if (this.stateSwapDepth > 0) {
        this.localStateTickNext += 1;
      } else {
        this.localStateTick += 1;
      }
      this.service.logAuto(`[5.1.5] 记本地状态 ${state}：${fileName} 命中 ${hit} 条消息`);
    }
  }

  /**
   * ★ 5.1.3：这条消息里**是否带了这个文件名**。
   *
   * ⚠️ **看 `files` 字段，不看 `content`** —— `appendFileChat` 的非媒体分支是
   *   `appendChat(..., label, ..., names.join('\n'))`，label 就是「N 个文件」那句：
   *   `content` = 合并后的文案（**不含文件名**），`files` = 全部文件名（`\n` 分隔）。
   *   v5.1.2 拿 `content` 比 ⇒ 多发时必失效（编译却完全通过）。
   *
   * 两处都查（`files` 为主、`content` 兜底）：
   *   - `files` 逐行：单发 = 1 行、多发 = N 行
   *   - `content` 兜底：**媒体批**的消息 `content` 与 `files` 同值（各带自己那个名字），
   *     虽然非媒体用不到，但留着零成本，且能兼容历史数据/将来新增的消息形态。
   */
  private msgCarriesFileName(m: ChatMessage, fileName: string, bare: string): boolean {
    if (m.files.length > 0) {
      const rows: string[] = m.files.split('\n');
      for (let i: number = 0; i < rows.length; i++) {
        const n: string = rows[i];
        if (n === fileName || Index.stripDedupeSuffix(n) === bare) {
          return true;
        }
      }
    }
    return m.content === fileName || Index.stripDedupeSuffix(m.content) === bare;
  }

  /**
   * ★ 5.1.1：气泡底部**整行**提示。
   *
   * 媒体 ⇒ `N 张/个 · <相册状态>`（与宫格同款）
   * 非媒体 ⇒ 只有 `点击查看`（**不带「N 张」** —— zip/pdf/apk 没有「张」的概念，
   *   而且 5.1.1 之前那行是 `1 张 · 长按存入相册`，两个词都是错的）
   */
  private bubbleFooterText(m: ChatMessage, mediaPath: string): string {
    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      // ★ 5.1.2：非媒体的三态 —— 点击查看 / 已存入本地 / 已删除。
      //   ⚠️ 顺序固定：先「有没有动过」，再落到具体状态。
      //   ⚠️ 这三条互斥（一个 Map key 一个值），所以 if/else 链即可。
      //
      // ★★ 5.1.5：这里的 `tick` 是**故意传给 padHint 的**，作用只有一个 ——
      //   **建立 @State 依赖**。`localStateOf` 读的是服务端**普通 Map**（非 @State），
      //   而本分支原本**不读任何 @State** ⇒ 记账后这一格不重建 ⇒
      //   提示永远停在「点击查看」（5.0.71 → 5.0.72 踩过同一个坑）。
      //   ⚠️ `padHint` **不用它拼返回值**（拼进去会因改文案而销毁重建三态文本）。
      const tick: number = this.localStateTick;
      const st: string = this.service.localStateOf(m.id);
      if (st.length > 0) {
        return this.padHint(st, tick);
      }
      return this.padHint(Index.HINT_FILE, tick);
    }
    return `${this.bubbleCountText(m)} · ${this.bubbleHintOf(m, mediaPath)}`;
  }

  private bubbleHintOf(m: ChatMessage, mediaPath: string): string {
    // 5.0.39：已经在相册里了，就明确告诉用户「点一下是去相册」
    // ★ 5.0.74（vivi 20:11 指定口径）：已存 → 「已存入相册，点击查看」
    //   ⚠️ 仍**必须等宽**（5.0.70 的规矩）：两句字数不同 ⇒ 短的补半角空格，
    //     否则存相册瞬间又会重排闪一下。
    // ★ 5.0.75（vivi 20:19 定稿）：未存那句补上「长按」——
    //   用户是**长按**存相册的（不是自动弹框），文案要如实反映操作方式。
    // ★★ 5.0.76：**判据在这里** —— 5.0.74 整段重写时把它弄丢了，
    //   导致单张气泡无论存没存都显示「长按保存到相册，点击查看」（vivi 20:30 反馈）。
    // ⚠️ 教训：整段重写容易只抄「长相」漏抄「判据」—— 编译能过、行为静默错误。
    //   所以「整段重写」之后必须**回读被改方法的每一行**，而不只看新写的部分。
    //
    // ★★ 5.1.1：这里原本**只有相册状态三维、没有「是不是媒体」这一维** ⇒
    //   非媒体文件（zip/pdf/apk）必然落到「未存」分支 ⇒ 显示「长按存入相册」
    //   （vivi 20:58 反馈）。而 5.0.77 单张并入宫格后，`chatFileBubble`
    //   这条路**只剩非媒体**，所以是 100% 必现。
    //   ⇒ 判据必须**先问「是不是媒体」**，再问相册状态。
    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      return this.padHint(Index.HINT_FILE);
    }
    if (this.mediaGoneFromAlbum(m, 0)) {
      return this.padHint(Index.HINT_GONE);
    }
    if (this.albumPartOf(m.id, 0, 0).length > 0) {
      return this.padHint(Index.HINT_IN_ALBUM);
    }
    return this.padHint(Index.HINT_NOT_YET);
  }

  /**
   * ★ 5.0.76：把提示文案**补齐到同一宽度**（5.0.70 立的规矩，必须一直守住）。
   *
   * ⚠️ 存相册那一刻 uri 从无变有 ⇒ 文案从「长按存入相册」切到「已存入相册」，
   *   两者字数不同 ⇒ 若不补齐就会**整行重排 ⇒ 闪一下**（5.0.70~5.0.75 反复踩过）。
   *   三个分支（含「已删除」）统一按**最长那条**补半角空格。
   */
  /**
   * 等宽补齐：按 `HINT_MAX_LEN` 补半角空格（5.0.70 立的规矩）。
   *
   * ★ 5.1.5：`_tick` 是**只为建立 @State 依赖而存在的形参** ——
   *   调用方 `bubbleFooterText` 的非媒体分支读的是服务端**普通 Map**（非 @State），
   *   那个分支**不读任何 @State** ⇒ 记账后不重建 ⇒ 提示停在旧值。
   *   把 `this.localStateTick` 传进来（哪怕这里不用）就**建立了依赖**。
   *   ⚠️ **它绝不参与拼接**：拼进去会因「改文案」销毁重建三态文本。
   *   ⚠️ 名字带下划线前缀 = 明示「故意不用」，也让 lint 不报未使用参数。
   */
  private padHint(s: string, _tick: number = 0): string {
    const gap: number = Index.HINT_MAX_LEN - s.length;
    return gap > 0 ? `${s}${' '.repeat(gap)}` : s;
  }

  /** 关闭全屏预览并复位缩放 / 位移（否则下一张图会带着上一张的倍率打开） */
  private closeMediaPreview(): void {
    // 视频先停：浮层虽然会被销毁，但显式停掉更保险（别让声音多跑半秒）
    try {
      this.videoCtl.stop();
    } catch (e) {
      // 没在播放时 stop 会抛，忽略
    }
    this.imgPreview = '';
    this.imgPreviewName = '';
    this.imgPreviewKey = '';
    this.imgPreviewVideo = false;
    this.imgScale = 1;
    this.imgPinchBase = 1;
    this.imgOffX = 0;
    this.imgOffY = 0;
    this.galleryPaths = [];
    this.galleryNames = [];
    this.galleryKeys = [];
    this.galleryIndex = 0;
  }

  /**
   * 重建「文件名 → 沙箱路径」索引。
   *
   * ⚠️ 关键在**别名**：对端发来的图叫 `photo.jpg`，而沙箱里已经有一张同名图时，
   *    落盘名会被 `FileKinds.dedupeName` 改成 `photo(1).jpg`，
   *    可气泡里存的永远是**对端发来的原名**。只登记真名的话，第二张同名的图
   *    在消息页就永远没有缩略图 —— 而 `IMG_0001.jpg` 这种一发就是一批，太常见。
   *    所以每个文件登记两个键：真名 + 去掉重名后缀的别名。
   *
   * ⚠️ `list` 是**按时间倒序**的，「先到先得」= 取最新的那张，符合直觉。
   */
  private rebuildRecvIndex(list: ReceivedFile[]): void {
    const m: Map<string, string> = new Map<string, string>();
    for (let i = 0; i < list.length; i++) {
      const f: ReceivedFile = list[i];
      if (!m.has(f.name)) {
        m.set(f.name, f.path);
      }
      const base: string = Index.stripDedupeSuffix(f.name);
      if (base !== f.name && !m.has(base)) {
        m.set(base, f.path);
      }
    }
    this.recvIndex = m;
  }

  /**
   * `photo(1).jpg` → `photo.jpg`。不是 `(n)` 形态就原样返回。
   *
   * 手写而不用正则：`FileKinds.dedupeName` 只会产出「数字包在圆括号里」这一种形态，
   * 逐字符判断足够，也免掉正则字面量在 ArkTS 里的转义麻烦。
   */
  private static stripDedupeSuffix(name: string): string {
    // ★ 5.1.52：改用 `splitExt` —— 它从右往左找**已知扩展名**。
    //   旧代码 `lastIndexOf('.')` 对 `IMG_...jpg.1 (1)` 会把 `1` 当扩展名，
    //   于是去重括号判断作用在了错的 stem 上（`.jpg.1 (1)` 的 base 不以 `)` 结尾）
    //   ⇒ 剥不掉 `(1)`。
    const se: string[] = LanService.splitExt(name);
    const base: string = se[0];
    const ext: string = se[1].length > 0 ? `.${se[1]}` : '';
    if (!base.endsWith(')')) {
      return name;
    }
    const lp: number = base.lastIndexOf('(');
    if (lp <= 0) {
      return name;
    }
    const inner: string = base.substring(lp + 1, base.length - 1);
    if (inner.length === 0 || inner.length > 6) {
      return name;
    }
    for (let i = 0; i < inner.length; i++) {
      const c: number = inner.charCodeAt(i);
      if (c < 0x30 || c > 0x39) {
        return name;
      }
    }
    return `${base.substring(0, lp)}${ext}`;
  }

  /**
   * ★ 5.0.52：相册索引的 key —— **消息 id + 该消息里第几个媒体**（0 起）。
   *
   * ⚠️ 为什么必须带序号：对端一次发 N 张图，我们只产生**一条**「N 个文件」消息
   *    （`V5Transfer` 收完整批才回一次终态；`FileTransfer` 把名字合并成「N 个文件」）。
   *    5.0.39~5.0.51 的相册索引是 `Map<消息id, "uri|thumb">` —— **一条消息只有一个槽位**：
   *    这一批 N 张图的缩略图全写进同一个 `<消息id>.jpg`（后写覆盖前写，只剩最后一张），
   *    albumMap 也只记得最后那个 uri。
   *    真机症状（vivi 2026-10-02）：在系统相册里删掉其中一张，**这一批全部**提示
   *    「已删除」；点击打开的也不是缩略图显示的那张。改成 `消息id#序号` 之后，
   *    每张图各有一条 uri + 一份缩略图，互不影响。
   */
  private static albumKeyOf(id: string, k: number): string {
    return `${id}#${k}`;
  }

  /**
   * ★ 5.0.52：这条消息里**媒体**的名字，顺序与对端发来的一致。
   *
   * ⚠️ 关键：**只看消息本身**（`m.files` / `m.content`），**不看沙箱里还剩几个文件**。
   *    5.0.51 之前拿 `mediaPathsOf()`（沙箱里还在的路径）当下标来源 —— 自动存相册后
   *    沙箱副本被删，数组会**塌缩**：第 2 张的下标变成 0，于是「第 2 张的相册条目」
   *    被写成了「第 1 张的」（还是 5.0.48 那个「靠刷新建索引」的老病灶的另一种形态）。
   */
  private mediaNamesOf(m: ChatMessage): string[] {
    const out: string[] = [];
    if (m.files.length > 0) {
      const ns: string[] = Index.splitFileNames(m.files);
      for (let i: number = 0; i < ns.length; i++) {
        if (this.isMediaName(ns[i])) {
          out.push(ns[i]);
        }
      }
    }
    // 单发时 `files` 可能为空，名字只在 content 里
    if (out.length === 0 && this.isMediaName(m.content)) {
      out.push(m.content);
    }
    return out;
  }

  /**
   * ★ 5.0.52：读一条相册条目 —— 先按新格式 `id#k`，读不到再兜底旧格式（裸 id）。
   *
   * 旧格式只有 k=0 能兜底：那时整条消息只存了一个槽位，
   * 我们对不上它是这一批里的第几张，只能当第一张用。
   */
  private albumPartOf(id: string, k: number, part: number): string {
    const v: string = this.albumPart(Index.albumKeyOf(id, k), part);
    if (v.length > 0) {
      return v;
    }
    return k === 0 ? this.albumPart(id, part) : '';
  }

  /**
   * ★ 5.0.52：把「对端发来的名字」翻成沙箱路径 —— **按与这条消息的时间差就近取**。
   *
   * ⚠️ 为什么不能再用单纯的名字表：同名文件会跨消息串台。
   *    对端发来 `IMG_1.jpg`、沙箱里已经有一张同名的老图时，落盘名会被
   *    `FileKinds.dedupeName` 改成 `IMG_1(1).jpg` ——「名字 → 路径」是**多对一**，
   *    谁先谁后就决定了气泡显示哪一张。真机症状：删掉老图后再收同名新图，
   *    气泡显示的却是**以前那张**。
   *    现在按 `|文件时间 - 消息时间|` 就近取：每条消息只会命中**自己那一批**落下的文件。
   *    `k` 用来区分「同一条消息里同名的第 k 个」（对端真发了两张同名图时）。
   */
  private recvPathFor(name: string, k: number, msgTimeMs: number): string {
    // ★★ 5.1.68：拆成「精确匹配」与「退化匹配」**两个候选池**。
    //
    // ## 为什么（vivi 2026-10-05 真机：426 张里固定残留 15 张在沙箱）
    //   原实现是 `f.name === name || stripDedupeSuffix(f.name) === name`，
    //   而 `stripDedupeSuffix('X(2).jpg') === 'X.jpg'`。
    //   PC 端发来的这批里**有 28 对「同名但内容相同」的文件**：
    //     清单[241] size=14210 "X(2).jpg"  ≡  清单[242] size=14210 "X.jpg"
    //   两份**各自是独立的单文件消息**，`k` 都是 0。
    //   ⇒ 查 `X.jpg` 时两份都被收进同一个 `cands`
    //   ⇒ 都取 `cands[0]`（同一个文件）
    //   ⇒ 一份被 copyTo + 删沙箱，另一份拿到的是**已删的路径**
    //   ⇒ stat 失败 ⇒「未解析出路径」⇒ 重试 6 次/60 秒 ⇒「放弃等待落盘」
    //   ⇒ **每轮固定丢一批**（14:30 丢 14 个、14:41 丢 15 个，名单还不同）
    //
    // ## 修法
    //   精确命中优先：只有 `f.name === name` 的才算「同名同容的候选」。
    //   退化匹配（剥掉去重后缀）**仅在没有精确命中时使用**，用于兼容
    //   「协议原始名 vs 落盘时被 dedupeName 改成 X (2).jpg」的单份场景。
    //   ⇒ 两份同名时**不再互相串台**：查 X.jpg 只命中 X.jpg。
    const exact: ReceivedFile[] = [];
    const loose: ReceivedFile[] = [];
    for (let i: number = 0; i < this.receivedFiles.length; i++) {
      const f: ReceivedFile = this.receivedFiles[i];
      if (f.name === name) {
        exact.push(f);
      } else if (Index.stripDedupeSuffix(f.name) === name) {
        loose.push(f);
      }
    }
    // 精确命中优先；没有才退化（loose 已被设计成「至多一份」）
    const cands: ReceivedFile[] = exact.length > 0 ? exact : loose;
    if (cands.length === 0) {
      // 兜底：老表（按名字取最新）。文件已被删 / 超出列表上限时走这里。
      const hit: string | undefined = this.recvIndex.get(name);
      return hit === undefined ? '' : hit;
    }
    if (cands.length > 1) {
      cands.sort((a: ReceivedFile, b: ReceivedFile) => {
        const da: number = Math.abs(a.time - msgTimeMs);
        const db: number = Math.abs(b.time - msgTimeMs);
        return da - db;
      });
    }
    return (k >= 0 && k < cands.length ? cands[k] : cands[0]).path;
  }

  /**
   * ★ 5.0.52：这条消息第 k 个媒体**当前最好的显示源**：
   * 沙箱那份还在就用它（原图），已经被删（存进相册了）就用**这一张自己的**缓存缩略图。
   *
   * ⚠️ 5.0.61 起这个方法**只给「要看清楚」的场合用**（全屏预览 / 画廊 / 长按存图）——
   *    气泡缩略图请走 `mediaThumbSrcOf()`。原因见那个方法的注释：
   *    本方法的返回值会随「沙箱副本被删」而变，挂进 ForEach key 就会引发整屏重建。
   */
  private mediaSrcOf(m: ChatMessage, k: number): string {
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return '';
    }
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      return p;
    }
    return this.albumPartOf(m.id, k, 1);
  }

  /**
   * ★ 5.0.61：气泡缩略图的**恒定显示源** —— 缓存小图优先。
   *
   * 与 `mediaSrcOf` 的分工（本次改动的核心，别混用）：
   *   - `mediaSrcOf`  = **尽力高清**源（沙箱原图优先）→ 全屏预览 / 画廊 / 长按存图；
   *   - 本方法        = **稳定**源（缓存小图优先）→ 气泡缩略图 + ForEach key。
   *
   * ⚠️ 为什么必须另立一个：`mediaSrcOf` 的返回值会随「沙箱副本被删」而切换
   *    （沙箱原图 → 缓存小图）。而 ForEach 的 key 里带着它 ⇒ 一次「存相册」
   *    就把**整屏**气泡的 key 全改掉 ⇒ 全部销毁重建、重新解码。vivi 2026-10-02
   *    反馈的「接收完那一刻缩略图已经生成了，保存完相册又刷一遍」就是这条链
   *    （三层成因里的第一、二层）。
   *    缓存文件名只由「消息 id + 媒体序号」决定（幂等），正好提供了一个
   *    **不会消失的显示身份** —— 接收时就把小图生成好，之后源恒定、key 恒定。
   *
   * ⚠️ 为什么 `_full`（原图复制兜底）不参与恒定路径：那类图的内容与沙箱原图
   *    **逐字节相同**，切过去视觉上零变化、用户本来就感知不到；而预生成会让每张
   *    竖拍照片都多存一份原图（磁盘翻倍），不值。所以它们继续「沙箱优先」。
   */
  private mediaThumbSrcOf(m: ChatMessage, k: number): string {
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return '';
    }
    const cached: string = this.albumPartOf(m.id, k, 1);
    if (cached.length > 0 && !Index.isFullCopyThumb(cached)) {
      return cached;
    }
    // ★★ 5.0.63：**这里绝不回退沙箱原图**。
    //   5.0.61 的写法是「缓存没有就返回沙箱原图」—— 可那意味着**显示源自己会变一次**：
    //   接收瞬间显示沙箱原图 → 预生成完成后切缓存小图 ⇒ `thumbSigOf` 的 src 变了
    //   ⇒ ForEach key 变 ⇒ 那���格销毁重建 ⇒ vivi 反馈的**第一次闪**。
    //   显示源只要「最终会变」，把它放进 key 就等于给闪烁开门。
    //   所以缓存没有时统一走下方兜底（可能返回空串 = 占位），源**全程只有 cache 一个值**。
    //   代价：接收瞬间空拍几十 ms（缓存生成完即出现）；换来彻底不闪。
    //
    //   预生成照旧「渲染到才补」，不做全量预热（5.0.33 的卡顿不能再犯）。
    const p: string = this.recvPathFor(names[k], k, m.timeMs);
    if (p.length > 0) {
      this.maybePrefetchThumb(m.id, k, p);
    }
    // `_full`（5.0.60 的 EXIF 原图复制兜底）不参与恒定路径：它与原图逐字节相同，
    // 恒定源对它无意义，且预生成会让每张竖拍照片多存一份原图 ⇒ 磁盘翻倍。
    if (cached.length > 0) {
      return cached;
    }
    return this.thumbPlaceholderOf(p);
  }

  /**
   * ★ 5.0.63：没有缓存缩略图时的**占位源**。
   *
   * 只对「EXIF 方向图」放行沙箱原图 —— 那类图 5.0.60 走 `_full` 原图复制，
   * 缓存与原图内容逐字节相同，显示源在两者间切换**用户感知不到**，
   * 所以让它们继续「沙箱优先」（顺带避免给每张竖拍照多存一份原图）。
   *
   * ⚠️ 普通图片一律返回**空串**（占位）：宁可空拍几十 ms，也不让显示源变。
   */
  private thumbPlaceholderOf(sandboxPath: string): string {
    if (sandboxPath.length === 0) {
      return '';
    }
    // 带 EXIF 方向（deg≠0）⇒ 5.0.60 的 `_full` 分支：显示源切换不可感知，放行。
    if (!this.isVideoName(sandboxPath) && Index.jpegExifDeg(sandboxPath) !== 0) {
      return sandboxPath;
    }
    return '';
  }

  /** `_full` = 5.0.60 起的「原图复制兜底」，内容与原图相同 ⇒ 不参与恒定显示源 */
  private static isFullCopyThumb(p: string): boolean {
    return p.indexOf('_full.') >= 0;
  }

  /**
   * 这条消息的第 1 个媒体是不是视频。
   *
   * ⚠️ 必须从**消息本身**判断，不能看显示源的扩展名 —— 视频的缓存封面是普通
   *    `.jpg`，看路径会把「视频的封面」误判成图片，丢掉 ▶ 角标。
   */
  private msgIsVideo(m: ChatMessage): boolean {
    const ns: string[] = this.mediaNamesOf(m);
    return ns.length > 0 && this.isVideoName(ns[0]);
  }

  /**
   * 气泡缩略图在 ForEach key 里的**每项签名**：显示源 + 比例 + 补转角度。
   *
   * ★ 5.0.61：用它替掉 key 里的**全局** `thumbTick` —— 那个计数器每生成一张缩略图
   *   就 +1，于是「一张图存进相册」会把整屏气泡的 key 全改掉、全部销毁重建。
   *   签名下移到每一项自己的显示要素之后，只有真正变了的那个格子会重建。
   */
  private thumbSigOf(m: ChatMessage): string {
    const src: string = this.mediaThumbSrcOf(m, 0);
    // ⚠️ 5.0.63：这里**故意读一次 `thumbTick`**，但**不用它拼 key**。
    //   `ratioOf`(2510) 靠 `if (this.thumbTick < 0)` 建立 @State 依赖；
    //   而比例是 `ensureMediaRatio` 异步量的，量到后 `thumbTick++`(2444) 踢重绘。
    //   保留这次读 ⇒ 比例变化仍能触发「重排版」；
    //   而 key 里不含比例 ⇒ **不会销毁重建**（消除「先按 1:1 画再跳真比例」的闪动）。
    //
    //   ⚠️ `tick` 只作为「读一次」的载体存在，**绝不参与返回值** ——
    //     把它拼进 key 等于退回 5.0.61 之前的全局计数器（一动作动全屏）。
    //     ArkTS 对「读了但不用」不报警（这里 `void` 显式标注意图）。
    this.thumbTick;
    if (src.length === 0) {
      return `${m.id}:-`;
    }
    return `${m.id}:${src}:${this.service.rotOf(src) ?? 0}`;
  }

  /**
   * ★ 5.0.61：缓存缩略图的**按需预生成** —— 渲染到哪张补哪张，不做全量预热
   * （5.0.33 那次「刷新就把全部文件同步算一遍」的卡顿不能再犯）。
   *
   * 三道去重：内存 `thumbPrepare`（本轮已提交）、磁盘索引（已有缓存）、
   * `cacheThumb` 自己的单飞表。生成失败撤销记录 —— 下次渲染还能再试。
   */
  private maybePrefetchThumb(id: string, k: number, srcPath: string): void {
    const key: string = Index.albumKeyOf(id, k);
    if (this.thumbPrepare.has(key)) {
      return;
    }
    this.thumbPrepare.add(key);
    this.prefetchThumbInner(key, srcPath).catch(() => {
      this.thumbPrepare.delete(key);
    });
  }

  private async prefetchThumbInner(key: string, srcPath: string): Promise<void> {
    try {
      // ⚠️ 先让出一拍：本方法是从**渲染路径**上发起的，而下一步读 EXIF 是同步 IO。
      //   不 await 的话这段 IO 会挤在 build 阶段里，滚动时掉帧。
      await Index.yieldOnce();
      // ⚠️ 带 EXIF 方向的图**不预生成**（理由见 mediaThumbSrcOf 的注释）：
      //   5.0.60 对它们走「复制原图当缓存」，预生成等于给每张竖拍照片多存一份原图。
      if (!this.isVideoName(srcPath) && Index.jpegExifDeg(srcPath) !== 0) {
        return;
      }
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      const thumb: string = await this.cacheThumb(ctx, srcPath, key);
      if (thumb.length === 0) {
        this.thumbPrepare.delete(key);
        return;
      }
      const rot: number = this.service.rotOf(thumb) ?? 0;
      // ⚠️ 只补缩略图，**绝不碰相册 URI** —— 用户还没点确认框（见 setThumbOnlyBatch）
      // ★★ 5.1.66 C2b：原来这里是 `await setThumbOnly(...)` —— 每张都
      //   persistAlbumIndex + persistAlbumRot 各全量遍历 + flush
      //   ⇒ **400 张 = 800 次全量写** ⇒ 缩略图生成时卡顿（vivi 2026-10-05 实测）。
      //   ⇒ 改成**只进数组**（纯内存），落盘交给 `flushThumbBatch()` 一起做。
      this.thumbIndexBatch.push(`${key}|${thumb}|${rot}`);
      // ★★ 5.0.63：**不在这里换 `albumIndex` 引用**。
      //   `albumIndex` 是 @State，换引用 = 整个消息页重渲染。原先每张图换一次
      //   ⇒ 收 15 张闪 15 下（vivi 说的「闪一次」其实是闪一批）。
      //   改成进缓冲区，由 `flushThumbBatch()` 一批只换一次。
      this.thumbBatch.add(key);
      this.thumbBatchDirty = true;
      this.scheduleThumbFlush();
      Log.i(TAG, `缩略图预生成就绪（显示源此后恒定）: ${Index.baseName(srcPath)}`
        + ` -> ${Index.baseName(thumb)}`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `预生成缩略图失败: ${err.code} ${err.message}`);
      this.thumbPrepare.delete(key);
    }
  }


  // ★ 5.1.0：`diagSnapshot()`（5.0.68 的临时诊断）已随本次发版移除。

  /**
   * ★ 5.0.63：缩略图预生成的**去抖批量提交**。
   *
   * 消「闪一批」的正解：`albumIndex` 是 @State，换一次引用 = 整个消息页重渲染。
   * 一批只换一次 ⇒ 收 15 张至多重渲染 1 次，而且这一次正好是「数据真正到位」的时刻。
   *
   * ⚠️ 为什么必须**去抖**而不是「攒够 N 张就提交」：预生成是**并发**的
   *   （每张一个 Promise，谁先完成不确定）。攒够 N 张会漏掉最后那几张，
   *   导致「有的图永远不出现」。去抖则保证「最后一张完成后再等一拍」必提交。
   */
  private scheduleThumbFlush(): void {
    if (this.thumbBatchTimer !== -1) {
      return;
    }
    this.thumbBatchTimer = setTimeout(() => {
      this.thumbBatchTimer = -1;
      this.flushThumbBatch();
    }, Index.THUMB_FLUSH_DELAY_MS);
  }

  /** 真正提交：换一次 `albumIndex` 引用，UI 重渲染一次 */
  private flushThumbBatch(): void {
    if (!this.thumbBatchDirty) {
      return;
    }
    this.thumbBatchDirty = false;
    const n: number = this.thumbBatch.size;
    this.thumbBatch.clear();
    // ★★ 5.1.66 C2b：把这一批缩略图索引**一次**落盘。
    //   放在这里是因为 `flushThumbBatch` 本身已经是「批量 + 防抖」节奏
    //   （`scheduleThumbFlush` 合并），**零新增定时器**。
    this.service.setThumbOnlyBatch(this.thumbIndexBatch);
    this.thumbIndexBatch = [];
    this.albumIndex = this.service.albumSnapshot();
    Log.i(TAG, `缩略图批量提交：${n} 张，显示源一次性恒定（避免逐张重渲染）`);
  }

  /**
   * 这一张是不是「已经不在沙箱、也不在相册」= 用户在系统相册里把它删了。
   *
   * ★ 5.0.61：判据里补上「沙箱副本也没了」这一条。改之前是
   *   「无相册 URI 且 有缩略图」⇒ 已删；可**预生成之后，还没存过相册的图也有缩略图**，
   *   那种判法会把每张新图都标成「已删」。
   */
  private mediaGoneFromAlbum(m: ChatMessage, k: number): boolean {
    if (this.albumPartOf(m.id, k, 0).length > 0) {
      return false;
    }
    if (this.albumPartOf(m.id, k, 1).length === 0) {
      return false;
    }
    const names: string[] = this.mediaNamesOf(m);
    if (k < 0 || k >= names.length) {
      return false;
    }
    return this.recvPathFor(names[k], k, m.timeMs).length === 0;
  }

  /**
   * 把「每条消息 -> 其媒体沙箱路径」算好存进 @State，供气泡渲染缩略图。
   *
   * ⚠️ 为什么另立一张表而不是在气泡里直接 `recvIndex.get`：
   *    `recvIndex` 是普通 Map，气泡渲染它不会触发重绘；而气泡**首次**渲染时
   *    `recvIndex` 常常还没建好（订阅回调可能先于 `refreshReceived` 跑，或文件刚落盘），
   *    于是路径算出空串后**再也不重算** —— 图片缩略图永远空白。
   *    （视频靠解码完成的 `videoThumbTick` 触发了重绘，所以只有图片中招。）
   *    这里把结果写进 @State 的 Map：recvIndex 一变 / 聊天条数一变就整体换引用 →
   *    组件重绘、气泡 key 带上本表里的路径 → 路径从空变实的那一行单独重建，
   *    其余行 key 不变、列表滚动位置不跳。
   */
  private syncChatMediaPaths(): void {
    const m: Map<string, string> = new Map<string, string>();
    const g: Map<string, string[]> = new Map<string, string[]>();
    let sig: string = '';
    for (let i = 0; i < this.chat.length; i++) {
      const msg: ChatMessage = this.chat[i];
      let p: string = '';
      const paths: string[] = [];
      if (msg.kind === 'file' && msg.incoming) {
        // ★ 5.0.52：下标 = **消息里的媒体序号**（`mediaNamesOf` 只看消息本身，
        //   不随沙箱副本被删而塌缩）；路径按「与这条消息的时间差」就近取，
        //   同名文件再也不会跨消息串台（见 `recvPathFor`）。
        // ⚠️ 去重按**路径**：同一张图被登记了两个键时别重复进画廊。
        const medias: string[] = this.mediaNamesOf(msg);
        for (let k: number = 0; k < medias.length; k++) {
          const hit2: string = this.recvPathFor(medias[k], k, msg.timeMs);
          if (hit2.length > 0 && !paths.includes(hit2)) {
            paths.push(hit2);
          }
          if (p.length === 0 && hit2.length > 0) {
            p = hit2;
          }
        }
      }
      m.set(msg.id, p);
      g.set(msg.id, paths);
      sig += `${msg.id}:${paths.join(',')};`;
    }
    // 分组：签名没变就不换引用（下面那张表同理）
    if (sig !== this.chatMediaGroupsSig) {
      this.chatMediaGroupsSig = sig;
      this.chatGroupNext2(g);
    }
    // 内容没变就不换引用，避免无谓重绘（文件页刷新很频繁）
    if (this.chatMediaPaths.size === m.size) {
      let same: boolean = true;
      for (const key of m.keys()) {
        if (this.chatMediaPaths.get(key) !== m.get(key)) {
          same = false;
          break;
        }
      }
      if (same) {
        return;
      }
    }
    this.chatPathsNext2(m);
  }

  /**
   * ★ 5.0.70：`chatMediaGroups` 落地（**已降级为普通字段，不再走闸门**）。
   *
   * 与 `chatPathsNext2` 同理：去掉 `@State` 后换引用不再触发重绘，闸门失去意义。
   */
  private chatGroupNext2(v: Map<string, string[]>): void {
    this.chatMediaGroups = v;
  }

  /**
   * ★ 5.0.69：`chatMediaPaths` 落地（**已降级为普通字段，不再走闸门**）。
   *
   * 5.0.64 时它是 @State，所以要经闸门合并、并在 flush 里换引用。
   * 5.0.69 去掉 @State 后，换引用不再触发重绘 ⇒ **闸门对它失去意义**，
   * 直接落地即可（保留这个方法名与调用点，避免牵动 syncChatMediaPaths 的结构）。
   */
  private chatPathsNext2(v: Map<string, string>): void {
    this.chatMediaPaths = v;
  }

  /**
   * 把沙箱里的一张图存进系统相册。
   *
   * ⚠️ 用 `showAssetsCreationDialog` 而不是 `createAsset` / `MediaAssetChangeRequest`：
   *    后两者要 `ohos.permission.WRITE_IMAGEVIDEO`（受限权限，普通应用申请不到），
   *    或者必须由 **SaveButton 安全控件**的点击来换临时授权 ——
   *    而我们的入口是「长按气泡 / 预览页按钮」，接不上那个控件。
   *    `showAssetsCreationDialog` **不需要任何权限声明**：它弹一个系统确认框，
   *    用户点保存后返回一批带写权限的媒体 URI，往里写字节就落相册了。
   *
   * ⚠️ 写字节直接复用 `ExportService.copyTo` —— 「另存为」用的就是它，
   *    Picker 给的 URI 与这里拿到的媒体 URI 是同一类 `file://` 地址，
   *    真机上已经跑通的路径没必要再写第二份。
   */
  /**
   * @returns true = 已存进相册；false = 用户取消或保存失败
   */
  private async saveImageToAlbum(path: string, name: string, key: string = ''): Promise<boolean> {
    if (path.length === 0) {
      this.toast('找不到源文件');
      return false;
    }
    // ⚠️ title 的硬性规则：**不能带扩展名**（扩展名单独走 fileNameExtension）、
    //    不能含 \ / : * ? " ' ` < > | { } [ ]、总长 1~255。
    // ★ 5.1.48：先剥 ` (n)` 再切，否则 `xxx.jpg (1)` 的 title 会变成
    //   `扫描全能王 2026-10-01 09.47`（丢了 .jpg）、ext 变成 `jpg (1)`。
    const isVideo: boolean = this.isVideoName(name);
    // ★★ 5.1.52：title 与 ext **必须来自同一次拆分**（vivi 实测存相册失败）。
    //   旧代码用 `lastIndexOf('.')`：`IMG_20260929_201632.jpg.1` ⇒
    //     title='IMG_20260929_201632.jpg'（**带点，违规**）
    //     ext='1'（**非法后缀**）⇒ 系统拒绝建资产。
    //   `splitExt` 从右往左找已知扩展名 ⇒ 两个字段同时正确。
    const se: string[] = LanService.splitExt(name);
    const title: string = Index.safeAlbumTitle(se[0]);
    const ext: string = se[1].length > 0 ? se[1] : (isVideo ? 'mp4' : 'jpg');
    try {
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      const helper: photoAccessHelper.PhotoAccessHelper =
        photoAccessHelper.getPhotoAccessHelper(ctx);
      const cfg: photoAccessHelper.PhotoCreationConfig = {
        title: title,
        fileNameExtension: ext,
        photoType: isVideo ? photoAccessHelper.PhotoType.VIDEO : photoAccessHelper.PhotoType.IMAGE
      };
      // ⚠️ 传进去的必须是 `fileUri.getUriFromPath()` 取到的沙箱 URI（见 imageUri 注释）。
      //    系统对这种 URI 的说明是「能存，但确认框里没法预览」，属已知行为。
      // ★ 5.0.54：手动保存同样套超时 —— 长按存相册走的是同一个系统接口，
      //   真机上它有永不返回的实例（见 awaitDialog 注释），裸 await 会把
      //   「长按保存」也变成永久无响应。
      let uris: string[] = [];
      try {
        uris = await Index.awaitDialog(helper, [this.imageUri(path)], [cfg]);
      } catch (de) {
        this.service.logAuto(`手动存相册：确认框 ${Index.DIALOG_TIMEOUT_MS / 1000} 秒无响应`);
        this.toast('存相册确认框无响应，请重试');
        return false;
      }
      if (uris.length === 0) {
        // 用户点了取消 —— 系统返回空数组，不是错误
        this.toast('已取消保存');
        return false;
      }
      // ⚠️ 视频动辄几百 MB，`copyTo` 是**同步**逐块读写 —— 直接调用会把主线程
      //    按住好几秒，连「正在保存」这句 toast 都画不出来（同一帧内就被阻塞了）。
      //    先弹提示、让出一帧，再开始拷。
      this.toast(isVideo ? '正在保存视频…' : '正在保存…');
      await Index.yieldOnce();
      const msg: string = await ExportService.copyTo(path, uris[0], name);
      this.toast(msg);
      Log.i(TAG, `存相册：${msg}`);
      if (!msg.startsWith('已保存')) {
        return false;
      }
      // ★ 5.0.52：同上 —— 手动保存也校准一次
      this.albumProbeCalibrate(uris[0]);
      // 5.0.44：手动保存也要缓存缩略图并记相册 URI，否则沙箱原图一删就丢。
      // ★ 5.0.52：`key` 是**每一张图**的相册 key（`消息id#媒体序号`），空串 = 不记账。
      if (key.length > 0) {
        try {
          // 5.0.45：源文件**就是**这条消息已有的缓存缩略图时（历史图补存这条路径），
          //         不能再 cacheThumb 一遍 —— 那等于「自己解码自己再写回同一路径」，
          //         有把缓存图写坏的风险。直接用现成的那份。
          const oldThumb: string = this.albumPart(key, 1);
          const thumb: string = (oldThumb.length > 0 && oldThumb === path)
            ? path : await this.cacheThumb(ctx, path, key);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(key, uris[0], thumb, rot);
        } catch (x) {
          Log.w(TAG, `手动保存后缓存缩略图失败: ${path}`);
        }
      }
      // 5.0.46：索引写进 service 了，但**页面快照还停在旧值** ——
      //         不刷新的话 albumPart(m.id,0) 一直查不到 URI，
      //         历史图每次点击都会再弹一次保存框（5.0.45 真机复现）。
      this.swapAlbumIndex();
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `存相册失败: ${err.code} ${err.message}`);
      this.toast(`保存失败：${err.message}`);
      return false;
    }
  }

  /*
   * 5.0.50：`historyToAlbum()` 已删除 —— vivi 要求「相册里删掉的就别再偷存回去」，
   *   现在点只剩缓存缩略图的气泡只提示「该文件已从相册删除」并做应用内预览，
   *   不再自动写相册。保留此注释说明去处，避免后人以为漏了实现。
   */

  /**
   * 5.0.38：刚收到的图片/视频 -> 自动存进系统相册。
   *
   * ⚠️ 为什么只认「新增的那几条」：聊天条数变化有两个来源 ——
   *   ① 真的收到新文件；② 启动时 `restoreChat` 把历史记录灌进来。
   *   后者条数也会跳变，如果不管，每次开 App 都会把历史里所有图视频
   *   重新弹一遍保存框。用 `timeMs` 的 60 秒新鲜度把这一茬挡掉。
   *
   * @param oldCount 本次变化的**前**一条聊天条数（新增消息 = chat[oldCount..]）
   */
  /**
   * 5.0.39：刚收到的图片/视频 -> 排进「待存相册」队列，并立刻尝试一次。
   *
   * ⚠️ 5.0.38 为什么「1 张不弹、2 张才弹」（vivi 2026-10-02 真机反馈）：
   *    路径是从 `recvIndex` 反查的，而 `recvIndex` 只在 `refreshReceived()` 里重建，
   *    `refreshReceived()` 又只在「`transferText` 由非空变空」时触发 ——
   *    **小文件一次进度都没刷过**（transferText 全程空串）就永远不触发。
   *    1 张小图正好命中（索引是旧的 → 解析出 0 条路径 → 静默 return）；
   *    2 张耗时够长、刷过进度 → 索引是新的 → 才弹得出来。
   * 修法：**不再依赖时序** —— 入队后无条件先 `refreshReceived()` 把索引建出来，
   *    解析不出路径的留在队列里，等下一次 `refreshReceived()` 再试。
   *
   * @param oldCount 本次变化的**前**一条聊天条数（新增消息 = chat[oldCount..]）
   */
  private autoSaveNewMedia(oldCount: number): void {
    if (oldCount >= this.chat.length) {
      return;
    }
    // 5.0.48：这条链路每步都打 UI 日志 —— 之前弹窗没出现时真机上什么都看不到
    this.service.logAuto(`新消息 ${oldCount} -> ${this.chat.length}，自动存相册开关=${this.autoAlbum}`);
    if (!this.autoAlbum) {
      return;
    }
    const now: number = Date.now();
    // ★★ 5.1.65 A4：本轮入队的名字先收集，循环结束后按数量决定打日志的粒度。
    //   `logAuto` 会 emit ⇒ onSnapshot ⇒ refreshReceived ⇒ 全量扫盘 + 三个全量重算
    //   ⇒ 426 张逐条打 = 同一秒 426 次 O(n) 重建（vivi 2026-10-05 实测卡顿真凶）。
    const enqueued: string[] = [];
    for (let i: number = oldCount; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (!m.incoming || m.kind !== 'file') {
        continue;
      }
      // ★★ 5.1.31：AUTOSAVE_MEDIA_GUARD —— **必须判「是不是媒体」**。
      //
      // 【真机事故】网页上传 .apk（645.9MB）传完后进程闪退。日志：
      //   网页上传完成 -> 入队待存相册：「launchermap_...apk」
      //   -> 队列 1 项暂未解析出沙箱路径（等文件落盘后再试）  <- 末条
      //   根因：这里只判了 kind，没判媒体 ⇒ **apk 也入队**；
      //   而消费侧 `mediaNamesOf(m)` 对 apk 返回空数组 ⇒ 永远解析不出路径
      //   ⇒ 每轮刷新都重试（flushAutoSave -> logAuto -> emit -> onSnapshot
      //      -> refreshReceived -> flushAutoSave）⇒ 无限轮询拖死进程。
      //   ⚠️ LanService.ets:353 记录过同一条链路的同步重入（5.0.51 修过
      //      「同一秒刷 200 条」），但当时没堵住「非媒体入队」这个源头。
      //
      // 【判据对齐】用 `mediaNamesOf(m).length === 0` 而不是另写一套后缀判断：
      //   入队判据与消费判据**必须同一个函数**，否则又会出现
      //   「入了队却永远解析不出来」。
      if (this.mediaNamesOf(m).length === 0) {
        continue;
      }
      // 60 秒新鲜度：挡掉「启动恢复历史聊天」那一茬条数跳变
      if (now - m.timeMs > 60000) {
        continue;
      }
      if (this.autoSaveHandled.has(m.id) || this.autoSavePending.indexOf(m.id) >= 0) {
        continue;
      }
      this.autoSavePending.push(m.id);
      enqueued.push(`${m.content}|${m.id}`);
    }
    // ★★ 5.1.65 A4：按数量选粒度（>8 张只打一条汇总）。
    if (enqueued.length > 8) {
      this.service.logAuto(`[相册] 本次入队 ${enqueued.length} 项`
        + `（示例：「${enqueued[0]}」…「${enqueued[enqueued.length - 1]}」），`
        + `待存队列共 ${this.autoSavePending.length} 项`);
    } else {
      for (let i: number = 0; i < enqueued.length; i++) {
        this.service.logAuto(`入队待存相册：${enqueued[i]}`);
      }
      this.service.logAuto(`待存队列共 ${this.autoSavePending.length} 项`);
    }
    if (this.autoSavePending.length === 0) {
      return;
    }
    // 关键一步：先把「文件名 -> 沙箱路径」索引建出来，再去解析 —— 不再赌刷新时序
    this.refreshReceived();
    this.flushAutoSave();
  }

  /** 队列里能解析出路径的那些 -> 一次弹框存进相册；还没落盘的继续留在队列里 */
  private flushAutoSave(): void {
    // 5.0.50：**卡死看门狗**（第二道防线）。
    // ★ 5.0.54：第一道防线改成 `awaitDialog` 的 20 秒超时了 —— 弹窗不会再
    //   无限制挂住。这里放宽到 60 秒，只兜「超时机制本身也没生效」的极端情况；
    //   放宽是为了避免在**正常的长拷贝**中途复位闸门、把同一批弹第二遍。
    //   （真机 2026-10-02：45 秒档曾让闸门被钉死 108 秒，期间新到 3 张图一次弹窗都没有。）
    if (this.autoSaveBusy && this.autoSaveBusySince > 0
      && Date.now() - this.autoSaveBusySince > 60000) {
      const stuck: number = Date.now() - this.autoSaveBusySince;
      this.service.logAuto(`自动存相册疑似卡死 ${stuck}ms，强制复位重试`);
      this.autoSaveBusy = false;
    }
    if (this.autoSaveBusy || this.autoSavePending.length === 0) {
      return;
    }
    const paths: string[] = [];
    // ★ 5.0.52：与 `paths` 一一对应的**相册 key**（`消息id#媒体序号`）——
    //   一批 N 张图各占一条条目，删其中一张不再连带全批。
    const keys: string[] = [];
    const ready: string[] = [];
    const now: number = Date.now();
    const expired: string[] = [];
    for (let i: number = 0; i < this.autoSavePending.length; i++) {
      const id: string = this.autoSavePending[i];
      const m: ChatMessage | undefined = this.msgById(id);
      if (m === undefined) {
        this.autoSaveHandled.add(id);
        continue;
      }
      // ★ 5.0.52：按 `mediaNamesOf` 的**媒体序号**逐个解析 —— 下标只取决于消息本身
      //   （不随沙箱副本被删而塌缩），相册 key 直接用这个序号。
      const medias: string[] = this.mediaNamesOf(m);
      let any: boolean = false;
      for (let k: number = 0; k < medias.length; k++) {
        const p: string = this.recvPathFor(medias[k], k, m.timeMs);
        if (p.length === 0) {
          continue;
        }
        any = true;
        if (paths.indexOf(p) >= 0) {
          continue;
        }
        paths.push(p);
        keys.push(Index.albumKeyOf(id, k));
      }
      if (!any) {
        // 文件还没进索引 —— 留在队列里，等下一次 refreshReceived。
        // 5.0.51：但**不能无限等** —— 见 `autoSaveTry` 上的注释。
        const n: number = (this.autoSaveTry.get(id) ?? 0) + 1;
        this.autoSaveTry.set(id, n);
        if (!this.autoSaveFirstMs.has(id)) {
          this.autoSaveFirstMs.set(id, now);
        }
        const waited: number = now - (this.autoSaveFirstMs.get(id) ?? now);
        if (n >= 6 || waited > 60000) {
          expired.push(id);
        }
        continue;
      }
      ready.push(id);
    }
    if (expired.length > 0) {
      // 结案放弃：不再占着队列、不再刷日志（否则就是永久热循环）
      for (let i: number = 0; i < expired.length; i++) {
        this.autoSaveHandled.add(expired[i]);
        this.autoSaveTry.delete(expired[i]);
        this.autoSaveFirstMs.delete(expired[i]);
      }
      const rest0: string[] = [];
      for (let i: number = 0; i < this.autoSavePending.length; i++) {
        if (!this.autoSaveHandled.has(this.autoSavePending[i])) {
          rest0.push(this.autoSavePending[i]);
        }
      }
      this.autoSavePending = rest0;
      this.service.logAuto(`放弃等待落盘 ${expired.length} 项`
        + `（重试 6 次 / 60 秒仍未解析出路径），已从队列移除`);
    }
    if (paths.length === 0) {
      this.noteAutoSaveWaiting();
      return;
    }
    // 5.0.51：闸门必须在**打日志之前**关门 —— logAuto 会立刻 emit，
    //   重入进来的 flushAutoSave 若看到闸门还开着，就会再解析、再打日志。
    this.autoSaveBusy = true;
    this.autoSaveBusySince = Date.now();
    this.service.logAuto(`准备弹存相册确认框：${paths.length} 个文件`);
    this.autoSaveAlbumBatch(paths, keys, ready).then(() => {
      this.autoSaveBusy = false;
      this.autoSaveBusySince = 0;
      // 5.0.47：batch 的 finally 里那次 flushAutoSave 发生在 busy 清零**之前**
      // （被 busy 挡掉），必须在这里补一次，否则弹框期间入队的后续图片
      // 永远没人再触发 -> 只有第一次有弹窗（真机复现）。
      this.flushAutoSave();
    }).catch((e: Object) => {
      // 5.0.50：**必须兜住**。5.0.49 只挂了 then —— 一旦 batch reject
      //   （比如 finally 里那次 refreshReceived 抛异常），`autoSaveBusy`
      //   就永远停在 true，之后**再也不会弹框**。这是 5.0.49「不弹窗」的病灶之一。
      const err: BusinessError = e as BusinessError;
      this.service.logAuto(`自动存相册批处理异常：${err.code} ${err.message}`);
      // ★ 5.0.54：失败也自己排一次重试，不等 UI 刷新来救
      this.scheduleAutoSaveRetry(3000);
      this.autoSaveBusy = false;
      this.autoSaveBusySince = 0;
      this.flushAutoSave();
    });
  }

  /**
   * 「队列里还有项、但路径还没解析出来」这条日志的**限频器**（5.0.51）。
   *
   * 真正的重试在 `flushAutoSave` 里（由刷新驱动）；这里只保证：
   * 同样的内容 5 秒内最多打一条。日志环只有 200 条，
   * 一条刷屏日志会把真正的线索全部挤掉 —— vivi 2026-10-02 就是这么丢掉现场的。
   */
  private noteAutoSaveWaiting(): void {
    const msg: string =
      `队列 ${this.autoSavePending.length} 项暂未解析出沙箱路径（等文件落盘后再试）`;
    const at: number = Date.now();
    if (msg === this.autoSaveWaitLog && at - this.autoSaveWaitLogAt < 5000) {
      return;
    }
    this.autoSaveWaitLog = msg;
    this.autoSaveWaitLogAt = at;
    this.service.logAuto(msg);
  }

  /** 消息 id -> 消息（聊天条数不多，线性找即可） */
  private msgById(id: string): ChatMessage | undefined {
    for (let i: number = 0; i < this.chat.length; i++) {
      if (this.chat[i].id === id) {
        return this.chat[i];
      }
    }
    return undefined;
  }

  /*
   * 5.0.52：`resolveMediaPaths()` 已删除。
   *   它按**名字**反查、且只返回「沙箱里还在」的路径 —— 下标会随沙箱副本被删而塌缩，
   *   于是「第 2 张图」的下标变成 0，相册条目被写到第 1 张头上。
   *   现在统一走 `mediaNamesOf()`（下标来源）+ `recvPathFor()`（时间就近取路径）+
   *   `mediaSrcOf()`（沙箱优先、否则用这一张自己的缓存缩略图）。
   */


  /**
   * 整批存进系统相册 —— **只弹一次**确认框。
   *
   * `showAssetsCreationDialog` 一次可以传 N 个源文件 + N 份配置，
   * 返回 N 个带写权限的媒体 URI，逐个 `ExportService.copyTo` 写字节即可。
   * ⚠️ 不需要任何权限声明（WRITE_IMAGEVIDEO 是受限权限，申请不到），
   *    前提只有一条：module.json5 的 abilities 里配了 label 和 icon，
   *    否则确认框显示不出应用名。
   * ⚠️ 拷贝是同步逐块的，先把提示 toast 画出去（yieldOnce 让一帧）再开拷。
   */
  /**
   * 整批存进系统相册 —— **只弹一次**确认框。
   *
   * `showAssetsCreationDialog` 一次可以传 N 个源文件 + N 份配置，
   * 返回 N 个带写权限的媒体 URI，逐个 `ExportService.copyTo` 写字节即可。
   * ⚠️ 不需要任何权限声明（WRITE_IMAGEVIDEO 是受限权限，申请不到），
   *    前提只有一条：module.json5 的 abilities 里配了 label 和 icon，
   *    否则确认框显示不出应用名。
   *
   * 5.0.39 存完之后的两件事（vivi 2026-10-02 要求）：
   *   ① **删掉沙箱里那份** —— 相册里已经有一份，留着就是双份占空间；
   *   ② 删之前先缓存一张 320px 小图 + 记下相册 URI ——
   *      否则气泡缩略图和「点击打开相册」都失去来源。
   *      ⚠️ 顺序不能反：**先出缩略图，再删**。
   *   ③ 用户在确认框上点取消时**不删** —— 那份是唯一的一份。
   * ⚠️ 拷贝是同步逐块的，先把提示 toast 画出去（yieldOnce 让一帧）再开拷。
   */
  private async autoSaveAlbumBatch(paths: string[], keys: string[],
                                   ready: string[]): Promise<void> {
    // ★★ 5.1.64：**提交前**按系统容量切批（一次最多 40 个）。
    //   5.1.63 的事故：400 个文件一次塞进弹框 ⇒ 20 秒永不返回 ⇒ 0/6 成功 ⇒ 进程挂掉。
    //   ★ 不能靠 `autoSaveSingleShot` 兜（它只在弹框**返回后**才生效）。
    //   ⚠️ 必须放在 `try` 之前 —— 抛异常会被外层 catch 当成「失败」而重试整批。
    //   ⚠️ 用**新的局部常量**而不是重新赋值入参：ArkTS 对参数重新赋值管得严，
    //   且下面所有 `paths[i]` / `ready[i]` 都得跟着换成新名字（漏一处就是错位）。
    //   ⚠️⚠️ 必须用**三元表达式一次求值**，不能写 `let x = 数组; if (cond) x = 数组.slice(...)` ——
    //   ArkTS 的流分析会判 `x`「可能未赋值」⇒ 报 10605999 + 10505001（双重报错）。
    const CAP: number = Index.ALBUM_DIALOG_MAX;
    const total: number = paths.length;
    const over: boolean = total > CAP;
    if (over) {
      this.service.logAuto(`存相册分批：本次只提交前 ${CAP} 个，余 ${total - CAP} 个留在队列等下一轮`);
    }
    const batchPaths: string[] = over ? paths.slice(0, CAP) : paths;
    const batchKeys: string[] = over ? keys.slice(0, CAP) : keys;
    const batchReady: string[] = over ? ready.slice(0, CAP) : ready;
    // 5.0.47：用户取消（cancelled）= 结案不再弹；异常（failed）= 留队重试。
    // ⚠️ 必须声明在 try 外 —— catch/finally 里要用。
    let cancelled: boolean = false;
    let failed: boolean = false;
    // ★★ 5.1.65：这两个数组在 `try` **块外**也要用（落盘 + 删沙箱），
    //   ArkTS 块级作用域是硬性的 ⇒ 声明必须提到 try 之前（同 cancelled/failed）。
    const idxBatch: string[] = [];
    const toDelete: string[] = [];
    try {
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      const helper: photoAccessHelper.PhotoAccessHelper =
        photoAccessHelper.getPhotoAccessHelper(ctx);
      // ---- 准备 title / 后缀 / 类型（与源 URI 一一对应）----
      const srcUris: string[] = [];
      const rawTitles: string[] = [];
      const exts: string[] = [];
      const vids: boolean[] = [];
      for (let i: number = 0; i < batchPaths.length; i++) {
        const name: string = Index.baseName(batchPaths[i]);
        // ★ 5.1.52：同 saveImageToAlbum —— title/ext 来自同一次 `splitExt`
        const se: string[] = LanService.splitExt(name);
        const isVideo: boolean = this.isVideoName(name);
        srcUris.push(this.imageUri(batchPaths[i]));
        rawTitles.push(Index.safeAlbumTitle(se[0]));
        exts.push(se[1].length > 0 ? se[1] : (isVideo ? 'mp4' : 'jpg'));
        vids.push(isVideo);
      }
      // ★ 5.0.54：批内 title 去重 —— 系统对同名同后缀会少建资产（见 uniqueAlbumTitles）
      const titles: string[] = Index.uniqueAlbumTitles(rawTitles);
      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];
      for (let i: number = 0; i < batchPaths.length; i++) {
        const cfg: photoAccessHelper.PhotoCreationConfig = {
          title: titles[i],
          fileNameExtension: exts[i],
          photoType: vids[i] ? photoAccessHelper.PhotoType.VIDEO
            : photoAccessHelper.PhotoType.IMAGE
        };
        cfgs.push(cfg);
      }
      this.service.logAuto(`存相册提交 ${batchPaths.length} 项，title：${titles.join(' | ')}`);

      // ---- 拿 URI：得到的是**确定能配对**的 (paths 下标, 相册 URI) ----
      const idxs: number[] = [];
      const gotUris: string[] = [];
      if (this.autoSaveSingleShot) {
        // ★ 5.0.54：逐张模式 —— 每次只提交 1 个，返回只可能是 0 或 1，**无歧义**
        for (let i: number = 0; i < batchPaths.length; i++) {
          let one: string[] = [];
          try {
            one = await Index.awaitDialog(helper, [srcUris[i]], [cfgs[i]]);
          } catch (de) {
            this.service.logAuto(`逐张存相册：第 ${i + 1}/${batchPaths.length} 项确认框无响应，跳过`);
            continue;
          }
          if (one.length === 1) {
            idxs.push(i);
            gotUris.push(one[0]);
          } else {
            this.service.logAuto(`逐张存相册：第 ${i + 1}/${batchPaths.length} 项未获得 URI`
              + `（提交 1 个返回 ${one.length} 个），跳过`);
          }
        }
        this.service.logAuto(`逐张提交完成：${gotUris.length}/${batchPaths.length} 项拿到 URI`);
      } else {
        let uris: string[] = [];
        let timedOut: boolean = false;
        try {
          uris = await Index.awaitDialog(helper, srcUris, cfgs);
        } catch (de) {
          timedOut = true;
        }
        if (timedOut) {
          // ★ 5.0.54 —— 修「没有弹窗 + 闸门卡死 108 秒」
          this.autoSaveDialogFails += 1;
          this.service.logAuto(`存相册确认框 ${Index.DIALOG_TIMEOUT_MS / 1000} 秒无响应`
            + `（第 ${this.autoSaveDialogFails} 次），本次放弃；文件留在沙箱，稍后自动重试`);
          if (this.autoSaveDialogFails >= 3) {
            if (this.autoSaveTimer >= 0) {
              clearTimeout(this.autoSaveTimer);
              this.autoSaveTimer = -1;
            }
            this.service.logAuto('自动存相册连续 3 次无响应，停止自动重试'
              + '（文件仍留在沙箱，可长按图片手动存相册）');
            this.toast('自动存相册无响应，已停止重试；可长按图片手动保存');
          } else {
            this.scheduleAutoSaveRetry(3000);
          }
          failed = true;
          return;
        }
        this.service.logAuto(`确认框返回 ${uris.length} 个 URI（提交 ${srcUris.length} 个）`);
        if (uris.length === 0) {
          // 用户在确认框上点了取消 —— 系统返回空数组，不是错误
          this.autoSaveDialogFails = 0;
          this.toast('已跳过存入相册');
          cancelled = true;
          return;
        }
        this.autoSaveDialogFails = 0;
        if (uris.length !== batchPaths.length) {
          // ★★ 5.0.54 —— 修「4 张只成功 2 张」以及它背后的**内容错位 + 原图误删**。
          //   数量不符时**绝不能按位置配对**：返回的 URI 只对应系统接受的那几项，
          //   位置对不上。真机：提交 [screenshot, IMG_0929, 扫描全能王, IMG_0907]，
          //   回来的是 title 不带点的 [IMG_0929, IMG_0907]，旧代码却把
          //   batchPaths[0]、batchPaths[1] 写进它们 ⇒ 相册内容全错位，且 batchPaths[0]/batchPaths[1]
          //   的沙箱副本被当成"成功"删掉 ⇒ 原图丢失。
          //   现在：本次**不写任何字节、不删任何文件**，翻成逐张模式重试。
          for (let i: number = 0; i < uris.length; i++) {
            this.service.logAuto(`  返回 URI[${i}]：${Index.baseName(uris[i])}`);
          }
          this.autoSaveSingleShot = true;
          this.service.logAuto(`⚠️ 返回数量 ${uris.length} ≠ 提交数量 ${batchPaths.length}，`
            + `无法确定对应关系 ⇒ 本次不写入（避免内容错位/误删），下一轮改「逐张提交」`);
          failed = true;
          return;
        }
        // 数量一致 ⇒ 按提交顺序一一对应（系统对该顺序有约定）
        for (let i: number = 0; i < uris.length; i++) {
          idxs.push(i);
          gotUris.push(uris[i]);
        }
      }
      if (gotUris.length === 0) {
        this.service.logAuto('未能获得任何相册 URI，文件留在沙箱，稍后重试');
        failed = true;
        return;
      }
      this.toast(`正在存入相册（${gotUris.length} 个）…`);
      await Index.yieldOnce();
      let ok: number = 0;
      const missed: string[] = [];
      // ★★ 5.1.70：**三段计时**（vivi 要据「确认框返回→完成 = 3.5s / 40 张 /
      //   65.7MB ≈ 19MB/s」判断该砍哪一段：拷贝 / 解码 / 删沙箱）。
      //   ⚠️ 只**累加**、循环结束后打**一条**汇总 ——
      //   逐张打就是 40 次 logAuto ⇒ 40 次 emit ⇒ 40 次全量重建
      //   （那正是 5.1.69 B 刚治好的病，别在这里复发）。
      let tCopy: number = 0;
      let tThumb: number = 0;
      // ★★ 5.1.65：整批收集，循环结束后**一次性**落盘 + 一次性删沙箱。
      //   （`idxBatch` / `toDelete` 已声明在 try 之前，见本方法开头。）
      // ★★ 5.1.69：**循环内**周期性让帧。
      //   原来循环外有一次 `yieldOnce()`，循环内 40 张连续做
      //   （每张 = 一次分块异步拷贝 + 一次完整解码 + 一次 pack 写文件）
      //   ⇒ 主线程连续被占 3~4 秒 ⇒ 界面全冻（vivi 2026-10-05 实测）。
      //   ⇒ 每 ALBUM_YIELD_EVERY(5) 张让一帧，单次连续占用压到 ~0.5 秒。
      let sinceYield: number = 0;
      for (let j: number = 0; j < gotUris.length; j++) {
        const i: number = idxs[j];
        sinceYield += 1;
        if (sinceYield >= Index.ALBUM_YIELD_EVERY) {
          sinceYield = 0;
          await Index.yieldOnce();
        }
        // 5.0.47：单文件失败（copyTo/cacheThumb 抛异常）不再中断整批
        try {
          // ★ 5.1.70：分段计时
          const t0: number = Date.now();
          const msg: string = await ExportService.copyTo(batchPaths[i], gotUris[j], Index.baseName(batchPaths[i]));
          tCopy += Date.now() - t0;
          if (!msg.startsWith('已保存')) {
            missed.push(Index.baseName(batchPaths[i]));
            continue;
          }
          ok += 1;
          // ★ 5.0.52：拿刚写进去的资产校准探针（见 albumProbeCalibrate）
          this.albumProbeCalibrate(gotUris[j]);
          // ★★ 5.1.71 A：**存相册阶段不再生成缩略图**（省 48% 的 CPU 开销）。
          //
          // 【为什么可以跳过】`mediaThumbSrcOf` 的注释（5.0.63）已定案：
          //   > 「缓存没有时统一走下方兜底（**可能返回空串 = 占位**），
          //   >  源**全程只有 cache 一个值**」
          // 而缩略图**本来就是懒生成**（`maybePrefetchThumb`，渲染到才补）。
          // ⇒ 这里跳过，气泡只是**短暂占位几十 ms**，随后懒生成补上。
          //   ⚠️ 这**不是新 bug**，5.0.63 早就选了「宁可空拍几十 ms，
          //     也不让显示源中途变一次」（变一次 ⇒ ForEach key 变 ⇒ 整屏闪）。
          //
          // 【仍然必须做的两件】
          //   ① 记**相册 URI**（part 0）⇒ 用户点气泡能跳系统相册看大图；
          //   ② 删沙箱副本（走 `toDelete`，循环外统一做）。
          //
          // 【数据依据】vivi 2026-10-05 真机 426 张计时：
          //   拷贝 18100ms(50%) + **解码缩略图 17323ms(48%)** + 落盘删沙箱 640ms(2%)
          //   ⇒ 解码是纯 CPU（41ms/张），**不是 IO 下限，可以砍**。
          //
          // 【顺带】沙箱副本若还在（用户取消存相册 / 弹框失败），
          //   `maybePrefetchThumb` 会在滚动到时正常补缩略图。
          const thumb: string = '';
          // ★ 5.1.71 A: thumb 恒为空串 ⇒ rotOf('') 必然是 0。
          //   这里仍显式算一次，保持 idxBatch 的数据形状与旧版一致
          //   （albumPartOf(.,.,1) 读的是 thumb 字符串，'' 是合法值）。
          const rot: number = this.service.rotOf(thumb) ?? 0;
          // ★★ 5.1.67 关键修正：这里**只进数组**。
          //   5.1.65 的 A1/A2 声明了 `idxBatch`/`toDelete`、循环后也用了，
          //   但**中间这两行 push 被误删** ⇒ 两个数组恒为空 ⇒ 批量落盘完整失效
          //   （真机复测：每批仍是 3~4 秒，与 5.1.64 一模一样）。
          //   ⚠️ 少了 push 编译器**不报错**（只是未使用变量的 warning）⇒ 静默失效。
          idxBatch.push(`${batchKeys[i]}|${gotUris[j]}|${thumb}|${rot}`);
          // ③ 删沙箱副本挪到**索引落盘之后**（见循环外）——
          //   万一进程挂掉，沙箱副本还在 ⇒ 缩略图与索引可重建，不会丢图。
          toDelete.push(batchPaths[i]);
        } catch (x) {
          const xe: BusinessError = x as BusinessError;
          missed.push(Index.baseName(batchPaths[i]));
          Log.w(TAG, `单文件存相册失败: ${batchPaths[i]} ${xe.code} ${xe.message}`);
        }
      }
      // ★ 5.0.54：把「没存进去的那些」如实报出来 —— 它们仍在沙箱里，可长按手动存。
      const extra: string = missed.length > 0
        ? `，${missed.length} 个未成功（文件仍在沙箱，可长按手动保存）` : '';
      // ★★ 5.1.65：**先落盘、再删沙箱**（与原来「每张落盘后立刻删」相反，更安全）。
      //   原来每张「落盘索引 → 立刻删沙箱」；中途崩溃 ⇒ 索引写了、文件已删。
      //   现在整批落盘成功后才删 ⇒ 任一步崩溃都还能靠沙箱副本重建缩略图。
      // ★ 5.1.70：三段计时汇总（**整批一条**日志）。
      //   判据：拷贝 vs 解码 谁占大头 ⇒ 决定「砍 cacheThumb」还是「让帧已够」。
      //   例：拷贝 2.5s / 解码 0.8s / 删 0.2s ⇒ 大头是纯 IO，让帧就是最优解。
      const tDel0: number = Date.now();
      await this.service.setAlbumIndexBatch(idxBatch);
      for (let i: number = 0; i < toDelete.length; i++) {
        const derr: string | null =
          ExportService.deleteFile(this.service.receiveRoot, toDelete[i]);
        if (derr !== null) {
          Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${toDelete[i]}`);
        }
      }
      const tDel: number = Date.now() - tDel0;
      // ★ 5.1.71 A：解码已跳过，`tThumb` 恒为 0，保留字段便于对照历史日志。
      this.service.logAuto(`[耗时] 存相册 ${gotUris.length} 项：`
        + `拷贝 ${tCopy}ms + 解码缩略图 ${tThumb}ms + 落盘删沙箱 ${tDel}ms`
        + `（让帧 ${Index.ALBUM_YIELD_EVERY} 张/次，缩略图改懒生成）`);
      this.toast(ok > 0 ? `已存入相册 ${ok} 个${extra}` : '存入相册失败');
      this.service.logAuto(`自动存相册完成：成功 ${ok}/${batchPaths.length}`
        + (missed.length > 0 ? `，未成功：${missed.join('、')}` : ''));
      Log.i(TAG, `自动存相册：${ok}/${batchPaths.length}`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);
      this.service.logAuto(`自动存相册失败：${err.code} ${err.message}`);
      this.toast(`自动存相册失败：${err.message}`);
      failed = true;
    } finally {
      // 5.0.47：存完 / 用户取消 -> 结案；**异常** -> 留队，等下一次 refreshReceived
      // 重试（flushAutoSave 只由消息/刷新触发，不会自旋）。之前一律结案，
      // 一次系统瞬时错误就永久不弹了。
      if (!failed) {
        for (let i: number = 0; i < batchReady.length; i++) {
          this.autoSaveHandled.add(batchReady[i]);
          // 5.0.51：结案了就清掉重试计数，避免表无限增长
          this.autoSaveTry.delete(batchReady[i]);
          this.autoSaveFirstMs.delete(batchReady[i]);
        }
      }
      const rest: string[] = [];
      for (let i: number = 0; i < this.autoSavePending.length; i++) {
        if (!this.autoSaveHandled.has(this.autoSavePending[i])) {
          rest.push(this.autoSavePending[i]);
        }
      }
      this.autoSavePending = rest;
      // ★ 5.0.64：整段包进换引用闸门 —— 原先这里是「换 albumIndex」+
      //   「refreshReceived 内部再换 receivedFiles/chatMediaPaths/chatGroups」
      //   = 一次操作 4 次重渲染（观感：闪几下）。现在合成 1 次。
      this.beginStateSwap();
      try {
        this.swapAlbumIndex();
        this.refreshReceivedInner();
      } finally {
        this.endStateSwap();
      }
    }
  }

  /**
   * ★ 5.0.54：带**超时**的 `showAssetsCreationDialog`。
   *
   * ⚠️ 为什么必须包一层：真机上它**出现过永不 settle** ——
   *   vivi 2026-10-02 的日志里，14:53:42 提交后一句 `确认框返回` 都没有，
   *   直到 14:55:31 才被 45 秒看门狗强行复位（实际钉了 108642ms）；
   *   这期间 14:54:10 收到的 3 张图**一次弹窗都没有**（闸门还关着）。
   *   超时按「本次失败」处理（**不当作取消**）：文件留在沙箱、下一轮重试，
   *   绝不让一个不返回的 Promise 把整条自动存相册链路锁死。
   */
  private static DIALOG_TIMEOUT_MS: number = 20000;

  /**
   * ★★ 5.1.64：单次 `showAssetsCreationDialog` 的**安全文件数上限**。
   *
   * ## 实证（vivi 2026-10-05 真机，425 张批量）
   *   5.1.63 把 `MAX_CHAT` 从 200 提到 1000 后，426 项一次性入队 ⇒
   *   `flushAutoSave` 把 **400 个文件**塞进一次弹框 ⇒
   *   日志连续 6 次 `存相册提交 400 项` → `存相册确认框 20 秒无响应` →
   *   **`自动存相册完成` 一次都没出现（0/6 成功）** ⇒ 最后进程挂掉。
   *   对照 5.1.62：队列只有 200 项时，系统自己按 **40 个/次** 分批，
   *   每批都 `成功 40/40`。
   *
   * ## 结论
   *   40 是 `showAssetsCreationDialog` 的实际容量；一次超过就**永不返回**。
   *   ★ **`autoSaveSingleShot` 救不了这种情况** —— 它只在「弹框**返回了**且数量
   *     不匹配」时才置 true；现在是弹框**根本不返回**（20s 超时）⇒ 永远走批量。
   *   ⇒ 必须在**提交前**切批，不能等弹框反馈。
   *
   * ★ 「剩下的」不丢弃：`ready` 里未处理的 id 会留在 `autoSavePending` 队列，
   *   下一轮 `flushAutoSave` 继续弹（每轮 40 张），直到清空。
   */
  private static ALBUM_DIALOG_MAX: number = 40;

  /**
   * ★★ 5.1.66 C1：切消息页探测相册资产时，**每多少张让一帧**。
   *
   * 背景（vivi 2026-10-05）：400+ 张缩略图时「切消息页 + 删除提示」卡顿。
   * `albumAssetAlive` 是纯同步 IO（statSync / openSync / readSync），
   * 几百张逐个探会把主线程占死。
   *
   * 取 20 的理由：一次 `statSync` 约几十微秒量级，20 张 ≈ 毫秒级，
   * 对比一帧 16.7ms 仍有富余；再大就让帧变稀、探测总时长变长。
   */
  private static PROBE_YIELD_EVERY: number = 20;

  /**
   * ★★ 5.1.69：存相册主循环**每处理多少张让一帧**。
   *
   * 背景（vivi 2026-10-05 真机 426 张）：`确认框返回 → 完成` = **3~4 秒 / 40 张**。
   * 根因：循环内 `await copyTo` + `await cacheThumb`（完整解码 + rotate + pack）
   * **连续 40 次，中间一次都不让帧** ⇒ 主线程被占满 3~4 秒 ⇒ 界面全冻。
   *
   * 取 5 的理由：
   * - 每张都让（`yieldOnce` 是 setTimeout 30ms）⇒ 40 张至少多等 1.2 秒，**更慢**；
   * - 每 5 张让 ⇒ 单次连续占用从 ~3.5s 压到 ~0.5s，
   *   总耗时只多 8×30ms = 0.24s，但界面全程可响应。
   * ★ 与 `PROBE_YIELD_EVERY`（探测循环，20 张/次）是**同一个病的两条路径**。
   */
  private static ALBUM_YIELD_EVERY: number = 5;

  private static awaitDialog(helper: photoAccessHelper.PhotoAccessHelper,
                             srcUris: string[],
                             cfgs: photoAccessHelper.PhotoCreationConfig[]): Promise<string[]> {
    return new Promise<string[]>((resolve: (v: string[]) => void,
                                 reject: (e: Error) => void) => {
      let settled: boolean = false;
      const timer: number = setTimeout(() => {
        if (!settled) {
          settled = true;
          reject(new Error('showAssetsCreationDialog 超时未返回'));
        }
      }, Index.DIALOG_TIMEOUT_MS);
      helper.showAssetsCreationDialog(srcUris, cfgs).then((u: string[]) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        resolve(u);
      }).catch((e: Object) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        reject(e as Error);
      });
    });
  }

  /**
   * ★ 5.0.54：不依赖 UI 刷新的**自驱重试**。
   *
   * ⚠️ 为什么需要：`flushAutoSave` 只在「消息变化 / 文件列表刷新」时被调用。
   *   真机 14:53:42 那次确认框不返回之后，直到用户把应用切后台再切回来
   *   （触发 refreshReceived）才恢复 —— 中间 108 秒完全静默。
   *   有了它，超时后 3 秒自己再试一次。
   */
  private scheduleAutoSaveRetry(delayMs: number): void {
    if (this.autoSaveTimer >= 0) {
      clearTimeout(this.autoSaveTimer);
    }
    this.autoSaveTimer = setTimeout(() => {
      this.autoSaveTimer = -1;
      if (this.autoSaveBusy || this.autoSavePending.length === 0) {
        return;
      }
      this.service.logAuto(`定时重试存相册（队列 ${this.autoSavePending.length} 项）`);
      this.flushAutoSave();
    }, delayMs);
  }


  /**
   * 删沙箱副本之前，先缓存一张 320px 的小图 —— 气泡缩略图之后的**唯一**来源。
   *
   * ⚠️ 为什么必须缓存：沙箱那份删掉后 `recvIndex` 里就没它了，
   *    而相册那份的 URI 是「写授权」，回头再去读不一定读得到。
   *    趁**还握着沙箱原文件**的时候把缩略图落进 `cacheDir` 最稳。
   *
   * @returns 缩略图路径；失败返回空串（气泡退回占位块，**不影响删除**）
   */  /**
   * 把收到的图/视频做成 320px 小图存进 `filesDir/album_thumbs`，
   * 供「沙箱副本已删」之后继续显示缩略图用。
   *
   * ⚠️ 5.0.42 为什么又重写一遍：5.0.40 / 5.0.41 都没修好「纵拍照片存进相册后缩略图变横」。
   *    根因是**旋转角度拿到的其实是 0** —— 系统 `getImageProperty(ORIENTATION)` 的返回值
   *    格式各版本不统一，解析不出就按「不转」处理，于是 pack 出来的小图是**物理躺着**的，
   *    而它又不带 EXIF，Image 也帮不上忙。
   *    这次不再猜：① **自己读 JPEG 字节拿 EXIF 方向**（位置是标准规定的，与设备实现无关）；
   *    ② pack 完**把小图再读回来验一次**横竖性；③ 万一还是不对，
   *    **直接复制原文件兜底**（那份带 EXIF，交给 Image 自己转）—— 宁可多占空间，也不给错方向。
   */
  /**
   * 5.0.49：`cacheThumbInner` 的**单飞包装**（见 `thumbInFlight` 的注释）。
   */
  private cacheThumb(ctx: common.UIAbilityContext, srcPath: string,
                     id: string): Promise<string> {
    const key: string = `${id}|${srcPath}`;
    const running: Promise<string> | undefined = this.thumbInFlight.get(key);
    if (running !== undefined) {
      return running;
    }
    const raw: Promise<string> = this.cacheThumbInner(ctx, srcPath, id);
    // 5.0.50：**8 秒超时兜底**。单飞表里一旦留下一个永不 settle 的 Promise，
    //   同 key 的后续调用（含存相册链路）就会全部卡在它身上 ——
    //   真机表现就是「收过一次图之后，再也不弹存相册框」。
    //   解码是纯本地活，8 秒还没结果就按失败处理（返回空串 = 气泡退回占位块），
    //   绝不能让它把整条链拖死。
    const p: Promise<string> = new Promise<string>((resolve: (v: string) => void) => {
      let done: boolean = false;
      const finish: (v: string) => void = (v: string) => {
        if (!done) {
          done = true;
          resolve(v);
        }
      };
      raw.then((v: string) => {
        finish(v);
      }).catch(() => {
        finish('');
      });
      setTimeout(() => {
        if (!done) {
          Log.w(TAG, `缩略图解码超时 8s，放弃: ${srcPath}`);
        }
        finish('');
      }, 8000);
    });
    this.thumbInFlight.set(key, p);
    // ⚠️ 这里必须挂 catch：这个「清理链路」不能自己变成未处理的 rejection
    p.then(() => {
      this.thumbInFlight.delete(key);
    }).catch(() => {
      this.thumbInFlight.delete(key);
    });
    return p;
  }

  private async cacheThumbInner(ctx: common.UIAbilityContext, srcPath: string,
                                id: string): Promise<string> {
    let pm: image.PixelMap | null = null;
    let gen: media.AVImageGenerator | null = null;
    let f: fileIo.File | null = null;
    // 5.0.49：ImageSource 也提到外层 —— 之前只在**成功路径**里释放，
    //         中间任何一步抛异常就漏一个原生 ImageSource（累积就是闪退）。
    let srcRef: image.ImageSource | null = null;
    // 这三项要带到方法末尾做「最终验证」，所以提到外层声明
    let srcW: number = 0;
    let srcH: number = 0;
    let deg: number = 0;
    // 5.0.49：原来是实例字段 `pendingRot`，并发调用时会互相串台（方向错乱）→ 改局部
    let pendRot: number = 0;
    // ★ 5.0.60：带 EXIF 方向（deg≠0）时**直接走原图缓存**，不做物理旋转。
    //   理由见下方校验块（物理旋转会转错方向，而校验只看横竖性、抓不到）。
    let preferFull: boolean = false;
    try {
      if (this.isVideoName(srcPath)) {
        // 视频：取离 0 最近的关键帧当封面（与 decodeVideoThumb 同一套取法）
        f = fileIo.openSync(srcPath, fileIo.OpenMode.READ_ONLY);
        gen = await media.createAVImageGenerator();
        gen.fdSrc = { fd: f.fd };
        pm = await gen.fetchFrameByTime(
          0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: -1, height: -1 });
      } else {
        const src: image.ImageSource = image.createImageSource(srcPath);
        srcRef = src;   // 5.0.49：登记到外层，保证异常路径也能释放
        // 5.0.40：解码**不会**应用 EXIF，而 pack 出来的 jpg 也不带 orientation，
        //         所以必须在这里把像素物理转正（见方法头注释的根因）。
        let degApi: number = 0;
        let degRaw: number = 0;
        let oriRaw: string = '';
        try {
          oriRaw = await src.getImageProperty(image.PropertyKey.ORIENTATION);
          degApi = Index.exifDeg(oriRaw);
        } catch (x) {
          // 没 EXIF / 这个格式不支持读 EXIF —— 按不转处理
          degApi = 0;
        }
        // 5.0.42：系统 API 的返回值格式在不同版本/设备上不统一，解析不出来就是 0。
        //         用「自己读 JPEG 字节」的结果补位 —— EXIF 在哪儿是标准规定的，与实现无关。
        degRaw = Index.jpegExifDeg(srcPath);
        deg = degApi !== 0 ? degApi : degRaw;
        // ★ 5.0.60：只要带方向就改走原图缓存（见下方校验块的长注释）
        preferFull = (deg !== 0);
        // 三个值都打出来：下次再不对，一眼看出到底卡在哪一环
        Log.i(TAG, `EXIF ${Index.baseName(srcPath)}: api='${oriRaw}'->${degApi}, bytes=${degRaw}, use=${deg}`);
        const info: image.ImageInfo = src.getImageInfoSync(0);
        srcW = info.size.width;
        srcH = info.size.height;
        // 5.0.49：极端尺寸保护 —— 有些全景图宽度上万，即使按 320 出缩略图，
        //         部分实现仍会先分配整张原图的缓冲，直接 OOM 闪退。
        //         宁可不出缩略图（气泡退回占位块），也不能把应用整个弄崩。
        if (srcW <= 0 || srcH <= 0 || srcW > 16384 || srcH > 16384) {
          Log.w(TAG, `原图尺寸异常 ${srcW}x${srcH}，跳过缩略图解码: ${srcPath}`);
          return '';
        }
        const w: number = srcW;
        const h: number = srcH;
        const longest: number = w > h ? w : h;
        // ★★ 5.1.71 B：320 → **224**。气泡是 48vp，224px 足够覆盖 2~3 倍屏密度。
        //   解码耗时与像素数近似线性 ⇒ (224/320)² ≈ 0.49 ⇒ 理论上省一半。
        //   （真正省时间的是「存相册阶段跳过解码」；这条是叠加收益，
        //     且**对懒生成路径同样有效** —— 滚动到时生成的缩略图也变小。）
        const s: number = longest > 224 ? 224 / longest : 1;
        // desiredSize 直接按目标尺寸解码 —— 4K 原图整张进内存太贵。
        // ⚠️ editable 必须给 true：不可编辑的 PixelMap 上写像素类操作（含 rotate）会失败。
        pm = await src.createPixelMap({
          desiredSize: {
            width: Math.max(1, Math.round(w * s)),
            height: Math.max(1, Math.round(h * s))
          },
          rotate: deg,
          editable: true
        });
        // 5.0.50：**不能 await**。`release()` 的 Promise 在异常态（重复释放 /
        //   服务忙）可能**永不 settle**，一旦 await 就把它变成整条链的挂起点
        //   （配合单飞表 = 永久卡死，真机表现就是「之后再也不弹存相册框」）。
        //   改用 `.catch()`：同样接住异步 rejection（5.0.49 的闪退防护不丢），
        //   但绝不阻塞流程。
        src.release().catch(() => {
          // 释放失败 / 已经释放过，都不影响缩略图
        });
        srcRef = null;
        // ---- 运行时验证：解码时那一步 rotate 到底生效没有 ----
        // 判据：90/270 时「横竖性」必须翻转（原来是横的就得变竖的）。
        let turned: boolean = false;
        if (pm !== null && Index.isQuarter(deg)) {
          try {
            const after: image.ImageInfo = pm.getImageInfoSync();
            turned = (after.size.width > after.size.height) !== (w > h);
          } catch (x) {
            turned = false;
          }
        }
        if (pm !== null && deg !== 0 && !turned) {
          // 解码那步没转 -> 补一次显式 rotate，再验一次
          try {
            await pm.rotate(deg);
            if (Index.isQuarter(deg)) {
              const after2: image.ImageInfo = pm.getImageInfoSync();
              turned = (after2.size.width > after2.size.height) !== (w > h);
            } else {
              turned = true;
            }
          } catch (x) {
            Log.w(TAG, `缩略图物理旋转失败，改用显示层补转: ${deg} ${srcPath}`);
          }
        }
        if (deg !== 0 && !turned) {
          // 两条物理路都不通 —— 记下来，交给 Image.orientation() 在显示层补
          Log.w(TAG, `物理旋转均未生效，显示层补转 ${deg}度: ${srcPath}`);
          pendRot = deg;
        }
      }
      if (pm === null) {
        return '';
      }
      const inf: image.ImageInfo = pm.getImageInfoSync();
      const iw: number = inf.size.width;
      const ih: number = inf.size.height;
      const longest2: number = iw > ih ? iw : ih;
      if (longest2 > 320) {
        const s2: number = 320 / longest2;
        await pm.scale(s2, s2);
      }
      const packer: image.ImagePacker = image.createImagePacker();
      const buf: ArrayBuffer = await packer.packing(pm, { format: 'image/jpeg', quality: 80 });
      // 5.0.50：两个 release 都不 await —— 结果不重要，绝不能阻塞编码路径
      packer.release().catch(() => {
        // 忽略
      });
      pm.release().catch(() => {
        // 忽略
      });
      pm = null;
      // ⚠️ 5.0.43：从 `cacheDir` 挪到 `filesDir` —— 鸿蒙**会清 cacheDir**（存储压力下，
      //    应用重启也可能丢），缩略图一丢就又变回「点气泡跳文件 tab」了。
      const dir: string = `${ctx.filesDir}/album_thumbs`;
      try {
        fileIo.mkdirSync(dir);
      } catch (x) {
        // 目录已存在 —— 正常情况
      }
      const out: string = `${dir}/${id}.jpg`;
      // ★★★ 5.0.67：**缓存已存在且非空 ⇒ 直接复用，不截断重写。**
      //
      // 背景：预生成（5.0.63 的 maybePrefetchThumb）与存相册（autoSaveAlbumBatch
      // 里的 cacheThumb）写的是**同一个路径** `${filesDir}/album_thumbs/<key>.jpg`
      // —— 路径只由 key 决定，幂等。而下面的 openSync 带 **TRUNC**，会把已有文件
      // 清空重写；此刻气泡正在显示这张图，`Image` 读到被截断的内容 ⇒ **闪一下**。
      //   ⇒ 这是**文件层面的原地覆盖**，与 key / 重渲染次数 / rows 结构全都无关，
      //     所以那些手段一个都治不了它。只能「不覆盖」。
      //
      // ⚠️ 为什么必须额外判「非空」：TRUNC 打开的瞬间文件大小就是 0。
      //   若此刻另一个协程正在写（同 key 的预生成与存相册可能并发），
      //   只判「存在」会误判为已就绪而返回**半截文件**，比闪更糟。
      // ⚠️ 这是 5.0.45 那条注释（「源文件就是已有缓存缩略图时不要再 cacheThumb
      //   一遍，否则等于自己解码自己再写回同一路径，有把缓存图写坏的风险」）
      //   在**自动存相册**路径上的补全 —— 手动那条早有保护，自动这条一直漏着。
      try {
        const st: fileIo.Stat = fileIo.statSync(out);
        if (st.size > 0) {
          Log.i(TAG, `缓存小图已就绪，复用不重写（避免截断闪烁）: ${Index.baseName(out)}`);
          return out;
        }
      } catch (x) {
        // 不存在（或读不到）—— 正常情况，继续生成
      }
      const fo: fileIo.File = fileIo.openSync(out,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.TRUNC);
      try {
        fileIo.writeSync(fo.fd, buf);
      } finally {
        fileIo.closeSync(fo);
      }
      // ---- 5.0.42 终极验证：把刚写出去的小图再读回来，看它的横竖性对不对 ----
      // 前面任何一环（EXIF 解析 / decode rotate / pm.rotate / packing）出问题，都会在这里暴露。
      if (srcW > 0 && srcH > 0) {
        let ok: boolean = true;
        let gw: number = 0;
        let gh: number = 0;
        try {
          const chk: image.ImageSource = image.createImageSource(out);
          const ci: image.ImageInfo = chk.getImageInfoSync(0);
          gw = ci.size.width;
          gh = ci.size.height;
          // 5.0.50：理由同 src.release() —— 不 await，只挂 catch
          chk.release().catch(() => {
            // 忽略
          });
          // 「转完之后该是竖的还是横的」：只有 90/270 会翻转横竖性，180 不会
          const wantTall: boolean = Index.isQuarter(deg) ? !(srcH > srcW) : (srcH > srcW);
          const gotTall: boolean = gh > gw;
          ok = (wantTall === gotTall);
        } catch (x) {
          // 校验本身失败就别折腾了，按成功处理（宁可不兜底，也别把能用的图丢掉）
          ok = true;
        }
        // ★ 5.0.60：**只要 deg≠0 就直接走原图缓存，不信任物理旋转。**
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
          }
          // 兜底：直接复制沙箱原文件 —— 它**带着 EXIF**，Image 会自己转正，
          //       跟「弹窗那一刻显示沙箱原图」是完全同一条路，方向必定正确。
          //       代价是 cacheDir 里多一份原图（只在前面全失败时才会走到这儿）。
          try {
            fileIo.unlinkSync(out);
          } catch (x) {
            // 删不掉也无所谓，下面换文件名
          }
          let ext: string = '';
          const dot: number = srcPath.lastIndexOf('.');
          if (dot >= 0 && srcPath.length - dot <= 6) {
            ext = srcPath.substring(dot);
          }
          const fullPath: string = `${dir}/${id}_full${ext}`;
          try {
            fileIo.unlinkSync(fullPath);
          } catch (x) {
            // 目标不存在 —— 正常情况
          }
          try {
            fileIo.copyFileSync(srcPath, fullPath);
            const swapF: boolean = Index.isQuarter(deg);
            const fw: number = swapF ? srcH : srcW;
            const fh: number = swapF ? srcW : srcH;
            this.mediaRatio.set(fullPath, Index.clampRatio(fw / fh));
            // -1 = 这份缓存**保留了 EXIF** —— 显示层必须 AUTO，让 Image 自己转
            this.service.albumRotMap.set(fullPath, -1);
            this.thumbTick++;
            return fullPath;
          } catch (x) {
            Log.w(TAG, `原图缓存兜底也失败，只能沿用小图: ${srcPath}`);
          }
        }
      }
      // 记下真实比例：气泡的缩略图框按它算，不然又变正方形。
      // ⚠️ 物理没转成、要靠显示层补转时，`iw/ih` 还是「躺着」的比例 ——
      //    框必须按**转完之后**的给（90/270 就是交换宽高），否则内容转了框没转，
      //    Contain 出来就是「竖图塞在横框里」。
      if (iw > 0 && ih > 0) {
        const swap: boolean = Index.isQuarter(pendRot);
        const rw: number = swap ? ih : iw;
        const rh: number = swap ? iw : ih;
        this.mediaRatio.set(out, Index.clampRatio(rw / rh));
        this.thumbTick++;
      }
      // 缓存小图是「我们自己 pack 的、不带 EXIF」的图，Image 不会替我们转，
      // 所以这里必须明确告诉显示层还要不要补转（0 = 已物理转正，别再转）。
      // 5.0.44：把这个角度同步到 service，setAlbumIndex 会一起持久化。
      this.service.albumRotMap.set(out, pendRot);
      return out;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `缓存缩略图失败: ${err.code} ${err.message} ${srcPath}`);
      return '';
    } finally {
      if (gen !== null) {
        // 5.0.50：**finally 里的 await 最危险** —— 它会让整个方法永不返回，
        //   进而把单飞表里这个 Promise 永久钉住。改成非阻塞。
        gen.release().catch(() => {
          // 忽略
        });
      }
      if (srcRef !== null) {
        // 5.0.49：异常路径下 ImageSource 的兜底释放（之前会漏）
        // 5.0.50：同样不能 await（理由见上面 src.release() 处）
        srcRef.release().catch(() => {
          // 已经释放过 / 释放失败都不影响
        });
      }
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
  }

  /** 相册索引的第 n 段：0 = 相册 URI，1 = 缩略图缓存路径 */
  private albumPart(id: string, part: number): string {
    const raw: string = this.albumIndex.get(id) ?? '';
    if (raw.length === 0) {
      return '';
    }
    const segs: string[] = raw.split('|');
    return part >= 0 && part < segs.length ? segs[part] : '';
  }

  /**
   * 气泡缩略图的来源 —— **恒定源**（缓存小图优先，见 `mediaThumbSrcOf`）。
   *
   * ★ 5.0.61：从 `mediaSrcOf` 换成 `mediaThumbSrcOf`。两者取图的取舍不同：
   *   缩略图只要「稳定 + 够清楚」，而沙箱原图换来的是每次存相册一次全屏重建。
   *   点开大图那条路（`onFileBubbleClick` → 画廊 / 全屏预览）走的仍是 `mediaSrcOf`，
   *   清晰度不受影响。
   */
  private bubbleMediaPath(m: ChatMessage): string {
    // ★ 5.0.52：气泡显示的是**这一批里的第 1 张**，缩略图必须取第 1 张自己的那份。
    //   （5.0.51 之前取的是「这条消息那唯一一个槽位」= 一批里最后写进去的那张，
    //    于是「缩略图显示的不是刚收到的那张」。）
    return this.mediaThumbSrcOf(m, 0);
  }

  /**
   * 点一下「收到文件」气泡。
   *
   * 5.0.39（vivi 要求）：已经存进相册的图/视频 -> **直接跳系统相册**；
   *   还没存的（用户当时点了取消 / 自动存关着）-> 走原来那条应用内预览；
   *   其余（非媒体、或文件找不着）-> 跳「文件」页。
   */
  private onFileBubbleClick(m: ChatMessage): void {
    // ★ 5.0.52：全部按**每一张图**记账（key = `消息id#媒体序号`）。
    //   气泡显示的是这一批的第 1 张，所以这里也只处理第 1 张的相册条目。
    const key0: string = Index.albumKeyOf(m.id, 0);
    const album: string = this.albumPartOf(m.id, 0, 0);
    if (album.length > 0) {
      // 5.0.49：先确认相册里那份**还在**。
      //   用户可能已经在系统相册里把它删了 —— 那时直接 startAbility 会跳进
      //   一个**空白相册页**，而且没有任何提示（vivi 2026-10-02 反馈）。
      if (this.albumAssetAlive(album)) {
        this.openInGallery(album);
        return;
      }
      this.toast('该文件已从相册删除');
      this.service.logAuto(`相册资产已不存在（已从相册删除），摘掉失效 URI：${key0}`);
      this.service.clearAlbumUri(key0);
      this.albumIndex = this.service.albumSnapshot();
      // 降级：还有缓存的 320px 小图就打开它，至少让用户看到内容
      const gone: string = this.albumPartOf(m.id, 0, 1);
      if (gone.length > 0 && this.isMediaName(gone)) {
        this.openMediaPreview(gone, m.content, key0);
      }
      return;
    }
    // 还没存相册：一张 -> 直接预览；一批 -> 进画廊左右滑（每页各自对应自己的相册条目）
    if (this.mediaNamesOf(m).length > 1) {
      if (this.openChatGallery(m.id, 0)) {
        return;
      }
      this.openFileTab();
      return;
    }
    const src: string = this.mediaSrcOf(m, 0);
    if (src.length > 0 && this.isMediaName(src)) {
      this.openMediaPreview(src, m.content, key0);
      return;
    }
    // 5.0.50（vivi 要求）：**不再自动补存相册**。
    //   5.0.45 这里会把「只剩缓存缩略图」的图悄悄存回相册 ——
    //   用户在系统相册里删掉之后再点，它就被偷偷存回来了，等于删不掉。
    //   现在统一：只提示 + 用缓存小图在应用内看，绝不再写相册。
    const thumb: string = this.albumPartOf(m.id, 0, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.toast('该文件已从相册删除');
      this.openMediaPreview(thumb, m.content, key0);
      return;
    }
    this.openFileTab();
  }

  /**
   * 相册里那一份**还在不在**（5.0.51 重写：stat + 只读读字节，见方法内注释）。
   */
  /**
   * ★ 5.0.75（vivi 20:21）：切到消息 tab 时**全量**探一次「相册资产还在不在」。
   *
   * 【为什么需要】`albumAssetAlive` 的三信号探测（5.0.51 定的）此前**只在
   *   点击气泡时**跑（`onFileBubbleClick`），是被动的、且只查被点的那一张。
   *   用户在系统相册里删了图，气泡上**没有任何提示**，只有点它才弹
   *   「该文件已从相册删除」⇒ 体验上像是「列表没刷新」。
   *
   * 【做法】遍历 `albumIndex` 所有 key，对**有 uri** 的逐个探，死掉的
   *   `clearAlbumUri(key)`（**只清 uri、保留缩略图** —— 气泡还能显示小图）。
   *
   * ⚠️ **必须复用 `albumAssetAlive`，不新造判据**：那套三信号
   *   （stat size>0 → 只读打开真读几字节）是踩过坑定下来的 ——
   *   **写打开只能证伪**、stat/读打开可能**一律失败**（≠ 不存在，5.0.52 定案）。
   *   换一套必然退化成「全判为已删」或「永远判为还在」。
   * ⚠️ **同步 IO 必须让帧**：`albumAssetAlive` 是 `statSync`/`openSync`/`readSync`，
   *   一批几十张会把主线程占住掉帧 ⇒ 先 `yieldOnce()` 再逐个探。
   * ⚠️ **节流**：`albumClearedIds` 记住刚清过的 id ⇒ 同一批死 uri 不重复探。
   * ⚠️ **只清索引、不删缓存小图**：用户删的是**系统相册**里那份，我们自己的
   *   320px 缓存还要留着显示，否则气泡变空白（5.0.52~5.0.56 稳定下来的行为）。
   * ⚠️ 全程 try/catch：探测失败**绝不能**影响切 tab。
   */
  private async probeAlbumOnEnterChat(): Promise<void> {
    // ★★ 5.1.70：**重入闸门**。原来切 tab 会触发、点击气泡也会触发，
    //   两路并发时会对同一批 uri 重复探一遍（426 张 = 白干）。
    if (this.albumProbeRunning) {
      return;
    }
    this.albumProbeRunning = true;
    try {
      await Index.yieldOnce();
      let checked: number = 0;
      const dead: string[] = [];
      // ★★ 5.1.66 C1b：**循环内**周期性让帧。
      //   `albumAssetAlive` 是纯同步 IO（statSync / openSync / readSync），
      //   400+ 张逐个探会把主线程占死 ⇒ 切消息页卡住（vivi 2026-10-05 实测）。
      //   ⚠️ 原实现只在**循环之前**调了一次 `yieldOnce()`，那等于没让 ——
      //   几百张的 IO 全挤在第一次让帧之后的整段里。
      //   ⇒ 每 PROBE_YIELD_EVERY 张让一帧，把单次连续占用压到 20 张的量。
      let sinceYield: number = 0;
      for (const key of this.albumIndex.keys()) {
        // key 形如 `消息id#序号`；只看 part 0（相册 uri）
        const uri: string = this.albumPart(key, 0);
        if (uri.length === 0 || this.albumClearedIds.has(key)) {
          continue;
        }
        checked += 1;
        sinceYield += 1;
        if (sinceYield >= Index.PROBE_YIELD_EVERY) {
          sinceYield = 0;
          await Index.yieldOnce();
        }
        if (!this.albumAssetAlive(uri)) {
          dead.push(key);
        }
      }
      // 收尾再让一帧：最后不足一批的也别把尾段留到下一帧
      if (sinceYield > 0) {
        await Index.yieldOnce();
      }
      if (dead.length === 0) {
        this.service.logAuto(`[切消息页] 相册资产全量探测：${checked} 条，未发现被删`);
        return;
      }
      this.beginStateSwap();
      try {
        for (let i: number = 0; i < dead.length; i++) {
          this.service.clearAlbumUri(dead[i]);
          this.albumClearedIds.add(dead[i]);
          Log.i(TAG, `切消息页探测：相册资产已不存在，摘掉失效 URI：${dead[i]}`);
        }
        this.swapAlbumIndex();
      } finally {
        this.endStateSwap();
      }
      this.service.logAuto(`[切消息页] 相册资产探测：${checked} 条，`
        + `发现 ${dead.length} 条已被用户从相册删除（角标会更新）`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // ⚠️ 探测失败**绝不能**影响切 tab，只记日志
      this.service.logAuto(`切消息页相册探测异常（已忽略）：${err.code} ${err.message}`);
    } finally {
      this.albumProbeRunning = false;
    }
  }

  /**
   * ★★ 5.1.70（vivi 要求）：相册资产探测改为**后台静默**。
   *
   * 【原来】只在「切到消息 tab」时跑 `probeAlbumOnEnterChat()`
   *   ⇒ 426 张时切页必卡（每 20 张让一帧也救不了，扫盘 + 打开 + 读字节本身就要时间）。
   *
   * 【现在】`onPageShow`（应用回前台）就启动一次，
   *   **与 tab 切换完全解耦** ⇒ 用户什么时候切页都不再触发探测。
   *
   * 【为什么不直接 `void` 掉不 await】探测是 async；
   *   `onPageShow` 里不 await ⇒ 不阻塞启动流程，但**闸门 + 静默日志**保证不重入。
   *
   * ⚠️ 「已删除」的处置**完全不变**（清 uri + 更新角标 + 一条汇总日志），
   *   只是**不再占用切页那一帧**。
   */
  private scheduleBackgroundAlbumProbe(): void {
    this.probeAlbumOnEnterChat();
  }

  private albumAssetAlive(uri: string): boolean {
    if (uri.length === 0) {
      return false;
    }
    const codes: string[] = [];
    // 信号①：stat（首选。不写内容、不创建任何东西；size>0 就确定还在）
    let statSize: number = -1;
    try {
      const st: fileIo.Stat = fileIo.statSync(uri);
      statSize = st.size;
      if (st.size > 0) {
        return true;
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      codes.push(`stat=${err.code}`);
    }
    // 信号②：只读打开，并且**真读几个字节**（读得到内容才算在）
    let f: fileIo.File | null = null;
    try {
      f = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      const buf: ArrayBuffer = new ArrayBuffer(16);
      const n: number = fileIo.readSync(f.fd, buf);
      if (n > 0) {
        return true;
      }
      codes.push('read=0');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      codes.push(`open=${err.code}`);
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (x) {
          // 忽略
        }
      }
    }
    // ★ 5.0.52：两个信号**都失败**时，**只有「明确不存在」(13900002) 才算真删了**。
    //   ⚠️ 5.0.51 把「都失败」一律判删除 —— 真机上 `showAssetsCreationDialog` 给的是
    //   **写授权** URI，读它可能因权限失败（≠ 文件不存在），于是**每一张图**都被
    //   谎报「已从相册删除」（vivi 2026-10-02：「删掉第一张后所有图片都提示已删除」）。
    //   宁可像 5.0.50 那样「判定不出来就照常跳相册」，也不要谎报删除。
    //   原始错误码照旧写进 UI 日志 —— 下一轮真机日志就能给出平台真相。
    const gone: boolean = codes.indexOf('stat=13900002') >= 0
      || codes.indexOf('open=13900002') >= 0;
    // ★ 5.0.52：结论还要受「探针可信度」约束 —— 见 `albumProbeCalibrate`。
    //   本机探针被证伪时，一律按「还在」处理（照常跳相册），**绝不谎报已删除**。
    const trusted: boolean = this.service.probeTrusted();
    this.service.logAuto(`相册探活：${gone ? '已不存在' : '判定不出（按还在处理）'}`
      + `（信任=${trusted ? 1 : 0}，statSize=${statSize}，信号: ${codes.join(' ')}）：${uri}`);
    return !(gone && trusted);
  }

  /**
   * ★ 5.0.52：拿**刚写进相册的资产**当场校准「探活」可信度。
   *
   * 为什么需要：这一秒我们刚把字节写进去，资产**必然存在**。
   *   此刻 `albumAssetAlive(uri)` 若判「不存在」，那唯一解释就是**探针本身不可信**
   *   （媒体 URI 是写授权，读它可能一律失败）—— 从此不再采信它的「已删除」结论，
   *   否则会把**每一张图**都谎报成「已从相册删除」（vivi 2026-10-02 报的正是这个）。
   * ⚠️ 单向翻：只允许 可信 -> 不可信；绝不因为某次「说还在」就恢复 ——
   *   说还在也可能是错误兜底，不构成探针有效的证据。
   */
  private albumProbeCalibrate(uri: string): void {
    if (!this.service.probeTrusted()) {
      return;
    }
    if (this.albumAssetAlive(uri)) {
      return;
    }
    this.service.setProbeTrusted(false);
    this.service.logAuto('刚写入的相册资产被判「不存在」⇒ 本机探针不可信，已关闭「已删除」提示');
    this.toast('本机无法校验相册状态，已关闭「已删除」提示');
  }

  /**
   * 跳系统相册看这一个资产。
   *
   * ⚠️ 包名两套都要试：HarmonyOS（华为手机）是 `com.huawei.hmos.photos`，
   *    OpenHarmony 是 `com.ohos.photos` —— 写死一个在另一种形态上必失败，
   *    而失败**没有任何界面提示**（startAbility 只是 reject），排查很浪费时间。
   * 5.0.49 这两行注释曾被误挂在 `albumAssetAlive` 头上（方法被插在注释与本体之间），
   * 5.0.51 归位。
   */
  private openInGallery(uri: string): void {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const p1: Record<string, Object> = { 'uri': uri };
    const w1: Want = {
      action: 'ohos.want.action.viewData',
      parameters: p1,
      bundleName: 'com.huawei.hmos.photos',
      abilityName: 'com.huawei.hmos.photos.MainAbility'
    };
    ctx.startAbility(w1).then(() => {
      Log.i(TAG, '已跳转相册');
    }).catch(() => {
      const p2: Record<string, Object> = { 'uri': uri };
      const w2: Want = {
        action: 'ohos.want.action.viewData',
        parameters: p2,
        bundleName: 'com.ohos.photos',
        abilityName: 'com.ohos.photos.MainAbility'
      };
      ctx.startAbility(w2).catch((e: BusinessError) => {
        Log.w(TAG, `跳转相册失败: ${e.code} ${e.message}`);
        this.toast('跳转相册失败');
      });
    });
  }

  /**
   * 把文件名压成系统允许的相册 title（非法字符统一换成下划线）。
   *
   * ★★ 5.0.54：**`title` 里绝不能带 `.`** —— 它的语义是「不含后缀的文件名」，
   *   带点的 title 会让系统**建不出资产**。真机证据（vivi 2026-10-02）：
   *   一次提交 4 个只回来 2 个 URI，而挂掉的恰好就是两个 title 带点的
   *   （`screenshot_..._com.fgsqw.lanshare`、`扫描全能王 2026-09-22 22.33`），
   *   另两个不带点的正常 —— 4 个里挂 2 个，与「4 张只成功 2 张」**逐个对上**。
   *   旧实现的非法字符表漏了点，只换 `\/:*?"'`<>|{}[]`。
   */
  private static safeAlbumTitle(raw: string): string {
    const bad: string = '\\/:*?"\'`<>|{}[].';
    let out: string = '';
    for (let i = 0; i < raw.length; i++) {
      const c: string = raw.substring(i, i + 1);
      out += bad.indexOf(c) >= 0 ? '_' : c;
    }
    if (out.length === 0) {
      out = 'image';
    }
    if (out.length > 200) {
      out = out.substring(0, 200);
    }
    return out;
  }

  /**
   * ★ 5.0.54：把一批 title 去重（第 2 个起追加 `_2`、`_3`…）。
   *
   * ⚠️ 系统对**同名同后缀**的多个资产会少建 —— 一批里出现两个 `IMG_0001`
   *   （对端真发了两张同名图，或截断到 200 字后重名）时，就会重演
   *   「提交 N 个只回来 M 个」的错位。去重是零成本的防御。
   */
  private static uniqueAlbumTitles(raw: string[]): string[] {
    const out: string[] = [];
    const seen: Map<string, number> = new Map<string, number>();
    for (let i: number = 0; i < raw.length; i++) {
      const t: string = raw[i];
      const n: number = seen.get(t) ?? 0;
      seen.set(t, n + 1);
      out.push(n === 0 ? t : `${t}_${n + 1}`);
    }
    return out;
  }

  /**
   * 让出一帧，给 UI 一次上屏的机会。
   *
   * ⚠️ 用途只有一个：`ExportService.copyTo` 是**同步**拷贝（见其实现），
   *    视频几百 MB 会按住主线程数秒。先 toast 再让一帧，用户至少看得到「正在保存」。
   */
  private static async yieldOnce(): Promise<void> {
    await new Promise<void>((resolve: (value: void) => void) => {
      setTimeout(() => {
        resolve();
      }, 30);
    });
  }

  /**
   * 这条路径的首帧解出来了没有。
   *
   * ⚠️ 拆成「查询 + 取值」两个方法是为了**建立 @State 依赖**：
   *    `videoThumbs` 是普通 Map，在渲染里读它不会让组件重绘；
   *    这里读一下 `videoThumbTick`，解码完成（tick +1）时调用方就会重新执行。
   */
  private hasVideoThumb(path: string): boolean {
    if (this.videoThumbTick < 0) {
      return false;
    }
    // 5.0.34：轮到渲染视频缩略图时还没解出来，就**按需**触发一次首帧解
    // （异步、busy 去重；放在表达式上下文调用，@Builder 顶层不允许裸方法调用）。
    if (!this.videoThumbs.has(path)) {
      this.ensureVideoThumb(path);
    }
    return this.videoThumbs.has(path);
  }

  /**
   * 取首帧。**调用前必须先用 `hasVideoThumb()` 判过。**
   *
   * ⚠️ 返回类型带 `undefined` 是因为 `Map.get()` 本来就能返回它 ——
   *    渲染处用 `as image.PixelMap` 收敛（ArkTS 不做跨方法调用的类型收窄，
   *    而 `Image()` 又不接受 `undefined`）。
   */
  private videoThumbOf(path: string): image.PixelMap | undefined {
    return this.videoThumbs.get(path);
  }

  /**
   * 预热一批视频的首帧缩略图。
   *
   * ⚠️ 为什么不在 `@Builder` 里按需触发：`@Builder` 每次重绘都会重新执行，
   *    在里面启动异步解码 = 每次重绘都提交一次（虽然有 busy 表挡着，但那是治标）。
   *    把副作用放在**数据刷新**这条路径上（`refreshReceived` 末尾），渲染就保持纯粹。
   */
  private prewarmVideoThumbs(list: ReceivedFile[]): void {
    for (let i = 0; i < list.length; i++) {
      if (this.isVideoName(list[i].name)) {
        this.ensureVideoThumb(list[i].path);
      }
    }
    // 消息里那条 `kind='file'` 记录带的是**对端发来的原名**，落盘名可能被加了
    // 重名后缀 —— 路径走 `recvIndex` 反查（与气泡显示缩略图用的是同一张表）。
    for (let i = 0; i < this.chat.length; i++) {
      const m: ChatMessage = this.chat[i];
      if (m.kind === 'file' && m.incoming && this.isVideoName(m.content)) {
        const p: string | undefined = this.recvIndex.get(m.content);
        if (p !== undefined) {
          this.ensureVideoThumb(p);
        }
      }
    }
  }

  /** 提交一次解码（已解过 / 正在解 / 空路径直接跳过） */
  private ensureVideoThumb(path: string): void {
    if (path.length === 0 || this.videoThumbBusy.has(path) || this.videoThumbs.has(path)) {
      return;
    }
    this.videoThumbBusy.add(path);
    this.decodeVideoThumb(path).catch(() => {
      // 内部已有 try/catch，这里只兜底，避免未处理的 Promise
    });
  }

  /**
   * 解一条视频的首帧。
   *
   * ⚠️ 三个必须守住的点：
   *    ① fd **要活到 `fetchFrameByTime` 返回**（提前 close 直接解不出来）；
   *    ② `release()` 是 Promise，要 await；
   *    ③ 取「离 0 最近的关键帧」而不是第 0 帧 —— 不少视频开头是纯黑，
   *       关键帧才是真正有画面的那一帧。
   */
  private async decodeVideoThumb(path: string): Promise<void> {
    let f: fileIo.File | null = null;
    let gen: media.AVImageGenerator | null = null;
    try {
      f = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
      gen = await media.createAVImageGenerator();
      const desc: media.AVFileDescriptor = { fd: f.fd };
      gen.fdSrc = desc;
      // ⚠️ 5.0.31：**不能**再传 {width:192,height:192}。PixelMapParams 的语义是
      //    「按给定宽高缩放」（SDK media.d.ts：值须 >0 且 <= 原视频宽高，否则不缩放），
      //    给正方形就是把 16:9 硬拉成 1:1 —— 视频缩略图变形的根因。
      //    这里传 -1 取**原尺寸首帧**，量出真实比例后再等比缩到 320 以内。
      let pm: image.PixelMap | null = null;
      try {
        pm = await gen.fetchFrameByTime(
          0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: -1, height: -1 });
      } catch (e1) {
        // 个别版本不接受 -1：退回固定尺寸，宁可小一点也不留空白
        pm = await gen.fetchFrameByTime(
          0, media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST_SYNC, { width: 192, height: 192 });
      }
      if (pm !== null) {
        try {
          const info: image.ImageInfo = pm.getImageInfoSync();
          const vw: number = info.size.width;
          const vh: number = info.size.height;
          if (vw > 0 && vh > 0) {
            this.mediaRatio.set(path, Index.clampRatio(vw / vh));
            const longest: number = vw > vh ? vw : vh;
            // ★ 5.1.71 B：视频封面同样 320 → 224（与 cacheThumb 的图片缩略图一致）。
            //   ⚠️ 这处是**第一次语义自检抓出来的**（'320 阈值仍在'）——
            //   漏改会让视频封面仍是 320px，两类媒体的缩略图尺寸不一致。
            if (longest > 224) {
              const s: number = 224 / longest;
              await pm.scale(s, s);
            }
          }
        } catch (x) {
          // 量不到比例就按正方形处理，不影响显示
        }
        this.videoThumbs.set(path, pm);
        // @State 计数器自增 —— Map 本身不是可观察对象，靠它把重绘踢起来
        this.videoThumbTick++;
        this.thumbTick++;
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `解视频首帧失败: ${err.code} ${err.message} ${path}`);
    } finally {
      this.videoThumbBusy.delete(path);
      if (gen !== null) {
        // 5.0.50：finally 里的 await 会让整个方法永不返回 —— 改成非阻塞
        gen.release().catch(() => {
          // 忽略
        });
      }
      if (f !== null) {
        try {
          fileIo.closeSync(f);
        } catch (e) {
          // 忽略
        }
      }
    }
  }

  /**
   * 全屏媒体预览（图片 = 缩放预览；视频 = 播放器）。
   *
   * `Image` 自身没有缩放能力，靠 `.scale()` + `.translate()` 做 ——
   * 所以放大后拖动的位移也要自己按倍率算（这里只做平移，不做边界回弹：
   * 照片查看器里那属于锦上添花，先保证不崩、不飘）。
   *
   * 关闭的三条路：顶栏「关闭」/ 双击复位后再点 / **系统返回键**（见 onBackPress）。
   * ⚠️ 刻意**不做**「单击任意处关闭」：放大状态下单击太容易误触，
   *    而双击复位本身就会吃掉单击。
   */
  @Builder
  imgPreviewView() {
    if (this.imgPreview.length > 0) {
      Stack({ alignContent: Alignment.Top }) {
        if (this.galleryPaths.length > 1) {
          // 5.0.31：一批图 —— Swiper 左右滑。单张时**不**走这里，
          //    保持 5.0.30 那条已验证的单图预览路径不动。
          Swiper(this.swiperCtl) {
            ForEach(this.galleryPaths, (p: string, i: number) => {
              this.mediaPreviewPage(p, this.galleryNameAt(i), i === this.galleryIndex,
                this.galleryKeyAt(i))
            }, (p: string) => p)
          }
          .index(this.galleryIndex)
          .width('100%')
          .height('100%')
          .loop(false)
          .indicator(false)
          .cachedCount(1)
          .onChange((idx: number) => {
            this.onGalleryPageChanged(idx);
          })
        } else {
          this.mediaPreviewPage(this.imgPreview, this.imgPreviewName, true, this.imgPreviewKey)
        }

        // 顶栏：文件名 + 关闭。文件名占满剩余宽度，放不下就省略号
        Row({ space: 10 }) {
          Text(this.imgPreviewName)
            .fontSize(13)
            .fontColor('#EAEAEA')
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          if (this.galleryPaths.length > 1) {
            Text(`${this.galleryIndex + 1}/${this.galleryPaths.length}`)
              .fontSize(13)
              .fontColor('#EAEAEA')
          }
          Button('存相册')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.saveImageToAlbum(this.imgPreview, this.imgPreviewName, this.imgPreviewKey))
          Button('关闭')
            .fontSize(13)
            .height(32)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#33FFFFFF')
            .fontColor(Color.White)
            .onClick(() => this.closeMediaPreview())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: this.topInset + 10 })
      }
      .width('100%')
      .height('100%')
      // 近黑底：看照片时最不干扰
      .backgroundColor('#F0000000')
    }
  }

  /**
   * 画廊的一页（图片 = 缩放预览；视频 = 播放器）。
   *
   * ⚠️ 只有**当前页**才挂 `Video`：多个 Video 共用同一个 `VideoController`
   *    行为未定义（stop 到底停哪个说不清），所以非当前页退回首帧缩略图 + ▶。
   */
  @Builder
  mediaPreviewPage(path: string, name: string, active: boolean, key: string) {
    Stack({ alignContent: Alignment.Center }) {
      if (this.isVideoName(name)) {
        if (active) {
          // 视频：交给 ArkUI 内置 `Video`（同进程读自己的沙箱，不需要任何权限）。
          // ⚠️ `src` 必须是 `fileUri.getUriFromPath()` 的沙箱 URI
          //    （`file://<bundleName>/<沙箱路径>`）—— 官方声明里明确支持这一形态，
          //    手拼的 `'file://' + path` 播不出来（同 `Image` 那个坑）。
          Video({ src: this.imageUri(path), controller: this.videoCtl })
            .width('100%')
            .height('100%')
            .objectFit(ImageFit.Contain)
            .controls(true)
            .autoPlay(true)
            .loop(false)
            .onError(() => {
              this.toast('无法播放这个视频（编码或封装格式不支持）');
            })
        } else {
          // 非当前页：只出首帧（解不出来就留个 ▶，滑到这一页时才真正起播放器）
          if (this.hasVideoThumb(path)) {
            Image(this.videoThumbOf(path) as image.PixelMap)
              .width('80%')
              .height('80%')
              .objectFit(ImageFit.Contain)
          }
          Text('▶')
            .fontSize(48)
            .fontColor('#FFFFFF')
        }
      } else {
        Image(this.imageUri(path))
          .width('100%')
          .height('100%')
          .objectFit(ImageFit.Contain)
          // 5.0.41：同上（预览可能显示沙箱原图，也可能是缓存小图，同一套判定）
          .orientation(this.thumbOri(path))
          .scale({ x: this.imgScale, y: this.imgScale })
          .translate({ x: this.imgOffX, y: this.imgOffY })
          .gesture(
            GestureGroup(GestureMode.Parallel,
              // 双指捏合缩放：1x ~ 8x
              PinchGesture({ fingers: 2 })
                .onActionUpdate((e: GestureEvent) => {
                  const s: number = this.imgPinchBase * e.scale;
                  this.imgScale = s < 1 ? 1 : (s > 8 ? 8 : s);
                })
                .onActionEnd(() => {
                  this.imgPinchBase = this.imgScale;
                  // 回到 1x 附近就顺手把位移归零，免得到处飘
                  if (this.imgScale <= 1.02) {
                    this.imgScale = 1;
                    this.imgPinchBase = 1;
                    this.imgOffX = 0;
                    this.imgOffY = 0;
                  }
                }),
              // 单指拖动：只在放大后生效（1x 时拖它就是浪费手势）
              PanGesture({ fingers: 1, distance: 6 })
                .onActionStart(() => {
                  this.imgDragBaseX = this.imgOffX;
                  this.imgDragBaseY = this.imgOffY;
                })
                .onActionUpdate((e: GestureEvent) => {
                  if (this.imgScale > 1) {
                    this.imgOffX = this.imgDragBaseX + e.offsetX;
                    this.imgOffY = this.imgDragBaseY + e.offsetY;
                  }
                }),
              // 双击：>1x 复位，=1x 放大到 2.5x（看细节不用两根手指）
              TapGesture({ count: 2 })
                .onAction(() => {
                  if (this.imgScale > 1) {
                    this.imgScale = 1;
                    this.imgPinchBase = 1;
                    this.imgOffX = 0;
                    this.imgOffY = 0;
                  } else {
                    this.imgScale = 2.5;
                    this.imgPinchBase = 2.5;
                  }
                }),
              // 长按存相册（vivi 2026-10-01：「点开图片后长按就能选择保存到相册」）。
              // 与捏合/拖动/双击并列在 Parallel 组里：长按时手指不动，
              // PanGesture 的 distance:6 不会触发，互不打架。
              LongPressGesture({ repeat: false, duration: 400 })
                .onAction(() => {
                  // ★ 5.0.52：用**这一页自己的** key，不是当前页的
                  this.saveImageToAlbum(path, name, key);
                })
            )
          )
      }
    }
    .width('100%')
    .height('100%')
  }

  private stateText(): string {
    switch (this.snapshot.state) {
      case ServiceState.RUNNING: return '共享中';
      case ServiceState.STARTING: return '启动中…';
      case ServiceState.FAILED: return '启动失败';
      default: return '未开启';
    }
  }

  private stateColor(): string {
    switch (this.snapshot.state) {
      case ServiceState.RUNNING: return '#64BB5C';
      case ServiceState.STARTING: return '#E8A33D';
      case ServiceState.FAILED: return '#E84026';
      default: return C_SUB;
    }
  }

  /** 共享是否处于"该起来但没起来"的状态（决定要不要露出重试入口） */
  private needRetry(): boolean {
    return !this.busy
      && this.snapshot.state !== ServiceState.RUNNING
      && this.snapshot.state !== ServiceState.STARTING;
  }

  // ==================================================================
  // UI 片段
  // ==================================================================

  @Builder
  tabBarItem(title: string, idx: number) {
    Column() {
      Text(title)
        .fontSize(14)
        .fontWeight(this.curTab === idx ? FontWeight.Medium : FontWeight.Normal)
        .fontColor(this.curTab === idx ? C_PRIMARY : C_SUB)
    }
    .width('100%')
    .height(50)
    .justifyContent(FlexAlign.Center)
  }

  /** 顶部的服务状态点（自动启动后基本恒为"共享中"） */
  @Builder
  stateChip() {
    Row({ space: 6 }) {
      Circle({ width: 8, height: 8 }).fill(this.stateColor())
      Text(this.stateText())
        .fontSize(13)
        .fontColor(this.stateColor())
    }
    .padding({ left: 10, right: 10, top: 4, bottom: 4 })
    .backgroundColor(C_CARD)
    .borderRadius(20)
  }

  /**
   * 访问地址卡片。
   *
   * 版式：**标题行（标签 + 本机名 + 复制 / 二维码）+ 网址独占一行**。
   * ⚠️ 网址绝不可与按钮同行 —— 见方法体里的原因说明。
   */
  @Builder
  addrCard() {
    Column({ space: 8 }) {
      // ⚠️ 网址**必须独占整行**：上一版把「复制 / 二维码」两个按钮和网址放同一行，
      //    网址用 `layoutWeight(1)` 只能拿到「剩余宽度」——
      //    360vp 屏上两个按钮吃掉约 130vp，留给 `http://192.168.10.146:5856`
      //    这种 26 字符的地址只剩 ~200vp，直接被省略号截断
      //    （vivi 2026-10-01 真机：「首页的网址显示不全了」）。
      //    现在把按钮上移到标题行、网址自己一行铺满整宽，任何常规地址都放得下。
      Row({ space: 8 }) {
        Text('访问地址')
          .fontSize(12)
          .fontColor(C_SUB)

        // 本机名放标题行、可压缩：设备名是用户数据，长名字让它省略，
        // 绝不能反过来去挤网址那一行
        Text(this.snapshot.deviceName.length > 0 ? this.snapshot.deviceName : '本机')
          .fontSize(12)
          .fontColor(C_SUB)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
          .textAlign(TextAlign.End)

        Button('复制')
          .fontSize(12)
          .height(28)
          .padding({ left: 12, right: 12 })
          .backgroundColor('#EAF0FF')
          .fontColor(C_PRIMARY)
          .enabled(this.snapshot.webUrl.length > 0)
          .onClick(() => this.copyUrl())

        // 二维码：省掉「输网址」这一步 —— 别的设备扫一下就能打开网页端
        Button('二维码')
          .fontSize(12)
          .height(28)
          .padding({ left: 12, right: 12 })
          .backgroundColor('#EAF0FF')
          .fontColor(C_PRIMARY)
          .enabled(this.snapshot.webUrl.length > 0)
          .onClick(() => this.openQr())
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.snapshot.webUrl.length > 0 ? this.snapshot.webUrl : '启动中…')
        .fontSize(17)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.snapshot.webUrl.length > 0 ? C_PRIMARY : '#AAAAAA')
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .width('100%')
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 12, bottom: 12 })
    .backgroundColor(C_CARD)
    .borderRadius(12)
  }

  /** 运行模式 + 网页授权 + 自检，合并成一张卡片 */
  @Builder
  runtimeCard() {
    Column({ space: 6 }) {
      // ---------------- 本机设备名（可手动修改） ----------------
      Row({ space: 8 }) {
        Text('本机名称')
          .fontSize(13)
          .fontColor('#666666')
        Blank()
        if (this.deviceNameEditing) {
          TextInput({ text: this.deviceNameDraft, placeholder: '输入设备名' })
            .layoutWeight(1)
            .height(32)
            .fontSize(13)
            .maxLength(20)
            .backgroundColor('#FFFFFF')
            .borderRadius(6)
            .onChange((v: string) => {
              this.deviceNameDraft = v;
            })
          Button('保存')
            .fontSize(12)
            .height(30)
            .padding({ left: 12, right: 12 })
            .backgroundColor(C_PRIMARY)
            .fontColor(Color.White)
            .onClick(() => this.saveDeviceName())
          Button('恢复默认')
            .fontSize(12)
            .height(30)
            .padding({ left: 12, right: 12 })
            .backgroundColor('#F2F2F2')
            .fontColor('#666666')
            .onClick(() => this.resetDeviceName())
          Button('取消')
            .fontSize(12)
            .height(30)
            .padding({ left: 12, right: 12 })
            .backgroundColor('#F2F2F2')
            .fontColor('#666666')
            .onClick(() => {
              this.deviceNameEditing = false;
            })
        } else {
          Row({ space: 6 }) {
            Text(this.snapshot.deviceName.length > 0 ? this.snapshot.deviceName : '本机')
              .fontSize(13)
              .fontColor(C_TEXT)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Button('编辑')
              .fontSize(11)
              .height(26)
              .padding({ left: 10, right: 10 })
              .backgroundColor('#EAF0FF')
              .fontColor(C_PRIMARY)
              .onClick(() => this.startEditDeviceName())
          }
          .alignItems(VerticalAlign.Center)
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Row({ space: 8 }) {
        Text('运行模式')
          .fontSize(13)
          .fontColor('#666666')
        Blank()
        Text(this.snapshot.sessionActive ? '前台服务中' : '未提供服务')
          .fontSize(13)
          .fontColor(this.snapshot.sessionActive ? '#64BB5C' : C_SUB)
        // 只在真的没起来时露出，正常路径下不占版面
        if (this.needRetry()) {
          Button('重试')
            .fontSize(11)
            .height(26)
            .padding({ left: 10, right: 10 })
            .backgroundColor('#FFECEA')
            .fontColor('#E84026')
            .onClick(() => this.retryStart())
        }
      }
      .width('100%')

      Text('本应用不申请后台保活：请保持本页面在前台。离开应用共享会自动暂停，切回来会自动恢复。')
        .fontSize(11)
        .fontColor(C_SUB)
        .width('100%')

      if (this.snapshot.sessionActive) {
        Text('传输期间已开启屏幕常亮，避免息屏打断连接')
          .fontSize(11)
          .fontColor(C_PRIMARY)
          .width('100%')
      }

      // 端到端自检结果 —— 专门用来区分「本机没监听上」「应用层不响应」「网络路径不通」。
      // 没有这一条时，界面显示 5856 但外部连不上，只能靠猜。
      if (this.snapshot.listenDetail.length > 0) {
        Row({ space: 8 }) {
          Text(`监听自检：${this.snapshot.listenDetail}`)
            .fontSize(11)
            .fontColor(this.snapshot.listenDetail.includes('自检通过') ? '#64BB5C' : '#E84026')
            .layoutWeight(1)
          Button(this.diagBusy ? '自检中…' : '重新自检')
            .fontSize(11)
            .height(26)
            .padding({ left: 10, right: 10 })
            .backgroundColor('#EAF0FF')
            .fontColor(C_PRIMARY)
            .enabled(!this.diagBusy && this.service.isRunning)
            .onClick(() => this.runDiag())
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
      }

      if (this.snapshot.saveLocation.length > 0) {
        Text(`接收文件保存到：${this.snapshot.saveLocation}`)
          .fontSize(11)
          .fontColor(C_SUB)
          .width('100%')
      }

      Divider().color('#F0F0F0').margin({ top: 4, bottom: 4 })

      // ---------------- 网页访问授权 ----------------
      Row({ space: 8 }) {
        Column({ space: 2 }) {
          Text('网页访问免确认')
            .fontSize(13)
            .fontColor(C_TEXT)
          Text(this.snapshot.webOpen
            ? '新设备可直接打开网页，无需在本机确认'
            : '新设备首次打开网页，需在本机点「允许」')
            .fontSize(11)
            .fontColor(C_SUB)
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: this.snapshot.webOpen })
          .onChange((on: boolean) => this.switchWebOpen(on))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // ---------------- 收到图片/视频自动存相册 ----------------
      Row({ space: 8 }) {
        Column({ space: 2 }) {
          Text('收到图片/视频自动存相册')
            .fontSize(13)
            .fontColor(C_TEXT)
          Text(this.autoAlbum
            ? '接收完成后弹一次确认框，同意即存入系统相册'
            : '只留在应用内，不写入系统相册')
            .fontSize(11)
            .fontColor(C_SUB)
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: this.autoAlbum })
          .onChange((on: boolean) => this.switchAutoAlbum(on))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 待授权设备 —— 对应原 Android 的 SERVICE_HTTP_NEW_CLIENT 弹框。
      // 没有这块 UI，网页那句「请在手机上同意之后刷新页面」就无从落实。
      if (this.snapshot.pendingWebClients.length > 0) {
        Column({ space: 6 }) {
          Text(`有 ${this.snapshot.pendingWebClients.length} 个设备请求访问网页`)
            .fontSize(12)
            .fontWeight(FontWeight.Medium)
            .fontColor('#E84026')
            .width('100%')
          ForEach(this.snapshot.pendingWebClients, (c: WebClient) => {
            Row({ space: 8 }) {
              Column({ space: 2 }) {
                Text(c.name.length > 0 ? c.name : c.ip)
                  .fontSize(13)
                  .fontColor(C_TEXT)
                Text(c.ip.length > 0 ? c.ip : '未知 IP')
                  .fontSize(11)
                  .fontColor(C_SUB)
              }
              .alignItems(HorizontalAlign.Start)
              .layoutWeight(1)

              Button('拒绝')
                .fontSize(12)
                .height(28)
                .padding({ left: 10, right: 10 })
                .backgroundColor('#F2F2F2')
                .fontColor('#666666')
                .onClick(() => this.denyWeb(c.token))
              Button('允许')
                .fontSize(12)
                .height(28)
                .padding({ left: 14, right: 14 })
                .backgroundColor(C_PRIMARY)
                .fontColor('#FFFFFF')
                .onClick(() => this.approveWeb(c.token))
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }, (c: WebClient) => c.token)
        }
        .width('100%')
        .padding(8)
        .backgroundColor('#FFF6F5')
        .borderRadius(8)
      }
    }
    .width('100%')
    .padding(12)
    .backgroundColor(C_CARD)
    .borderRadius(12)
    .alignItems(HorizontalAlign.Start)
  }

  /** 设备列表 —— 「发送文件」的唯一入口 */
  @Builder
  deviceCard() {
    Column({ space: 8 }) {
      Text(`已发现设备 (${this.devices.length})`)
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
        .fontColor(C_TEXT)
        .width('100%')
      ForEach(this.devices, (d: LanDevice) => {
        Row({ space: 10 }) {
          Column({ space: 2 }) {
            Row({ space: 6 }) {
              Text(d.devName.length > 0 ? d.devName : d.devIp)
                .fontSize(15)
                .fontColor(C_TEXT)
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .layoutWeight(1)
              // 协议版本徽章（V3/V4/V5/V?）—— 真机上排查「谁是谁」的第一眼依据
              Text(this.protoLabel(d))
                .fontSize(10)
                .fontColor(Color.White)
                .backgroundColor(this.protoColor(d))
                .borderRadius(6)
                .padding({ left: 5, right: 5, top: 1, bottom: 1 })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)

            Text(`${d.manufacturer} · ${d.devIp}:${d.devPort}`)
              .fontSize(12)
              .fontColor(C_SUB)
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)

          if (d.batteryLevel >= 0) {
            Text(`${d.batteryLevel}%`)
              .fontSize(12)
              .fontColor('#666666')
          }

          // ---- 发送入口：相册与文件管理器并列 ----
          // 鸿蒙侧没有"从相册/文件管理器长按分享到本应用"的等价入口，
          // 所以发送必须由用户在设备行上主动点出来。
          // 相册（图片/视频）与文件（任意类型）两个入口平级，不叠在二级菜单里 ——
          // 选图是最常用的一种发送，多一次点击就是多一次劝退。
          Button('相册')
            .fontSize(12)
            .height(32)
            .padding({ left: 10, right: 10 })
            .backgroundColor(this.transferring ? '#C8C8C8' : '#E8F0FE')
            .fontColor(this.transferring ? '#FFFFFF' : C_PRIMARY)
            .enabled(!this.transferring && this.service.isRunning)
            .onClick(() => this.pickAlbumAndSend(d))

          Button('文件')
            .fontSize(12)
            .height(32)
            .padding({ left: 10, right: 10 })
            .backgroundColor(this.transferring ? '#C8C8C8' : C_PRIMARY)
            .fontColor(Color.White)
            .enabled(!this.transferring && this.service.isRunning)
            .onClick(() => this.pickAndSend(d))
        }
        .width('100%')
        .padding({ top: 8, bottom: 8 })
      }, (d: LanDevice) => `${d.uniqueUuid}|${d.devIp}|${d.dataVersion}`)
    }
    .width('100%')
    .padding(16)
    .backgroundColor(C_CARD)
    .borderRadius(14)
  }

  /**
   * 「发送到网页端」卡片。
   *
   * 官方网页端只有「浏览器 → 手机」这一个方向，手机上想把文件发给浏览器
   * 是没有入口的。这里补上：选好文件 → 搬进沙箱 → WebSocket 通知浏览器来取。
   *
   * ⚠️ 没有网页端连接时按钮直接禁用（不是点了才报错）：
   * 推送是「通知」，没人连着就必然失败，与其让用户白点一次不如提前说清楚。
   */
  @Builder
  webPushCard() {
    Column({ space: 8 }) {
      Text('发送到网页端')
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
        .fontColor(C_TEXT)
        .width('100%')
      Text(this.snapshot.wsClients > 0
        ? `当前有 ${this.snapshot.wsClients} 个网页端连接着；选好文件后浏览器会自动开始下载（多个文件打包成 zip）`
        : '当前没有网页端连接：请先用浏览器打开上面的地址，并保持页面开着')
        .fontSize(11)
        .fontColor(C_SUB)
        .width('100%')

      Row({ space: 8 }) {
        Button('相册')
          .fontSize(12)
          .height(32)
          .padding({ left: 12, right: 12 })
          .backgroundColor(this.snapshot.wsClients > 0 ? '#E8F0FE' : '#F2F2F2')
          .fontColor(this.snapshot.wsClients > 0 ? C_PRIMARY : '#AAAAAA')
          .enabled(this.snapshot.wsClients > 0)
          .onClick(() => this.pickAlbumForWeb())
        Button('文件')
          .fontSize(12)
          .height(32)
          .padding({ left: 12, right: 12 })
          .backgroundColor(this.snapshot.wsClients > 0 ? C_PRIMARY : '#C8C8C8')
          .fontColor(Color.White)
          .enabled(this.snapshot.wsClients > 0)
          .onClick(() => this.pickFileForWeb())
      }
      .width('100%')
    }
    .width('100%')
    .padding(16)
    .backgroundColor(C_CARD)
    .borderRadius(14)
  }

  /**
   * 「文件」页 —— 沙箱里接收到的文件（另存为 + 删除）。
   *
   * 单独成一页而不是塞在共享页底部，是因为手机形态下收到的文件**只能落在应用沙箱**，
   * 系统「文件管理」里根本看不到（见 docs/迁移对照表.md 第十三节）。
   * 也就是说这里的「另存为」是用户唯一的取文件通道、「删除」是唯一的清空间通道 ——
   * 埋在共享页最底下太容易被忽略，用户会以为"传完就找不着了"。
   */
  @Builder
  filesTab() {
    Column() {
      // ---------------- 顶部工具条（普通态 / 多选态） ----------------
      Row({ space: 8 }) {
        if (this.fileSelectMode) {
          Text(`已选 ${this.fileSelected.length} 项`)
            .fontSize(13)
            .fontColor(C_TEXT)
            .fontWeight(FontWeight.Medium)
            .layoutWeight(1)
          Button(this.receivedFiles.length > 0 && this.fileSelected.length === this.receivedFiles.length
            ? '取消全选' : '全选')
            .fontSize(12)
            .height(28)
            .padding({ left: 12, right: 12 })
            .backgroundColor('#ECECEC')
            .fontColor('#333333')
            .enabled(this.receivedFiles.length > 0)
            .onClick(() => this.toggleSelectAllFiles())
          Button('取消')
            .fontSize(12)
            .height(28)
            .padding({ left: 12, right: 12 })
            .backgroundColor('#F2F2F2')
            .fontColor('#666666')
            .onClick(() => this.exitFileSelect())
        } else {
          Text(`接收到的文件 · ${this.receivedFiles.length}`)
            .fontSize(13)
            .fontColor('#666666')
            .layoutWeight(1)

          // 清空：沙箱里堆着的文件只能从这里清，列表非空时才露出
          if (this.receivedFiles.length > 0) {
            Button('清空')
              .fontSize(12)
              .height(28)
              .padding({ left: 12, right: 12 })
              .backgroundColor('#FDECEA')
              .fontColor('#E84026')
              .onClick(() => this.deleteAllFiles())
          }

          Button('刷新')
            .fontSize(12)
            .height(28)
            .padding({ left: 12, right: 12 })
            .backgroundColor('#ECECEC')
            .fontColor('#333333')
            .onClick(() => this.refreshReceived())
        }
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 12, bottom: 8 })

      // ★ 5.1.1：非多选态时 `saveLocationHint()` 里已含「可点击『另存为』保存到本地」；
      //   多选态换成勾选提示（底部条本来就有 `另存为 (N)`，两处入口都指得到）。
      Text(this.fileSelectMode ? '点击文件可切换勾选（长按同样有效）' : this.saveLocationHint())
        .fontSize(11)
        .fontColor(C_SUB)
        .width('100%')
        .padding({ left: 16, right: 16, bottom: 8 })

      if (this.receivedFiles.length === 0) {
        Column({ space: 6 }) {
          Text('还没有收到文件')
            .fontSize(14)
            .fontColor('#888888')
          Text('别的设备或网页端发过来的文件会出现在这里')
            .fontSize(12)
            .fontColor('#AAAAAA')
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Start)
        .alignItems(HorizontalAlign.Start)
        .padding({ left: 16, top: 28 })
      } else {
        List({ space: 8 }) {
          ForEach(this.receivedFiles, (f: ReceivedFile) => {
            ListItem() {
              Row({ space: 10 }) {
                // 多选态：左侧勾选圆。放这里而不是挤按钮行，是为了不占文件名宽度
                if (this.fileSelectMode) {
                  Text(this.isFileSelected(f.path) ? '✓' : '')
                    .fontSize(13)
                    .fontColor(Color.White)
                    .textAlign(TextAlign.Center)
                    .width(22)
                    .height(22)
                    .borderRadius(11)
                    .backgroundColor(this.isFileSelected(f.path) ? C_PRIMARY : '#00000000')
                    .border({
                      width: this.isFileSelected(f.path) ? 0 : 1.5,
                      color: '#C0C6CF'
                    })
                }

                // 图片 / 视频缩略图：能在 App 内直接打开的那两类。
                // 视频走 `AVImageGenerator` 解首帧（异步），所以下面多了「解出来没有」
                // 的分支 —— 没解出来就停在灰色占位。
                // ⚠️ `.sourceSize()` 把解码尺寸压到 96×96 —— 不设的话 40 张
                //    1200 万像素的原图会被**整张**解进内存，列表一滚就是几百 MB。
                //    下面的 Text 是占位（也是解码完成前的样子），真图载入后盖住它。
                if (this.isMediaName(f.name)) {
                  // 5.0.31：等比缩略图（见 mediaThumb 的注释）
                  this.mediaThumb(f.path, 48, this.isVideoName(f.path))
                }

                Column({ space: 6 }) {
                  // ⚠️ 文件名「一行放得下就一行、放不下才两行」的正确写法**只有**
                  //    `maxLines(2)`：Text 高度随实际行数走，单行内容绝不会被撑成两行高。
                  //    ⚠️ **不要再叠加 `lineHeight`** —— 它会同时约束行高与组件高度，
                  //       是上一版「两行没生效」的元凶（本次已移除）。
                  //    `wordBreak(BREAK_ALL)`：无空格的长英文 / 哈希文件名默认被当成
                  //       一个「整词」整体溢出，第二行根本折不出来。
                  Text(f.name)
                    .fontSize(14)
                    .fontColor(C_TEXT)
                    .width('100%')
                    .maxLines(2)
                    .wordBreak(WordBreak.BREAK_ALL)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })

                  Row({ space: 8 }) {
                    // ⚠️ 钉死单行：左边多了 48vp 缩略图后，这行要是允许折行，
                    //    窄屏上会被挤成两行、把卡片撑高（见 5.0.16 说明）
                    Text(`${f.sizeText} · ${f.timeText}`)
                      .fontSize(11)
                      .fontColor(C_SUB)
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })

                    // 单行操作只在普通态露出。多选态下批量操作在底部条，
                    // 行内不再有按钮 —— 点行任意位置即可勾选。
                    // 单行操作只在普通态露出。多选态下批量操作在底部条，
                    // 行内不再有按钮 —— 点行任意位置即可勾选。
                    if (!this.fileSelectMode) {
                      // 推给网页端：文件已经在沙箱里，不用复制，直接通知浏览器来取
                      Button('发到网页')
                        .fontSize(12)
                        .height(30)
                        .padding({ left: 10, right: 10 })
                        .backgroundColor('#E8F0FE')
                        .fontColor(C_PRIMARY)
                        .onClick(() => this.pushOneToWeb(f))

                      Button('另存为')
                        .fontSize(12)
                        .height(30)
                        .padding({ left: 12, right: 12 })
                        .backgroundColor(C_PRIMARY)
                        .fontColor(Color.White)
                        .onClick(() => this.saveAsFile(f))

                      // 单条删除（vivi 2026-10-01：「把文件页的删除按钮加回来」）。
                      // 长按多选仍然保留 —— 删一个用这个、删一批用多选，两条路都通。
                      // ⚠️ 它落在**第二行**（元信息那一行）的右侧：文件名独占第一行，
                      //    所以第三个按钮不会再像 5.0.12 那样把文件名挤扁。
                      Button('删除')
                        .fontSize(12)
                        .height(30)
                        .padding({ left: 10, right: 10 })
                        .backgroundColor('#FDECEA')
                        .fontColor('#E84026')
                        .onClick(() => this.deleteOne(f))
                    }
                  }
                  .width('100%')
                  .alignItems(VerticalAlign.Center)
                }
                .alignItems(HorizontalAlign.Start)
                .layoutWeight(1)
              }
              .width('100%')
              .padding(12)
              .backgroundColor(C_CARD)
              .borderRadius(12)
              .onClick(() => {
                if (this.fileSelectMode) {
                  this.toggleFileSelect(f.path);
                } else if (this.isMediaName(f.name)) {
                  // 普通态：图片/视频点一下进全屏预览（视频走播放器）；
                  // 5.0.31：把**列表里所有媒体**都装进画廊，可左右滑；
                  // 其它类型不做任何事（避免误触）
                  this.openFileGallery(f);
                }
              })
              .gesture(
                LongPressGesture({ repeat: false, duration: 400 })
                  .onAction(() => {
                    this.enterFileSelect(f.path);
                  })
              )
            }
          }, (f: ReceivedFile) => `${f.path}|${f.size}|${f.time}|${this.isFileSelected(f.path) ? 1 : 0}|${this.videoThumbTick}|${this.thumbTick}`)
        }
        .width('100%')
        .layoutWeight(1)
        .padding({ left: 12, right: 12 })
        .scrollBar(BarState.Off)
      }

      // ---------------- 多选态底部操作条 ----------------
      if (this.fileSelectMode) {
        Row({ space: 10 }) {
          Button(this.fileSelected.length > 0 ? `另存为 (${this.fileSelected.length})` : '另存为')
            .fontSize(14)
            .height(38)
            .layoutWeight(1)
            .backgroundColor(this.fileSelected.length > 0 ? C_PRIMARY : '#C8C8C8')
            .fontColor(Color.White)
            .enabled(this.fileSelected.length > 0)
            .onClick(() => this.batchSaveSelected())
          Button(this.fileSelected.length > 0 ? `删除 (${this.fileSelected.length})` : '删除')
            .fontSize(14)
            .height(38)
            .layoutWeight(1)
            .backgroundColor(this.fileSelected.length > 0 ? '#FDECEA' : '#F2F2F2')
            .fontColor(this.fileSelected.length > 0 ? '#E84026' : '#AAAAAA')
            .enabled(this.fileSelected.length > 0)
            .onClick(() => this.batchDeleteSelected())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 8, bottom: 12 })
      } else {
        Text('列表最多显示最近 1000 个；长按文件可多选，批量保存 / 删除')
          .fontSize(11)
          .fontColor('#AAAAAA')
          .width('100%')
          .padding({ left: 16, right: 16, top: 10, bottom: 12 })
      }
    }
    .width('100%')
    .height('100%')
  }
  /** 目标设备胶囊。value 用设备 IP —— 与网页端下拉框的 address 保持同一套标识 */
  @Builder
  targetChip(label: string, value: string) {
    Text(label)
      .fontSize(12)
      .fontColor(this.chatTargetIp === value ? '#FFFFFF' : C_TEXT)
      .padding({ left: 12, right: 12, top: 6, bottom: 6 })
      .backgroundColor(this.chatTargetIp === value ? C_PRIMARY : C_CARD)
      .borderRadius(14)
      .maxLines(1)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .onClick(() => {
        this.chatTargetIp = value;
      })
  }

  /**
   * 一条聊天气泡。
   *
   * 用「Row + Blank 顶开」而不是给气泡设百分比宽度：
   * 气泡要**贴着内容收缩**（短消息不该占满一行），只有 Blank 能在不写死宽度的
   * 前提下把气泡推到左边或右边。
   */
  @Builder
  chatBubble(m: ChatMessage) {
    Row() {
      if (!m.incoming) {
        Blank()
      }
      Column({ space: 3 }) {
        // 多选态：左上角勾选圆（与文件页一致）
        if (this.chatSelectMode) {
          Text(this.isChatSelected(m.id) ? '✓' : '')
            .fontSize(13)
            .fontColor(Color.White)
            .textAlign(TextAlign.Center)
            .width(22)
            .height(22)
            .borderRadius(11)
            .backgroundColor(this.isChatSelected(m.id) ? C_PRIMARY : '#00000000')
            .border({ width: this.isChatSelected(m.id) ? 0 : 1.5, color: '#C0C6CF' })
        }
        // 发出消息（右侧气泡）显示本机名，收到消息（左侧气泡）显示对端名。
        // ⚠️ 之前无脑用 m.peerName：发出时 peerName 被填成了接收方设备名，
        // 于是自己发的消息气泡上挂着对方名字（vivi 2026-09-30 反馈）。
        Text(`${m.incoming ? m.peerName : (this.snapshot.deviceName.length > 0 ? this.snapshot.deviceName : '我')} ${fmtTime(m.timeMs)}`)
          .fontSize(10)
          .fontColor(C_SUB)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        if (m.kind === 'file') {
          // 文件消息：显示文件名（或「N 个文件」）。
          // ⚠️ 只有「收到的」可点并跳到「文件」页：收到的文件落在沙箱里，
          // 系统「文件管理」看不到，不指路用户就找不到；
          // 自己发出去的原文件还在用户手上，文件页里也没有它，点了是死路。
          // 图片路径在调用点算好（`@Builder` 里不声明局部变量最省心）。
          // 非图片 / 自己发出的消息拿到的是空串，行为与改动前完全一致。
          this.chatFileBubble(m, this.bubbleMediaPath(m), this.msgIsVideo(m))
        } else {
          Text(m.content)
            .fontSize(15)
            .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
            .borderRadius(10)
            .textAlign(TextAlign.Start)
        }
      }
      .alignItems(m.incoming ? HorizontalAlign.Start : HorizontalAlign.End)
      // 5.0.50：给整列一个**有限的宽度上限**（相对外层满宽 Row）。
      //   没有它，内部所有百分比约束都会落到「无限宽」上而失效 ——
      //   这就是「文件名溢出气泡」的根因。
      .constraintSize({ maxWidth: '92%' })
      .onClick(() => {
        if (Date.now() < this.clickMuteUntil) {
          return;
        }
        if (this.chatSelectMode) {
          this.toggleChatSelect(m.id);
          return;
        }
        // 普通态：文件消息按「是否已存进相册」分流；文本消息不导航
        if (m.kind === 'file' && m.incoming) {
          this.onFileBubbleClick(m);
        }
      })
      .gesture(
        LongPressGesture({ repeat: false, duration: 400 })
          .onAction(() => {
            if (this.chatSelectMode) {
              this.toggleChatSelect(m.id);
              return;
            }
            // 普通态：长按进入多选（vivi 2026-10-01：消息页长按气泡多选删除）
            this.clickMuteUntil = Date.now() + 800;
            this.enterChatSelect(m.id);
          })
      )

      if (m.incoming) {
        Blank()
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }


  /**
   * ★ 5.0.55：一个「气泡」—— 单条消息走老路径，同批多张媒体走宫格。
   *
   * ⚠️ 单条时**原样转发**给 `chatBubble`：所有既有行为（点击分流、长按多选、
   *   勾选圆、文件名气泡）完全不变，零风险。
   */
  @Builder
  chatGroupBubble(g: ChatGroup) {
    if (g.isMedia) {
      this.chatMediaBubble(g)
    } else {
      this.chatBubble(g.msgs[0])
    }
  }

  /**
   * ★ 5.0.55：宫格气泡 —— 同一次接收的多张图片/视频，一个气泡里多缩略图，
   * **不显示文件名**（vivi 2026-10-02 要求）。
   *
   * 结构与 `chatBubble` 同构（Row + Blank 顶开、左/右对齐、多选勾选圆、
   * 长按进多选），只是中间从「文件名」换成「缩略图宫格」。
   * ⚠️ 没有 `constraintSize(maxWidth:'92%')` 会重演 5.0.50 那个
   *    「百分比约束落到无限宽」的老坑 —— 所以两层都给了上限。
   */
  @Builder
  chatMediaBubble(g: ChatGroup) {
    Row() {
      if (!g.incoming) {
        Blank()
      }
      Column({ space: 3 }) {
        // 多选态：左上角勾选圆（整组全选 = ✓，部分选中 = −，与文件页一致）
        if (this.chatSelectMode) {
          Text(this.isGroupFullySelected(g) ? '✓' : (this.isGroupPartlySelected(g) ? '−' : ''))
            .fontSize(13)
            .fontColor(Color.White)
            .textAlign(TextAlign.Center)
            .width(22)
            .height(22)
            .borderRadius(11)
            .backgroundColor(this.isGroupPartlySelected(g) ? '#9AA4B0'
              : (this.isGroupFullySelected(g) ? C_PRIMARY : '#00000000'))
            .border({
              width: this.isGroupFullySelected(g) ? 0 : 1.5,
              color: '#C0C6CF'
            })
        }
        Text(`${g.incoming ? g.msgs[0].peerName : (this.snapshot.deviceName.length > 0 ? this.snapshot.deviceName : '我')} ${fmtTime(g.timeMs)}`)
          .fontSize(10)
          .fontColor(C_SUB)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        this.chatMediaGrid(g)

        // ★ 5.1.50：宫格气泡也显示「总大小 · 平均速度」
        //   （5.1.49 只做了单文件气泡，宫格这条路径是 `appendFileChat` 的
        //   媒体分支，靠每条消息各自的 meta；这里把**整组**的汇总值取第一条非空的。
        //   ⚠️ 刻意不并进下面那行 —— 那行是「N 张 · 提示」，属固定文案，
        //     与 5.1.47 的 `bubbleFooterText` 同理，塞变长内容会抖布局。
        if (g.incoming && !this.chatSelectMode) {
          // ★ 5.0.75：改用「整组任一张已存」判据（原先只看 `g.msgs[0]`，见方法注释）
          Text(`${g.msgs.length} 张 · ${this.bubbleHintOfGroup(g)}`)
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          // ⚠️ ArkTS：**@Builder 内不允许 `const` 声明**（10905209
          //   "Only UI component syntax can be written here"）⇒ 直接在
          //   Text() 里调方法，长度判空交给 groupMetaText 内部的空串。
          //   空串时这行 Text 不占任何高度（无内容 + maxLines(1)）。
          Text(this.groupMetaText(g))
            .fontSize(10)
            .fontColor(C_SUB)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .padding({ left: 8, right: 8, top: 6, bottom: 6 })
      .backgroundColor(g.incoming ? C_CARD : C_PRIMARY)
      .borderRadius(10)
      .constraintSize({ maxWidth: '92%' })
      .onClick(() => {
        if (Date.now() < this.clickMuteUntil) {
          return;
        }
        // 多选态下点空白处 = 整组切换；想只选一张请点那张缩略图（见 chatMediaGrid）
        if (this.chatSelectMode) {
          this.enterChatGroupSelect(g);
        }
      })
      .gesture(
        LongPressGesture({ repeat: false, duration: 400 })
          .onAction(() => {
            // 普通态：长按进入多选（整组选中）
            this.clickMuteUntil = Date.now() + 800;
            this.enterChatGroupSelect(g);
          })
      )

      if (g.incoming) {
        Blank()
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }

  /** ★ 5.0.56：缩略图宫格 —— 外框边长（vp）。固定正方形，图片 `Cover` 居中裁切铺满 */
  /** 5.0.63：缩略图批量提交的去抖间隔（ms）—— 覆盖同批剩余的完成回调 */
  private static readonly THUMB_FLUSH_DELAY_MS: number = 150;

  private static GRID_SIDE: number = 88;
  // ★ 5.0.76：气泡底部提示的**三个文案**（vivi 20:30 定稿）
  /** 已存入系统相册（点击可跳系统相册，文案不再写「点击查看」——存了之后跳的是相册） */
  private static readonly HINT_IN_ALBUM: string = '已存入相册';
  /** 还没存：提示用户长按气泡触发保存 */
  private static readonly HINT_NOT_YET: string = '长按存入相册';

  /**
   * ★ 5.1.50：取一组媒体消息的「总大小 · 平均速度」副信息。
   *
   * ## 数据来源
   *   每次接收 `appendFileChat` 会把**同一批**的 `meta`（`646.1 MB · 36.5 MB/s`）
   *   写进该批的**每一条**消息（它们共享 `batchId`）。
   *   ⇒ 取第一条非空的即可（同一批的值是同一个）。
   *
   * ## 为什么不在这里累加大小
   *   同一批每条都记了**整批**的总量（不是「这一张」的大小），
   *   累加会重复计算 N 倍。★ 要改成按张累加，得先让上报方带 per-file 大小。
   */
  private groupMetaText(g: ChatGroup): string {
    for (let i: number = 0; i < g.msgs.length; i++) {
      if (g.msgs[i].meta.length > 0) {
        return g.msgs[i].meta;
      }
    }
    return '';
  }
  /** 存过、但已被用户在系统相册里删掉 */
  private static readonly HINT_GONE: string = '已删除';
  /** ★ 5.1.1：**非媒体文件**（zip / pdf / apk…）的唯一合理提示。
   *  它们既没有缩略图、也存不进相册 ⇒ 说「长按存入相册」是错的（vivi 20:58 反馈）。 */
  private static readonly HINT_FILE: string = '点击查看';
  /** ★ 5.1.6：视频文件的文件名徽标（宫格那支走 `mediaThumbFixed` 已有 ▶ 角标，
   *  但**沙箱缩略图缺失时**视频会落到 `chatFileBubble` 的文件名分支 ⇒ 补这个徽标）。 */
  private static readonly VIDEO_BADGE: string = '视频';
  /** ★ 5.1.2：非媒体文件**已另存为到本地**（另存成功后沙箱副本已删）。 */
  private static readonly HINT_LOCAL_SAVED: string = '已存入本地';
  /** ★ 5.1.2：非媒体文件**已被删除**（文件页点了删除，或另存后清沙箱）。 */
  private static readonly HINT_LOCAL_DELETED: string = '已删除';
  /** 六条里最长的那条长度 —— 等宽补齐的基准（5.0.70 的规矩）。
   *  ⚠️ 用 `Math.max` 而不是手写三元嵌套：**新增文案时不会漏改**（5.1.1 的教训）。 */
  private static readonly HINT_MAX_LEN: number = Math.max(
    Index.HINT_IN_ALBUM.length, Index.HINT_NOT_YET.length,
    Index.HINT_GONE.length, Index.HINT_FILE.length,
    Index.HINT_LOCAL_SAVED.length, Index.HINT_LOCAL_DELETED.length);
  /** ★ 5.0.56：每行**恒定**这么多个（vivi 2026-10-02 明确要求「固定每行 3 个」） */
  private static GRID_COLS: number = 3;
  /** ★ 5.0.56：格子间距（vp）。3×88 + 2×4 = 272，加气泡左右内边距 16 = 288，
   *  在 320vp 窄屏上仍 ≤ 92%×320 = 294 —— 不会溢出。 */
  private static GRID_GAP: number = 4;

  /**
   * ★ 5.0.55：缩略图宫格（每行 3 个，`Flex.wrap` 自动换行）。
   *
   * ⚠️ **每张缩略图有自己的 `onClick`**，直接落到它**自己那条消息**上：
   *   普通态 → `onFileBubbleClick(m)`（该张自己的相册条目 / 应用内预览）；
   *   多选态 → 切换**该张**的勾选。
   *   这正是「点第 2 张就能打开第 2 张」的关键 —— 5.0.52 之前做不到，
   *   是因为那时 N 张图共用**一个**消息、只有一个点击入口。
   *
   * ⚠️ `Stack` 里垫的标记是「沙箱副本没了、但缓存缩略图还在」= 用户已在系统相册
   *   删过这张（与 `onFileBubbleClick` 的判定口径一致，只是这里只做**视觉提示**，
   *   不做实际判定 —— 真正的判定要走探活，代价高，不能挂在每次渲染上）。
   */
  @Builder
  chatMediaGrid(g: ChatGroup) {
    // ★ 5.0.56：`Column{ Row{…} }` —— 每行**恒定 3 个**（分行在 `ChatGroup.rows` 里切好）。
    //   不再用 `Flex(wrap)`：它的换行取决于元素宽度，而格子宽度此前是等比的，
    //   于是「一行几个」飘忽不定（vivi 2026-10-02 实测反馈）。
    //   现在外框固定 + 分行固定 ⇒ 与图片比例彻底无关。
    Column({ space: Index.GRID_GAP }) {
      ForEach(g.rows, (row: ChatMessage[]) => {
        Row({ space: Index.GRID_GAP }) {
          ForEach(row, (m: ChatMessage) => {
            Stack() {
              this.mediaThumbFixed(this.mediaThumbSrcOf(m, 0), Index.GRID_SIDE,
                this.msgIsVideo(m))
              if (this.mediaGoneFromAlbum(m, 0)) {
                Text('已删')
                  .fontSize(10)
                  .fontColor('#FFFFFF')
                  .padding({ left: 4, right: 4, top: 1, bottom: 1 })
                  .backgroundColor('#99000000')
                  .borderRadius(4)
              }
            }
            .onClick(() => {
              if (Date.now() < this.clickMuteUntil) {
                return;
              }
              if (this.chatSelectMode) {
                this.toggleChatSelect(m.id);
                return;
              }
              this.onFileBubbleClick(m);
            })
          }, (m: ChatMessage) => `${this.videoThumbTick}|${this.thumbSigOf(m)}`)
        }
      }, (row: ChatMessage[]) => this.rowKey(row))
    }
    .alignItems(HorizontalAlign.Start)
    // ⚠️ **不能写 `width('100%')`**：父 Column 是 wrapContent 宽，
    //   百分比会落到「无限宽」上（5.0.50 那个老坑的同款），于是 2 张图也撑到 92% 上限。
    //   按**列数**算一个确定宽度，气泡就贴合内容了。
    .width(this.gridWidth(g))
  }

  /**
   * 宫格宽度：按**列数**（最多 3）算，让气泡贴合内容而不是撑满。
   *
   * ★ 5.0.56：格子的**外框固定为 `GRID_SIDE` 正方形**（图片 `Cover` 铺满 + 居中裁切），
   *   所以宽度就是 `列数 × 边长 + (列数-1) × 间距` —— 与图片比例无关，恒定可预测。
   *   （旧实现按 88 算宽度、格子却是等比宽度，两者对不上，Flex 换行点因此飘忽。）
   */
  private gridWidth(g: ChatGroup): number {
    const n: number = g.msgs.length < Index.GRID_COLS ? g.msgs.length : Index.GRID_COLS;
    return n * Index.GRID_SIDE + (n - 1) * Index.GRID_GAP;
  }

  /**
   * ★ 5.0.56：一行（最多 3 个）的 key —— 带上行内每条**各自**的媒体源与解码 tick。
   * ★ 5.0.61：`thumbTick` 换成每项自己的签名（见 `thumbSigOf`），一张图的变化
   *   不再波及整屏。
   */
  private rowKey(row: ChatMessage[]): string {
    let s: string = `${this.videoThumbTick}|`;
    for (let i: number = 0; i < row.length; i++) {
      s += `${this.thumbSigOf(row[i])},`;
    }
    return s;
  }

  /**
   * 「文件」消息的气泡本体（**纯展示**：缩略图 + 文件名 + 提示）。
   *
   * ⚠️ 单独抽成一个 @Builder 而不是在 `chatBubble` 里就地写：
   *    `@Builder` 内**不声明局部变量**最省心，把 `mediaPath` 当参数传进来，
   *    `chatBubble` 那边就只剩一行。
   *
   * 5.0.34：消息页也显示小缩略图（与文件页同款 48vp、保持原比例）；
   * 点一下 / 长按的处理统一交给外层 `chatBubble`（普通态跳文件页、多选态切换勾选），
   * 这里不再挂自己的 onClick / gesture，避免和外层重复触发。
   */
  @Builder
  chatFileBubble(m: ChatMessage, mediaPath: string, isVideo: boolean) {
    // ★★ 5.0.74（vivi 20:11）：整段重写成**竖排**，让提示行落到**左下角**、
    //   与宫格 `chatMediaBubble` 的位置一致。
    // ⚠️ 取舍变更说明：5.0.35 当初改成**横排**（左图右名）是为了「像文件页那样矮」，
    //   现在按 vivi 要求让位给「与宫格一致」—— **不是回退**。
    // ⚠️ 为什么整段重写而不是「往 Row 里再插一层 Column」：插入法要同时维护
    //   上下两层的收尾括号，dry-run 里实测**结构就错乱了**（留下裸 `{`）。
    //   改层级结构时，**整段重写比插入更可控**（5.0.72 已栽过一次：
    //   helper 插到 `@Builder` 标记与函数之间 ⇒ 标记配错函数）。
    // ⚠️ 外层 Row 的 `Blank()` 顶开（自己发的靠右）在 `chatBubble` 里，不在这里。
    Row() {
      Column({ space: 3 }) {
        // 「收到文件 / 已发送文件」：宫格那边是「发送方名 + 时间」，
        //   单张保留原措辞，只把它放在缩略图**上方**。
        Text(m.incoming ? '收到文件' : '已发送文件')
          .fontSize(11)
          .fontColor(m.incoming ? C_SUB : '#DCE8FF')
        if (mediaPath.length > 0 && this.isMediaName(mediaPath)) {
          // ★ 5.0.72：48 -> `GRID_SIDE`(88) + 固定方框；5.0.73：改 `Cover` 铺满
          this.mediaThumb(mediaPath, Index.GRID_SIDE, isVideo, true)
        } else {
          // ★ 5.0.55（vivi 2026-10-02）：**图片/视频不显示文件名**（缩略图已说明内容）。
          //   非媒体的文件（zip / pdf / apk…）没有缩略图，文件名是**唯一**标识，必须保留。
          //   ⚠️ 5.0.50：文件名**必须**带宽度上限 —— wrapContent 的容器会用「无限宽」
          //   测量子项，长文件名单行摊开、直接画出气泡背景之外。
          //   `maxLines(2)` 只有拿到有限宽度才会真的折行，所以把约束一路下沉到 Text。
          // ★ 5.1.6：视频走到这一支（沙箱缩略图缺失）时补一枚 VIDEO 徽标 ——
          //   宫格那支（`mediaThumbFixed`）本来就有 ▶ 角标，这里补的是它的兜底。
          //   ⚠️ 判据用 `msgIsVideo`（走 `mediaNamesOf` + `isVideoName`），
          //   对 mp4/mov/mkv 等命中；zip/pdf 不命中 ⇒ 无副作用。
          if (this.msgIsVideo(m)) {
            Row({ space: 6 }) {
              Text(Index.VIDEO_BADGE)
                .fontSize(11)
                .fontColor('#FFFFFF')
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .backgroundColor('#66000000')
                .borderRadius(4)

              Text(m.content)
                .fontSize(15)
                .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .constraintSize({ maxWidth: '100%' })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          } else {
            Text(m.content)
              .fontSize(15)
              .fontColor(m.incoming ? C_TEXT : '#FFFFFF')
              .maxLines(2)
              .wordBreak(WordBreak.BREAK_ALL)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .constraintSize({ maxWidth: '100%' })
          }
        }
        // ★★ 5.1.47：文件大小 + 平均速度，落在文件名**下面**独立一行。
        //   ⚠️ **刻意不并进 `bubbleFooterText`** —— 那个函数的文案必须**等宽**
        //   （5.0.70 / 5.0.74 / 5.0.76 连续踩过三次：字数一变就布局抖一下）。
        if (m.meta.length > 0) {
          Text(m.meta)
            .fontSize(10)
            .fontColor(m.incoming ? C_SUB : '#DCE8FF')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
        if (m.incoming && !this.chatSelectMode) {
          // ★ 5.0.74：与宫格**同款** —— `N 张/个 · 提示`，落在**左下角**。
          //   只有「收到的」才给入口：收到的文件落在沙箱里，系统「文件管理」看不到，
          //   不指路用户就找不到。自己发出去的原文件还在用户手上，不需要跳。
          // ★ 5.1.1：改由 bubbleFooterText 统一拼 —— 非媒体不帶「N 张」，
          //   也不再误报「长按存入相册」（它存不进相册）。
          Text(this.bubbleFooterText(m, mediaPath))
            .fontSize(10)
            .fontColor(C_PRIMARY)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: '100%' })
        }
      }
      // 5.0.36：不再 `layoutWeight(1)` 撑满 —— 气泡按内容自适应收缩。
      // 5.0.50：`maxWidth: '100%'` 把外层的 88% 上限**透传**给内部文本。
      .alignItems(HorizontalAlign.Start)
      .constraintSize({ maxWidth: '100%' })
    }
    .alignItems(VerticalAlign.Center)
    .constraintSize({ maxWidth: '88%' })
    .padding({ left: 10, right: 10, top: 6, bottom: 6 })
    .backgroundColor(m.incoming ? C_CARD : C_PRIMARY)
    .borderRadius(10)
  }

  /**
   * 5.0.31：等比缩略图（**保持原宽高比**）。
   *
   * 以前是写死 `width(128).height(128)` + `objectFit(Cover)`：非正方形原图
   * 直接被**裁成正方形**，画面变形。现在：
   *   ① 框尺寸按真实比例算（最长边 = maxSide，`thumbW/thumbH`）；
   *   ② `objectFit` 改 **Contain** —— 比例还没量出来时（首次渲染）宁可留边也不裁；
   *   ③ 解码尺寸交给 `autoResize(true)` 按显示区域**等比**下采样（不压的话 40 张原图会整张进内存；用 `sourceSize` 压成正方形/依赖比例表都会把图弄变形 —— 三个坑都得躲）。
   *
   * @param maxSide 最长边（聊天气泡 128 / 文件页 48）
   */
  /**
   * ★ 5.0.73：这张图该用哪种填充（供 @Builder 内表达式调用，不能在 Builder 里写 const）。
   *
   * 【为什么】5.0.72 给 `mediaThumb` 加了 `fixedSquare`（容器恒 88×88 正方形），
   * 但图片本身仍是 `ImageFit.Contain` —— 等比**完整**显示、**留白**。
   * 容器变成正方形后留白反而更明显（vivi 20:04 反馈「没有铺满图框」）。
   * 宫格 `mediaThumbFixed` 用的是 `ImageFit.Cover`（等比**铺满** + 居中裁切），
   * 所以「多张图片正常」。
   *
   * ⇒ `fixedSquare` 时用 `Cover`（铺满），否则保持 `Contain`（文件页仍传 48，
   *   那里是「不裁切、完整显示小图」的设计，裁掉内容反而是回归）。
   *
   * ⚠️ **`Cover` 不会变形**（5.0.59 验证过）：等比铺满 + 居中裁切，配合
   *   `autoResize(true)`（按显示区域**等比**下采样）⇒ 像素不变形，只是**裁掉**超出部分。
   */
  private mediaFitOf(fixedSquare: boolean): ImageFit {
    return fixedSquare ? ImageFit.Cover : ImageFit.Contain;
  }

  /**
   * ★ 5.0.74：气泡底部提示行的**数量 + 单位**（单张气泡用）。
   *
   * vivi 20:11：「也写上 1 张，视频写成 1 个」⇒ **视频的单位是「个」不是「张」**。
   * 判据用 `msgIsVideo(m)`（从**消息本身**判断，不看显示源的扩展名 ——
   * 视频的缓存封面是普通 `.jpg`，看路径会把视频误判成图片）。
   *
   * ⚠️ 宫格那行目前恒用「张」（`${g.msgs.length} 张`）。一批里混了视频时
   * 单位会不准 —— 那是**既有行为**，本轮只按 vivi 的要求改单张，
   * 不擅自扩大范围（避免又一次「改了没问」）。
   */
  private bubbleCountText(m: ChatMessage): string {
    return this.msgIsVideo(m) ? '1 个' : '1 张';
  }

  /** 5.0.72：固定方框时恒返回 `maxSide`，否则按比例算（供 @Builder 内表达式调用） */
  private boxSide(path: string, maxSide: number, fixedSquare: boolean): number {
    return fixedSquare ? maxSide : this.thumbW(path, maxSide);
  }

  /** 5.0.72：同上，高度方向 */
  private boxSideH(path: string, maxSide: number, fixedSquare: boolean): number {
    return fixedSquare ? maxSide : this.thumbH(path, maxSide);
  }

  /**
   * 气泡里的缩略图。
   *
   * ★★ 5.0.72（vivi 2026-10-02）：`fixedSquare` = true 时**容器恒为
   * `maxSide × maxSide` 正方形**，与宫格 `mediaThumbFixed` 同款；
   * 图片本身仍走 `autoResize(true)` 等比下采样 + `Contain` ⇒ **不变形**。
   *
   * ⚠️ 为什么单张气泡要这样：此前 `chatFileBubble` 传的是 `48`
   *   （5.0.34 定的「与文件页一致的小缩略图」），vivi 反馈「很小窗口」，
   *   要求**与宫格格框一样大** ⇒ 改传 `GRID_SIDE`（88）。
   * ⚠️ 比例表（`mediaRatio`）缺失时 `thumbW/thumbH` 会退回「正方形 maxSide」，
   *   所以**固定方框**反而更稳：框恒定 ⇒ 只有图片内容随比例变，不会跳动。
   */
  @Builder
  mediaThumb(path: string, maxSide: number, isVideo: boolean, fixedSquare: boolean = false) {
    // 固定方框模式下，图片显示区恒为 maxSide；非固定时沿用按比例算的尺寸
    Stack() {
      // 占位（也是解码失败 / 还没解出来的样子），真图载入后盖住它
      Text(isVideo ? '视频' : '图片')
        .fontSize(11)
        .fontColor('#AAAAAA')
      if (isVideo && this.isVideoName(path)) {
        if (this.hasVideoThumb(path)) {
          // ★ 5.0.72：视频图框也固定（vivi 诉求③）
          Image(this.videoThumbOf(path) as image.PixelMap)
            .width(this.boxSide(path, maxSide, fixedSquare))
            .height(this.boxSideH(path, maxSide, fixedSquare))
            // ★ 5.0.73：固定方框时铺满（vivi 反馈「视频图框也没铺满」）
            .objectFit(this.mediaFitOf(fixedSquare))
            .autoResize(true)
        }
        // 播放角标：盖在图上，一眼区分「图」和「视频」
        Text('▶')
          .fontSize(maxSide >= 100 ? 30 : 16)
          .fontColor('#FFFFFF')
      } else {
        Image(this.imageUri(path))
          .width(this.boxSide(path, maxSide, fixedSquare))
          .height(this.boxSideH(path, maxSide, fixedSquare))
          // ★ 5.0.73：固定方框时铺满（同上），否则仍 Contain（文件页不改）
          .objectFit(this.mediaFitOf(fixedSquare))
          // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
          .orientation(this.thumbOri(path))
          // ★ 5.0.59b：与宫格同款原因换成 `autoResize(true)`。
          //   旧写法给的是等比 `sourceSize`，看着没问题，但 `thumbW/thumbH` 依赖
          //   `mediaRatio` 比例表 —— 比例量不出来时退回 1，`sourceSize` 变正方形
          //   而框也是正方形 ⇒ 图被压进方框 ⇒ **变形**。
          //   换成 `autoResize(true)` 后：比例已知 = 等比框 + 等比解码（原样）；
          //   比例缺失 = 正方形框 + 等比解码 ⇒ `Contain` 留白，**不变形**。
          .autoResize(true)
      }
    }
    .width(this.boxSide(path, maxSide, fixedSquare))
    .height(this.boxSideH(path, maxSide, fixedSquare))
    .backgroundColor('#EFF2F6')
    .borderRadius(8)
    .clip(true)
  }

  /**
   * ★ 5.0.56：**固定外框**的缩略图 —— 宫格专用。
   *
   * 与 `mediaThumb` 的唯一区别：外框恒为 `side × side` **正方形**，
   * 图片 `Cover`（等比放大到覆盖 + **居中裁切**）填满框内，等价于
   * CSS `object-fit: cover; object-position: center`（vivi 2026-10-02 明确要求）。
   *
   * ⚠️ 为什么必须固定外框：宫格要「每行恒定 3 个」就必须让**每个格子的占地一致**；
   *   而等比框（横 88×44 / 竖 44×88）会让一行的个数随图片比例飘 —— 真机实测正是如此。
   * ⚠️ **`Cover` 生效的前提是「解码阶段不改变宽高比」**（5.0.59 踩实的坑）：
   *   用 `sourceSize` 指定解码尺寸时，只要给的不是原图比例（旧写法给正方形），
   *   图在**解码阶段**就已经变形，`Cover` 之后无事可做 ⇒ 表现为**拉伸**。
   *   所以这里用 `autoResize(true)`：按显示区域**等比**下采样，
   *   **不需要预先知道原图比例** ⇒ 不受「比例表量不出来」影响。
   * ⚠️ 框尺寸复用 `thumbW/thumbH`（「按比例 contain 到 maxSide 方框」）。
   */
  @Builder
  mediaThumbFixed(path: string, side: number, isVideo: boolean) {
    Stack() {
      // ★ 5.1.7：占位文字**只在「没有图」时显示**。
      //   ⚠️ 原写法是**无条件**显示（靠「写在 Stack 第一个子项 = 最低层」想让它被
      //     盖住），但 `Stack` 的三个子项**都没写 `align`、全部居中且完全重叠** ⇒
      //     图片铺满方框后**必然把它盖住**（vivi 21:44 反馈「视频文字被缩略图盖住了」）。
      //   ⇒ 现在把「视频/图片」**限定为占位语义**（图还没解出来时的样子），
      //     视频的区分**交给 ▶ 角标**（它写在最后 = 最上层，一直可见）。
      //   ★ 语义也更干净：这两个字本来就是「占位」，不是「类型标签」。
      if (path.length === 0) {
        Text(isVideo ? '视频' : '图片')
          .fontSize(11)
          .fontColor('#AAAAAA')
      }
      if (path.length > 0) {
        if (isVideo && this.isVideoName(path)) {
          if (this.hasVideoThumb(path)) {
            Image(this.videoThumbOf(path) as image.PixelMap)
              // ★ 5.0.57：直接撑满方框 + `Cover` 居中裁切（vivi：把框铺满）
              .width(side)
              .height(side)
              .objectFit(ImageFit.Cover)
          }
          // ★★ 5.1.8：▶ 角标**移走了**（到 Stack 末尾）——
          //   它原先被包在 `if (path.length > 0)` 里，而 `chatMediaGrid` 传的是
          //   `mediaThumbSrcOf(m, 0)`，**缓存小图未生成时为空串** ⇒ 整块跳过
          //   ⇒ **连播放按钮都看不到、只剩一个空白灰框**（vivi 21:4x 反馈）。
        } else {
          Image(this.imageUri(path))
            .width(side)
            .height(side)
            .objectFit(ImageFit.Cover)
            // 5.0.41：缓存小图按 `mediaRot` 补转；沙箱原图不在表里 -> AUTO（Image 自己读 EXIF）
            .orientation(this.thumbOri(path))
            // ★ 5.0.59b：改用 `autoResize(true)`，**不要用 `sourceSize`**。
            //   ① `sourceSize` 是**解码尺寸** —— 旧写法给正方形 `{side*2, side*2}`
            //      等于在**解码阶段**就把图压成正方形，`Cover` 拿到的已是方图、
            //      无从裁切，只能原样铺满 ⇒ **拉伸变形**（vivi 真机眼睛确认）。
            //   ② 改成「等比 `sourceSize`」方向对但不稳：它依赖 `mediaRatio` 比例表，
            //      而比例表靠 `ensureMediaRatio()` 读**沙箱文件**量 —— 自动存相册会删
            //      沙箱副本 ⇒ 量不出来 ⇒ 退回 1（正方形）⇒ **又拉伸**。
            //   ③ `autoResize(true)` 是「按显示区域**等比**下采样」，官方文档原文：
            //      原图 800×1200、显示区 200×200 ⇒ 解码为 **200×300**（比例不变）。
            //      **它不需要预先知道原图比例** ⇒ 比例表缺失也照样正确 —— 决定性优势。
            .autoResize(true)
        }
      }
      // ★★★ 5.1.8：视频身份标识，**无条件**画（只要这条消息是视频）。
      //   ⚠️ 判据用**形参 `isVideo`**（由 `msgIsVideo(m)` 从消息算出来），
      //     **不用 `isVideoName(path)`** —— `path` 为空时后者恒为 false
      //     ⇒ 这正是「▶ 连同『视频』两个字一起消失」的真根因。
      //   ⚠️ 放**Stack 最后一个子项** ⇒ 在最上层，不会被 Image 盖住（5.1.7 的教训）。
      //   ⚠️ 半透明黑底衬：白字在浅色封面上几乎看不见（图片都铺满方框）。
      if (isVideo) {
        // ★ 5.1.9：文字角标（vivi「播放按钮不太好看，改成文字显示」）。
        //   ⚠️ **挪到左下角**：用一层 `Stack({alignContent})` 定位 ——
        //     `Text` **没有 `.align()` 方法**（那是 `Stack` 的参数），
        //     直接写在 `Stack` 里会沿用默认居中、正好盖住封面主体。
        //     另：「已删」角标也在同一个 `Stack` 里（且同样默认居中），
        //     两者同时出现时叠在一起 ⇒ 视频角标选左下、避开中心。
        Stack({ alignContent: Alignment.BottomStart }) {
          Text('视频')
            .fontSize(11)
            .fontColor('#FFFFFF')
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .backgroundColor('#66000000')
            .borderRadius(4)
        }
        .width('100%')
        .height('100%')
      }
    }
    // ★ 固定外框 —— 宫格「每行 3 个」的基础
    .width(side)
    .height(side)
    .backgroundColor('#EFF2F6')
    .borderRadius(8)
    .clip(true)
  }

  @Builder
  chatTab() {
    Column({ space: 8 }) {
      // ---------------- 目标设备 ----------------
      Row({ space: 8 }) {
        Text('发送给')
          .fontSize(12)
          .fontColor(C_SUB)
        Scroll() {
          Row({ space: 8 }) {
            this.targetChip('所有设备', '')
            ForEach(this.devices, (d: LanDevice) => {
              // 名字后面带协议版本，多台设备/多版本共存时一眼分得清
              this.targetChip(
                `${d.devName.length > 0 ? d.devName : d.devIp} ${this.protoLabel(d)}`, d.devIp)
            }, (d: LanDevice) => `${d.devIp}|${d.dataVersion}`)
          }
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .layoutWeight(1)
        .height(34)
      }
        .width('100%')
        .padding({ left: 16, right: 16, top: 10 })
        .alignItems(VerticalAlign.Center)

      Row({ space: 8 }) {
        Text(this.devices.length === 0
          ? '当前没有在线设备：消息仍会推送到浏览器网页端'
          : `已发现 ${this.devices.length} 台设备；选「所有设备」即群发`)
          .fontSize(11)
          .fontColor(C_SUB)
          .layoutWeight(1)
        Button('复制')
          .fontSize(11)
          .height(26)
          .padding({ left: 10, right: 10 })
          .backgroundColor('#EAF0FF')
          .fontColor(C_PRIMARY)
          .enabled(this.chat.length > 0)
          .onClick(() => this.copyChat())
        Button('清空')
          .fontSize(11)
          .height(26)
          .padding({ left: 10, right: 10 })
          .backgroundColor('#F2F2F2')
          .fontColor('#666666')
          .enabled(this.chat.length > 0)
          .onClick(() => this.clearChatHistory())
      }
      .width('100%')
      .padding({ left: 16, right: 16 })
      .alignItems(VerticalAlign.Center)

      // ---------------- 消息多选态顶栏 ----------------
      if (this.chatSelectMode) {
        Row({ space: 10 }) {
          Button('取消')
            .fontSize(13)
            .height(34)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#F2F2F2')
            .fontColor('#666666')
            .onClick(() => this.exitChatSelect())
          Text(`已选 ${this.chatSelected.length} 项`)
            .fontSize(13)
            .fontColor(C_SUB)
            .layoutWeight(1)
          Button('复制')
            .fontSize(13)
            .height(34)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#EAF0FF')
            .fontColor(C_PRIMARY)
            .enabled(this.chatSelected.length > 0)
            .onClick(() => this.copySelectedChat())
          Button(this.chat.length > 0 && this.chatSelected.length === this.chat.length ? '取消全选' : '全选')
            .fontSize(13)
            .height(34)
            .padding({ left: 14, right: 14 })
            .backgroundColor('#EAF0FF')
            .fontColor(C_PRIMARY)
            .enabled(this.chat.length > 0)
            .onClick(() => this.toggleSelectAllChat())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 4, bottom: 8 })
      }

      // ---------------- 消息列表 ----------------
      if (this.chat.length === 0) {
        Column({ space: 6 }) {
          Text('还没有消息')
            .fontSize(13)
            .fontColor('#AAAAAA')
          Text('手机 ↔ 局域网设备 / 浏览器网页端，双向互通')
            .fontSize(11)
            .fontColor('#BBBBBB')
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      } else {
        List({ space: 10, scroller: this.chatScroller }) {
          // ★ 5.0.55：数据源从「每条消息」换成「每个气泡（可能含多条消息）」——
          //   同一次接收的多张图片/视频聚合成一个宫格气泡。
          ForEach(this.chatGroups, (g: ChatGroup) => {
            ListItem() {
              this.chatGroupBubble(g)
            }
            // ⚠️ key 带上 `videoThumbTick`：视频首帧是**异步**解出来的，
            //    key 不变的话 ForEach 会复用旧行、缩略图永远不出现。
            //    List 是懒加载的，只重建可见那几行，代价可忽略。
            // ★ 5.0.55：带上组内**每条**的媒体路径 ——
            //   路径从空变实要让这一行重建（缩略图源变了）。
            // ★★ 5.0.71：相册那一维**从 `groupAlbumSig` 换成 `groupGoneSig`** ——
            //   「存相册」会让 uri 从空变有 ⇒ `groupAlbumSig` 必变 ⇒
            //   **整颗气泡销毁重建**（这才是「存完闪一下」的结构性原因）。
            //   而「已存入」的提示已由 5.0.70 的**等宽文案**承载，无需重建；
            //   只有「已删」角标翻转（true->false）仍需重建刷掉 ⇒ 只保留它。
          }, (g: ChatGroup) => `${g.key}|${this.videoThumbTick}|${this.groupMediaSig(g)}|${this.groupGoneSig(g)}`)
        }
        .width('100%')
        .layoutWeight(1)
        .padding({ left: 16, right: 16 })
        .scrollBar(BarState.Off)
      }

      // ---------------- 消息多选态底部操作条 ----------------
      if (this.chatSelectMode) {
        Row({ space: 10 }) {
          // ★ 5.0.57（vivi 2026-10-02）：多选态加「存相册」—— 补存那些
          //   自动存相册被取消过 / 在系统相册里删掉过的图片视频。
          //   ⚠️ 数量用 `chatAlbumCount()`（只数**可存**的），不用 `chatSelected.length` ——
          //      否则用户选了 3 条（1 张图 + 2 条文本）时按钮会说「存相册 (3)」，是错的。
          Button(this.chatAlbumCount() > 0 ? `存相册 (${this.chatAlbumCount()})` : '存相册')
            .fontSize(14)
            .height(38)
            .layoutWeight(1)
            .backgroundColor(this.chatAlbumCount() > 0 ? '#E8F0FE' : '#F2F2F2')
            .fontColor(this.chatAlbumCount() > 0 ? C_PRIMARY : '#AAAAAA')
            .enabled(this.chatAlbumCount() > 0)
            .onClick(() => this.batchSaveChatToAlbum())
          Button(this.chatSelected.length > 0 ? `删除 (${this.chatSelected.length})` : '删除')
            .fontSize(14)
            .height(38)
            .layoutWeight(1)
            .backgroundColor(this.chatSelected.length > 0 ? '#FDECEA' : '#F2F2F2')
            .fontColor(this.chatSelected.length > 0 ? '#E84026' : '#AAAAAA')
            .enabled(this.chatSelected.length > 0)
            .onClick(() => this.batchDeleteChat())
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 8, bottom: 12 })
      } else {
      // ---------------- 输入区（文本 + 加号菜单 + 发送） ----------------
      Row({ space: 8 }) {
        TextInput({ text: this.chatInput, placeholder: '输入消息…' })
          .layoutWeight(1)
          .height(40)
          .fontSize(15)
          .backgroundColor(C_CARD)
          .borderRadius(8)
          .maxLength(700)
          .onChange((v: string) => {
            this.chatInput = v;
          })
          .onSubmit(() => {
            this.sendChat();
          })
        // 加号菜单：选中目标设备后可从此发相册 / 文件。
        // 放在输入框右侧（vivi 2026-09-30 要求），点开弹出选择，替代原独立的「相册/文件」行。
        // ⚠️ 用 ButtonType.Normal + flexShrink(0)：
        //   1) Normal 不会被 Capsule 默认样式在靠右贴边时把"+"字形裁掉
        //      （vivi 2026-09-30 反馈"加号显示不全"的根因之一）；
        //   2) 菜单 placement 设 BottomEnd，从按钮右边缘向左展开，避免弹出菜单超出屏幕右侧被切。
        Button('+', { type: ButtonType.Normal })
          .width(44)
          .height(40)
          .padding(0)
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .fontColor(C_PRIMARY)
          .backgroundColor(this.transferring ? '#C8C8C8' : '#E8F0FE')
          .borderRadius(20)
          .flexShrink(0)
          .enabled(!this.transferring && this.service.isRunning)
          // ⚠️ 这里用 onClick 而不是 bindMenu：多台设备在线时要先弹「发给谁」，
          //    菜单是静态的做不到按设备数量分叉（vivi 2026-10-01 要求）。
          .onClick(() => {
            this.openPlus();
          })
        Button('发送')
          .height(40)
          .fontSize(14)
          .padding({ left: 18, right: 18 })
          .backgroundColor(this.chatInput.trim().length > 0 ? C_PRIMARY : '#C8C8C8')
          .fontColor(Color.White)
          .flexShrink(0)
          .enabled(this.chatInput.trim().length > 0)
          .onClick(() => {
            this.sendChat();
          })
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 4, bottom: 8 })
      .alignItems(VerticalAlign.Center)
      }
    }
    .width('100%')
    .height('100%')
  }

  @Builder
  shareTab() {
    Scroll() {
      Column({ space: 12 }) {
        this.addrCard()
        this.runtimeCard()

        // 网页端推送入口：官方网页端只能单向上传，手机上「发文件给浏览器」
        // 没有入口。这里补上 —— 选好文件后通知浏览器自动下载。
        if (this.snapshot.webUrl.length > 0) {
          this.webPushCard()
        }

        if (this.devices.length > 0) {
          this.deviceCard()
        }

        // ---------------- 提示信息 ----------------
        if (this.snapshot.message.length > 0) {
          Text(this.snapshot.message)
            .fontSize(13)
            .fontColor('#666666')
            .width('100%')
            .padding(12)
            .backgroundColor('#FFF8E8')
            .borderRadius(10)
        }

        Row({ space: 8 }) {
          Text('协议与 Android 端保持一致（已通过字节级对拍验证），可与现网 Android / Windows 客户端互通')
            .fontSize(11)
            .fontColor('#999999')
            .layoutWeight(1)
          // 日志 tab 已删，这里留一个复制出口：排障时要贴日志出来看
          Button('复制日志')
            .fontSize(11)
            .height(26)
            .padding({ left: 10, right: 10 })
            .backgroundColor('#ECECEC')
            .fontColor('#555555')
            .onClick(() => this.copyLogs())
        }
        .width('100%')
        .padding({ bottom: 16 })
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 12 })
    }
    .width('100%')
    .height('100%')
    .scrollBar(BarState.Off)
    .align(Alignment.Top)
  }

  /**
   * 全局传输进度浮层。
   *
   * 收发文件的进度**不再**塞在共享页 / 文件页里（那样切到消息页就看不见了），
   * 而是浮在应用内所有 tab 之上 —— 一个应用内的浮窗，不是系统级悬浮窗
   * （系统级需要 WindowType.TYPE_FLOAT 等受限能力，本项目不需要）。
   * 收到 / 发出任一文件时由 `snapshot.transferText` 驱动，传输结束自动消失。
   */
  @Builder
  /**
   * 「发文件给谁」弹窗（消息 tab 的「+」调起）。
   *
   * 自己做遮罩 + 卡片而不是用 `bindDialog` / `CustomDialogController`：
   * 这里是**两步表单**（选设备 → 选相册/文件），需要在同一次弹出里改内容，
   * 自定义浮层只靠一个 `pickStep` 状态就能切换，比对话框控制器间传状态简单得多。
   *
   * ⚠️ 遮罩和卡片是 Stack 的兄弟节点：遮罩单独吃点击用来关闭，
   *    卡片自己也挂一个空 onClick 把点击吃掉 ——
   *    否则点卡片会穿透到遮罩上，弹窗直接被关掉。
   */
  /**
   * 「关于」弹窗：版本号 + 上游开源仓库 + 移植说明。
   *
   * 为什么走自绘而不是 `showDialog`：系统弹窗 title 字号固定、不按内容折行，
   * 仓库 URL 那种长串会被截断（本页删文件弹窗已经踩过一次，见文件头记录）。
   */
  @Builder
  aboutDialog() {
    if (this.showAbout) {
      Stack() {
        Column()
          .width('100%')
          .height('100%')
          .onClick(() => {
            this.showAbout = false;
          })

        // ⚠️ 5.0.37：QQ 群 / 更新地址两块必须写在**这个 Column 内部**。
        // 5.0.35 曾把它们插到本 Column 的收尾花括号之后，导致
        // padding / backgroundColor / borderRadius / shadow 这些链式属性
        // 被挂到最后一个子块上 —— 主卡片丢白底，只剩两个网址浮在遮罩上。
        Column({ space: 12 }) {
          // ---------------- 标题 + 关闭 ----------------
          Row() {
            Text('关于 LANShare')
              .fontSize(16)
              .fontWeight(FontWeight.Bold)
              .fontColor(C_TEXT)
              .layoutWeight(1)
            Text('关闭')
              .fontSize(13)
              .fontColor(C_PRIMARY)
              .onClick(() => {
                this.showAbout = false;
              })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // ---------------- 版本号（+ 测试版角标）----------------
          Row({ space: 8 }) {
            Text('版本')
              .fontSize(13)
              .fontColor(C_SUB)
            Text(this.aboutVer)
              .fontSize(13)
              .fontWeight(FontWeight.Medium)
              .fontColor(C_TEXT)
            // ★ 5.1.13：只在测试版显示角标，正式版**什么都不加**（保持干净）。
            //   判据用 `isTestVersion(this.aboutVer)` 而不是 `!== LAST_STABLE_VER`
            //   —— 后者会把 5.1.9 这种**更早的正式版**也标成测试版。
            if (isTestVersion(this.aboutVer)) {
              Text('测试版')
                .fontSize(11)
                .fontWeight(FontWeight.Medium)
                .fontColor('#FFFFFF')
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .backgroundColor('#E8833A')
                .borderRadius(4)
            }
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // ---------------- 移植说明 ----------------
          Text('本应用是基于「梦醒了」大佬的开源项目 LANShare 移植的鸿蒙（HarmonyOS）版本。'
            + '协议实现与核心代码均来自原开源项目，在此致谢。')
            .fontSize(13)
            .fontColor(C_TEXT)
            .width('100%')

          // ---------------- 开源仓库（可复制）----------------
          Column({ space: 6 }) {
            Text('开源仓库')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text(ABOUT_REPO)
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .layoutWeight(1)
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyRepo();
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)

          // ---------------- QQ 交流群（可复制）----------------
          Column({ space: 6 }) {
            Text('QQ 交流群')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text('538809905')
                .fontSize(13)
                .fontColor(C_TEXT)
                .layoutWeight(1)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyText('538809905');
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)

          // ---------------- 更新地址（网盘，可复制）----------------
          Column({ space: 6 }) {
            Text('更新地址')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text(ABOUT_UPDATE)
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .layoutWeight(1)
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyText(ABOUT_UPDATE);
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)
        }
        .width('86%')
        .constraintSize({ maxHeight: '82%' })
        .padding(16)
        .backgroundColor(C_CARD)
        .borderRadius(14)
        .shadow({ radius: 24, color: '#33000000', offsetX: 0, offsetY: 8 })
        .onClick(() => {
          // 吃掉点击，避免穿透到遮罩把弹窗关掉
        })
      }
      .width('100%')
      .height('100%')
      .backgroundColor('#80000000')
    }
  }

  @Builder
  pickDialog() {
    if (this.pickStep > 0) {
      Stack() {
        Column()
          .width('100%')
          .height('100%')
          .onClick(() => {
            this.closePick();
          })

        Column({ space: 10 }) {
          // ---------------- 标题 + 关闭 ----------------
          Row() {
            Text(this.pickStep === 1 ? '选择发送设备' : `发送到 ${this.pickName}`)
              .fontSize(16)
              .fontWeight(FontWeight.Bold)
              .fontColor(C_TEXT)
              .layoutWeight(1)
            Text('取消')
              .fontSize(13)
              .fontColor(C_PRIMARY)
              .onClick(() => {
                this.closePick();
              })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          if (this.pickStep === 1) {
            Text('文件一次只能发给一台设备（不支持群发）')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')

            List({ space: 8 }) {
              ForEach(this.devices, (d: LanDevice) => {
                ListItem() {
                  Row({ space: 10 }) {
                    Column({ space: 2 }) {
                      Text(d.devName.length > 0 ? d.devName : d.devIp)
                        .fontSize(15)
                        .fontColor(C_TEXT)
                        .maxLines(1)
                        .textOverflow({ overflow: TextOverflow.Ellipsis })
                      Text(`${this.protoLabel(d)} · ${d.devIp}`)
                        .fontSize(11)
                        .fontColor(C_SUB)
                    }
                    .alignItems(HorizontalAlign.Start)
                    .layoutWeight(1)
                  }
                  .width('100%')
                  .padding({ left: 12, right: 12, top: 10, bottom: 10 })
                  .backgroundColor('#F6F8FB')
                  .borderRadius(10)
                }
                .onClick(() => {
                  this.beginPickType(d);
                })
              }, (d: LanDevice) => `${d.devIp}|${d.dataVersion}`)
            }
            .width('100%')
            .height(240)
            .scrollBar(BarState.Off)
          } else {
            this.pickTypeRow('相册', '从相册选图片 / 视频', () => {
              this.doPick(true);
            })
            this.pickTypeRow('文件', '从文件管理器选文件', () => {
              this.doPick(false);
            })
          }
        }
        .width('86%')
        .padding(16)
        .backgroundColor(C_CARD)
        .borderRadius(14)
        .shadow({ radius: 24, color: '#33000000', offsetX: 0, offsetY: 8 })
        .onClick(() => {
          // 吃掉点击，避免穿透到遮罩把弹窗关掉
        })
      }
      .width('100%')
      .height('100%')
      .backgroundColor('#80000000')
    }
  }

  /** 弹窗第二步的一行：「相册」/「文件」 */
  @Builder
  pickTypeRow(title: string, sub: string, onTap: () => void) {
    Row({ space: 10 }) {
      Column({ space: 2 }) {
        Text(title)
          .fontSize(15)
          .fontColor(C_TEXT)
        Text(sub)
          .fontSize(11)
          .fontColor(C_SUB)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Text('›')
        .fontSize(18)
        .fontColor(C_SUB)
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 12, bottom: 12 })
    .backgroundColor('#F6F8FB')
    .borderRadius(10)
    .onClick(() => {
      onTap();
    })
  }

  build() {
    Stack({ alignContent: Alignment.Top }) {
      Column() {
        // ---------------- 标题栏 ----------------
        // top 用运行时取到的状态栏高度：EntryAbility 开了沉浸式，不让位就会和状态栏叠在一起
        Row() {
          Text('LANShare')
            .fontSize(22)
            .fontWeight(FontWeight.Bold)
            .fontColor(C_TEXT)
          Blank()
          // 「关于」入口：版本号 + 上游开源仓库 + 移植说明
          Text('关于')
            .fontSize(13)
            .fontColor(C_PRIMARY)
            .padding({ left: 10, right: 10, top: 4, bottom: 4 })
            .onClick(() => {
              this.showAbout = true;
            })
          this.stateChip()
        }
        .width('100%')
        .padding({ left: 20, right: 20, top: this.topInset + 10, bottom: 10 })

        // ---------------- 主体：底部三 tab（消息放中间） ----------------
        Tabs({ barPosition: BarPosition.End, index: this.curTab, controller: this.tabsController }) {
          TabContent() {
            this.shareTab()
          }
          // 键盘弹起：内容区底部让出键盘高度，输入框正好落在键盘上沿。
          // ⚠️ 只加在 TabContent 上 —— tab 栏是 Tabs 的 bar，不吃这个 padding，
          //    于是底栏留在屏幕底部不动（vivi 要求：不跟随键盘上移）。
          .padding({ bottom: this.keyboardVp })
          .tabBar(this.tabBarItem('共享', 0))

          TabContent() {
            this.chatTab()
          }
          // 键盘弹起：内容区底部让出键盘高度，输入框正好落在键盘上沿。
          // ⚠️ 只加在 TabContent 上 —— tab 栏是 Tabs 的 bar，不吃这个 padding，
          //    于是底栏留在屏幕底部不动（vivi 要求：不跟随键盘上移）。
          .padding({ bottom: this.keyboardVp })
          .tabBar(this.tabBarItem('消息', 1))

          TabContent() {
            this.filesTab()
          }
          // 键盘弹起：内容区底部让出键盘高度，输入框正好落在键盘上沿。
          // ⚠️ 只加在 TabContent 上 —— tab 栏是 Tabs 的 bar，不吃这个 padding，
          //    于是底栏留在屏幕底部不动（vivi 要求：不跟随键盘上移）。
          .padding({ bottom: this.keyboardVp })
          .tabBar(this.tabBarItem('文件', 2))
        }
        .barHeight(50)
        .barBackgroundColor(C_CARD)
        .layoutWeight(1)
        .onChange((index: number) => {
          this.curTab = index;
          this.lastChatCount = this.snapshot.chat.length;
          if (index === 1) {
            try {
              this.chatScroller.scrollEdge(Edge.Bottom);
            } catch (e) {
              // 列表还没挂载，忽略
            }
            // ★★ 5.1.70 C：这里**不再**做相册资产全量探测。
            //   原来 5.0.75 是「切到消息 tab 才探」⇒ 426 张时切页必卡。
            //   现已改为**后台静默**（`aboutToAppear` → `loadAlbumIndex` 完成后
            //   `scheduleBackgroundAlbumProbe()`），与 tab 切换完全解耦。
            //   ⚠️ 效果不变：用户删了相册里的图，气泡角标照样更新
            //   （处置逻辑在 `probeAlbumOnEnterChat` 里没动过）。
          }
          // 切到「文件」页时刷一次 —— 可能是在别的页期间收到的文件
          if (index === 2) {
            this.refreshReceived();
          }
        })

        // ---------------- 底部安全区 ----------------
        // 沉浸式下 tab 栏会铺到系统导航条（小白条）底下，而它的高度属于"窗口外"，
        // 之前用 Tabs.padding(bottom) 让位，露出来的却是根节点的灰底 #F1F3F5 ——
        // 于是小白条那一条和上面的白色 tab 栏明显分成两色。
        // 这里改成显式的同色条：高度取运行时拿到的导航条高度，颜色与 tab 栏一致。
        Row()
          .width('100%')
          .height(this.bottomInset)
          .backgroundColor(C_CARD)
      }
      .width('100%')
      .height('100%')
      .backgroundColor(C_PAGE)

      // ---------------- 全局传输进度浮层（跨 tab）----------------
      // ★★★ 5.1.46：**完全内联**，不用 @Builder。
      //   依据（vivi 5.1.45 实测）：`if (this.tDone)` 提到 build() 顶层后条件生效了
      //   （完成态的 ✓ 图标与满格白条都出现了），**但同一个 @Builder 内部的
      //   `.backgroundColor(C_DONE_OK)` 依然是蓝的** ⇒ 说明「@Builder 整体」
      //   对随状态变化的链式属性都不可靠，不只是条件分支。
      //   ⇒ ArkUI 里凡是「随状态变化的样式/条件渲染」，一律写在 build() 的
      //     执行上下文里，这是最原始也最可靠的写法。
      if (this.tText.length > 0) {
        if (this.tDone) {
          // ── 完成态：绿底 + 静态 ✓ + 满格白条 ──
          // ⚠️ 不渲染 LoadingProgress：它是**动画组件**，挂在树上就一直转。
          Column({ space: 8 }) {
            Row({ space: 8 }) {
              Text('\u2713')
                .fontSize(16)
                .fontColor('#FFFFFF')
                .width(18)
                .textAlign(TextAlign.Center)
              // ★ 5.1.51：这里原本是 5.1.50 加的**空占位**（只为了对齐），
              //   vivi 反馈「对勾和文件名中间有一个空白」⇒ 改成显示「完成」。
              //   与传输中同样是两段结构（32 宽），切态时文件名不会横向跳。
              Text('完成')
                .width(32)
                .fontSize(13)
                .fontColor('#FFFFFF')
                .maxLines(1)
              Text(this.tText)
                .layoutWeight(1)
                .fontSize(13)
                .fontColor('#FFFFFF')
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            Row() {
              Row()
                .height(4)
                .borderRadius(2)
                .backgroundColor('#FFFFFF')
                .width('100%')
            }
            .width('100%')
            .height(4)
            .borderRadius(2)
            .backgroundColor('#FFFFFF')
            if (this.tSub.length > 0) {
              Text(this.tSub)
                .fontSize(11)
                .fontColor('#E0E0E0')
                .width('100%')
            }
          }
          .width('96%')
          .padding({ left: 14, right: 14, top: 12, bottom: 12 })
          .backgroundColor(C_DONE_OK)
          .borderRadius(12)
          .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
          .margin({ top: this.topInset + 56 })
        } else {
          // ── 传输中：蓝底 + **转动的地球** + 文件名 + 进度条 + 副行 ──
          Column({ space: 8 }) {
            Row({ space: 8 }) {
              // ★ 5.1.46 补回：5.1.45 重写时把地球（LoadingProgress）删掉了，
              //   vivi 截图确认「传输过程中的地球也没了」。
              LoadingProgress()
                .width(18)
                .height(18)
                .color('#FFFFFF')
              // ★★ 5.1.50：动词是**独立组件**，保证与文件名同一行。
              //   5.1.49 把它拼进 transferText，ArkUI 在空格处折行 ⇒
              //   「接收」独占第一行、文件名被挤掉（vivi 截图）。
              //   ⚠️ 宽度**固定 32**，绝不能给 layoutWeight（那是文件名该用的）。
              if (this.tVerb.length > 0) {
                Text(this.tVerb)
                  .fontSize(13)
                  .fontColor('#FFFFFF')
                  .width(32)
                  .maxLines(1)
              }
              // ★ 文件名独占剩余宽度，最多两行。
              //   5.1.44 实测超长文件名时 ArkUI 的 ellipsis 会把可用宽度算成 0
              //   （只画 `...`），所以给两行。
              Text(this.tText)
                .layoutWeight(1)
                .fontSize(13)
                .fontColor('#FFFFFF')
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            Row({ space: 8 }) {
              Row() {
                Row()
                  .height(4)
                  .borderRadius(2)
                  .backgroundColor('#FFD54F')
                  .width(`${this.tPercent}%`)
                  .animation({ duration: 240, curve: Curve.Linear })
              }
              .layoutWeight(1)
              .height(4)
              .borderRadius(2)
              .backgroundColor('#FFFFFF')
              Text(`${this.tPercent}%`)
                .fontSize(13)
                .fontColor('#FFFFFF')
                .fontWeight(FontWeight.Bold)
                .width(46)
                .textAlign(TextAlign.End)
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            if (this.tSub.length > 0 || this.tSpeed.length > 0) {
              Row() {
                Text(this.tSub)
                  .fontSize(11)
                  .fontColor('#E0E0E0')
                  .layoutWeight(1)
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
                Text(this.tSpeed)
                  .fontSize(11)
                  .fontColor('#FFFFFF')
                  .fontWeight(FontWeight.Medium)
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)
            }
          }
          .width('96%')
          .padding({ left: 14, right: 14, top: 12, bottom: 12 })
          .backgroundColor(C_PRIMARY)
          .borderRadius(12)
          .shadow({ radius: 16, color: '#20000000', offsetX: 0, offsetY: 6 })
          .margin({ top: this.topInset + 56 })
        }
      }

      // ---------------- 「发文件给谁」弹窗（消息 tab 加号） ----------------
      this.pickDialog()

      // ---------------- 网页地址二维码弹窗 ----------------
      this.qrDialog()

      // ---------------- 「关于」弹窗（版本号 / 开源仓库 / 移植说明）----------------
      this.aboutDialog()

      // ---------------- 图片全屏预览 ----------------
      this.imgPreviewView()

      // ---------------- 危险操作确认弹窗（始终最上层） ----------------
      this.confirmDialogView()
    }
    .width('100%')
    .height('100%')
  }
}
