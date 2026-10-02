/*
  فاکتور ساز آنلاین — سرور با دیتابیس واقعی (SQLite)
  ------------------------------------------------------------
  این نسخه دیگه فایل JSON نیست — یه دیتابیس SQL واقعیه، با جدول،
  ایندکس، تراکنش (transaction) و قیدهای یکتایی (constraint) در سطح
  خود دیتابیس. از ماژول داخلی خود Node.js استفاده می‌کنه
  (node:sqlite، از Node 22 به بعد وجود داره) — پس بازم بدون هیچ
  npm install اجرا می‌شه.

  درباره‌ی Sharding: شاردینگ یعنی یه دیتابیس رو به چند سرور جدا
  تقسیم کنی، و فقط وقتی لازم می‌شه که حجم داده یا تعداد درخواست از
  چیزی که یک سرور تنها می‌تونه جواب بده رد بشه (معمولاً میلیون‌ها
  ردیف یا هزاران درخواست در ثانیه). یه دیتابیس SQL تک‌سروری با
  ایندکس درست، برای تا ده‌ها هزار کسب‌وکار و صدها هزار فاکتور بدون
  مشکل جواب می‌ده. اگه یه روز واقعاً به اون مقیاس رسیدی، مسیر
  طبیعی قبل از شاردینگ معمولاً «رفتن به Postgres روی یک سرور
  قوی‌تر + یک کپی فقط-خواندنی (read replica)»ست، نه شاردینگ —
  و اون هم وقتیه که این مشکل واقعی شده باشه، نه از الان.

  اجرا: node server.js
*/

const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const db = require('./db'); // Postgres اگه DATABASE_URL تنظیم باشه، وگرنه SQLite

const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 3000;

/* ============================================================
   دیتابیس — schema، ایندکس‌ها، و prepared statementها
   ============================================================ */

const SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    business_name TEXT,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    signature TEXT,
    stamp TEXT,
    created_at BIGINT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

  CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at BIGINT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

  CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    linked_username TEXT,
    created_at BIGINT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts(owner_id);

  CREATE TABLE IF NOT EXISTS invoice_counters (
    user_id TEXT PRIMARY KEY,
    counter BIGINT NOT NULL DEFAULT 0
  );

  CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    number BIGINT NOT NULL,
    seller_id TEXT NOT NULL,
    buyer_id TEXT,
    buyer_contact_id TEXT,
    share_token TEXT,
    lines TEXT NOT NULL,
    subtotal DOUBLE PRECISION DEFAULT 0, discount DOUBLE PRECISION DEFAULT 0, tax_rate DOUBLE PRECISION DEFAULT 0, tax DOUBLE PRECISION DEFAULT 0, total DOUBLE PRECISION DEFAULT 0,
    terms TEXT, payment_method TEXT, note TEXT,
    seller_signature TEXT, seller_stamp TEXT, buyer_signature TEXT,
    status TEXT NOT NULL DEFAULT 'pending_buyer',
    created_at BIGINT, seller_signed_at BIGINT, buyer_signed_at BIGINT
  );
  CREATE INDEX IF NOT EXISTS idx_invoices_seller ON invoices(seller_id);
  CREATE INDEX IF NOT EXISTS idx_invoices_buyer ON invoices(buyer_id);
  CREATE INDEX IF NOT EXISTS idx_invoices_share ON invoices(id, share_token);

  CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at BIGINT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_messages_from_to ON messages(from_id, to_id);
  CREATE INDEX IF NOT EXISTS idx_messages_to_from ON messages(to_id, from_id);

  CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    to_user_id TEXT NOT NULL,
    type TEXT, text TEXT, invoice_id TEXT,
    created_at BIGINT NOT NULL,
    read BIGINT NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(to_user_id);

  CREATE TABLE IF NOT EXISTS stores (
    user_id TEXT PRIMARY KEY,
    name TEXT,
    category TEXT,
    description TEXT,
    photos TEXT NOT NULL DEFAULT '[]',
    views BIGINT NOT NULL DEFAULT 0
  );

  CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    store_user_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    positive BIGINT NOT NULL,
    stars BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    UNIQUE(store_user_id, reviewer_id)
  );
  CREATE INDEX IF NOT EXISTS idx_reviews_store ON reviews(store_user_id);

  CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    inviter_id TEXT NOT NULL,
    used BIGINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL
  );
`;

const SCHEMA2_SQL = `
  CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone ON users(phone) WHERE phone IS NOT NULL;
  CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone_norm);
  CREATE TABLE IF NOT EXISTS store_posts (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, text TEXT, image TEXT,
    created_at BIGINT NOT NULL, edited_at BIGINT
  );
  CREATE INDEX IF NOT EXISTS idx_posts_user ON store_posts(user_id, created_at);
