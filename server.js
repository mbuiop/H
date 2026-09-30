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
const { DatabaseSync } = require('node:sqlite');

const DB_FILE = path.join(__dirname, 'app.db');
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 3000;

/* ============================================================
   دیتابیس — schema، ایندکس‌ها، و prepared statementها
   ============================================================ */
const db = new DatabaseSync(DB_FILE);
db.exec('PRAGMA journal_mode = WAL;'); // نوشتن هم‌زمان امن‌تر و سریع‌تر
db.exec('PRAGMA foreign_keys = ON;');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    business_name TEXT,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    signature TEXT,
    stamp TEXT,
    created_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

  CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

  CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    linked_username TEXT,
    created_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts(owner_id);

  CREATE TABLE IF NOT EXISTS invoice_counters (
    user_id TEXT PRIMARY KEY,
    counter INTEGER NOT NULL DEFAULT 0
  );

  CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL,
    seller_id TEXT NOT NULL,
    buyer_id TEXT,
    buyer_contact_id TEXT,
    share_token TEXT,
    lines TEXT NOT NULL,
    subtotal REAL DEFAULT 0, discount REAL DEFAULT 0, tax_rate REAL DEFAULT 0, tax REAL DEFAULT 0, total REAL DEFAULT 0,
    terms TEXT, payment_method TEXT, note TEXT,
    seller_signature TEXT, seller_stamp TEXT, buyer_signature TEXT,
    status TEXT NOT NULL DEFAULT 'pending_buyer',
    created_at INTEGER, seller_signed_at INTEGER, buyer_signed_at INTEGER
  );
  CREATE INDEX IF NOT EXISTS idx_invoices_seller ON invoices(seller_id);
  CREATE INDEX IF NOT EXISTS idx_invoices_buyer ON invoices(buyer_id);
  CREATE INDEX IF NOT EXISTS idx_invoices_share ON invoices(id, share_token);

  CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_messages_from_to ON messages(from_id, to_id);
  CREATE INDEX IF NOT EXISTS idx_messages_to_from ON messages(to_id, from_id);

  CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    to_user_id TEXT NOT NULL,
    type TEXT, text TEXT, invoice_id TEXT,
    created_at INTEGER NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(to_user_id);

  CREATE TABLE IF NOT EXISTS stores (
    user_id TEXT PRIMARY KEY,
    name TEXT,
    category TEXT,
    description TEXT,
    photos TEXT NOT NULL DEFAULT '[]',
    views INTEGER NOT NULL DEFAULT 0
  );

  CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    store_user_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    positive INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(store_user_id, reviewer_id)
  );
  CREATE INDEX IF NOT EXISTS idx_reviews_store ON reviews(store_user_id);

  CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    inviter_id TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
  );
