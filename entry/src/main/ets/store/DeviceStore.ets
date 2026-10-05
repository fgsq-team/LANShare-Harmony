/**
 * 设备与消息持久化 —— 替代 app/src/main/java/com/fgsqw/lanshare/db/*.java
 *
 * ## 迁移映射
 * | Android                    | 鸿蒙                          |
 * |----------------------------|-------------------------------|
 * | android.database.sqlite.SQLiteOpenHelper | relationalStore.getRdbStore |
 * | SQLiteDatabase.rawQuery    | rdbStore.querySql             |
 * | SQLiteDatabase.execSQL     | rdbStore.executeSql           |
 * | ContentValues 插入          | rdbStore.insert               |
 *
 * 建表 SQL 沿用原 DBHelper 的 schema，只是把 SQLiteDatabase 换成 rdbStore。
 * rdbStore 底层就是 SQLite，SQL 语法可直接复用。
 *
 * ## 为什么不用对象映射（ORM）
 * 原项目也没有用 ORM，全是手写 SQL。保持手写 SQL 的好处是迁移时不用重写查询语义，
 * 且表结构变更可控。
 */
import { relationalStore } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { LanDevice } from '../core/DeviceCodec';
import { Log } from '../core/Logger';

const TAG: string = 'DeviceStore';
const DB_NAME: string = 'lanshare.db';

/** 建表语句。沿用原 DBHelper 的表结构 */
const SQL_CREATE_DEVICE: string = `
CREATE TABLE IF NOT EXISTS device (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  unique_uuid  TEXT NOT NULL UNIQUE,
  dev_name     TEXT,
  dev_ip       TEXT,
  dev_port     INTEGER,
  dev_mode     INTEGER,
  data_version INTEGER,
  battery_level INTEGER,
  charge_status INTEGER,
  last_seen    INTEGER
)`;

const SQL_CREATE_MESSAGE: string = `
CREATE TABLE IF NOT EXISTS message (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  msg_id     TEXT NOT NULL UNIQUE,
  peer_ip    TEXT,
  direction  INTEGER,
  content    TEXT,
  msg_type   INTEGER,
  length     INTEGER,
  created_at INTEGER
)`;

const SQL_CREATE_FILE_SHARE: string = `
CREATE TABLE IF NOT EXISTS file_share (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  file_name  TEXT,
  file_path  TEXT,
  file_size  INTEGER,
  peer_ip    TEXT,
  direction  INTEGER,
  created_at INTEGER
)`;

/** 一条聊天/文件消息记录 */
export class MessageRecord {
  msgId: string = '';
  peerIp: string = '';
  /** 0 = 收到，1 = 发出 */
  direction: number = 0;
  content: string = '';
  msgType: number = 0;
  length: number = 0;
  createdAt: number = 0;
}

export class DeviceStore {
  private store: relationalStore.RdbStore | null = null;
  private ready: boolean = false;

  get isReady(): boolean {
    return this.ready;
  }

  /** 打开（必要时创建）数据库。应用启动时调一次 */
  async init(ctx: common.UIAbilityContext): Promise<boolean> {
    if (this.ready) {
      return true;
    }
    try {
      const config: relationalStore.StoreConfig = {
        name: DB_NAME,
        securityLevel: relationalStore.SecurityLevel.S1
      };
      this.store = await relationalStore.getRdbStore(ctx, config);
      await this.store.executeSql(SQL_CREATE_DEVICE);
      await this.store.executeSql(SQL_CREATE_MESSAGE);
      await this.store.executeSql(SQL_CREATE_FILE_SHARE);
      this.ready = true;
      Log.i(TAG, '数据库已就绪');
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.e(TAG, `数据库初始化失败: ${err.code} ${err.message}`);
      return false;
    }
  }

  /** 插入或更新设备（按 uuid 去重） */
  async upsertDevice(d: LanDevice): Promise<void> {
    if (!this.ready || this.store === null) {
      return;
    }
    try {
      // 先查是否存在，存在则 UPDATE。rdbStore 没有原生 upsert
      const rs: relationalStore.ResultSet = await this.store.querySql(
        'SELECT id FROM device WHERE unique_uuid = ?', [d.uniqueUuid]
      );
      const exists: boolean = rs.goToFirstRow();
      rs.close();

      if (exists) {
        const predicates: relationalStore.RdbPredicates =
          new relationalStore.RdbPredicates('device');
        predicates.equalTo('unique_uuid', d.uniqueUuid);
        const values: relationalStore.ValuesBucket = this.toValues(d);
        await this.store.update(values, predicates);
      } else {
        await this.store.insert('device', this.toValues(d));
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `upsertDevice 失败: ${err.code} ${err.message}`);
    }
  }

  private toValues(d: LanDevice): relationalStore.ValuesBucket {
    const v: relationalStore.ValuesBucket = {
      'unique_uuid': d.uniqueUuid,
      'dev_name': d.devName,
      'dev_ip': d.devIp,
      'dev_port': d.devPort,
      'dev_mode': d.devMode,
      'data_version': d.dataVersion,
      'battery_level': d.batteryLevel,
      'charge_status': d.chargeStatus,
      'last_seen': d.lastSeenMs
    };
    return v;
  }

