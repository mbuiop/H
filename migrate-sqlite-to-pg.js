/*
  انتقال داده‌های قدیمی SQLite به Postgres (یک‌بار):
    1) DATABASE_URL رو تنظیم کن و یک بار  node server.js  رو اجرا کن تا جدول‌ها ساخته بشن، بعد متوقفش کن
    2) DATABASE_URL=postgres://... node migrate-sqlite-to-pg.js app.db
  ردیف‌های تکراری نادیده گرفته می‌شن، پس اجرای دوباره‌اش بی‌خطره.
*/
const { DatabaseSync } = require('node:sqlite');
const { Pool } = require('pg');
const TABLES = ['users', 'sessions', 'contacts', 'invoice_counters', 'invoices', 'messages', 'notifications', 'stores', 'reviews', 'invites', 'store_posts'];
(async () => {
  if (!process.env.DATABASE_URL) throw new Error('DATABASE_URL تنظیم نشده');
  const src = new DatabaseSync(process.argv[2] || 'app.db');
  const pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: process.env.PGSSL === '1' ? { rejectUnauthorized: false } : undefined });
  for (const t of TABLES){
    let rows; try { rows = src.prepare('SELECT * FROM ' + t).all(); } catch(e){ console.log(t + ': (در SQLite نیست)'); continue; }
    let n = 0;
    for (const r of rows){
      const cols = Object.keys(r);
      await pool.query('INSERT INTO ' + t + ' (' + cols.join(',') + ') VALUES (' + cols.map((_, i) => '$' + (i + 1)).join(',') + ') ON CONFLICT DO NOTHING', cols.map(c => r[c]));
      n++;
    }
    console.log(t + ': ' + n + ' ردیف');
  }
  await pool.end();
})().catch(e => { console.error(e.message); process.exit(1); });