`;

const stmt = {
  insertUser: db.prepare('INSERT INTO users (id, username, business_name, salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)'),
  getUserByUsername: db.prepare('SELECT * FROM users WHERE username = ?'),
  getUserById: db.prepare('SELECT * FROM users WHERE id = ?'),
  updateBusinessName: db.prepare('UPDATE users SET business_name = ? WHERE id = ?'),
  updateSignature: db.prepare('UPDATE users SET signature = ? WHERE id = ?'),
  updateStamp: db.prepare('UPDATE users SET stamp = ? WHERE id = ?'),

  insertSession: db.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)'),
  getSession: db.prepare('SELECT * FROM sessions WHERE token = ?'),
  deleteExpiredSessions: db.prepare('DELETE FROM sessions WHERE expires_at < ?'),

  insertContact: db.prepare('INSERT INTO contacts (id, owner_id, name, phone, linked_username, created_at) VALUES (?, ?, ?, ?, ?, ?)'),
  listContacts: db.prepare('SELECT * FROM contacts WHERE owner_id = ? ORDER BY LOWER(name)'),
  getContact: db.prepare('SELECT * FROM contacts WHERE id = ? AND owner_id = ?'),
  getContactById: db.prepare('SELECT * FROM contacts WHERE id = ?'),
  deleteContact: db.prepare('DELETE FROM contacts WHERE id = ? AND owner_id = ?'),
  linkContact: db.prepare('UPDATE contacts SET linked_username = ? WHERE id = ?'),

  getCounter: db.prepare('SELECT counter FROM invoice_counters WHERE user_id = ?'),
  upsertCounter: db.prepare('INSERT INTO invoice_counters (user_id, counter) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET counter = invoice_counters.counter + 1 RETURNING counter'),

  insertInvoice: db.prepare(`INSERT INTO invoices
    (id, number, seller_id, buyer_id, buyer_contact_id, share_token, lines, subtotal, discount, tax_rate, tax, total,
     terms, payment_method, note, design, seller_signature, seller_stamp, buyer_signature, status, created_at, seller_signed_at, buyer_signed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending_buyer', ?, ?, NULL)`),
  getInvoice: db.prepare('SELECT * FROM invoices WHERE id = ?'),
  listSales: db.prepare('SELECT * FROM invoices WHERE seller_id = ? ORDER BY created_at DESC LIMIT 300'),
  listPurchases: db.prepare('SELECT * FROM invoices WHERE buyer_id = ? ORDER BY created_at DESC LIMIT 300'),
  signInvoice: db.prepare("UPDATE invoices SET buyer_signature = ?, status = 'complete', buyer_signed_at = ? WHERE id = ?"),

  insertMessage: db.prepare('INSERT INTO messages (id, from_id, to_id, text, created_at) VALUES (?, ?, ?, ?, ?)'),
  getThread: db.prepare('SELECT * FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) ORDER BY created_at ASC'),
  partnersFromMessages: db.prepare('SELECT DISTINCT to_id AS pid FROM messages WHERE from_id = ? UNION SELECT DISTINCT from_id AS pid FROM messages WHERE to_id = ?'),
  lastMessageBetween: db.prepare('SELECT * FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) ORDER BY created_at DESC LIMIT 1'),

  insertNotification: db.prepare('INSERT INTO notifications (id, to_user_id, type, text, invoice_id, created_at, read) VALUES (?, ?, ?, ?, ?, ?, 0)'),
  listNotifications: db.prepare('SELECT * FROM notifications WHERE to_user_id = ? ORDER BY created_at DESC LIMIT 50'),
  markNotifRead: db.prepare('UPDATE notifications SET read = 1 WHERE id = ? AND to_user_id = ?'),
  markAllNotifRead: db.prepare('UPDATE notifications SET read = 1 WHERE to_user_id = ?'),

  getStore: db.prepare('SELECT * FROM stores WHERE user_id = ?'),
  insertEmptyStore: db.prepare("INSERT INTO stores (user_id, name, category, description, photos, views) VALUES (?, '', '', '', '[]', 0) ON CONFLICT DO NOTHING"),
  updateStoreInfo: db.prepare('UPDATE stores SET name = ?, category = ?, description = ? WHERE user_id = ?'),
  updateStorePhotos: db.prepare('UPDATE stores SET photos = ? WHERE user_id = ?'),
  bumpStoreViews: db.prepare('UPDATE stores SET views = views + 1 WHERE user_id = ?'),
  listStoresByCategory: db.prepare("SELECT s.*, u.username, u.business_name FROM stores s JOIN users u ON u.id = s.user_id WHERE s.category = ? AND s.name != ''"),
  listAllStores: db.prepare("SELECT s.*, u.username, u.business_name FROM stores s JOIN users u ON u.id = s.user_id WHERE s.name != ''"),

  upsertReview: db.prepare(`INSERT INTO reviews (id, store_user_id, reviewer_id, positive, stars, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(store_user_id, reviewer_id) DO UPDATE SET positive = excluded.positive, stars = excluded.stars, created_at = excluded.created_at`),
  getMyReview: db.prepare('SELECT * FROM reviews WHERE store_user_id = ? AND reviewer_id = ?'),
  reviewStats: db.prepare('SELECT COUNT(*) AS total, SUM(positive) AS pos, AVG(stars) AS avg_stars FROM reviews WHERE store_user_id = ?'),

  createInvite: db.prepare('INSERT INTO invites (token, contact_id, inviter_id, used, created_at) VALUES (?, ?, ?, 0, ?)'),
  getInvite: db.prepare('SELECT * FROM invites WHERE token = ?'),
  useInvite: db.prepare('UPDATE invites SET used = 1 WHERE token = ?'),
};

/* ============================================================
   رمز عبور و نشست (نشست‌ها هم تو دیتابیسن — ری‌استارت سرور
   دیگه همه رو از حساب بیرون نمی‌ندازه)
   ============================================================ */
