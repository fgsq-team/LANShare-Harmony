# -*- coding: utf-8 -*-
"""
5.0.55 ①（数据层）：给消息加「批号」`batchId`，供 UI 把同一批拆出的多条媒体消息
**聚合成一个气泡**显示成多缩略图（vivi 2026-10-02 要求）。

⚠️ 关键设计：**只加一个字段，不动记账粒度**。
   5.0.53 把接收的多张图拆成了 N 条消息（每条一个 id / 一条相册条目 / 一个点击入口），
   那是修「删一张整批失效」的正解，**不能回退**。
   现在要的「一个气泡多个缩略图」是**显示层**的事 —— 用批号把 N 条聚成一个气泡即可，
   组内每条仍各自独立记账 ⇒ 点第 2 张就打开第 2 张、删第 1 张不影响其余。

幂等：哨兵 `batchId`。写文件保持 LF。
"""
import io, sys

LS = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
SENTINEL = 'batchId: string = \'\';'

# ---------------------------------------------------------------- 1. ChatMessage 加字段
A_OLD = """  files: string = '';
}
"""
A_NEW = """  files: string = '';
  /**
   * ★ 5.0.55：**批号** —— 同一次传输拆出来的多条媒体消息共享同一个值。
   *
   * ⚠️ 为什么要有它：5.0.53 把「接收 N 张图」拆成了 N 条消息（为了每张各有独立的
   *   相册条目与点击入口，修「删一张整批失效」），但界面上一个气泡一条显得碎。
   *   有了批号，UI 可以把同批的 N 条**聚合成一个气泡**、显示成宫格缩略图，
   *   而组内每条仍各自独立记账 —— 显示聚合 ≠ 记账聚合。
   *   （vivi 2026-10-02：「接受的图片和视频是否可以在一个气泡里显示多个缩略图」）
   *
   * 空串 = 不属于任何批次（单发、发送方向、文本消息、以及 5.0.55 之前的历史数据），
   * 这种消息在 UI 里各自成一个气泡 —— 与改动前行为完全一致。
   */
  batchId: string = '';
}

/**
 * ★ 5.0.55：**显示层**的分组 —— 一个「气泡」对应一条或多条消息。
 *
 * ⚠️ 只是视图模型，不参与任何记账：`msgs` 里的每个元素都是 `chatRing` 里的
 *   真实消息对象（同一引用），所以点第 k 张、删第 k 条全都走各自原本的逻辑。
 */
export class ChatGroup {
  /** ForEach 的 key（由 `Index.buildChatGroups` 按「会变的量」拼出来，见其注释） */
  key: string = '';
  /** 组内消息（按时间顺序）。长度 1 = 普通消息，>1 = 同批媒体 */
  msgs: ChatMessage[] = [];
  /** 整组是否都是「文件」类消息（宫格只对这类生效） */
  isFiles: boolean = false;
  /** 组内**全部**是图片/视频 —— 决定了渲染成宫格而不是文件名气泡 */
  isMedia: boolean = false;
  incoming: boolean = true;
  timeMs: number = 0;
}
"""
# 注意：ChatGroup 紧跟 ChatMessage 之后定义，放在同一个 OLD 块里更省事。
A_OLD_TAIL = """  /**
   * 5.0.31：这一批的**全部文件名**（'\\n' 分隔，顺序 = 传输顺序）。
   *
   * ⚠️ 为什么要它：多发时 `content` 只是「N 个文件」，UI 拿不到任何一个名字，
   *    于是既出不了缩略图、也没法做「点开左右滑」。老版本只能显示一行干文字。
   *    单发时也填（长度 1），省得调用方分叉。
   */
  files: string = '';
}
"""
assert_old = A_OLD_TAIL

