/**
 * AES 加解密 —— 平移自 app/src/main/java/com/fgsqw/lanshare/utils/AESUtils.java
 *
 * ## 与原实现的兼容性约束
 * Java 侧：
 *   Cipher.getInstance("AES/ECB/PKCS5Padding")
 *   SecretKeySpec(padKey(key), "AES")   其中 padKey 用 '\0' 补到 32 字节
 *   -> 实际算法 = **AES-256-ECB-PKCS7**（PKCS5 与 PKCS7 在 16 字节分组下等价）
 * 鸿蒙侧用 cryptoFramework 等价实现，算法串为 `AES256|ECB|PKCS7`。
 * 密钥补齐规则必须保持一致，否则两端密文不同，无法互通。
 *
 * ## ⚠️ 安全债（迁移到鸿蒙后建议排期修掉，但本次为保互通必须保持原样）
 * 1. **固定密钥**：密钥硬编码在客户端，任何拿到包的人都能提取。它不提供机密性。
 * 2. **ECB 模式**：相同明文块产生相同密文块，会泄漏明文结构（例如同一张图片的
 *    重复块可见）。标准做法是 GCM（带认证）或 CBC+随机 IV。
 * 3. **密钥补齐用 '\0'**：把 15 字符密码补成 32 字节，熵最多 15 字节。
 * 4. **无完整性校验**：ECB 无认证标签，密文可被篡改而不被发现。
 *
 * 建议的升级路径（协议 v5，需两端同时改）：
 *   首次握手 ECDH 协商会话密钥 -> AES-256-GCM + 每条消息随机 nonce
 * 详见 docs/迁移对照表.md 的「安全债」章节。
 */
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { util } from '@kit.ArkTS';
import { Log } from './Logger';

const TAG: string = 'AesCodec';

/** AES 分组字节数 */
const BLOCK_SIZE: number = 16;
/** 与 Java SecretKeySpec 对齐：密钥一律补齐到 32 字节 = AES-256 */
const KEY_SIZE: number = 32;

/** 缓存已转换的密钥对象，避免每条消息都重新构造（convertKeySync 有开销） */
let cachedKey: cryptoFramework.SymKey | null = null;
let cachedKeySource: string = '';

/**
 * 对应 Java AESUtils.padKey()：不足 32 位用 '\0' 补齐。
 * Java 用的是 key.getBytes()（平台默认编码），在中文 Windows 上是 GBK —— 但原密钥
 * '6c9b%8ErII@Rc&f' 全是 ASCII，所以 UTF-8 / GBK 结果一致，这里用 UTF-8 安全。
 */
function padKey(key: string): Uint8Array {
  const encoder: util.TextEncoder = new util.TextEncoder();
  const raw: Uint8Array = encoder.encodeInto(key);
  // ⚠️ 这里必须是 `>` 而不是 `>=`：**恰好 32 字节是合法的 AES-256 密钥**，
  // Java 的 padKey 也只在 `keyLength < 32` 时才补 '\0'。
  // 写成 `>=` 的后果是对聊天消息密钥（解密后正好 32 字符）抛异常，
  // 表现为「消息发出去对方解不开 / 自己也解不开」这种看起来像协议错位的故障。
  if (raw.length > KEY_SIZE) {
    // Java 侧 SecretKeySpec 对 >32 字节会抛 InvalidKeyException；这里显式报错，不静默截断
    throw new Error(`AES 密钥长度 ${raw.length} 超过 ${KEY_SIZE} 字节`);
  }
  const padded: Uint8Array = new Uint8Array(KEY_SIZE);
  padded.set(raw, 0);
  // 其余保持 0 —— 即 Java 补的 '\0'
  return padded;
}

function getSymKey(key: string): cryptoFramework.SymKey {
  if (cachedKey !== null && cachedKeySource === key) {
    return cachedKey;
  }
  const generator: cryptoFramework.SymKeyGenerator =
    cryptoFramework.createSymKeyGenerator('AES256');
  const blob: cryptoFramework.DataBlob = { data: padKey(key) };
  const symKey: cryptoFramework.SymKey = generator.convertKeySync(blob);
  cachedKey = symKey;
  cachedKeySource = key;
  return symKey;
}

/** 字节数组转小写十六进制（对应 Java AESUtils.bytesToHex） */
export function bytesToHex(bytes: Uint8Array): string {
  let out: string = '';
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, '0');
  }
  return out;
}

/** 十六进制转字节数组（对应 Java AESUtils.hexToBytes） */
export function hexToBytes(hex: string): Uint8Array {
  const len: number = Math.floor(hex.length / 2);
  const out: Uint8Array = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    out[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
  }
  return out;
}

export class AesCodec {
  /** 对应 Java AESUtils.encrypt：返回十六进制字符串 */
  static encrypt(data: string, key: string): string {
    const plain: Uint8Array = new util.TextEncoder().encodeInto(data);
    return bytesToHex(AesCodec.encryptBytes(plain, key));
  }

