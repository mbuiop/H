/*
  لایه‌ی دیتابیس با شاردینگ.
  • DATABASE_URLS=postgres://a,postgres://b,...   → هر آدرس یک شارد (Postgres)
  • DATABASE_URL=postgres://...                   → یک شارد
  • هیچ‌کدام                                        → SQLite محلی (SQLITE_SHARDS=n برای تست چندشاردی)
  کد SQL با «?» نوشته می‌شه و برای Postgres خودکار به $1,$2,... تبدیل می‌شه.

  مسیریابی: شارد هر کاربر از روی شناسه‌اش مشخص می‌شه (shardOf). شناسه‌ی فاکتور/نشست/دعوت‌نامه
  طوری ساخته می‌شه که روی همون شاردِ صاحبش بیفته (newIdOn)، پس از روی خودِ شناسه شارد پیدا می‌شه.
  جدول‌های «دایرکتوری» (نام‌کاربری و تلفن) روی شاردِ hash(کلید) نگه‌داری می‌شن تا یکتایی سراسری بمونه.
*/
const path = require('path');
const crypto = require('crypto');

function makePg(url){
  const { Pool, types } = require('pg');
  types.setTypeParser(20, v => Number(v));
  types.setTypeParser(1700, v => parseFloat(v));
  const pool = new Pool({ connectionString: url, max: Number(process.env.PG_POOL) || 10, ssl: process.env.PGSSL === '1' ? { rejectUnauthorized: false } : undefined });
  pool.on('error', e => console.error('pg pool error:', e.message));
  const conv = sql => { let i = 0; return sql.replace(/\?/g, () => '$' + (++i)); };
  return {
    driver: 'postgres',
    init: () => pool.query('SELECT 1'),
    exec: sql => pool.query(sql),
    addColumn: (t, c, d) => pool.query('ALTER TABLE ' + t + ' ADD COLUMN IF NOT EXISTS ' + c + ' ' + d),
    prepare(sql){
      const text = conv(sql);
      return { get: async (...a) => (await pool.query(text, a)).rows[0], all: async (...a) => (await pool.query(text, a)).rows, run: async (...a) => { await pool.query(text, a); } };
    },
  };
}
function makeSqlite(file){
  const { DatabaseSync } = require('node:sqlite');
  const raw = new DatabaseSync(file);
  raw.exec('PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL; PRAGMA busy_timeout = 5000;');
  return {
    driver: 'sqlite',
    init: async () => {},
    exec: async sql => { raw.exec(sql); },
    addColumn: async (t, c, d) => { try { raw.exec('ALTER TABLE ' + t + ' ADD COLUMN ' + c + ' ' + d); } catch(e){} },
    prepare(sql){
      let st = null; const s = () => st || (st = raw.prepare(sql));
      return { get: async (...a) => s().get(...a), all: async (...a) => s().all(...a), run: async (...a) => { s().run(...a); } };
    },
  };
}

const urls = (process.env.DATABASE_URLS || process.env.DATABASE_URL || '').split(',').map(s => s.trim()).filter(Boolean);
let shards;
if (urls.length) shards = urls.map(makePg);
else {
  const n = Math.max(1, Number(process.env.SQLITE_SHARDS) || 1);
  shards = Array.from({ length: n }, (_, i) => makeSqlite(n === 1 ? (process.env.DB_FILE || path.join(__dirname, 'app.db')) : path.join(process.env.DB_DIR || __dirname, 'app.shard' + i + '.db')));
}
const N = shards.length;
const md5n = s => crypto.createHash('md5').update(String(s)).digest().readUInt32BE(0);
const shardOf = id => N === 1 ? 0 : (/^[0-9a-f]{8}/.test(id) ? parseInt(id.slice(0, 8), 16) : md5n(id)) % N;
const dirShard = key => N === 1 ? 0 : md5n(key) % N;
function newIdOn(shard, bytes){
  for (let i = 0; i < 100000; i++){ const id = crypto.randomBytes(bytes || 8).toString('hex'); if (shardOf(id) === shard) return id; }
  throw new Error('cannot generate id for shard ' + shard);
}
module.exports = { shards, N, shardOf, dirShard, newIdOn, driver: shards[0].driver };