function hashPassword(password, salt){ return crypto.scryptSync(password, salt, 64).toString('hex'); }
// نسخه‌ی غیرمسدودکننده — ورود هم‌زمان چندصد نفر دیگه سرور رو قفل نمی‌کنه
const scryptAsync = (p, s) => new Promise((ok, no) => crypto.scrypt(p, s, 64, (e, k) => e ? no(e) : ok(k.toString('hex'))));
Object.assign(stmt, {
  setUserPhone: db.prepare('UPDATE users SET phone = ? WHERE id = ?'),
  getUserByPhone: db.prepare('SELECT * FROM users WHERE phone = ?'),
  contactsByPhone: db.prepare('SELECT * FROM contacts WHERE phone_norm = ? AND linked_username IS NULL'),
  insertContactP: db.prepare('INSERT INTO contacts (id, owner_id, name, phone, phone_norm, linked_username, created_at) VALUES (?,?,?,?,?,?,?)'),
  updateInvoice: db.prepare("UPDATE invoices SET lines=?, subtotal=?, discount=?, tax_rate=?, tax=?, total=?, terms=?, payment_method=?, note=?, design=?, buyer_signature=NULL, buyer_signed_at=NULL, status='pending_buyer' WHERE id=?"),
  contactByOwnerLink: db.prepare('SELECT id FROM contacts WHERE owner_id = ? AND linked_username = ?'),
  deleteInvoice: db.prepare('DELETE FROM invoices WHERE id = ?'),
  insertPost: db.prepare('INSERT INTO store_posts (id, user_id, text, image, created_at) VALUES (?,?,?,?,?)'),
  listPosts: db.prepare('SELECT * FROM store_posts WHERE user_id = ? ORDER BY created_at DESC LIMIT 60'),
  getPost: db.prepare('SELECT * FROM store_posts WHERE id = ? AND user_id = ?'),
  updatePost: db.prepare('UPDATE store_posts SET text = ?, edited_at = ? WHERE id = ? AND user_id = ?'),
  deletePost: db.prepare('DELETE FROM store_posts WHERE id = ? AND user_id = ?'),
  latestPostImage: db.prepare('SELECT image FROM store_posts WHERE user_id = ? AND image IS NOT NULL ORDER BY created_at DESC LIMIT 1'),
});
function normPhone(p){
  let d = String(p || '').replace(/[۰-۹]/g, c => '۰۱۲۳۴۵۶۷۸۹'.indexOf(c)).replace(/\D/g, '');
  if (d.startsWith('0098')) d = d.slice(4); else if (d.startsWith('98') && d.length >= 12) d = d.slice(2);
  if (d.length === 10 && d[0] === '9') d = '0' + d;
  return d.length >= 10 && d.length <= 11 ? d : '';
}
const DZ_LAYOUTS = ['diag', 'band', 'side', 'min', 'dark', 'card'], DZ_FONTS = ['Lalezar', 'Noto Kufi Arabic', 'Vazirmatn'];
function sanitizeDesign(d){
  d = (d && typeof d === 'object') ? d : {};
  const hex = v => /^#[0-9a-fA-F]{6}$/.test(v) ? v : null;
  return { layout: DZ_LAYOUTS.includes(d.layout) ? d.layout : 'diag', font: DZ_FONTS.includes(d.font) ? d.font : 'Lalezar', c1: hex(d.c1) || '#0f3d4c', c2: hex(d.c2) || '#12909f' };
}
function parseDesign(str){ try { return sanitizeDesign(JSON.parse(str)); } catch(e){ return sanitizeDesign(); } }
function calcTotals(lines, taxRate){
  const L = (Array.isArray(lines) ? lines : []).slice(0, 50).map(l => {
    const qty = Math.max(0, +l.qty || 0), price = Math.max(0, +l.price || 0), gross = qty * price;
    const discount = Math.min(gross, Math.max(0, +l.discount || 0));
    return { name: String(l.name || '').slice(0, 120), qty, price, discount, net: gross - discount, gross };
  }).filter(l => l.name && l.qty > 0 && l.price > 0);
  const subtotal = L.reduce((a, l) => a + l.gross, 0), discount = L.reduce((a, l) => a + l.discount, 0);
  const tr = Math.min(100, Math.max(0, +taxRate || 0)), base = subtotal - discount, tax = Math.round(base * tr / 100);
  return { lines: L.map(({ gross, ...r }) => r), subtotal, discount, taxRate: tr, tax, total: base + tax };
}
function newId(bytes){ return crypto.randomBytes(bytes || 8).toString('hex'); }

const SESSION_TTL = 30 * 24 * 60 * 60 * 1000; // ۳۰ روز
async function makeToken(userId){
  const token = newId(32);
  await stmt.insertSession.run(token, userId, Date.now() + SESSION_TTL);
  return token;
}
async function userFromToken(token){
  if (!token) return null;
  const s = (await stmt.getSession.get(token));
  if (!s) return null;
  if (s.expires_at < Date.now()) return null;
  return (await stmt.getUserById.get(s.user_id)) || null;
}
setInterval(async () => { try { await stmt.deleteExpiredSessions.run(Date.now()); } catch(err){} }, 60 * 60 * 1000);

/* ============================================================
   محدودسازی نرخ درخواست روی ورود/ثبت‌نام
   ============================================================ */
const attempts = new Map();
function rateLimited(ip){
  const now = Date.now();
  const windowMs = 60 * 1000;
  const list = (attempts.get(ip) || []).filter(t => now - t < windowMs);
  list.push(now);
  attempts.set(ip, list);
  return list.length > 15;
}

/* ============================================================
   ابزارهای HTTP پایه
   ============================================================ */
function send(res, status, obj){
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(body);
}
function readBody(req){
  return new Promise((resolve) => {
    let data = '';
    req.on('data', chunk => { data += chunk; if (data.length > 8 * 1024 * 1024) req.destroy(); });
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch(err){ resolve({}); } });
    req.on('error', () => resolve({}));
  });
}

const routes = [];
function route(method, pattern, opts, handler){
  if (typeof opts === 'function'){ handler = opts; opts = {}; }
  routes.push({ method, segments: pattern.split('/').filter(Boolean), handler, auth: opts.auth !== false });
}
function matchRoute(method, pathname){
  const segs = pathname.split('/').filter(Boolean);
  for (const r of routes){
    if (r.method !== method) continue;
    if (r.segments.length !== segs.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < segs.length; i++){
      const rs = r.segments[i];
      if (rs.startsWith(':')) params[rs.slice(1)] = decodeURIComponent(segs[i]);
      else if (rs !== segs[i]) { ok = false; break; }
    }
    if (ok) return { route: r, params };
  }
  return null;
}

/* ============================================================
   کمکی‌ها برای تبدیل ردیف دیتابیس (snake_case) به شکلی که
   فرانت‌اند قبلاً باهاش کار می‌کرد
   ============================================================ */
function userPublic(u){ return { username: u.username, businessName: u.business_name }; }

async function invoiceRowView(inv, forUserId, light){
  const isSeller = inv.seller_id === forUserId;
  const seller = (await stmt.getUserById.get(inv.seller_id));
  const buyer = inv.buyer_id ? (await stmt.getUserById.get(inv.buyer_id)) : null;
  const contact = inv.buyer_contact_id ? (await stmt.getContactById.get(inv.buyer_contact_id)) : null;
  return {
    id: inv.id, number: inv.number,
    role: isSeller ? 'seller' : 'buyer',
    label: isSeller ? 'فاکتور فروش' : 'فاکتور خرید',
    counterpartName: isSeller ? (buyer ? buyer.business_name : (contact && contact.name)) : (seller && seller.business_name),
    counterpartUsername: isSeller ? (buyer && buyer.username) : (seller && seller.username),
    buyerRegistered: !!buyer,
    sellerName: seller && seller.business_name, buyerName: buyer ? buyer.business_name : (contact && contact.name),
    lines: JSON.parse(inv.lines), subtotal: inv.subtotal, discount: inv.discount,
    taxRate: inv.tax_rate, tax: inv.tax, total: inv.total,
    terms: inv.terms, paymentMethod: inv.payment_method, note: inv.note,
    ...(light ? {} : { sellerSignature: inv.seller_signature, sellerStamp: inv.seller_stamp, buyerSignature: inv.buyer_signature }),
    design: parseDesign(inv.design), status: inv.status, createdAt: inv.created_at,
  };
}