`);

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
  listContacts: db.prepare('SELECT * FROM contacts WHERE owner_id = ? ORDER BY name COLLATE NOCASE'),
  getContact: db.prepare('SELECT * FROM contacts WHERE id = ? AND owner_id = ?'),
  getContactById: db.prepare('SELECT * FROM contacts WHERE id = ?'),
  deleteContact: db.prepare('DELETE FROM contacts WHERE id = ? AND owner_id = ?'),
  linkContact: db.prepare('UPDATE contacts SET linked_username = ? WHERE id = ?'),

  getCounter: db.prepare('SELECT counter FROM invoice_counters WHERE user_id = ?'),
  upsertCounter: db.prepare('INSERT INTO invoice_counters (user_id, counter) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET counter = counter + 1'),

  insertInvoice: db.prepare(`INSERT INTO invoices
    (id, number, seller_id, buyer_id, buyer_contact_id, share_token, lines, subtotal, discount, tax_rate, tax, total,
     terms, payment_method, note, seller_signature, seller_stamp, buyer_signature, status, created_at, seller_signed_at, buyer_signed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending_buyer', ?, ?, NULL)`),
  getInvoice: db.prepare('SELECT * FROM invoices WHERE id = ?'),
  listSales: db.prepare('SELECT * FROM invoices WHERE seller_id = ? ORDER BY created_at DESC'),
  listPurchases: db.prepare('SELECT * FROM invoices WHERE buyer_id = ? ORDER BY created_at DESC'),
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
  insertEmptyStore: db.prepare("INSERT OR IGNORE INTO stores (user_id, name, category, description, photos, views) VALUES (?, '', '', '', '[]', 0)"),
  updateStoreInfo: db.prepare('UPDATE stores SET name = ?, category = ?, description = ? WHERE user_id = ?'),
  updateStorePhotos: db.prepare('UPDATE stores SET photos = ? WHERE user_id = ?'),
  bumpStoreViews: db.prepare('UPDATE stores SET views = views + 1 WHERE user_id = ?'),
  listStoresByCategory: db.prepare("SELECT s.*, u.username, u.business_name FROM stores s JOIN users u ON u.id = s.user_id WHERE s.category = ? AND s.name != ''"),
  listAllStores: db.prepare("SELECT s.*, u.username, u.business_name FROM stores s JOIN users u ON u.id = s.user_id WHERE s.name != ''"),

  upsertReview: db.prepare(`INSERT INTO reviews (id, store_user_id, reviewer_id, positive, stars, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(store_user_id, reviewer_id) DO UPDATE SET positive = excluded.positive, stars = excluded.stars, created_at = excluded.created_at`),
  getMyReview: db.prepare('SELECT * FROM reviews WHERE store_user_id = ? AND reviewer_id = ?'),
  reviewStats: db.prepare('SELECT COUNT(*) AS total, SUM(positive) AS pos, AVG(stars) AS avgStars FROM reviews WHERE store_user_id = ?'),

  createInvite: db.prepare('INSERT INTO invites (token, contact_id, inviter_id, used, created_at) VALUES (?, ?, ?, 0, ?)'),
  getInvite: db.prepare('SELECT * FROM invites WHERE token = ?'),
  useInvite: db.prepare('UPDATE invites SET used = 1 WHERE token = ?'),
};

/* ============================================================
   رمز عبور و نشست (نشست‌ها هم تو دیتابیسن — ری‌استارت سرور
   دیگه همه رو از حساب بیرون نمی‌ندازه)
   ============================================================ */
function hashPassword(password, salt){ return crypto.scryptSync(password, salt, 64).toString('hex'); }
function newId(bytes){ return crypto.randomBytes(bytes || 8).toString('hex'); }

const SESSION_TTL = 30 * 24 * 60 * 60 * 1000; // ۳۰ روز
function makeToken(userId){
  const token = newId(32);
  stmt.insertSession.run(token, userId, Date.now() + SESSION_TTL);
  return token;
}
function userFromToken(token){
  if (!token) return null;
  const s = stmt.getSession.get(token);
  if (!s) return null;
  if (s.expires_at < Date.now()) return null;
  return stmt.getUserById.get(s.user_id) || null;
}
setInterval(() => { try { stmt.deleteExpiredSessions.run(Date.now()); } catch(err){} }, 60 * 60 * 1000);

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

function invoiceRowView(inv, forUserId){
  const isSeller = inv.seller_id === forUserId;
  const seller = stmt.getUserById.get(inv.seller_id);
  const buyer = inv.buyer_id ? stmt.getUserById.get(inv.buyer_id) : null;
  const contact = inv.buyer_contact_id ? stmt.getContactById.get(inv.buyer_contact_id) : null;
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
    sellerSignature: inv.seller_signature, sellerStamp: inv.seller_stamp, buyerSignature: inv.buyer_signature,
    status: inv.status, createdAt: inv.created_at,
  };
}

/* ============================================================
   احراز هویت
   ============================================================ */