  /** 对应 Java AESUtils.decrypt：入参为十六进制字符串 */
  static decrypt(encryptedHex: string, key: string): string {
    const cipherBytes: Uint8Array = hexToBytes(encryptedHex);
    const plain: Uint8Array = AesCodec.decryptBytes(cipherBytes, key);
    return new util.TextDecoder().decodeToString(plain);
  }

  /** 对应 Java AESUtils.encryptBase64 */
  static encryptBase64(data: string, key: string): string {
    const plain: Uint8Array = new util.TextEncoder().encodeInto(data);
    const cipherBytes: Uint8Array = AesCodec.encryptBytes(plain, key);
    return new util.Base64Helper().encodeToStringSync(cipherBytes);
  }

  /** 对应 Java AESUtils.decryptBase64 */
  static decryptBase64(encryptedBase64: string, key: string): string {
    const cipherBytes: Uint8Array = new util.Base64Helper().decodeSync(encryptedBase64);
    const plain: Uint8Array = AesCodec.decryptBytes(cipherBytes, key);
    return new util.TextDecoder().decodeToString(plain);
  }

  /** 原始字节加密（文件分片、二进制消息用） */
  static encryptBytes(plain: Uint8Array, key: string): Uint8Array {
    try {
      // ECB 模式无需 iv，params 传 null
      const cipher: cryptoFramework.Cipher =
        cryptoFramework.createCipher('AES256|ECB|PKCS7');
      cipher.initSync(cryptoFramework.CryptoMode.ENCRYPT_MODE, getSymKey(key), null);
      const input: cryptoFramework.DataBlob = { data: plain };
      const output: cryptoFramework.DataBlob = cipher.doFinalSync(input);
      return output.data;
    } catch (e) {
      Log.e(TAG, `encryptBytes 失败: ${(e as Error).message}`);
      throw e as Error;
    }
  }

  /** 原始字节解密 */
  static decryptBytes(cipherBytes: Uint8Array, key: string): Uint8Array {
    if (cipherBytes.length === 0 || cipherBytes.length % BLOCK_SIZE !== 0) {
      throw new Error(`AES 密文长度非法: ${cipherBytes.length}（必须是 ${BLOCK_SIZE} 的整数倍）`);
    }
    try {
      const cipher: cryptoFramework.Cipher =
        cryptoFramework.createCipher('AES256|ECB|PKCS7');
      cipher.initSync(cryptoFramework.CryptoMode.DECRYPT_MODE, getSymKey(key), null);
      const input: cryptoFramework.DataBlob = { data: cipherBytes };
      const output: cryptoFramework.DataBlob = cipher.doFinalSync(input);
      return output.data;
    } catch (e) {
      Log.e(TAG, `decryptBytes 失败: ${(e as Error).message}`);
      throw e as Error;
    }
  }

  /**
   * 分片加密流：用于大文件传输，避免一次性把整个文件读进内存。
   *
   * 用法（与 Java Cipher.update/doFinal 语义一致）：
   *   const c = new AesStreamCipher(key, true);
   *   while (有分片) { out = c.update(chunk); 写出; }
   *   out = c.doFinal(); 写出;
   */
  static createStream(key: string, forEncrypt: boolean): AesStreamCipher {
    return new AesStreamCipher(key, forEncrypt);
  }
}

/**
 * 分片 AES 加解密器。
 * ECB 模式下每个分组独立，所以分片边界只要是 16 字节整数倍就安全；
 * 非整数倍的尾块会由 cryptoFramework 内部缓存，直到 doFinal。
 */
export class AesStreamCipher {
  private cipher: cryptoFramework.Cipher;
  private finished: boolean = false;

  constructor(key: string, forEncrypt: boolean) {
    this.cipher = cryptoFramework.createCipher('AES256|ECB|PKCS7');
    const mode: cryptoFramework.CryptoMode = forEncrypt
      ? cryptoFramework.CryptoMode.ENCRYPT_MODE
      : cryptoFramework.CryptoMode.DECRYPT_MODE;
    this.cipher.initSync(mode, getSymKey(key), null);
  }

  /** 处理一块数据，返回可立即写出的密文/明文（可能为空） */
  update(chunk: Uint8Array): Uint8Array {
    if (this.finished) {
      throw new Error('AesStreamCipher 已结束，不能再 update');
    }
    if (chunk.length === 0) {
      return new Uint8Array(0);
    }
    const out: cryptoFramework.DataBlob = this.cipher.updateSync({ data: chunk });
    return out.data;
  }

  /** 结束并取出最后一块（含 padding） */
  doFinal(): Uint8Array {
    if (this.finished) {
      return new Uint8Array(0);
    }
    this.finished = true;
    // 传空 input 只为取出内部缓存的尾块；加解密对称
    const out: cryptoFramework.DataBlob = this.cipher.doFinalSync({ data: new Uint8Array(0) });
    return out.data;
  }
}