/* ============================================================
   احراز هویت
   ============================================================ */
route('POST', '/api/auth/register', { auth: false }, async (req, res, params, ip) => {
  if (rateLimited(ip)) return send(res, 429, { error: 'تلاش زیاد — یه دقیقه صبر کن' });
  const { username, password, businessName, phone } = await readBody(req);
  if (!username || !/^[\p{L}\p{N}_.]{3,24}$/u.test(username)) return send(res, 400, { error: 'نام کاربری ۳ تا ۲۴ حرف/عدد، بدون فاصله' });
  if (!password || password.length < 4) return send(res, 400, { error: 'رمز عبور حداقل ۴ کاراکتر' });
  if ((await stmt.getUserByUsername.get(username))) return send(res, 409, { error: 'این نام کاربری قبلاً گرفته شده' });
  const pn = normPhone(phone);
  if (phone && !pn) return send(res, 400, { error: 'شماره تلفن معتبر نیست' });
  if (pn && (await stmt.getUserByPhone.get(pn))) return send(res, 409, { error: 'این شماره قبلاً ثبت شده' });
  const salt = newId(16);
  const id = newId(8);
  try {
    await stmt.insertUser.run(id, username, String(businessName || username).slice(0, 80), salt, await scryptAsync(password, salt), Date.now());
    if (pn){ await stmt.setUserPhone.run(pn, id); for (const c of await stmt.contactsByPhone.all(pn)) await stmt.linkContact.run(username, c.id); }
  } catch(err){
    return send(res, 409, { error: 'این نام کاربری قبلاً گرفته شده' });
  }
  send(res, 200, { token: await makeToken(id), username, businessName: businessName || username });
});

route('POST', '/api/auth/login', { auth: false }, async (req, res, params, ip) => {
  if (rateLimited(ip)) return send(res, 429, { error: 'تلاش زیاد — یه دقیقه صبر کن' });
  const { username, password } = await readBody(req);
  const user = (await stmt.getUserByUsername.get(username));
  if (!user || (await scryptAsync(String(password || ''), user.salt)) !== user.password_hash){
    return send(res, 401, { error: 'نام کاربری یا رمز اشتباهه' });
  }
  send(res, 200, { token: await makeToken(user.id), username: user.username, businessName: user.business_name });
});

route('GET', '/api/me', {}, async (req, res, params, ip, user) => {
  send(res, 200, { username: user.username, businessName: user.business_name, hasSignature: !!user.signature, hasStamp: !!user.stamp, phone: user.phone || '' });
});
route('PUT', '/api/me', {}, async (req, res, params, ip, user) => {
  const { businessName, phone } = await readBody(req);
  if (businessName) await stmt.updateBusinessName.run(String(businessName).slice(0, 80), user.id);
  if (phone !== undefined){
    const pn = normPhone(phone);
    if (phone && !pn) return send(res, 400, { error: 'شماره تلفن معتبر نیست' });
    const other = pn && (await stmt.getUserByPhone.get(pn));
    if (other && other.id !== user.id) return send(res, 409, { error: 'این شماره قبلاً ثبت شده' });
    await stmt.setUserPhone.run(pn || null, user.id);
    if (pn) for (const c of await stmt.contactsByPhone.all(pn)) if (c.owner_id !== user.id) await stmt.linkContact.run(user.username, c.id);
  }
  send(res, 200, { ok: true });
});
route('POST', '/api/me/signature', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image) return send(res, 400, { error: 'تصویری نیومد' });
  await stmt.updateSignature.run(image, user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/me/stamp', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image) return send(res, 400, { error: 'تصویری نیومد' });
  await stmt.updateStamp.run(image, user.id);
  send(res, 200, { ok: true });
});
route('GET', '/api/me/signature', {}, async (req, res, params, ip, user) => {
  send(res, 200, { signature: user.signature, stamp: user.stamp });
});
route('GET', '/api/users/:username', {}, async (req, res, params, ip, user) => {
  const target = (await stmt.getUserByUsername.get(params.username));
  if (!target) return send(res, 404, { error: 'همچین کاربری پیدا نشد' });
  if (target.id === user.id) return send(res, 400, { error: 'نمی‌تونی خودت رو انتخاب کنی' });
  send(res, 200, userPublic(target));
});

/* ============================================================
   مشتری‌های من
   ============================================================ */
route('POST', '/api/contacts', {}, async (req, res, params, ip, user) => {
  const { name, phone, linkedUsername } = await readBody(req);
  if (!name || !name.trim()) return send(res, 400, { error: 'اسم مشتری رو بنویس' });
  let linked = null;
  if (linkedUsername){
    const target = (await stmt.getUserByUsername.get(linkedUsername));
    if (!target) return send(res, 404, { error: 'کاربری با این نام کاربری پیدا نشد' });
    if (target.id === user.id) return send(res, 400, { error: 'نمی‌تونی خودت رو اضافه کنی' });
    linked = target.username;
  }
  const pn = normPhone(phone);
  if (!linked && pn){ const pu = (await stmt.getUserByPhone.get(pn)); if (pu && pu.id !== user.id) linked = pu.username; }
  const id = newId(8);
  await stmt.insertContactP.run(id, user.id, name.trim().slice(0, 80), (phone || '').trim(), pn || null, linked, Date.now());
  send(res, 200, { id, ownerId: user.id, name: name.trim(), phone: (phone || '').trim(), linkedUsername: linked, createdAt: Date.now() });
});
route('GET', '/api/contacts', {}, async (req, res, params, ip, user) => {
  const rows = (await stmt.listContacts.all(user.id));
  send(res, 200, { contacts: rows.map(c => ({ id: c.id, name: c.name, phone: c.phone, linkedUsername: c.linked_username })) });
});
route('DELETE', '/api/contacts/:id', {}, async (req, res, params, ip, user) => {
  const c = (await stmt.getContact.get(params.id, user.id));
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  await stmt.deleteContact.run(params.id, user.id);
  send(res, 200, { ok: true });
});
route('PUT', '/api/contacts/:id/link', {}, async (req, res, params, ip, user) => {
  const c = (await stmt.getContact.get(params.id, user.id));
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  const { linkedUsername } = await readBody(req);
  const target = (await stmt.getUserByUsername.get(linkedUsername));
  if (!target) return send(res, 404, { error: 'همچین کاربری پیدا نشد' });
  await stmt.linkContact.run(target.username, params.id);
  send(res, 200, { ok: true });
});