route('POST', '/api/auth/register', { auth: false }, async (req, res) => {
  const { username, password, businessName } = await readBody(req);
  if (!username || username.length < 3) return send(res, 400, { error: 'نام کاربری حداقل ۳ کاراکتر' });
  if (!password || password.length < 4) return send(res, 400, { error: 'رمز عبور حداقل ۴ کاراکتر' });
  if (stmt.getUserByUsername.get(username)) return send(res, 409, { error: 'این نام کاربری قبلاً گرفته شده' });
  const salt = newId(16);
  const id = newId(8);
  try {
    stmt.insertUser.run(id, username, businessName || username, salt, hashPassword(password, salt), Date.now());
  } catch(err){
    return send(res, 409, { error: 'این نام کاربری قبلاً گرفته شده' });
  }
  send(res, 200, { token: makeToken(id), username, businessName: businessName || username });
});

route('POST', '/api/auth/login', { auth: false }, async (req, res, params, ip) => {
  if (rateLimited(ip)) return send(res, 429, { error: 'تلاش زیاد — یه دقیقه صبر کن' });
  const { username, password } = await readBody(req);
  const user = stmt.getUserByUsername.get(username);
  if (!user || hashPassword(password, user.salt) !== user.password_hash){
    return send(res, 401, { error: 'نام کاربری یا رمز اشتباهه' });
  }
  send(res, 200, { token: makeToken(user.id), username: user.username, businessName: user.business_name });
});

route('GET', '/api/me', {}, (req, res, params, ip, user) => {
  send(res, 200, { username: user.username, businessName: user.business_name, hasSignature: !!user.signature, hasStamp: !!user.stamp });
});
route('PUT', '/api/me', {}, async (req, res, params, ip, user) => {
  const { businessName } = await readBody(req);
  if (businessName) stmt.updateBusinessName.run(businessName, user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/me/signature', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image) return send(res, 400, { error: 'تصویری نیومد' });
  stmt.updateSignature.run(image, user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/me/stamp', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image) return send(res, 400, { error: 'تصویری نیومد' });
  stmt.updateStamp.run(image, user.id);
  send(res, 200, { ok: true });
});
route('GET', '/api/me/signature', {}, (req, res, params, ip, user) => {
  send(res, 200, { signature: user.signature, stamp: user.stamp });
});
route('GET', '/api/users/:username', {}, (req, res, params, ip, user) => {
  const target = stmt.getUserByUsername.get(params.username);
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
    const target = stmt.getUserByUsername.get(linkedUsername);
    if (!target) return send(res, 404, { error: 'کاربری با این نام کاربری پیدا نشد' });
    if (target.id === user.id) return send(res, 400, { error: 'نمی‌تونی خودت رو اضافه کنی' });
    linked = target.username;
  }
  const id = newId(8);
  stmt.insertContact.run(id, user.id, name.trim(), (phone || '').trim(), linked, Date.now());
  send(res, 200, { id, ownerId: user.id, name: name.trim(), phone: (phone || '').trim(), linkedUsername: linked, createdAt: Date.now() });
});
route('GET', '/api/contacts', {}, (req, res, params, ip, user) => {
  const rows = stmt.listContacts.all(user.id);
  send(res, 200, { contacts: rows.map(c => ({ id: c.id, name: c.name, phone: c.phone, linkedUsername: c.linked_username })) });
});
route('DELETE', '/api/contacts/:id', {}, (req, res, params, ip, user) => {
  const c = stmt.getContact.get(params.id, user.id);
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  stmt.deleteContact.run(params.id, user.id);
  send(res, 200, { ok: true });
});
route('PUT', '/api/contacts/:id/link', {}, async (req, res, params, ip, user) => {
  const c = stmt.getContact.get(params.id, user.id);
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  const { linkedUsername } = await readBody(req);
  const target = stmt.getUserByUsername.get(linkedUsername);
  if (!target) return send(res, 404, { error: 'همچین کاربری پیدا نشد' });
  stmt.linkContact.run(target.username, params.id);
  send(res, 200, { ok: true });
});

/* ============================================================
   فاکتورها
   ============================================================ */
route('POST', '/api/invoices', {}, async (req, res, params, ip, user) => {
  const body = await readBody(req);
  const contact = stmt.getContact.get(body.contactId, user.id);
  if (!contact) return send(res, 404, { error: 'اول این مشتری رو به لیست مشتری‌هات اضافه کن' });
  if (!Array.isArray(body.lines) || !body.lines.length) return send(res, 400, { error: 'حداقل یک قلم لازمه' });

  const buyerUser = contact.linked_username ? stmt.getUserByUsername.get(contact.linked_username) : null;

  stmt.upsertCounter.run(user.id);
  const number = stmt.getCounter.get(user.id).counter;

  const id = newId(10);
  const shareToken = buyerUser ? null : newId(16);
  const now = Date.now();
  stmt.insertInvoice.run(
    id, number, user.id, buyerUser ? buyerUser.id : null, contact.id, shareToken,
    JSON.stringify(body.lines), body.subtotal || 0, body.discount || 0, body.taxRate || 0, body.tax || 0, body.total || 0,
    body.terms || '', body.paymentMethod || '', body.note || '', user.signature || null, user.stamp || null,
    now, now
  );
  const shareLink = buyerUser ? null : ('/?sign=' + id + '&t=' + shareToken);
  send(res, 200, { id, number, shareLink, registered: !!buyerUser });
});

route('GET', '/api/invoices', {}, (req, res, params, ip, user) => {
  const sales = stmt.listSales.all(user.id).map(i => invoiceRowView(i, user.id));
  const purchases = stmt.listPurchases.all(user.id).map(i => invoiceRowView(i, user.id));
  send(res, 200, { sales, purchases });
});
route('GET', '/api/invoices/:id', {}, (req, res, params, ip, user) => {
  const inv = stmt.getInvoice.get(params.id);
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.seller_id !== user.id && inv.buyer_id !== user.id) return send(res, 403, { error: 'اجازه‌ی دیدن این فاکتور رو نداری' });
  send(res, 200, invoiceRowView(inv, user.id));
});

