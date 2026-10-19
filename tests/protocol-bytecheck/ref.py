"""
Java 侧协议的逐行可信转写（参考实现）

来源（逐行对应）：
  app/src/main/java/com/fgsqw/lanshare/utils/DataEnc.java
  app/src/main/java/com/fgsqw/lanshare/utils/DataDec.java
  app/src/main/java/com/fgsqw/lanshare/utils/UDPTools.java
  app/src/main/java/com/fgsqw/lanshare/service/CustomDataOutputStream.java
  com/fgsqw/utils/ByteUtil.class   <- 大端（由 CustomDataOutputStream.writeInt
                                      的 `v >>> 24` 位移序列交叉验证）

本文件不参与交付，只用于对拍：它代表「Android 端的真实行为」。
任何 HarmonyOS 端改动导致对拍失败，即说明协议被破坏、无法与现网互通。
"""

HEADER_LEN = 12
MAGIC_NUM = 0x66677371
XOR_KEY = 0x45

MASK32 = 0xFFFFFFFF


def _i32(v):
    """模拟 Java int 的 32 位有符号截断"""
    v &= MASK32
    return v - 0x100000000 if v >= 0x80000000 else v


def int_to_bytes(v):
    """ByteUtil.intToBytes —— 大端 4 字节"""
    v &= MASK32
    return bytes([(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def long_to_bytes(v):
    """ByteUtil.longToBytes —— 大端 8 字节"""
    v &= 0xFFFFFFFFFFFFFFFF
    return bytes([(v >> s) & 0xFF for s in (56, 48, 40, 32, 24, 16, 8, 0)])


def bytes_to_int(b, off=0):
    """ByteUtil.bytesToInt —— 大端，返回有符号值"""
    return _i32((b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3])


class DataEnc:
    """对应 Java DataEnc"""

    def __init__(self, size=0):
        self.byte_len = size + HEADER_LEN
        self.bytes = bytearray(self.byte_len)
        self.index = HEADER_LEN
        self.scrambled = False

    # -------- 头部填充（全部写绝对偏移，与 Java 一致） --------
    def pack_data(self, cmd):
        self.index = HEADER_LEN
        self.scrambled = False
        self.set_cmd(cmd)
        self.set_count(0)
        self.set_length(0)
        return self

    def set_cmd(self, cmd):
        self._put_int_at(cmd, 0)
        return self

    def set_count(self, count):
        self._put_int_at(count, 4)
        return self

    def set_length(self, length):
        self._put_int_at(length, 8)
        return self

    def _put_int_at(self, v, i):
        self.bytes[i:i + 4] = int_to_bytes(v)

    # -------- payload 写入（相对 index） --------
    def put_byte(self, b):
        self.bytes[self.index] = b & 0xFF
        self.index += 1
        return self

    def put_bool(self, v):
        return self.put_byte(1 if v else 0)

    def put_short(self, v):
        self.bytes[self.index] = (v >> 8) & 0xFF
        self.bytes[self.index + 1] = v & 0xFF
        self.index += 2
        return self

    def put_int(self, v):
        self.bytes[self.index:self.index + 4] = int_to_bytes(v)
        self.index += 4
        return self

    def put_long(self, v):
        self.bytes[self.index:self.index + 8] = long_to_bytes(v)
        self.index += 8
        return self

    def put_bytes(self, bs):
        """Java: putInt(bs.length) + arraycopy(bs, 0, bytes, index, len)"""
        self.put_int(len(bs))
        self.bytes[self.index:self.index + len(bs)] = bs
        self.index += len(bs)
        return self

    def put_string(self, s):
        """Java: putBytes(val.getBytes(UTF_8))"""
        return self.put_bytes(s.encode('utf-8'))

    # -------- 完成封装 --------
    def enc_data(self):
        """Java encData(): setLength(index-12) 后，对 [0, index) 全段混淆"""
        self.set_length(self.index - HEADER_LEN)
        if not self.scrambled:
            for i in range(self.index):
                self.bytes[i] = ((self.bytes[i] - 1) & 0xFF) ^ XOR_KEY
            self.scrambled = True
        return bytes(self.bytes)

    def get_data_len(self):
        return self.index

    def wire(self):
        # 真实上线字节。Java 侧 encData() 返回的是整个预分配数组（含尾部 0 填充），
        # 但 IOUtil.write(out, dataEnc.getData(), dataEnc.getDataLen()) 只写 dataLen 字节，
        # 所以线上传输等价于 data[0:index]。
        self.enc_data()
        return bytes(self.bytes[:self.index])

    def enc_data_udp(self):
        # UDPTools.sendData(): MAGIC(4, 未混淆) + data[0:index]
        return int_to_bytes(MAGIC_NUM) + self.wire()


class DataDec:
    """对应 Java DataDec"""

    def __init__(self, bs, byte_len=None):
        self.bytes = bytearray(bs)
        self.byte_len = byte_len if byte_len is not None else len(bs)
        self.index = HEADER_LEN
        self.decoded = False

    # -------- 解混淆 --------
    def dec_header(self):
        for i in range(HEADER_LEN):
            self.bytes[i] = ((self.bytes[i] ^ XOR_KEY) + 1) & 0xFF

    def dec_data(self):
        length = self.get_length()
        for i in range(HEADER_LEN, length + HEADER_LEN):
            self.bytes[i] = ((self.bytes[i] ^ XOR_KEY) + 1) & 0xFF

    def dec_all_data(self):
        if self.decoded:
            return
        self.dec_header()
        self.dec_data()
        self.decoded = True

    # -------- 读取 --------
    def get_cmd(self):
        return bytes_to_int(self.bytes, 0)

    def get_count(self):
        return bytes_to_int(self.bytes, 4)

    def get_length(self):
        return bytes_to_int(self.bytes, 8)

    def get_int(self):
        v = bytes_to_int(self.bytes, self.index)
        self.index += 4
        return v

    def get_byte(self):
        v = self.bytes[self.index]
        self.index += 1
        return v

    def get_bytes(self):
        """Java: 先读 int 长度，再取该长度字节"""
        n = self.get_int()
        out = bytes(self.bytes[self.index:self.index + n])
        self.index += n
        return out

    def get_string(self):
        return self.get_bytes().decode('utf-8')


def udp_unwrap(datagram):
    """LANService.udpServer 的接收侧逻辑：校验魔数 -> 剥 4 字节 -> 解全部"""
    if len(datagram) < HEADER_LEN:
        return None
    if bytes_to_int(datagram, 0) != MAGIC_NUM:
        return None
    buff = datagram[4:]
    d = DataDec(buff, len(buff))
    d.dec_all_data()
    return d