/* ============================================================
   فاکتورها
   ============================================================ */
route('POST', '/api/invoices', {}, async (req, res, params, ip, user) => {
  const body = await readBody(req);
  const contact = (await stmt.getContact.get(body.contactId, user.id));
  if (!contact) return send(res, 404, { error: 'اول این مشتری رو به لیست مشتری‌هات اضافه کن' });
  const T = calcTotals(body.lines, body.taxRate);
  if (!T.lines.length) return send(res, 400, { error: 'حداقل یک قلم لازمه' });

  const buyerUser = contact.linked_username ? (await stmt.getUserByUsername.get(contact.linked_username)) : null;

  const number = (await stmt.upsertCounter.get(user.id)).counter;

  const id = newId(10);
  const shareToken = buyerUser ? null : newId(16);
  const now = Date.now();
  await stmt.insertInvoice.run(
    id, number, user.id, buyerUser ? buyerUser.id : null, contact.id, shareToken,
    JSON.stringify(T.lines), T.subtotal, T.discount, T.taxRate, T.tax, T.total,
    String(body.terms || '').slice(0, 300), String(body.paymentMethod || '').slice(0, 60), String(body.note || '').slice(0, 500), JSON.stringify(sanitizeDesign(body.design)), user.signature || null, user.stamp || null,
    now, now
  );
  if (buyerUser){
    // لینک امضا مستقیم داخل پیام‌های سایت برای خریدار می‌ره
    await stmt.insertMessage.run(newId(8), user.id, buyerUser.id, '🧾 فاکتور #' + number + ' برای امضا: /?open=' + id, now);
    await stmt.insertNotification.run(newId(8), buyerUser.id, 'invoice_new', (user.business_name || user.username) + ' یه فاکتور برات صادر کرد (#' + number + ')', id, now);
  }
  const shareLink = buyerUser ? null : ('/?sign=' + id + '&t=' + shareToken);
  send(res, 200, { id, number, shareLink, registered: !!buyerUser });
});

route('GET', '/api/invoices', {}, async (req, res, params, ip, user) => {
  const sales = await Promise.all((await stmt.listSales.all(user.id)).map(i => invoiceRowView(i, user.id, true)));
  const purchases = await Promise.all((await stmt.listPurchases.all(user.id)).map(i => invoiceRowView(i, user.id, true)));
  send(res, 200, { sales, purchases });
});
route('GET', '/api/invoices/:id', {}, async (req, res, params, ip, user) => {
  const inv = (await stmt.getInvoice.get(params.id));
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.seller_id !== user.id && inv.buyer_id !== user.id) return send(res, 403, { error: 'اجازه‌ی دیدن این فاکتور رو نداری' });
  send(res, 200, await invoiceRowView(inv, user.id));
});

route('DELETE', '/api/invoices/:id', {}, async (req, res, params, ip, user) => {
  const inv = (await stmt.getInvoice.get(params.id));
  if (!inv || inv.seller_id !== user.id) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  await stmt.deleteInvoice.run(inv.id);
  if (inv.buyer_id) await stmt.insertNotification.run(newId(8), inv.buyer_id, 'invoice_deleted', (user.business_name || user.username) + ' فاکتور #' + inv.number + ' رو حذف کرد', null, Date.now());
  send(res, 200, { ok: true });
});
route('PUT', '/api/invoices/:id', {}, async (req, res, params, ip, user) => {
  const inv = (await stmt.getInvoice.get(params.id));
  if (!inv || inv.seller_id !== user.id) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  const body = await readBody(req);
  const T = calcTotals(body.lines, body.taxRate);
  if (!T.lines.length) return send(res, 400, { error: 'حداقل یک قلم لازمه' });
  // با ویرایش، امضای خریدار باطل می‌شه و باید دوباره امضا کنه
  await stmt.updateInvoice.run(JSON.stringify(T.lines), T.subtotal, T.discount, T.taxRate, T.tax, T.total,
    String(body.terms || '').slice(0, 300), String(body.paymentMethod || ''), String(body.note || '').slice(0, 500), JSON.stringify(sanitizeDesign(body.design)), inv.id);
  if (inv.buyer_id){
    await stmt.insertNotification.run(newId(8), inv.buyer_id, 'invoice_edited', (user.business_name || user.username) + ' فاکتور #' + inv.number + ' رو ویرایش کرد — دوباره امضا کن', inv.id, Date.now());
    await stmt.insertMessage.run(newId(8), user.id, inv.buyer_id, '✏️ فاکتور #' + inv.number + ' ویرایش شد، لطفاً دوباره امضا کن: /?open=' + inv.id, Date.now());
  }
  send(res, 200, { ok: true });
});

async function notifySeller(inv, signerName){
  await stmt.insertNotification.run(newId(8), inv.seller_id, 'invoice_signed', (signerName || 'مشتری') + ' فاکتور #' + inv.number + ' رو امضا کرد', inv.id, Date.now());
}

route('POST', '/api/invoices/:id/sign', {}, async (req, res, params, ip, user) => {
  const inv = (await stmt.getInvoice.get(params.id));
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.buyer_id !== user.id) return send(res, 403, { error: 'فقط خریدار می‌تونه امضا کنه' });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req);
  const signature = user.signature || body.signature;
  if (!signature) return send(res, 400, { error: 'امضایی موجود نیست' });
  if (body.saveAsDefault && body.signature && !user.signature){ await stmt.updateSignature.run(body.signature, user.id); }
  await stmt.signInvoice.run(signature, Date.now(), inv.id);
  await notifySeller(inv, user.business_name);
  send(res, 200, { ok: true });
});