function notifySeller(inv, signerName){
  stmt.insertNotification.run(newId(8), inv.seller_id, 'invoice_signed', (signerName || 'مشتری') + ' فاکتور #' + inv.number + ' رو امضا کرد', inv.id, Date.now());
}

route('POST', '/api/invoices/:id/sign', {}, async (req, res, params, ip, user) => {
  const inv = stmt.getInvoice.get(params.id);
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.buyer_id !== user.id) return send(res, 403, { error: 'فقط خریدار می‌تونه امضا کنه' });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req);
  const signature = user.signature || body.signature;
  if (!signature) return send(res, 400, { error: 'امضایی موجود نیست' });
  if (body.saveAsDefault && body.signature && !user.signature){ stmt.updateSignature.run(body.signature, user.id); }
  stmt.signInvoice.run(signature, Date.now(), inv.id);
  notifySeller(inv, user.business_name);
  send(res, 200, { ok: true });
});

route('GET', '/api/public/invoices/:id', { auth: false }, (req, res, params) => {
  const inv = stmt.getInvoice.get(params.id);
  if (!inv || inv.buyer_id) return send(res, 404, { error: 'پیدا نشد' });
  if (!inv.share_token || inv.share_token !== req.query.get('t')) return send(res, 403, { error: 'لینک نامعتبره' });
  const seller = stmt.getUserById.get(inv.seller_id);
  const contact = inv.buyer_contact_id ? stmt.getContactById.get(inv.buyer_contact_id) : null;
  send(res, 200, {
    number: inv.number, sellerName: seller && seller.business_name, buyerName: contact && contact.name,
    lines: JSON.parse(inv.lines), subtotal: inv.subtotal, discount: inv.discount, taxRate: inv.tax_rate, tax: inv.tax, total: inv.total,
    terms: inv.terms, paymentMethod: inv.payment_method, note: inv.note,
    sellerSignature: inv.seller_signature, sellerStamp: inv.seller_stamp, status: inv.status,
  });
});
route('POST', '/api/public/invoices/:id/sign', { auth: false }, async (req, res, params) => {
  const inv = stmt.getInvoice.get(params.id);
  if (!inv || inv.buyer_id) return send(res, 404, { error: 'پیدا نشد' });
  if (!inv.share_token || inv.share_token !== req.query.get('t')) return send(res, 403, { error: 'لینک نامعتبره' });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req);
  if (!body.signature) return send(res, 400, { error: 'اول امضا کن' });
  stmt.signInvoice.run(body.signature, Date.now(), inv.id);
  const contact = inv.buyer_contact_id ? stmt.getContactById.get(inv.buyer_contact_id) : null;
  notifySeller(inv, contact && contact.name);
  send(res, 200, { ok: true });
});

