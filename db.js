/*
  لایه‌ی دیتابیس — یک API async برای هر دو دیتابیس:
  • اگه DATABASE_URL تنظیم باشه  → Postgres (ماژول pg)
  • وگرنه                         → SQLite محلی (node:sqlite) برای توسعه
  کد SQL با «?» نوشته می‌شه و برای Postgres خودکار به $1,$2,... تبدیل می‌شه.
*/
const path = require('path');
let impl;
if (process.env.DATABASE_URL){
  const { Pool, types } = require('pg');
  types.setTypeParser(20, v => Number(v));      // BIGINT  → عدد (نه رشته)
  types.setTypeParser(1700, v => parseFloat(v)); // NUMERIC → عدد
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    max: Number(process.env.PG_POOL) || 10,
    ssl: process.env.PGSSL === '1' ? { rejectUnauthorized: false } : undefined,
  });
  pool.on('error', e => console.error('pg pool error:', e.message));
  const conv = sql => { let i = 0; return sql.replace(/\?/g, () => '$' + (++i)); };
  impl = {
    driver: 'postgres',
    init: () => pool.query('SELECT 1'),
    exec: sql => pool.query(sql),
    addColumn: (t, c, d) => pool.query('ALTER TABLE ' + t + ' ADD COLUMN IF NOT EXISTS ' + c + ' ' + d),
    prepare(sql){
      const text = conv(sql);
      return {
        get: async (...a) => (await pool.query(text, a)).rows[0],
        all: async (...a) => (await pool.query(text, a)).rows,
        run: async (...a) => { await pool.query(text, a); },
      };
    },
  };
} else {
  const { DatabaseSync } = require('node:sqlite');
  const raw = new DatabaseSync(process.env.DB_FILE || path.join(__dirname, 'app.db'));
  raw.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;');
  impl = {
    driver: 'sqlite',
    init: async () => {},
    exec: async sql => { raw.exec(sql); },
    addColumn: async (t, c, d) => { try { raw.exec('ALTER TABLE ' + t + ' ADD COLUMN ' + c + ' ' + d); } catch(e){} },
    prepare(sql){
      let st = null; const s = () => st || (st = raw.prepare(sql)); // lazy: جدول‌ها بعد از init ساخته می‌شن
      return { get: async (...a) => s().get(...a), all: async (...a) => s().all(...a), run: async (...a) => { s().run(...a); } };
    },
  };
}
module.exports = impl;