route('GET', '/api/public/invoices/:id', { auth: false }, async (req, res, params) => {
  const inv = (await stmt.getInvoice.get(params.id));
  if (!inv || inv.buyer_id) return send(res, 404, { error: 'پیدا نشد' });
  if (!inv.share_token || inv.share_token !== req.query.get('t')) return send(res, 403, { error: 'لینک نامعتبره' });
  const seller = (await stmt.getUserById.get(inv.seller_id));
  const contact = inv.buyer_contact_id ? (await stmt.getContactById.get(inv.buyer_contact_id)) : null;
  send(res, 200, {
    number: inv.number, sellerName: seller && seller.business_name, buyerName: contact && contact.name,
    lines: JSON.parse(inv.lines), subtotal: inv.subtotal, discount: inv.discount, taxRate: inv.tax_rate, tax: inv.tax, total: inv.total,
    terms: inv.terms, paymentMethod: inv.payment_method, note: inv.note,
    sellerSignature: inv.seller_signature, sellerStamp: inv.seller_stamp, status: inv.status,
    design: parseDesign(inv.design), createdAt: inv.created_at,
  });
});
route('POST', '/api/public/invoices/:id/sign', { auth: false }, async (req, res, params) => {
  const inv = (await stmt.getInvoice.get(params.id));
  if (!inv || inv.buyer_id) return send(res, 404, { error: 'پیدا نشد' });
  if (!inv.share_token || inv.share_token !== req.query.get('t')) return send(res, 403, { error: 'لینک نامعتبره' });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req);
  if (!body.signature) return send(res, 400, { error: 'اول امضا کن' });
  await stmt.signInvoice.run(body.signature, Date.now(), inv.id);
  const contact = inv.buyer_contact_id ? (await stmt.getContactById.get(inv.buyer_contact_id)) : null;
  await notifySeller(inv, contact && contact.name);
  send(res, 200, { ok: true });
});

/* ============================================================
   اعلان‌ها
   ============================================================ */