# ---------------------------------------------------------------- 2. 批号生成器 + appendChat 参数
B_OLD = """  /**
   * 新增一条聊天记录。
   * 与 Android 的 MessageContent 对齐：`incoming` 对应它的 `isLeft`。
   */
  private appendChat(
    incoming: boolean, peerName: string, peerIp: string, content: string, source: string,
    kind: string = 'text', files: string = ''
  ): void {
    const m: ChatMessage = new ChatMessage();
    this.chatSeq += 1;
    m.id = `c${this.chatSeq}-${Date.now()}`;
    m.incoming = incoming;
    m.peerName = peerName;
    m.peerIp = peerIp;
    m.content = content;
    m.timeMs = Date.now();
    m.source = source;
    m.kind = kind;
    m.files = files;
"""
B_NEW = """  /** ★ 5.0.55：批号自增计数（只要求唯一，不需要有语义） */
  private batchSeq: number = 0;

  /**
   * ★ 5.0.55：生成一个批号 —— 同一次传输拆出的多条媒体消息共享同一个值。
   * ⚠️ 不用「第一条消息的 id」当批号：那要先拿到 id 才能建后续条目，
   *    而 id 是在 `appendChat` 内部生成的，会绕成两段式写入。
   *    独立自增 + 时间戳最简单，且永不与 `c…` 形态的消息 id 相撞。
   */
  private nextBatchId(): string {
    this.batchSeq += 1;
    return `g${this.batchSeq}-${Date.now()}`;
  }

  /**
   * 新增一条聊天记录。
   * 与 Android 的 MessageContent 对齐：`incoming` 对应它的 `isLeft`。
   *
   * ★ 5.0.55：新增 `batchId`（默认空串）—— 见 `ChatMessage.batchId` 的注释。
   *   全部既有调用点都不传，行为不变。
   */
  private appendChat(
    incoming: boolean, peerName: string, peerIp: string, content: string, source: string,
    kind: string = 'text', files: string = '', batchId: string = ''
  ): void {
    const m: ChatMessage = new ChatMessage();
    this.chatSeq += 1;
    m.id = `c${this.chatSeq}-${Date.now()}`;
    m.incoming = incoming;
    m.peerName = peerName;
    m.peerIp = peerIp;
    m.content = content;
    m.timeMs = Date.now();
    m.source = source;
    m.kind = kind;
    m.files = files;
    m.batchId = batchId;
"""

# ---------------------------------------------------------------- 3. appendFileChat 打批号
C_OLD = """    if (incoming && names.length > 1 && LanService.allMedia(names)) {
      for (let i: number = 0; i < names.length; i++) {
        // 每条只带**自己那个**文件名：`content` = 名字（气泡文案）、
        // `files` = 名字（UI 靠它解析出媒体下标 0）。
        this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i]);
      }
      return;
    }
"""
C_NEW = """    if (incoming && names.length > 1 && LanService.allMedia(names)) {
      // ★ 5.0.55：这一批共用一个批号 —— UI 靠它把 N 条聚合成**一个**宫格气泡，
      //   而每条仍各自独立记账（点第 k 张 = 第 k 张，删第 k 条不影响其余）。
      const bid: string = this.nextBatchId();
      for (let i: number = 0; i < names.length; i++) {
        // 每条只带**自己那个**文件名：`content` = 名字（气泡文案）、
        // `files` = 名字（UI 靠它解析出媒体下标 0）。
        this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i], bid);
      }
      return;
    }
"""

# ---------------------------------------------------------------- 4. 序列化 / 反序列化
D_OLD = """        `"files":${MiniJson.quote(m.files)}}`);"""
D_NEW = """        `"files":${MiniJson.quote(m.files)},` +
        // ★ 5.0.55：批号也要落盘 —— 否则重启后同一批的多条消息散成 N 个气泡
        //  （与 5.0.43「Map 落盘必须把 key 一起写」是同一类失配）
        `"batchId":${MiniJson.quote(m.batchId)}}`);"""

E_OLD = """      m.files = LanService.chatStr(n, 'files');"""
E_NEW = """      m.files = LanService.chatStr(n, 'files');
      // ★ 5.0.55：旧数据没有这个字段 → 取到空串 → 各自成一个气泡（与改动前一致）
      m.batchId = LanService.chatStr(n, 'batchId');"""


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        assert s.count(old) == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, s.count(old))
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


src = io.open(LS, encoding='utf-8', newline='').read()
if SENTINEL in src:
    print('ALREADY APPLIED')
    sys.exit(0)

new_ls = apply(LS, [(assert_old, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW),
                    (D_OLD, D_NEW), (E_OLD, E_NEW)], 'LanService')

for sym, want in [('batchId: string = \'\';', 1),
                  ('export class ChatGroup {', 1),
                  ('private batchSeq: number = 0;', 1),
                  ('private nextBatchId(): string {', 1),
                  ('batchId: string = \'\'\n  ): void {', 1),
                  ('m.batchId = batchId;', 1),
                  ('const bid: string = this.nextBatchId();', 1),
                  ("'file', names[i], bid);", 1),
                  ('"batchId":${MiniJson.quote(m.batchId)}', 1),
                  ("m.batchId = LanService.chatStr(n, 'batchId');", 1)]:
    got = new_ls.count(sym)
    assert got == want, '符号校验失败 %r: 期望 %d 实为 %d' % (sym, want, got)
    print('  OK %2d  %s' % (got, sym[:56]))

delta = {}
for ch in '{}()[]':
    delta[ch] = new_ls.count(ch) - src.count(ch)
print('LanService 括号增量:', delta)

io.open(LS, 'w', encoding='utf-8', newline='\n').write(new_ls)
print('OK: 5.0.55 ① 数据层已应用')