/* ============================================================
   اعلان‌ها
   ============================================================ */
route('GET', '/api/notifications', {}, (req, res, params, ip, user) => {
  const list = stmt.listNotifications.all(user.id).map(n => ({ id: n.id, text: n.text, invoiceId: n.invoice_id, createdAt: n.created_at, read: !!n.read }));
  send(res, 200, { notifications: list, unreadCount: list.filter(n => !n.read).length });
});
route('POST', '/api/notifications/:id/read', {}, (req, res, params, ip, user) => {
  stmt.markNotifRead.run(params.id, user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/notifications/read-all', {}, (req, res, params, ip, user) => {
  stmt.markAllNotifRead.run(user.id);
  send(res, 200, { ok: true });
});

/* ============================================================
   گفتگوی خصوصی
   ============================================================ */
route('GET', '/api/messages/:username', {}, (req, res, params, ip, user) => {
  const other = stmt.getUserByUsername.get(params.username);
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const thread = stmt.getThread.all(user.id, other.id, other.id, user.id)
    .map(m => ({ from: m.from_id === user.id ? 'me' : 'them', text: m.text, createdAt: m.created_at }));
  send(res, 200, { messages: thread, businessName: other.business_name });
});
route('POST', '/api/messages/:username', {}, async (req, res, params, ip, user) => {
  const other = stmt.getUserByUsername.get(params.username);
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const { text } = await readBody(req);
  if (!text || !text.trim()) return send(res, 400, { error: 'متن خالیه' });
  stmt.insertMessage.run(newId(8), user.id, other.id, text.trim().slice(0, 2000), Date.now());
  send(res, 200, { ok: true });
});
route('GET', '/api/conversations', {}, (req, res, params, ip, user) => {
  const partnerRows = stmt.partnersFromMessages.all(user.id, user.id);
  const partnerIds = new Set(partnerRows.map(r => r.pid));
  // مشتری‌های لینک‌شده هم به لیست گفتگو اضافه می‌شن حتی اگه هنوز پیامی رد و بدل نشده
  stmt.listContacts.all(user.id).forEach(c => { if (c.linked_username){ const u = stmt.getUserByUsername.get(c.linked_username); if (u) partnerIds.add(u.id); } });

  const list = Array.from(partnerIds).map(id => {
    const u = stmt.getUserById.get(id);
    if (!u) return null;
    const last = stmt.lastMessageBetween.get(id, user.id, user.id, id);
    return { username: u.username, businessName: u.business_name, lastMessage: last ? last.text : null, lastAt: last ? last.created_at : 0 };
  }).filter(Boolean).sort((a, b) => b.lastAt - a.lastAt);
  send(res, 200, { conversations: list });
});

/* ============================================================
   فروشگاه من — مثل کانال، حداکثر ۱۰ عکس
   ============================================================ */
const MAX_STORE_PHOTOS = 10;
function ensureStore(userId){
  stmt.insertEmptyStore.run(userId);
  return stmt.getStore.get(userId);
}
route('GET', '/api/store', {}, (req, res, params, ip, user) => {
  const s = ensureStore(user.id);
  send(res, 200, { name: s.name, category: s.category, description: s.description, photos: JSON.parse(s.photos) });
});
route('PUT', '/api/store', {}, async (req, res, params, ip, user) => {
  ensureStore(user.id);
  const { name, category, description } = await readBody(req);
  stmt.updateStoreInfo.run(name || '', category || '', description || '', user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/store/photos', {}, async (req, res, params, ip, user) => {
  const s = ensureStore(user.id);
  const photos = JSON.parse(s.photos);
  const { photo, replaceIndex } = await readBody(req);
  if (!photo) return send(res, 400, { error: 'عکسی نیومد' });
  if (typeof replaceIndex === 'number' && replaceIndex >= 0 && replaceIndex < photos.length){
    photos[replaceIndex] = photo;
  } else {
    if (photos.length >= MAX_STORE_PHOTOS) return send(res, 400, { error: 'حداکثر ۱۰ عکس مجازه — اول یکی رو پاک کن یا جاش رو عوض کن' });
    photos.push(photo);
  }
  stmt.updateStorePhotos.run(JSON.stringify(photos), user.id);
  send(res, 200, { photos });
});
route('DELETE', '/api/store/photos/:index', {}, (req, res, params, ip, user) => {
  const s = ensureStore(user.id);
  const photos = JSON.parse(s.photos);
  const idx = parseInt(params.index, 10);
  if (isNaN(idx) || idx < 0 || idx >= photos.length) return send(res, 404, { error: 'پیدا نشد' });
  photos.splice(idx, 1);
  stmt.updateStorePhotos.run(JSON.stringify(photos), user.id);
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
  const target = stmt.getUserByUsername.get(params.username);
  if (!target) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  if (target.id === user.id) return send(res, 400, { error: 'نمی‌تونی به فروشگاه خودت نظر بدی' });
  const { positive, stars } = await readBody(req);
  const starsNum = Math.min(5, Math.max(1, parseInt(stars, 10) || 3));
  stmt.upsertReview.run(newId(8), target.id, user.id, positive ? 1 : 0, starsNum, Date.now());
  send(res, 200, { ok: true });
});

route('GET', '/api/stores/:username', {}, (req, res, params, ip, user) => {
  const target = stmt.getUserByUsername.get(params.username);
  if (!target) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  const s = ensureStore(target.id);
  if (target.id !== user.id) stmt.bumpStoreViews.run(target.id);
  const stats = stmt.reviewStats.get(target.id);
  const positive = stats.pos || 0, total = stats.total || 0, negative = total - positive;
  const myReview = stmt.getMyReview.get(target.id, user.id);
  send(res, 200, {
    username: target.username, businessName: target.business_name,
    name: s.name, category: s.category, description: s.description, photos: JSON.parse(s.photos),
    positive, negative, total, avgStars: stats.avgStars ? Math.round(stats.avgStars * 10) / 10 : 0,
    myReview: myReview ? { positive: !!myReview.positive, stars: myReview.stars } : null,
  });
});

route('GET', '/api/store/stats', {}, (req, res, params, ip, user) => {
  const stats = stmt.reviewStats.get(user.id);
  const s = stmt.getStore.get(user.id);
  const positive = stats.pos || 0, total = stats.total || 0, negative = total - positive;
  send(res, 200, {
    views: s ? s.views : 0, positive, negative, total,
    avgStars: stats.avgStars ? Math.round(stats.avgStars * 10) / 10 : 0,
    message: ownerFeedbackMessage(positive, negative),
  });
});

route('GET', '/api/discover', {}, (req, res, params, ip, user) => {
  const category = req.query.get('category');
  const rows = category ? stmt.listStoresByCategory.all(category) : stmt.listAllStores.all();
  const list = rows.map(s => {
    const stats = stmt.reviewStats.get(s.user_id);
    const positive = stats.pos || 0, total = stats.total || 0;
    const photos = JSON.parse(s.photos);
    return {
      username: s.username, businessName: s.business_name, name: s.name, category: s.category,
      coverPhoto: photos[0] || null, positive, negative: total - positive, total,
      avgStars: stats.avgStars ? Math.round(stats.avgStars * 10) / 10 : 0,
      score: wilsonScore(positive, total),
    };
  }).sort((a, b) => b.score - a.score);
  send(res, 200, { stores: list });
});

/* ============================================================
   دعوت مخاطب بدون حساب — یه لینک با توضیح آماده، قابل ارسال هر جا
   ============================================================ */
route('POST', '/api/contacts/:id/invite', {}, (req, res, params, ip, user) => {
  const c = stmt.getContact.get(params.id, user.id);
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  const token = newId(16);
  stmt.createInvite.run(token, c.id, user.id, Date.now());
  const message = 'سلام ' + c.name + '! ' + (user.business_name || user.username) + ' از طریق «فاکتور آنلاین» برات دعوت‌نامه فرستاده تا فاکتورها و پیام‌هامون رو یه‌جا و منظم مدیریت کنیم. با این لینک عضو شو: ';
  send(res, 200, { token, link: '/?invite=' + token, message });
});
route('GET', '/api/invites/:token', { auth: false }, (req, res, params) => {
  const inv = stmt.getInvite.get(params.token);
  if (!inv || inv.used) return send(res, 404, { error: 'این دعوت‌نامه پیدا نشد یا قبلاً استفاده شده' });
  const inviter = stmt.getUserById.get(inv.inviter_id);
  send(res, 200, { inviterName: inviter ? inviter.business_name : 'یک کسب‌وکار' });
});
route('POST', '/api/invites/:token/consume', {}, (req, res, params, ip, user) => {
  const inv = stmt.getInvite.get(params.token);
  if (!inv || inv.used) return send(res, 404, { error: 'این دعوت‌نامه پیدا نشد یا قبلاً استفاده شده' });
  const contact = stmt.getContactById.get(inv.contact_id);
  if (contact) stmt.linkContact.run(user.username, contact.id);
  // یه مخاطب متقابل هم برای کاربر تازه‌واردشده بساز، تا خودش هم بتونه به فرستنده فاکتور/پیام بده
  const inviter = stmt.getUserById.get(inv.inviter_id);
  if (inviter){
    const already = db.prepare('SELECT id FROM contacts WHERE owner_id = ? AND linked_username = ?').get(user.id, inviter.username);
    if (!already) stmt.insertContact.run(newId(8), user.id, inviter.business_name || inviter.username, '', inviter.username, Date.now());
  }
  stmt.useInvite.run(inv.token);
  send(res, 200, { ok: true, inviterName: inviter ? inviter.business_name : null, inviterUsername: inviter ? inviter.username : null });
});

route('GET', '/api/health', { auth: false }, (req, res) => send(res, 200, { ok: true, time: Date.now() }));

/* ============================================================
   فایل‌های استاتیک
   ============================================================ */
const MIME = { '.html':'text/html; charset=utf-8', '.js':'text/javascript', '.css':'text/css', '.json':'application/json',
  '.png':'image/png', '.jpg':'image/jpeg', '.svg':'image/svg+xml', '.webmanifest':'application/manifest+json' };
function serveStatic(req, res, pathname){
  let filePath = pathname === '/' ? '/index.html' : pathname;
  filePath = path.join(PUBLIC_DIR, filePath);
  if (!filePath.startsWith(PUBLIC_DIR)) { res.writeHead(403); return res.end('Forbidden'); }
  fs.readFile(filePath, (err, content) => {
    if (err){ res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream' });
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
    user = userFromToken(token);
    if (!user) return send(res, 401, { error: 'وارد نشدی یا نشستت منقضی شده' });
  }

  req.query = u.searchParams;

  try {
    await matched.route.handler(req, res, matched.params, ip, user);
  } catch(err){
    send(res, 500, { error: 'خطای سرور' });
  }
});

server.listen(PORT, () => {
  console.log('فاکتور ساز آنلاین (با دیتابیس SQLite) رو پورت ' + PORT + ' روشن شد');
});