route('GET', '/api/notifications', {}, async (req, res, params, ip, user) => {
  const list = (await stmt.listNotifications.all(user.id)).map(n => ({ id: n.id, text: n.text, invoiceId: n.invoice_id, createdAt: n.created_at, read: !!n.read }));
  send(res, 200, { notifications: list, unreadCount: list.filter(n => !n.read).length });
});
route('POST', '/api/notifications/:id/read', {}, async (req, res, params, ip, user) => {
  await stmt.markNotifRead.run(params.id, user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/notifications/read-all', {}, async (req, res, params, ip, user) => {
  await stmt.markAllNotifRead.run(user.id);
  send(res, 200, { ok: true });
});

/* ============================================================
   گفتگوی خصوصی
   ============================================================ */
route('GET', '/api/messages/:username', {}, async (req, res, params, ip, user) => {
  const other = (await stmt.getUserByUsername.get(params.username));
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const thread = (await stmt.getThread.all(user.id, other.id, other.id, user.id))
    .map(m => ({ from: m.from_id === user.id ? 'me' : 'them', text: m.text, createdAt: m.created_at }));
  send(res, 200, { messages: thread, businessName: other.business_name });
});
route('POST', '/api/messages/:username', {}, async (req, res, params, ip, user) => {
  const other = (await stmt.getUserByUsername.get(params.username));
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const { text } = await readBody(req);
  if (!text || !text.trim()) return send(res, 400, { error: 'متن خالیه' });
  await stmt.insertMessage.run(newId(8), user.id, other.id, text.trim().slice(0, 2000), Date.now());
  send(res, 200, { ok: true });
});
route('GET', '/api/conversations', {}, async (req, res, params, ip, user) => {
  const partnerRows = (await stmt.partnersFromMessages.all(user.id, user.id));
  const partnerIds = new Set(partnerRows.map(r => r.pid));
  // مشتری‌های لینک‌شده هم به لیست گفتگو اضافه می‌شن حتی اگه هنوز پیامی رد و بدل نشده
  for (const c of await stmt.listContacts.all(user.id)){ if (c.linked_username){ const u = await stmt.getUserByUsername.get(c.linked_username); if (u) partnerIds.add(u.id); } }
  const list = (await Promise.all(Array.from(partnerIds).map(async id => {
    const u = await stmt.getUserById.get(id);
    if (!u) return null;
    const last = await stmt.lastMessageBetween.get(id, user.id, user.id, id);
    return { username: u.username, businessName: u.business_name, lastMessage: last ? last.text : null, lastAt: last ? last.created_at : 0 };
  }))).filter(Boolean).sort((a, b) => b.lastAt - a.lastAt);
  send(res, 200, { conversations: list });
});

/* ============================================================
   فروشگاه من — مثل کانال، حداکثر ۱۰ عکس
   ============================================================ */
const MAX_STORE_PHOTOS = 10;
async function ensureStore(userId){
  await stmt.insertEmptyStore.run(userId);
  return (await stmt.getStore.get(userId));
}
route('GET', '/api/store', {}, async (req, res, params, ip, user) => {
  const s = await ensureStore(user.id);
  send(res, 200, { name: s.name, category: s.category, description: s.description, photos: JSON.parse(s.photos) });
});
route('PUT', '/api/store', {}, async (req, res, params, ip, user) => {
  await ensureStore(user.id);
  const { name, category, description } = await readBody(req);
  await stmt.updateStoreInfo.run(name || '', category || '', description || '', user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/store/photos', {}, async (req, res, params, ip, user) => {
  const s = await ensureStore(user.id);
  const photos = JSON.parse(s.photos);
  const { photo, replaceIndex } = await readBody(req);
  if (!photo) return send(res, 400, { error: 'عکسی نیومد' });
  if (typeof replaceIndex === 'number' && replaceIndex >= 0 && replaceIndex < photos.length){
    photos[replaceIndex] = photo;
  } else {
    if (photos.length >= MAX_STORE_PHOTOS) return send(res, 400, { error: 'حداکثر ۱۰ عکس مجازه — اول یکی رو پاک کن یا جاش رو عوض کن' });
    photos.push(photo);
  }
  await stmt.updateStorePhotos.run(JSON.stringify(photos), user.id);
  send(res, 200, { photos });
});
route('DELETE', '/api/store/photos/:index', {}, async (req, res, params, ip, user) => {
  const s = await ensureStore(user.id);
  const photos = JSON.parse(s.photos);
  const idx = parseInt(params.index, 10);
  if (isNaN(idx) || idx < 0 || idx >= photos.length) return send(res, 404, { error: 'پیدا نشد' });
  photos.splice(idx, 1);
  await stmt.updateStorePhotos.run(JSON.stringify(photos), user.id);
  send(res, 200, { photos });
});

/* ============================================================
   الگوریتم رتبه‌بندی منصفانه — Wilson score lower bound
   ------------------------------------------------------------
   چرا این الگوریتم؟ صرفاً درصد نظر مثبت رو مرتب کردن منصفانه نیست:
   یه فروشگاه با ۲ نظر مثبت از ۲ (۱۰۰٪) نباید بالاتر از فروشگاهی با
   ۸۰ نظر مثبت از ۱۰۰ (۸۰٪) بشینه — چون نمونه‌ش خیلی کوچیکه و
   اطمینانی بهش نیست. Wilson score این عدم‌قطعیت رو با تعداد نظرات
   می‌سنجه و یه عدد «حد پایین با ۹۵٪ اطمینان» می‌ده — همون روشی که
   ردیت برای مرتب کردن کامنت‌ها استفاده می‌کنه.
   ============================================================ */
function wilsonScore(positive, total){
  if (!total) return 0;
  const z = 1.96;
  const phat = positive / total;
  const denom = 1 + (z * z) / total;
  const centre = phat + (z * z) / (2 * total);
  const margin = z * Math.sqrt((phat * (1 - phat) + (z * z) / (4 * total)) / total);
  return (centre - margin) / denom;
}
function ownerFeedbackMessage(positive, negative){
  const total = positive + negative;
  if (!total) return 'هنوز نظری برای فروشگاهت ثبت نشده.';
  const badRatio = negative / total;
  if (badRatio <= 0.20) return 'شما ' + faDigitsSrv(negative) + ' نظر بد از ' + faDigitsSrv(total) + ' نظر دریافت کردی — همه‌چیز عالیه، همینطور ادامه بده.';
  if (badRatio <= 0.40) return 'شما ' + faDigitsSrv(negative) + ' نظر بد از ' + faDigitsSrv(total) + ' نظر دریافت کردی — وضعیت هنوز قابل قبوله، ولی رو کیفیت و اعتبار جنس‌هات بیشتر تمرکز کن.';
  return 'نظرات منفی شما نسبتاً زیاده (' + faDigitsSrv(negative) + ' از ' + faDigitsSrv(total) + ') — ممکنه فروشگاهت تو نتایج کم‌تر بالا بیاد. برای دیده‌شدن بهتر، رو کیفیت و صداقت در معرفی جنس‌هات کار کن.';
}
function faDigitsSrv(n){
  const map = {'0':'۰','1':'۱','2':'۲','3':'۳','4':'۴','5':'۵','6':'۶','7':'۷','8':'۸','9':'۹'};
  return String(n).replace(/[0-9]/g, d => map[d]);
}

route('POST', '/api/stores/:username/review', {}, async (req, res, params, ip, user) => {
  const target = (await stmt.getUserByUsername.get(params.username));
  if (!target) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  if (target.id === user.id) return send(res, 400, { error: 'نمی‌تونی به فروشگاه خودت نظر بدی' });
  const { positive, stars } = await readBody(req);
  const starsNum = Math.min(5, Math.max(1, parseInt(stars, 10) || 3));
  await stmt.upsertReview.run(newId(8), target.id, user.id, positive ? 1 : 0, starsNum, Date.now());
  send(res, 200, { ok: true });
});

route('GET', '/api/stores/:username', {}, async (req, res, params, ip, user) => {
  const target = (await stmt.getUserByUsername.get(params.username));
  if (!target) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  const s = await ensureStore(target.id);
  if (target.id !== user.id) await stmt.bumpStoreViews.run(target.id);
  const stats = (await stmt.reviewStats.get(target.id));
  const positive = stats.pos || 0, total = stats.total || 0, negative = total - positive;
  const myReview = (await stmt.getMyReview.get(target.id, user.id));
  send(res, 200, {
    username: target.username, businessName: target.business_name,
    name: s.name, category: s.category, description: s.description, photos: JSON.parse(s.photos),
    posts: (await stmt.listPosts.all(target.id)).map(postView),
    positive, negative, total, avgStars: stats.avg_stars ? Math.round(stats.avg_stars * 10) / 10 : 0,
    myReview: myReview ? { positive: !!myReview.positive, stars: myReview.stars } : null,
  });
});

route('GET', '/api/store/stats', {}, async (req, res, params, ip, user) => {
  const stats = (await stmt.reviewStats.get(user.id));
  const s = (await stmt.getStore.get(user.id));
  const positive = stats.pos || 0, total = stats.total || 0, negative = total - positive;
  send(res, 200, {
    views: s ? s.views : 0, positive, negative, total,
    avgStars: stats.avg_stars ? Math.round(stats.avg_stars * 10) / 10 : 0,
    message: ownerFeedbackMessage(positive, negative),
  });
});

route('GET', '/api/discover', {}, async (req, res, params, ip, user) => {
  const category = req.query.get('category');
  const rows = category ? (await stmt.listStoresByCategory.all(category)) : (await stmt.listAllStores.all());
  const list = (await Promise.all(rows.map(async s => {
    const stats = (await stmt.reviewStats.get(s.user_id));
    const positive = stats.pos || 0, total = stats.total || 0;
    const photos = JSON.parse(s.photos);
    return {
      username: s.username, businessName: s.business_name, name: s.name, category: s.category,
      coverPhoto: photos[0] || ((await stmt.latestPostImage.get(s.user_id)) || {}).image || null, positive, negative: total - positive, total,
      avgStars: stats.avg_stars ? Math.round(stats.avg_stars * 10) / 10 : 0,
      score: wilsonScore(positive, total),
    };
  }))).sort((a, b) => b.score - a.score);
  send(res, 200, { stores: list });
});

/* ============================================================
   دعوت مخاطب بدون حساب — یه لینک با توضیح آماده، قابل ارسال هر جا
   ============================================================ */
route('POST', '/api/contacts/:id/invite', {}, async (req, res, params, ip, user) => {
  const c = (await stmt.getContact.get(params.id, user.id));
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  const token = newId(16);
  await stmt.createInvite.run(token, c.id, user.id, Date.now());
  const message = 'سلام ' + c.name + '! ' + (user.business_name || user.username) + ' از طریق «فاکتور آنلاین» برات دعوت‌نامه فرستاده تا فاکتورها و پیام‌هامون رو یه‌جا و منظم مدیریت کنیم. با این لینک عضو شو: ';
  send(res, 200, { token, link: '/?invite=' + token, message });
});
route('GET', '/api/invites/:token', { auth: false }, async (req, res, params) => {
  const inv = (await stmt.getInvite.get(params.token));
  if (!inv || inv.used) return send(res, 404, { error: 'این دعوت‌نامه پیدا نشد یا قبلاً استفاده شده' });
  const inviter = (await stmt.getUserById.get(inv.inviter_id));
  send(res, 200, { inviterName: inviter ? inviter.business_name : 'یک کسب‌وکار' });
});
route('POST', '/api/invites/:token/consume', {}, async (req, res, params, ip, user) => {
  const inv = (await stmt.getInvite.get(params.token));
  if (!inv || inv.used) return send(res, 404, { error: 'این دعوت‌نامه پیدا نشد یا قبلاً استفاده شده' });
  const contact = (await stmt.getContactById.get(inv.contact_id));
  if (contact) await stmt.linkContact.run(user.username, contact.id);
  // یه مخاطب متقابل هم برای کاربر تازه‌واردشده بساز، تا خودش هم بتونه به فرستنده فاکتور/پیام بده
  const inviter = (await stmt.getUserById.get(inv.inviter_id));
  if (inviter){
    const already = await stmt.contactByOwnerLink.get(user.id, inviter.username);
    if (!already) await stmt.insertContact.run(newId(8), user.id, inviter.business_name || inviter.username, '', inviter.username, Date.now());
  }
  await stmt.useInvite.run(inv.token);
  send(res, 200, { ok: true, inviterName: inviter ? inviter.business_name : null, inviterUsername: inviter ? inviter.username : null });
});

const UPLOAD_DIR = path.join(__dirname, 'uploads');
fs.mkdirSync(UPLOAD_DIR, { recursive: true });
route('POST', '/api/upload', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  const m = /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$/.exec(image || '');
  if (!m) return send(res, 400, { error: 'فرمت عکس معتبر نیست' });
  const buf = Buffer.from(m[2], 'base64');
  if (buf.length > 3 * 1024 * 1024) return send(res, 413, { error: 'عکس بیش از ۳ مگابایته' });
  const name = newId(12) + '.' + (m[1] === 'jpeg' ? 'jpg' : m[1]);
  await fs.promises.writeFile(path.join(UPLOAD_DIR, name), buf);
  send(res, 200, { url: '/uploads/' + name });
});
const postView = p => ({ id: p.id, text: p.text, image: p.image, createdAt: p.created_at, editedAt: p.edited_at });
route('GET', '/api/store/posts', {}, async (req, res, params, ip, user) => send(res, 200, { posts: (await stmt.listPosts.all(user.id)).map(postView) }));
route('POST', '/api/store/posts', {}, async (req, res, params, ip, user) => {
  await ensureStore(user.id);
  const { text, image } = await readBody(req);
  const t = String(text || '').trim().slice(0, 3000);
  const img = typeof image === 'string' && /^\/uploads\/[a-f0-9]+\.(jpg|png|webp)$/.test(image) ? image : null;
  if (!t && !img) return send(res, 400, { error: 'متن یا عکس بفرست' });
  const id = newId(8), now = Date.now();
  await stmt.insertPost.run(id, user.id, t, img, now);
  send(res, 200, postView({ id, text: t, image: img, created_at: now, edited_at: null }));
});
route('PUT', '/api/store/posts/:id', {}, async (req, res, params, ip, user) => {
  if (!(await stmt.getPost.get(params.id, user.id))) return send(res, 404, { error: 'پست پیدا نشد' });
  const { text } = await readBody(req);
  await stmt.updatePost.run(String(text || '').trim().slice(0, 3000), Date.now(), params.id, user.id);
  send(res, 200, { ok: true });
});
route('DELETE', '/api/store/posts/:id', {}, async (req, res, params, ip, user) => {
  if (!(await stmt.getPost.get(params.id, user.id))) return send(res, 404, { error: 'پست پیدا نشد' });
  await stmt.deletePost.run(params.id, user.id);
  send(res, 200, { ok: true });
});

route('GET', '/api/health', { auth: false }, async (req, res) => send(res, 200, { ok: true, time: Date.now() }));

/* ============================================================
   فایل‌های استاتیک
   ============================================================ */
const MIME = { '.html':'text/html; charset=utf-8', '.js':'text/javascript', '.css':'text/css', '.json':'application/json',
  '.png':'image/png', '.jpg':'image/jpeg', '.svg':'image/svg+xml', '.webp':'image/webp', '.webmanifest':'application/manifest+json' };
function serveStatic(req, res, pathname){
  const isUp = pathname.startsWith('/uploads/');
  const base = isUp ? UPLOAD_DIR : PUBLIC_DIR;
  let filePath = path.join(base, isUp ? pathname.slice(8) : (pathname === '/' ? '/index.html' : pathname));
  if (!filePath.startsWith(base)) { res.writeHead(403); return res.end('Forbidden'); }
  fs.readFile(filePath, (err, content) => {
    if (err){ res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream', 'Cache-Control': isUp ? 'public, max-age=31536000, immutable' : 'no-cache' });
    res.end(content);
  });
}

/* ============================================================
   سرور اصلی
   ============================================================ */
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://localhost');
  const ip = req.socket.remoteAddress || 'unknown';

  if (req.method === 'OPTIONS'){
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    });
    return res.end();
  }

  if (!u.pathname.startsWith('/api/')) return serveStatic(req, res, u.pathname);

  const matched = matchRoute(req.method, u.pathname);
  if (!matched) return send(res, 404, { error: 'مسیر پیدا نشد' });

  let user = null;
  if (matched.route.auth){
    const authHeader = req.headers['authorization'] || '';
    const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
    user = await userFromToken(token);
    if (!user) return send(res, 401, { error: 'وارد نشدی یا نشستت منقضی شده' });
  }

  req.query = u.searchParams;

  try {
    await matched.route.handler(req, res, matched.params, ip, user);
  } catch(err){
    send(res, 500, { error: 'خطای سرور' });
  }
});

async function main(){
  await db.init();
  await db.exec(SCHEMA_SQL);
  await db.addColumn('users', 'phone', 'TEXT');
  await db.addColumn('contacts', 'phone_norm', 'TEXT');
  await db.addColumn('invoices', 'design', 'TEXT');
  await db.exec(SCHEMA2_SQL);
  server.listen(PORT, () => console.log('فاکتور ساز آنلاین (دیتابیس: ' + db.driver + ') رو پورت ' + PORT + ' روشن شد'));
}
main().catch(err => { console.error('خطا در راه‌اندازی:', err); process.exit(1); });