  /** 读取所有设备，按最后在线时间倒序 */
  async listDevices(): Promise<LanDevice[]> {
    const out: LanDevice[] = [];
    if (!this.ready || this.store === null) {
      return out;
    }
    try {
      const rs: relationalStore.ResultSet = await this.store.querySql(
        'SELECT * FROM device ORDER BY last_seen DESC', []
      );
      while (rs.goToNextRow()) {
        const d: LanDevice = new LanDevice();
        d.uniqueUuid = rs.getString(rs.getColumnIndex('unique_uuid'));
        d.devName = rs.getString(rs.getColumnIndex('dev_name'));
        d.devIp = rs.getString(rs.getColumnIndex('dev_ip'));
        d.devPort = rs.getLong(rs.getColumnIndex('dev_port'));
        d.devMode = rs.getLong(rs.getColumnIndex('dev_mode'));
        d.dataVersion = rs.getLong(rs.getColumnIndex('data_version'));
        d.batteryLevel = rs.getLong(rs.getColumnIndex('battery_level'));
        d.chargeStatus = rs.getLong(rs.getColumnIndex('charge_status'));
        d.lastSeenMs = rs.getLong(rs.getColumnIndex('last_seen'));
        out.push(d);
      }
      rs.close();
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `listDevices 失败: ${err.code} ${err.message}`);
    }
    return out;
  }

  async insertMessage(m: MessageRecord): Promise<void> {
    if (!this.ready || this.store === null) {
      return;
    }
    try {
      const v: relationalStore.ValuesBucket = {
        'msg_id': m.msgId,
        'peer_ip': m.peerIp,
        'direction': m.direction,
        'content': m.content,
        'msg_type': m.msgType,
        'length': m.length,
        'created_at': m.createdAt
      };
      await this.store.insert('message', v);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `insertMessage 失败: ${err.code} ${err.message}`);
    }
  }

  /** 取与某台设备的最近 n 条消息，按时间正序返回 */
  async listMessages(peerIp: string, limit: number = 100): Promise<MessageRecord[]> {
    const out: MessageRecord[] = [];
    if (!this.ready || this.store === null) {
      return out;
    }
    try {
      const rs: relationalStore.ResultSet = await this.store.querySql(
        'SELECT * FROM message WHERE peer_ip = ? ORDER BY created_at DESC LIMIT ?',
        [peerIp, limit]
      );
      while (rs.goToNextRow()) {
        const m: MessageRecord = new MessageRecord();
        m.msgId = rs.getString(rs.getColumnIndex('msg_id'));
        m.peerIp = rs.getString(rs.getColumnIndex('peer_ip'));
        m.direction = rs.getLong(rs.getColumnIndex('direction'));
        m.content = rs.getString(rs.getColumnIndex('content'));
        m.msgType = rs.getLong(rs.getColumnIndex('msg_type'));
        m.length = rs.getLong(rs.getColumnIndex('length'));
        m.createdAt = rs.getLong(rs.getColumnIndex('created_at'));
        out.push(m);
      }
      rs.close();
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `listMessages 失败: ${err.code} ${err.message}`);
    }
    // 结果集是倒序，翻正
    out.reverse();
    return out;
  }

  /** 记录一次文件收发 */
  async insertFileShare(
    fileName: string, filePath: string, fileSize: number, peerIp: string, direction: number
  ): Promise<void> {
    if (!this.ready || this.store === null) {
      return;
    }
    try {
      const v: relationalStore.ValuesBucket = {
        'file_name': fileName,
        'file_path': filePath,
        'file_size': fileSize,
        'peer_ip': peerIp,
        'direction': direction,
        'created_at': Date.now()
      };
      await this.store.insert('file_share', v);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `insertFileShare 失败: ${err.code} ${err.message}`);
    }
  }

  /** 清理超过 keepDays 天的历史记录 */
  async purgeOlderThan(keepDays: number): Promise<void> {
    if (!this.ready || this.store === null) {
      return;
    }
    const cutoff: number = Date.now() - keepDays * 24 * 3600 * 1000;
    try {
      await this.store.executeSql('DELETE FROM message WHERE created_at < ?', [cutoff]);
      await this.store.executeSql('DELETE FROM file_share WHERE created_at < ?', [cutoff]);
      Log.i(TAG, `已清理 ${keepDays} 天前的历史记录`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `purgeOlderThan 失败: ${err.code} ${err.message}`);
    }
  }

  /** 清空全部本地记录（设置页的"清除数据"） */
  async clearAll(): Promise<void> {
    if (!this.ready || this.store === null) {
      return;
    }
    try {
      await this.store.executeSql('DELETE FROM device');
      await this.store.executeSql('DELETE FROM message');
      await this.store.executeSql('DELETE FROM file_share');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `clearAll 失败: ${err.code} ${err.message}`);
    }
  }
}
