/*
  فاکتور ساز آنلاین — سرور (Postgres شاردشده + کش Redis)
  اجرا:  node server.js
  محیط:  DATABASE_URLS=pg1,pg2,...  REDIS_URL=redis://...  WORKERS=4  PORT=3000
         (بدون این‌ها: SQLite محلی + کش حافظه‌ای — برای توسعه)
*/
const http = require('http');
const cluster = require('cluster');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { shards, N, shardOf, dirShard, newIdOn, driver } = require('./db');
const cache = require('./cache');

const PORT = process.env.PORT || 3000;
const WORKERS = Number(process.env.WORKERS) || 1;
const PUBLIC_DIR = path.join(__dirname, 'public');
const UPLOAD_DIR = process.env.UPLOAD_DIR || path.join(__dirname, 'uploads');
const CATEGORIES = ['موبایل', 'پوشاک', 'لوازم آرایشی'];

/* ============================ schema (روی هر شارد) ============================ */
const SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT NOT NULL, business_name TEXT, salt TEXT NOT NULL, password_hash TEXT NOT NULL, signature TEXT, stamp TEXT, created_at BIGINT NOT NULL);
  CREATE TABLE IF NOT EXISTS usernames (username TEXT PRIMARY KEY, user_id TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS phones (phone TEXT PRIMARY KEY, user_id TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at BIGINT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
  CREATE TABLE IF NOT EXISTS contacts (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL, phone TEXT, linked_username TEXT, created_at BIGINT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts(owner_id);
  CREATE TABLE IF NOT EXISTS invoice_counters (user_id TEXT PRIMARY KEY, counter BIGINT NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY, number BIGINT NOT NULL, seller_id TEXT NOT NULL, buyer_id TEXT, buyer_contact_id TEXT, share_token TEXT, lines TEXT NOT NULL,
    subtotal DOUBLE PRECISION DEFAULT 0, discount DOUBLE PRECISION DEFAULT 0, tax_rate DOUBLE PRECISION DEFAULT 0, tax DOUBLE PRECISION DEFAULT 0, total DOUBLE PRECISION DEFAULT 0,
    terms TEXT, payment_method TEXT, note TEXT, seller_signature TEXT, seller_stamp TEXT, buyer_signature TEXT,
    status TEXT NOT NULL DEFAULT 'pending_buyer', created_at BIGINT, seller_signed_at BIGINT, buyer_signed_at BIGINT);
  CREATE INDEX IF NOT EXISTS idx_invoices_seller ON invoices(seller_id, created_at);
  CREATE TABLE IF NOT EXISTS purchases (buyer_id TEXT NOT NULL, invoice_id TEXT NOT NULL, created_at BIGINT NOT NULL, PRIMARY KEY (buyer_id, invoice_id));
  CREATE INDEX IF NOT EXISTS idx_purchases_buyer ON purchases(buyer_id, created_at);
  CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL, text TEXT NOT NULL, created_at BIGINT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_messages_from_to ON messages(from_id, to_id, created_at);
  CREATE INDEX IF NOT EXISTS idx_messages_to_from ON messages(to_id, from_id, created_at);
  CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, to_user_id TEXT NOT NULL, type TEXT, text TEXT, invoice_id TEXT, created_at BIGINT NOT NULL, read BIGINT NOT NULL DEFAULT 0);
  CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(to_user_id, created_at);
  CREATE TABLE IF NOT EXISTS stores (user_id TEXT PRIMARY KEY, name TEXT, category TEXT, description TEXT, photos TEXT NOT NULL DEFAULT '[]', views BIGINT NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, store_user_id TEXT NOT NULL, reviewer_id TEXT NOT NULL, positive BIGINT NOT NULL, stars BIGINT NOT NULL, created_at BIGINT NOT NULL, UNIQUE(store_user_id, reviewer_id));
  CREATE INDEX IF NOT EXISTS idx_reviews_store ON reviews(store_user_id);
  CREATE TABLE IF NOT EXISTS invites (token TEXT PRIMARY KEY, contact_id TEXT NOT NULL, inviter_id TEXT NOT NULL, used BIGINT NOT NULL DEFAULT 0, created_at BIGINT NOT NULL);
  CREATE TABLE IF NOT EXISTS store_posts (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, text TEXT, image TEXT, created_at BIGINT NOT NULL, edited_at BIGINT);
  CREATE INDEX IF NOT EXISTS idx_posts_user ON store_posts(user_id, created_at);
`;
const COLUMNS = [['users', 'phone', 'TEXT'], ['contacts', 'phone_norm', 'TEXT'], ['invoices', 'design', 'TEXT'], ['store_posts', 'kind', 'TEXT'],
  ['stores', 'rev_total', 'BIGINT'], ['stores', 'rev_pos', 'BIGINT'], ['stores', 'rev_avg', 'DOUBLE PRECISION']];
const INDEX_SQL = `
  CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone_norm);
  CREATE INDEX IF NOT EXISTS idx_stores_cat ON stores(category);
`;
async function initDb(){
  for (const sh of shards){
    await sh.init(); await sh.exec(SCHEMA_SQL);
    for (const [t, c, d] of COLUMNS) await sh.addColumn(t, c, d);
    await sh.exec(INDEX_SQL);
  }
  if (N === 1){ // دیتابیس نسخه‌ی قبلی: جدول‌های جدید رو یک‌بار از داده‌ی موجود پر کن
    const sh = shards[0], empty = async t => !(await sh.prepare('SELECT 1 AS x FROM ' + t + ' LIMIT 1').get());
    if (await empty('usernames')) await sh.exec('INSERT INTO usernames (username, user_id) SELECT username, id FROM users WHERE true ON CONFLICT DO NOTHING');
    if (await empty('phones')) await sh.exec("INSERT INTO phones (phone, user_id) SELECT phone, id FROM users WHERE phone IS NOT NULL AND phone != '' ON CONFLICT DO NOTHING");
    if (await empty('purchases')) await sh.exec('INSERT INTO purchases (buyer_id, invoice_id, created_at) SELECT buyer_id, id, COALESCE(created_at, 0) FROM invoices WHERE buyer_id IS NOT NULL ON CONFLICT DO NOTHING');
  }
  for (const sh of shards){
    await sh.exec("UPDATE store_posts SET kind = 'image' WHERE kind IS NULL AND image IS NOT NULL");
    await sh.exec('UPDATE stores SET rev_total = (SELECT COUNT(*) FROM reviews WHERE store_user_id = stores.user_id), rev_pos = (SELECT COALESCE(SUM(positive),0) FROM reviews WHERE store_user_id = stores.user_id), rev_avg = (SELECT COALESCE(AVG(stars),0) FROM reviews WHERE store_user_id = stores.user_id) WHERE rev_total IS NULL');
  }
}

/* ============================ statements (یک مجموعه برای هر شارد) ============================ */
function buildStmts(sh){
  const p = q => sh.prepare(q);
  return {
    sh,
    insertUser: p('INSERT INTO users (id, username, business_name, salt, password_hash, created_at) VALUES (?,?,?,?,?,?)'),
    getUserAuth: p('SELECT id, username, business_name, salt, password_hash FROM users WHERE id = ?'),
    getUserLight: p('SELECT id, username, business_name, phone, (signature IS NOT NULL) AS has_sig, (stamp IS NOT NULL) AS has_stamp FROM users WHERE id = ?'),
    getUserImages: p('SELECT signature, stamp FROM users WHERE id = ?'),
    updateBusinessName: p('UPDATE users SET business_name = ? WHERE id = ?'),
    setUserPhone: p('UPDATE users SET phone = ? WHERE id = ?'),
    updateSignature: p('UPDATE users SET signature = ? WHERE id = ?'),
    updateStamp: p('UPDATE users SET stamp = ? WHERE id = ?'),
    deleteUser: p('DELETE FROM users WHERE id = ?'),
    getUsername: p('SELECT user_id FROM usernames WHERE username = ?'),
    claimUsername: p('INSERT INTO usernames (username, user_id) VALUES (?, ?)'),
    releaseUsername: p('DELETE FROM usernames WHERE username = ?'),
    getPhone: p('SELECT user_id FROM phones WHERE phone = ?'),
    claimPhone: p('INSERT INTO phones (phone, user_id) VALUES (?, ?)'),
    releasePhone: p('DELETE FROM phones WHERE phone = ?'),
    insertSession: p('INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)'),
    getSession: p('SELECT * FROM sessions WHERE token = ?'),
    deleteExpiredSessions: p('DELETE FROM sessions WHERE expires_at < ?'),
    insertContact: p('INSERT INTO contacts (id, owner_id, name, phone, phone_norm, linked_username, created_at) VALUES (?,?,?,?,?,?,?)'),
    listContacts: p('SELECT * FROM contacts WHERE owner_id = ? ORDER BY LOWER(name) LIMIT 2000'),
    getContact: p('SELECT * FROM contacts WHERE id = ? AND owner_id = ?'),
    getContactById: p('SELECT * FROM contacts WHERE id = ?'),
    deleteContact: p('DELETE FROM contacts WHERE id = ? AND owner_id = ?'),
    linkContact: p('UPDATE contacts SET linked_username = ? WHERE id = ?'),
    contactsByPhone: p('SELECT id, owner_id FROM contacts WHERE phone_norm = ? AND linked_username IS NULL LIMIT 500'),
    contactByOwnerLink: p('SELECT id FROM contacts WHERE owner_id = ? AND linked_username = ?'),
    upsertCounter: p('INSERT INTO invoice_counters (user_id, counter) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET counter = invoice_counters.counter + 1 RETURNING counter'),
    insertInvoice: p(`INSERT INTO invoices (id, number, seller_id, buyer_id, buyer_contact_id, share_token, lines, subtotal, discount, tax_rate, tax, total, terms, payment_method, note, design, seller_signature, seller_stamp, buyer_signature, status, created_at, seller_signed_at, buyer_signed_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,'pending_buyer',?,?,NULL)`),
    getInvoice: p('SELECT * FROM invoices WHERE id = ?'),
    listSales: p('SELECT * FROM invoices WHERE seller_id = ? ORDER BY created_at DESC LIMIT 300'),
    signInvoice: p("UPDATE invoices SET buyer_signature = ?, status = 'complete', buyer_signed_at = ? WHERE id = ?"),
    updateInvoice: p("UPDATE invoices SET lines=?, subtotal=?, discount=?, tax_rate=?, tax=?, total=?, terms=?, payment_method=?, note=?, design=?, buyer_signature=NULL, buyer_signed_at=NULL, status='pending_buyer' WHERE id=?"),
    deleteInvoice: p('DELETE FROM invoices WHERE id = ?'),
    insertPurchase: p('INSERT INTO purchases (buyer_id, invoice_id, created_at) VALUES (?,?,?) ON CONFLICT DO NOTHING'),
    listPurchaseIds: p('SELECT invoice_id FROM purchases WHERE buyer_id = ? ORDER BY created_at DESC LIMIT 300'),
    deletePurchase: p('DELETE FROM purchases WHERE buyer_id = ? AND invoice_id = ?'),
    insertMessage: p('INSERT INTO messages (id, from_id, to_id, text, created_at) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING'),
    getThread: p('SELECT * FROM (SELECT * FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) ORDER BY created_at DESC LIMIT 300) t ORDER BY created_at ASC'),
    partnersFromMessages: p('SELECT DISTINCT to_id AS pid FROM messages WHERE from_id = ? UNION SELECT DISTINCT from_id AS pid FROM messages WHERE to_id = ?'),
    lastMessageBetween: p('SELECT * FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) ORDER BY created_at DESC LIMIT 1'),
    insertNotification: p('INSERT INTO notifications (id, to_user_id, type, text, invoice_id, created_at, read) VALUES (?,?,?,?,?,?,0)'),
    listNotifications: p('SELECT * FROM notifications WHERE to_user_id = ? ORDER BY created_at DESC LIMIT 50'),
    markNotifRead: p('UPDATE notifications SET read = 1 WHERE id = ? AND to_user_id = ?'),
    markAllNotifRead: p('UPDATE notifications SET read = 1 WHERE to_user_id = ?'),
    getStore: p('SELECT * FROM stores WHERE user_id = ?'),
    insertEmptyStore: p("INSERT INTO stores (user_id, name, category, description, photos, views, rev_total, rev_pos, rev_avg) VALUES (?, '', '', '', '[]', 0, 0, 0, 0) ON CONFLICT DO NOTHING"),
    updateStoreInfo: p('UPDATE stores SET name = ?, category = ?, description = ? WHERE user_id = ?'),
    addStoreViews: p('UPDATE stores SET views = views + ? WHERE user_id = ?'),
    upsertReview: p(`INSERT INTO reviews (id, store_user_id, reviewer_id, positive, stars, created_at) VALUES (?,?,?,?,?,?)
      ON CONFLICT(store_user_id, reviewer_id) DO UPDATE SET positive = excluded.positive, stars = excluded.stars, created_at = excluded.created_at`),
    refreshReviewAgg: p('UPDATE stores SET rev_total = (SELECT COUNT(*) FROM reviews WHERE store_user_id = ?), rev_pos = (SELECT COALESCE(SUM(positive),0) FROM reviews WHERE store_user_id = ?), rev_avg = (SELECT COALESCE(AVG(stars),0) FROM reviews WHERE store_user_id = ?) WHERE user_id = ?'),
    getMyReview: p('SELECT * FROM reviews WHERE store_user_id = ? AND reviewer_id = ?'),
    reviewStats: p('SELECT COUNT(*) AS total, COALESCE(SUM(positive),0) AS pos, COALESCE(AVG(stars),0) AS avg_stars FROM reviews WHERE store_user_id = ?'),
    discoverAll: p("SELECT s.user_id, s.name, s.category, s.rev_total, s.rev_pos, s.rev_avg, u.username, u.business_name, (SELECT image FROM store_posts q WHERE q.user_id = s.user_id AND q.kind = 'image' ORDER BY q.created_at DESC LIMIT 1) AS cover FROM stores s JOIN users u ON u.id = s.user_id WHERE s.name != '' ORDER BY s.rev_total DESC, s.views DESC LIMIT 120"),
    discoverCat: p("SELECT s.user_id, s.name, s.category, s.rev_total, s.rev_pos, s.rev_avg, u.username, u.business_name, (SELECT image FROM store_posts q WHERE q.user_id = s.user_id AND q.kind = 'image' ORDER BY q.created_at DESC LIMIT 1) AS cover FROM stores s JOIN users u ON u.id = s.user_id WHERE s.name != '' AND s.category = ? ORDER BY s.rev_total DESC, s.views DESC LIMIT 120"),
    insertPost: p('INSERT INTO store_posts (id, user_id, text, image, kind, created_at) VALUES (?,?,?,?,?,?)'),
    listPosts: p('SELECT * FROM store_posts WHERE user_id = ? AND created_at < ? ORDER BY created_at DESC LIMIT 61'),
    getPost: p('SELECT * FROM store_posts WHERE id = ? AND user_id = ?'),
    updatePost: p('UPDATE store_posts SET text = ?, edited_at = ? WHERE id = ? AND user_id = ?'),
    deletePost: p('DELETE FROM store_posts WHERE id = ? AND user_id = ?'),
    createInvite: p('INSERT INTO invites (token, contact_id, inviter_id, used, created_at) VALUES (?,?,?,0,?)'),
    getInvite: p('SELECT * FROM invites WHERE token = ?'),
    useInvite: p('UPDATE invites SET used = 1 WHERE token = ?'),
  };
}
const ST = shards.map(buildStmts);
const at = id => ST[shardOf(String(id))];       // شاردِ یک شناسه
const dir = key => ST[dirShard(String(key))];  // شاردِ دایرکتوری (نام‌کاربری/تلفن)
const newId = bytes => crypto.randomBytes(bytes || 8).toString('hex');
const idOn = (ownerId, bytes) => newIdOn(shardOf(ownerId), bytes); // شناسه‌ای که روی شاردِ صاحبش می‌افته

/* ============================ ابزارهای دامنه ============================ */
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

const SESSION_TTL = 30 * 24 * 60 * 60 * 1000;
const T_USER = 120, T_SESS = 300;
const normUser = r => r && ({ id: r.id, username: r.username, business_name: r.business_name, phone: r.phone || '', has_sig: !!r.has_sig, has_stamp: !!r.has_stamp });
async function getUserById(id){ if (!id) return null; return normUser(await cache.wrap('u:' + id, T_USER, async () => (await at(id).getUserLight.get(id)) || undefined)) || null; }
async function getUserByUsername(username){
  if (!username || typeof username !== 'string' || username.length > 40) return null;
  const id = await cache.wrap('un:' + username, 600, async () => { const r = await dir(username).getUsername.get(username); return r ? r.user_id : undefined; });
  return id ? getUserById(id) : null;
}
const dropUser = id => cache.del('u:' + id);
const seenAt = new Map();
function touchSeen(uid){
  const n = Date.now(); if ((seenAt.get(uid) || 0) > n - 30000) return;
  if (seenAt.size > 50000) seenAt.clear();
  seenAt.set(uid, n); cache.set('seen:' + uid, 1, 120);
}
const isOnline = async uid => (await cache.get('seen:' + uid)) !== undefined;
async function makeToken(userId){
  const token = newIdOn(shardOf(userId), 32);
  await at(userId).insertSession.run(token, userId, Date.now() + SESSION_TTL);
  return token;
}
async function userFromToken(token){
  if (!token || token.length > 128) return null;
  let uid = await cache.get('s:' + token);
  if (!uid){
    const s = await at(token).getSession.get(token);
    if (!s || s.expires_at < Date.now()) return null;
    uid = s.user_id; await cache.set('s:' + token, uid, T_SESS);
  }
  return getUserById(uid);
}
async function addNotification(toUserId, type, text, invoiceId){
  await at(toUserId).insertNotification.run(newId(8), toUserId, type, text, invoiceId || null, Date.now());
  await cache.del('nt:' + toUserId);
}
async function postMessage(from, to, text){
  const id = newId(8), now = Date.now();
  for (const i of new Set([shardOf(from), shardOf(to)])) await ST[i].insertMessage.run(id, from, to, text, now);
  await cache.del('t:' + from + ':' + to, 't:' + to + ':' + from);
}
async function linkContactsForPhone(pn, user){
  for (const st of ST) for (const c of await st.contactsByPhone.all(pn)) if (c.owner_id !== user.id) await at(c.owner_id).linkContact.run(user.username, c.id);
}
const viewsBuf = new Map();
setInterval(async () => { const b = [...viewsBuf]; viewsBuf.clear(); for (const [uid, n] of b){ try { await at(uid).addStoreViews.run(n, uid); } catch(e){} } }, 15000).unref();
setInterval(async () => { for (const st of ST){ try { await st.deleteExpiredSessions.run(Date.now()); } catch(e){} } }, 3600 * 1000).unref();

async function rateLimited(key, limit, windowSec){ return (await cache.incr('rl:' + key, windowSec)) > (limit || 15); }
const scryptAsync = (p, s) => new Promise((ok, no) => crypto.scrypt(p, s, 64, (e, k) => e ? no(e) : ok(k.toString('hex'))));
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


/* ============================ HTTP پایه ============================ */
function send(res, status, obj){
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(obj));
}
function readBody(req){
  return new Promise(resolve => {
    let data = '', dead = false;
    req.on('data', c => { data += c; if (data.length > 4 * 1024 * 1024 && !dead){ dead = true; req.destroy(); } });
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch(e){ resolve({}); } });
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
    if (r.method !== method || r.segments.length !== segs.length) continue;
    const params = {}; let ok = true;
    for (let i = 0; i < segs.length; i++){
      const rs = r.segments[i];
      if (rs.startsWith(':')) params[rs.slice(1)] = decodeURIComponent(segs[i]); else if (rs !== segs[i]){ ok = false; break; }
    }
    if (ok) return { route: r, params };
  }
  return null;
}
const userPublic = u => ({ username: u.username, businessName: u.business_name });
const postView = p => ({ id: p.id, text: p.text, media: p.image, kind: p.kind || (p.image ? 'image' : null), createdAt: p.created_at, editedAt: p.edited_at });

async function invoiceRowView(inv, forUserId, light, contactsMap){
  const isSeller = inv.seller_id === forUserId;
  const seller = await getUserById(inv.seller_id);
  const buyer = inv.buyer_id ? await getUserById(inv.buyer_id) : null;
  let contact = null;
  if (!buyer && inv.buyer_contact_id) contact = contactsMap ? contactsMap.get(inv.buyer_contact_id) : await at(inv.seller_id).getContactById.get(inv.buyer_contact_id);
  return {
    id: inv.id, number: inv.number, role: isSeller ? 'seller' : 'buyer', label: isSeller ? 'فاکتور فروش' : 'فاکتور خرید',
    counterpartName: isSeller ? (buyer ? buyer.business_name : (contact && contact.name)) : (seller && seller.business_name),
    counterpartUsername: isSeller ? (buyer && buyer.username) : (seller && seller.username),
    buyerRegistered: !!buyer, sellerName: seller && seller.business_name, buyerName: buyer ? buyer.business_name : (contact && contact.name),
    lines: JSON.parse(inv.lines), subtotal: inv.subtotal, discount: inv.discount, taxRate: inv.tax_rate, tax: inv.tax, total: inv.total,
    terms: inv.terms, paymentMethod: inv.payment_method, note: inv.note,
    ...(light ? {} : { sellerSignature: inv.seller_signature, sellerStamp: inv.seller_stamp, buyerSignature: inv.buyer_signature }),
    design: parseDesign(inv.design), status: inv.status, createdAt: inv.created_at,
  };
}

/* ============================ احراز هویت ============================ */
const clientIp = req => (process.env.TRUST_PROXY === '1' && req.headers['x-forwarded-for'] ? String(req.headers['x-forwarded-for']).split(',')[0].trim() : req.socket.remoteAddress) || 'unknown';
route('POST', '/api/auth/register', { auth: false }, async (req, res, params, ip) => {
  if (await rateLimited('reg:' + ip, 15, 60)) return send(res, 429, { error: 'تلاش زیاد — یه دقیقه صبر کن' });
  const { username, password, businessName, phone } = await readBody(req);
  if (!username || !/^[\p{L}\p{N}_.]{3,24}$/u.test(username)) return send(res, 400, { error: 'نام کاربری ۳ تا ۲۴ حرف/عدد، بدون فاصله' });
  if (!password || String(password).length < 4) return send(res, 400, { error: 'رمز عبور حداقل ۴ کاراکتر' });
  const pn = normPhone(phone);
  if (phone && !pn) return send(res, 400, { error: 'شماره تلفن معتبر نیست' });
  const id = newId(8), salt = newId(16), bn = String(businessName || username).slice(0, 80);
  // ۱) نام‌کاربری و تلفن رو روی دایرکتوری رزرو کن (کلید یکتا = جلوی رقابت هم‌زمان رو می‌گیره)
  try { await dir(username).claimUsername.run(username, id); } catch(e){ return send(res, 409, { error: 'این نام کاربری قبلاً گرفته شده' }); }
  if (pn){ try { await dir(pn).claimPhone.run(pn, id); } catch(e){ await dir(username).releaseUsername.run(username); return send(res, 409, { error: 'این شماره قبلاً ثبت شده' }); } }
  try {
    await at(id).insertUser.run(id, username, bn, salt, await scryptAsync(String(password), salt), Date.now());
    if (pn) await at(id).setUserPhone.run(pn, id);
  } catch(e){
    await dir(username).releaseUsername.run(username); if (pn) await dir(pn).releasePhone.run(pn);
    return send(res, 500, { error: 'خطای سرور' });
  }
  if (pn) await linkContactsForPhone(pn, { id, username });
  send(res, 200, { token: await makeToken(id), username, businessName: bn });
});
route('POST', '/api/auth/login', { auth: false }, async (req, res, params, ip) => {
  if (await rateLimited('login:' + ip, 15, 60)) return send(res, 429, { error: 'تلاش زیاد — یه دقیقه صبر کن' });
  const { username, password } = await readBody(req);
  const u = await getUserByUsername(username);
  const a = u && await at(u.id).getUserAuth.get(u.id);
  if (!a || (await scryptAsync(String(password || ''), a.salt)) !== a.password_hash) return send(res, 401, { error: 'نام کاربری یا رمز اشتباهه' });
  send(res, 200, { token: await makeToken(a.id), username: a.username, businessName: a.business_name });
});
route('GET', '/api/me', {}, (req, res, params, ip, user) => send(res, 200, { username: user.username, businessName: user.business_name, hasSignature: user.has_sig, hasStamp: user.has_stamp, phone: user.phone }));
route('PUT', '/api/me', {}, async (req, res, params, ip, user) => {
  const { businessName, phone } = await readBody(req);
  const st = at(user.id);
  if (phone !== undefined){
    const pn = normPhone(phone);
    if (phone && !pn) return send(res, 400, { error: 'شماره تلفن معتبر نیست' });
    if (pn !== (user.phone || '')){
      if (pn){ try { await dir(pn).claimPhone.run(pn, user.id); } catch(e){ return send(res, 409, { error: 'این شماره قبلاً ثبت شده' }); } }
      if (user.phone) await dir(user.phone).releasePhone.run(user.phone);
      await st.setUserPhone.run(pn || null, user.id);
      if (pn) await linkContactsForPhone(pn, user);
    }
  }
  if (businessName) await st.updateBusinessName.run(String(businessName).slice(0, 80), user.id);
  await dropUser(user.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/me/signature', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image || !String(image).startsWith('data:image/') || image.length > 600000) return send(res, 400, { error: 'تصویر معتبر نیست' });
  await at(user.id).updateSignature.run(image, user.id); await dropUser(user.id); send(res, 200, { ok: true });
});
route('POST', '/api/me/stamp', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image || !String(image).startsWith('data:image/') || image.length > 900000) return send(res, 400, { error: 'تصویر معتبر نیست' });
  await at(user.id).updateStamp.run(image, user.id); await dropUser(user.id); send(res, 200, { ok: true });
});
route('GET', '/api/me/signature', {}, async (req, res, params, ip, user) => send(res, 200, (await at(user.id).getUserImages.get(user.id)) || {}));
route('GET', '/api/users/:username', {}, async (req, res, params, ip, user) => {
  if (await rateLimited('lk:' + user.id, 40, 60)) return send(res, 429, { error: 'کمی صبر کن و دوباره امتحان کن' });
  const t = await getUserByUsername(params.username);
  if (!t) return send(res, 404, { error: 'همچین کاربری پیدا نشد' });
  if (t.id === user.id) return send(res, 400, { error: 'نمی‌تونی خودت رو انتخاب کنی' });
  send(res, 200, userPublic(t));
});

/* ============================ مشتری‌ها ============================ */
route('POST', '/api/contacts', {}, async (req, res, params, ip, user) => {
  const { name, phone, linkedUsername } = await readBody(req);
  if (!name || !String(name).trim()) return send(res, 400, { error: 'اسم مشتری رو بنویس' });
  let linked = null;
  if (linkedUsername){
    const t = await getUserByUsername(linkedUsername);
    if (!t) return send(res, 404, { error: 'کاربری با این نام کاربری پیدا نشد' });
    if (t.id === user.id) return send(res, 400, { error: 'نمی‌تونی خودت رو اضافه کنی' });
    linked = t.username;
  }
  const pn = normPhone(phone);
  if (!linked && pn){ const r = await dir(pn).getPhone.get(pn); if (r && r.user_id !== user.id){ const pu = await getUserById(r.user_id); if (pu) linked = pu.username; } }
  const id = newId(8), nm = String(name).trim().slice(0, 80);
  await at(user.id).insertContact.run(id, user.id, nm, String(phone || '').trim().slice(0, 30), pn || null, linked, Date.now());
  send(res, 200, { id, ownerId: user.id, name: nm, phone: String(phone || '').trim(), linkedUsername: linked, createdAt: Date.now() });
});
route('POST', '/api/contacts/bulk', {}, async (req, res, params, ip, user) => {
  if (await rateLimited('bulk:' + user.id, 6, 60)) return send(res, 429, { error: 'کمی صبر کن و دوباره امتحان کن' });
  const list = (await readBody(req)).contacts;
  if (!Array.isArray(list)) return send(res, 400, { error: 'داده‌ی نامعتبر' });
  const st = at(user.id), have = new Set((await st.listContacts.all(user.id)).map(c => c.phone_norm).filter(Boolean));
  let added = 0, skipped = 0;
  for (const c of list.slice(0, 500)){
    const pn = normPhone(c && c.phone), nm = String((c && c.name) || '').trim().slice(0, 80);
    if (!pn || !nm || have.has(pn)){ skipped++; continue; }
    have.add(pn);
    let linked = null; const r = await dir(pn).getPhone.get(pn);
    if (r){ if (r.user_id === user.id){ skipped++; continue; } const pu = await getUserById(r.user_id); if (pu) linked = pu.username; }
    await st.insertContact.run(newId(8), user.id, nm, String(c.phone).trim().slice(0, 30), pn, linked, Date.now());
    added++;
  }
  send(res, 200, { added, skipped });
});
route('GET', '/api/contacts', {}, async (req, res, params, ip, user) => {
  const rows = await at(user.id).listContacts.all(user.id);
  const out = await Promise.all(rows.map(async c => {
    let online = false, memberName = null;
    if (c.linked_username){ const u = await getUserByUsername(c.linked_username); if (u){ memberName = u.business_name; online = await isOnline(u.id); } }
    return { id: c.id, name: c.name, phone: c.phone, linkedUsername: c.linked_username, memberName, online };
  }));
  send(res, 200, { contacts: out });
});
route('DELETE', '/api/contacts/:id', {}, async (req, res, params, ip, user) => {
  const st = at(user.id);
  if (!(await st.getContact.get(params.id, user.id))) return send(res, 404, { error: 'پیدا نشد' });
  await st.deleteContact.run(params.id, user.id); send(res, 200, { ok: true });
});
route('PUT', '/api/contacts/:id/link', {}, async (req, res, params, ip, user) => {
  const st = at(user.id);
  if (!(await st.getContact.get(params.id, user.id))) return send(res, 404, { error: 'پیدا نشد' });
  const t = await getUserByUsername((await readBody(req)).linkedUsername);
  if (!t) return send(res, 404, { error: 'همچین کاربری پیدا نشد' });
  await st.linkContact.run(t.username, params.id); send(res, 200, { ok: true });
});

/* ============================ فاکتورها ============================ */
// فاکتور روی شاردِ فروشنده ذخیره می‌شه؛ برای خریدار یک ردیف «purchases» روی شاردِ خودش.
route('POST', '/api/invoices', {}, async (req, res, params, ip, user) => {
  const body = await readBody(req), st = at(user.id);
  const contact = await st.getContact.get(body.contactId, user.id);
  if (!contact) return send(res, 404, { error: 'اول این مشتری رو به لیست مشتری‌هات اضافه کن' });
  const T = calcTotals(body.lines, body.taxRate);
  if (!T.lines.length) return send(res, 400, { error: 'حداقل یک قلم لازمه' });
  const buyer = contact.linked_username ? await getUserByUsername(contact.linked_username) : null;
  const number = (await st.upsertCounter.get(user.id)).counter;
  const id = idOn(user.id, 10), shareToken = buyer ? null : newId(16), now = Date.now();
  const imgs = (await st.getUserImages.get(user.id)) || {};
  await st.insertInvoice.run(id, number, user.id, buyer ? buyer.id : null, contact.id, shareToken, JSON.stringify(T.lines), T.subtotal, T.discount, T.taxRate, T.tax, T.total,
    String(body.terms || '').slice(0, 300), String(body.paymentMethod || '').slice(0, 60), String(body.note || '').slice(0, 500), JSON.stringify(sanitizeDesign(body.design)),
    imgs.signature || null, imgs.stamp || null, now, now);
  if (buyer){
    await at(buyer.id).insertPurchase.run(buyer.id, id, now);
    await postMessage(user.id, buyer.id, '🧾 فاکتور #' + number + ' برای امضا: /?open=' + id);
    await addNotification(buyer.id, 'invoice_new', (user.business_name || user.username) + ' یه فاکتور برات صادر کرد (#' + number + ')', id);
  }
  send(res, 200, { id, number, shareLink: buyer ? null : ('/?sign=' + id + '&t=' + shareToken), registered: !!buyer });
});
route('GET', '/api/invoices', {}, async (req, res, params, ip, user) => {
  const st = at(user.id);
  const contactsMap = new Map((await st.listContacts.all(user.id)).map(c => [c.id, c]));
  const sales = await Promise.all((await st.listSales.all(user.id)).map(i => invoiceRowView(i, user.id, true, contactsMap)));
  const ids = (await st.listPurchaseIds.all(user.id)).map(r => r.invoice_id), by = new Map();
  ids.forEach(i => { const k = shardOf(i); (by.get(k) || by.set(k, []).get(k)).push(i); });
  const rows = (await Promise.all([...by].map(([k, list]) => ST[k].sh.prepare('SELECT * FROM invoices WHERE id IN (' + list.map(() => '?').join(',') + ')').all(...list)))).flat();
  rows.sort((a, b) => b.created_at - a.created_at);
  const purchases = await Promise.all(rows.map(i => invoiceRowView(i, user.id, true)));
  send(res, 200, { sales, purchases });
});
route('GET', '/api/invoices/:id', {}, async (req, res, params, ip, user) => {
  const inv = await at(params.id).getInvoice.get(params.id);
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.seller_id !== user.id && inv.buyer_id !== user.id) return send(res, 403, { error: 'اجازه‌ی دیدن این فاکتور رو نداری' });
  send(res, 200, await invoiceRowView(inv, user.id));
});
route('DELETE', '/api/invoices/:id', {}, async (req, res, params, ip, user) => {
  const st = at(params.id), inv = await st.getInvoice.get(params.id);
  if (!inv || inv.seller_id !== user.id) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  await st.deleteInvoice.run(inv.id);
  if (inv.buyer_id){
    await at(inv.buyer_id).deletePurchase.run(inv.buyer_id, inv.id);
    await addNotification(inv.buyer_id, 'invoice_deleted', (user.business_name || user.username) + ' فاکتور #' + inv.number + ' رو حذف کرد', null);
  }
  send(res, 200, { ok: true });
});
route('PUT', '/api/invoices/:id', {}, async (req, res, params, ip, user) => {
  const st = at(params.id), inv = await st.getInvoice.get(params.id);
  if (!inv || inv.seller_id !== user.id) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  const body = await readBody(req), T = calcTotals(body.lines, body.taxRate);
  if (!T.lines.length) return send(res, 400, { error: 'حداقل یک قلم لازمه' });
  await st.updateInvoice.run(JSON.stringify(T.lines), T.subtotal, T.discount, T.taxRate, T.tax, T.total, String(body.terms || '').slice(0, 300), String(body.paymentMethod || '').slice(0, 60), String(body.note || '').slice(0, 500), JSON.stringify(sanitizeDesign(body.design)), inv.id);
  if (inv.buyer_id){
    await addNotification(inv.buyer_id, 'invoice_edited', (user.business_name || user.username) + ' فاکتور #' + inv.number + ' رو ویرایش کرد — دوباره امضا کن', inv.id);
    await postMessage(user.id, inv.buyer_id, '✏️ فاکتور #' + inv.number + ' ویرایش شد، لطفاً دوباره امضا کن: /?open=' + inv.id);
  }
  send(res, 200, { ok: true });
});
const notifySeller = (inv, name) => addNotification(inv.seller_id, 'invoice_signed', (name || 'مشتری') + ' فاکتور #' + inv.number + ' رو امضا کرد', inv.id);
route('POST', '/api/invoices/:id/sign', {}, async (req, res, params, ip, user) => {
  const st = at(params.id), inv = await st.getInvoice.get(params.id);
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.buyer_id !== user.id) return send(res, 403, { error: 'فقط خریدار می‌تونه امضا کنه' });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req), mine = (await at(user.id).getUserImages.get(user.id)) || {};
  const signature = mine.signature || body.signature;
  if (!signature || !String(signature).startsWith('data:image/') || signature.length > 600000) return send(res, 400, { error: 'امضایی موجود نیست' });
  if (body.saveAsDefault && body.signature && !mine.signature){ await at(user.id).updateSignature.run(body.signature, user.id); await dropUser(user.id); }
  await st.signInvoice.run(signature, Date.now(), inv.id);
  await notifySeller(inv, user.business_name);
  send(res, 200, { ok: true });
});
async function publicInvoice(req, params){
  const inv = await at(params.id).getInvoice.get(params.id);
  if (!inv || inv.buyer_id) return { err: [404, 'پیدا نشد'] };
  if (!inv.share_token || inv.share_token !== req.query.get('t')) return { err: [403, 'لینک نامعتبره'] };
  return { inv };
}
route('GET', '/api/public/invoices/:id', { auth: false }, async (req, res, params) => {
  const { inv, err } = await publicInvoice(req, params); if (err) return send(res, err[0], { error: err[1] });
  const seller = await getUserById(inv.seller_id), contact = inv.buyer_contact_id ? await at(inv.seller_id).getContactById.get(inv.buyer_contact_id) : null;
  send(res, 200, { number: inv.number, sellerName: seller && seller.business_name, buyerName: contact && contact.name, lines: JSON.parse(inv.lines), subtotal: inv.subtotal, discount: inv.discount, taxRate: inv.tax_rate, tax: inv.tax, total: inv.total,
    terms: inv.terms, paymentMethod: inv.payment_method, note: inv.note, sellerSignature: inv.seller_signature, sellerStamp: inv.seller_stamp, status: inv.status, design: parseDesign(inv.design), createdAt: inv.created_at });
});
route('POST', '/api/public/invoices/:id/sign', { auth: false }, async (req, res, params, ip) => {
  if (await rateLimited('pubsign:' + ip, 20, 60)) return send(res, 429, { error: 'تلاش زیاد' });
  const { inv, err } = await publicInvoice(req, params); if (err) return send(res, err[0], { error: err[1] });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req);
  if (!body.signature || !String(body.signature).startsWith('data:image/') || body.signature.length > 600000) return send(res, 400, { error: 'اول امضا کن' });
  await at(inv.id).signInvoice.run(body.signature, Date.now(), inv.id);
  const contact = inv.buyer_contact_id ? await at(inv.seller_id).getContactById.get(inv.buyer_contact_id) : null;
  await notifySeller(inv, contact && contact.name);
  send(res, 200, { ok: true });
});

/* ============================ اعلان‌ها ============================ */
route('GET', '/api/notifications', {}, async (req, res, params, ip, user) => {
  send(res, 200, await cache.wrap('nt:' + user.id, 15, async () => {
    const list = (await at(user.id).listNotifications.all(user.id)).map(n => ({ id: n.id, text: n.text, invoiceId: n.invoice_id, createdAt: n.created_at, read: !!n.read }));
    return { notifications: list, unreadCount: list.filter(n => !n.read).length };
  }));
});
route('POST', '/api/notifications/:id/read', {}, async (req, res, params, ip, user) => { await at(user.id).markNotifRead.run(params.id, user.id); await cache.del('nt:' + user.id); send(res, 200, { ok: true }); });
route('POST', '/api/notifications/read-all', {}, async (req, res, params, ip, user) => { await at(user.id).markAllNotifRead.run(user.id); await cache.del('nt:' + user.id); send(res, 200, { ok: true }); });

/* ============================ گفتگو ============================ */
route('GET', '/api/messages/:username', {}, async (req, res, params, ip, user) => {
  const other = await getUserByUsername(params.username);
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const messages = await cache.wrap('t:' + user.id + ':' + other.id, 8, async () =>
    (await at(user.id).getThread.all(user.id, other.id, other.id, user.id)).map(m => ({ from: m.from_id === user.id ? 'me' : 'them', text: m.text, createdAt: m.created_at })));
  send(res, 200, { messages, businessName: other.business_name, online: await isOnline(other.id) });
});
route('POST', '/api/messages/:username', {}, async (req, res, params, ip, user) => {
  if (await rateLimited('msg:' + user.id, 60, 60)) return send(res, 429, { error: 'خیلی سریع پیام می‌دی' });
  const other = await getUserByUsername(params.username);
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  if (other.id === user.id) return send(res, 400, { error: 'نمی‌تونی به خودت پیام بدی' });
  const { text } = await readBody(req);
  if (!text || !String(text).trim()) return send(res, 400, { error: 'متن خالیه' });
  await postMessage(user.id, other.id, String(text).trim().slice(0, 2000));
  send(res, 200, { ok: true });
});
route('GET', '/api/conversations', {}, async (req, res, params, ip, user) => {
  const st = at(user.id), ids = new Set((await st.partnersFromMessages.all(user.id, user.id)).map(r => r.pid));
  for (const c of await st.listContacts.all(user.id)){ if (c.linked_username){ const u = await getUserByUsername(c.linked_username); if (u) ids.add(u.id); } }
  const list = (await Promise.all([...ids].map(async id => {
    const u = await getUserById(id); if (!u) return null;
    const last = await st.lastMessageBetween.get(id, user.id, user.id, id);
    return { username: u.username, businessName: u.business_name, lastMessage: last ? last.text : null, lastAt: last ? last.created_at : 0, lastFromMe: last ? last.from_id === user.id : false, online: await isOnline(id) };
  }))).filter(Boolean).sort((a, b) => b.lastAt - a.lastAt);
  send(res, 200, { conversations: list });
});

/* ============================ فروشگاه = کانال ============================ */
async function ensureStore(uid){ const st = at(uid); await st.insertEmptyStore.run(uid); return st.getStore.get(uid); }
async function postsPage(uid, before){
  const load = async () => { const rows = await at(uid).listPosts.all(uid, before || 9e15); return { posts: rows.slice(0, 60).map(postView), more: rows.length > 60 }; };
  return before ? load() : cache.wrap('po:' + uid, 30, load);
}
async function reviewStatsOf(uid){
  return cache.wrap('rv:' + uid, 60, async () => { const r = await at(uid).reviewStats.get(uid); const total = r.total || 0, pos = r.pos || 0; return { total, positive: pos, negative: total - pos, avgStars: r.avg_stars ? Math.round(r.avg_stars * 10) / 10 : 0 }; });
}
route('GET', '/api/store', {}, async (req, res, params, ip, user) => { const s = await ensureStore(user.id); send(res, 200, { name: s.name, category: s.category, description: s.description }); });
route('PUT', '/api/store', {}, async (req, res, params, ip, user) => {
  await ensureStore(user.id);
  const { name, category, description } = await readBody(req);
  if (!CATEGORIES.includes(category)) return send(res, 400, { error: 'دسته باید یکی از موبایل، پوشاک یا لوازم آرایشی باشه' });
  await at(user.id).updateStoreInfo.run(String(name || '').trim().slice(0, 60), category, String(description || '').slice(0, 160), user.id);
  send(res, 200, { ok: true });
});
route('GET', '/api/store/posts', {}, async (req, res, params, ip, user) => send(res, 200, await postsPage(user.id, +req.query.get('before') || 0)));
const MEDIA_RE = /^\/uploads\/[a-f0-9]{2}\/[a-f0-9]+\.(jpg|png|webp|mp4|webm)$/;
route('POST', '/api/store/posts', {}, async (req, res, params, ip, user) => {
  if (await rateLimited('post:' + user.id, 60, 60)) return send(res, 429, { error: 'خیلی سریع پست می‌ذاری' });
  await ensureStore(user.id);
  const { text, media } = await readBody(req);
  const t = String(text || '').trim().slice(0, 3000), m = typeof media === 'string' && MEDIA_RE.test(media) ? media : null;
  if (!t && !m) return send(res, 400, { error: 'متن یا عکس/ویدیو بفرست' });
  const kind = m ? (/\.(mp4|webm)$/.test(m) ? 'video' : 'image') : null, id = newId(8), now = Date.now();
  await at(user.id).insertPost.run(id, user.id, t, m, kind, now);
  await cache.del('po:' + user.id);
  send(res, 200, postView({ id, text: t, image: m, kind, created_at: now, edited_at: null }));
});
route('PUT', '/api/store/posts/:id', {}, async (req, res, params, ip, user) => {
  const st = at(user.id);
  if (!(await st.getPost.get(params.id, user.id))) return send(res, 404, { error: 'پست پیدا نشد' });
  await st.updatePost.run(String((await readBody(req)).text || '').trim().slice(0, 3000), Date.now(), params.id, user.id);
  await cache.del('po:' + user.id); send(res, 200, { ok: true });
});
route('DELETE', '/api/store/posts/:id', {}, async (req, res, params, ip, user) => {
  const st = at(user.id);
  if (!(await st.getPost.get(params.id, user.id))) return send(res, 404, { error: 'پست پیدا نشد' });
  await st.deletePost.run(params.id, user.id); await cache.del('po:' + user.id); send(res, 200, { ok: true });
});
route('GET', '/api/store/stats', {}, async (req, res, params, ip, user) => {
  const s = await at(user.id).getStore.get(user.id), r = await reviewStatsOf(user.id);
  send(res, 200, { views: s ? s.views : 0, ...r, message: ownerFeedbackMessage(r.positive, r.negative) });
});
route('GET', '/api/stores/:username', {}, async (req, res, params, ip, user) => {
  const t = await getUserByUsername(params.username);
  if (!t) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  const s = await ensureStore(t.id);
  if (t.id !== user.id) viewsBuf.set(t.id, (viewsBuf.get(t.id) || 0) + 1);
  const my = await at(t.id).getMyReview.get(t.id, user.id), pg = await postsPage(t.id, 0);
  send(res, 200, { username: t.username, businessName: t.business_name, name: s.name, category: s.category, description: s.description, photos: [], ...pg, ...(await reviewStatsOf(t.id)), myReview: my ? { positive: !!my.positive, stars: my.stars } : null });
});
route('GET', '/api/stores/:username/posts', {}, async (req, res, params) => {
  const t = await getUserByUsername(params.username);
  if (!t) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  send(res, 200, await postsPage(t.id, +req.query.get('before') || 0));
});
route('POST', '/api/stores/:username/review', {}, async (req, res, params, ip, user) => {
  const t = await getUserByUsername(params.username);
  if (!t) return send(res, 404, { error: 'فروشگاه پیدا نشد' });
  if (t.id === user.id) return send(res, 400, { error: 'نمی‌تونی به فروشگاه خودت نظر بدی' });
  const { positive, stars } = await readBody(req), st = at(t.id);
  await st.upsertReview.run(newId(8), t.id, user.id, positive ? 1 : 0, Math.min(5, Math.max(1, parseInt(stars, 10) || 3)), Date.now());
  await st.refreshReviewAgg.run(t.id, t.id, t.id, t.id); await cache.del('rv:' + t.id);
  send(res, 200, { ok: true });
});
route('GET', '/api/discover', {}, async (req, res) => {
  const cat = CATEGORIES.includes(req.query.get('category')) ? req.query.get('category') : '';
  send(res, 200, await cache.wrap('disc:' + (cat || 'all'), 45, async () => {
    const parts = await Promise.all(ST.map(st => cat ? st.discoverCat.all(cat) : st.discoverAll.all()));
    const stores = parts.flat().map(s => { const total = s.rev_total || 0, positive = s.rev_pos || 0; return { username: s.username, businessName: s.business_name, name: s.name, category: s.category, coverPhoto: s.cover || null, positive, negative: total - positive, total, avgStars: s.rev_avg ? Math.round(s.rev_avg * 10) / 10 : 0, score: wilsonScore(positive, total) }; });
    return { stores: stores.sort((a, b) => b.score - a.score).slice(0, 80) };
  }));
});

/* ============================ دعوت‌نامه ============================ */
route('POST', '/api/contacts/:id/invite', {}, async (req, res, params, ip, user) => {
  const st = at(user.id), c = await st.getContact.get(params.id, user.id);
  if (!c) return send(res, 404, { error: 'پیدا نشد' });
  const token = idOn(user.id, 16);
  await st.createInvite.run(token, c.id, user.id, Date.now());
  send(res, 200, { token, link: '/?invite=' + token, message: 'سلام ' + c.name + ' جان 👋\n' + (user.business_name || user.username) + ' تو «فاکتور آنلاین» منتظرته ✨\nفاکتور شیک، امضای آنلاین و پیام‌ها همه یه‌جا 👇\n' });
});
route('GET', '/api/invites/:token', { auth: false }, async (req, res, params) => {
  const inv = await at(params.token).getInvite.get(params.token);
  if (!inv || inv.used) return send(res, 404, { error: 'این دعوت‌نامه پیدا نشد یا قبلاً استفاده شده' });
  const inviter = await getUserById(inv.inviter_id);
  send(res, 200, { inviterName: inviter ? inviter.business_name : 'یک کسب‌وکار' });
});
route('POST', '/api/invites/:token/consume', {}, async (req, res, params, ip, user) => {
  const ist = at(params.token), inv = await ist.getInvite.get(params.token);
  if (!inv || inv.used) return send(res, 404, { error: 'این دعوت‌نامه پیدا نشد یا قبلاً استفاده شده' });
  const inviter = await getUserById(inv.inviter_id);
  await at(inv.inviter_id).linkContact.run(user.username, inv.contact_id);
  if (inviter){
    const mine = at(user.id);
    if (!(await mine.contactByOwnerLink.get(user.id, inviter.username))) await mine.insertContact.run(newId(8), user.id, inviter.business_name || inviter.username, '', null, inviter.username, Date.now());
  }
  await ist.useInvite.run(inv.token);
  send(res, 200, { ok: true, inviterName: inviter ? inviter.business_name : null, inviterUsername: inviter ? inviter.username : null });
});

/* ============================ آپلود (عکس/ویدیو، جریانی و بدون base64) ============================ */
const MEDIA_TYPES = { 'image/jpeg': ['jpg', 4], 'image/png': ['png', 4], 'image/webp': ['webp', 4], 'video/mp4': ['mp4', 30], 'video/webm': ['webm', 30] };
const MAGIC = {
  jpg: b => b[0] === 0xFF && b[1] === 0xD8, png: b => b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4E && b[3] === 0x47,
  webp: b => b.toString('latin1', 0, 4) === 'RIFF' && b.toString('latin1', 8, 12) === 'WEBP', mp4: b => b.toString('latin1', 4, 8) === 'ftyp', webm: b => b[0] === 0x1A && b[1] === 0x45 && b[2] === 0xDF && b[3] === 0xA3,
};
route('POST', '/api/upload', {}, async (req, res, params, ip, user) => {
  const deny = (code, error) => { req.resume(); return send(res, code, { error }); };
  if (await rateLimited('up:' + user.id, 60, 60)) return deny(429, 'آپلود زیاد — کمی صبر کن');
  const m = MEDIA_TYPES[String(req.headers['content-type'] || '').split(';')[0].trim()];
  if (!m) return deny(400, 'فرمت پشتیبانی نمی‌شه (jpg ، png ، webp ، mp4 ، webm)');
  const [ext, mb] = m, max = mb * 1024 * 1024;
  if ((+req.headers['content-length'] || 0) > max) return deny(413, 'حجم فایل بیش از ' + faDigitsSrv(mb) + ' مگابایته');
  const name = newId(12) + '.' + ext, sub = name.slice(0, 2), fp = path.join(UPLOAD_DIR, sub, name);
  await fs.promises.mkdir(path.join(UPLOAD_DIR, sub), { recursive: true });
  const result = await new Promise(resolve => {
    let size = 0, head = Buffer.alloc(0), done = false;
    const out = fs.createWriteStream(fp), end = r => { if (!done){ done = true; resolve(r); } };
    req.on('data', c => { size += c.length; if (head.length < 16) head = Buffer.concat([head, c]).subarray(0, 16); if (size > max){ req.unpipe(out); out.destroy(); end('big'); } });
    req.on('aborted', () => { out.destroy(); end('abort'); });
    out.on('error', () => end('err'));
    out.on('finish', () => end(size > 0 && MAGIC[ext](head) ? 'ok' : 'type'));
    req.pipe(out);
  });
  if (result !== 'ok'){ fs.unlink(fp, () => {}); return deny(result === 'big' ? 413 : 400, result === 'big' ? 'حجم فایل زیاده' : 'فایل معتبر نیست'); }
  send(res, 200, { url: '/uploads/' + sub + '/' + name, kind: /^(mp4|webm)$/.test(ext) ? 'video' : 'image' });
});

route('GET', '/api/health', { auth: false }, (req, res) => send(res, 200, { ok: true, db: driver, shards: N, cache: cache.kind, time: Date.now() }));

/* ============================ فایل‌های استاتیک ============================ */
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.mp4': 'video/mp4', '.webm': 'video/webm', '.webmanifest': 'application/manifest+json' };
function serveUpload(req, res, pathname){
  const rel = pathname.slice(9);
  if (!MEDIA_RE.test('/uploads/' + rel)){ res.writeHead(404); return res.end('Not found'); }
  const fp = path.join(UPLOAD_DIR, rel);
  fs.stat(fp, (err, stat) => {
    if (err){ res.writeHead(404); return res.end('Not found'); }
    const h = { 'Content-Type': MIME[path.extname(fp)], 'Accept-Ranges': 'bytes', 'Cache-Control': 'public, max-age=31536000, immutable', 'X-Content-Type-Options': 'nosniff' };
    const r = req.headers.range && /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
    if (!r){ res.writeHead(200, { ...h, 'Content-Length': stat.size }); return fs.createReadStream(fp).pipe(res); }
    let start = r[1] === '' ? Math.max(0, stat.size - +r[2]) : +r[1], end = (r[1] === '' || r[2] === '') ? stat.size - 1 : Math.min(+r[2], stat.size - 1);
    if (!(start <= end) || start >= stat.size){ res.writeHead(416, { 'Content-Range': 'bytes */' + stat.size }); return res.end(); }
    res.writeHead(206, { ...h, 'Content-Range': 'bytes ' + start + '-' + end + '/' + stat.size, 'Content-Length': end - start + 1 });
    fs.createReadStream(fp, { start, end }).pipe(res);
  });
}
function serveStatic(req, res, pathname){
  if (pathname.startsWith('/uploads/')) return serveUpload(req, res, pathname);
  const fp = path.join(PUBLIC_DIR, pathname === '/' ? '/index.html' : pathname);
  if (!fp.startsWith(PUBLIC_DIR)){ res.writeHead(403); return res.end('Forbidden'); }
  fs.readFile(fp, (err, content) => {
    if (err){ res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream', 'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff' });
    res.end(content);
  });
}

/* ============================ سرور ============================ */
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://localhost'), ip = clientIp(req);
  if (req.method === 'OPTIONS'){ res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS' }); return res.end(); }
  if (!u.pathname.startsWith('/api/')) return serveStatic(req, res, u.pathname);
  try {
    const matched = matchRoute(req.method, u.pathname);
    if (!matched) return send(res, 404, { error: 'مسیر پیدا نشد' });
    let user = null;
    if (matched.route.auth){
      const h = req.headers['authorization'] || '';
      user = await userFromToken(h.startsWith('Bearer ') ? h.slice(7) : null);
      if (!user) return send(res, 401, { error: 'وارد نشدی یا نشستت منقضی شده' });
      touchSeen(user.id);
    }
    req.query = u.searchParams;
    await matched.route.handler(req, res, matched.params, ip, user);
  } catch(err){
    console.error('خطا', req.method, u.pathname, err && err.message);
    if (!res.headersSent) send(res, 500, { error: 'خطای سرور' });
  }
});

if (cluster.isPrimary && WORKERS > 1){
  initDb().then(() => {
    for (let i = 0; i < WORKERS; i++) cluster.fork({ SKIP_INIT: '1' });
    cluster.on('exit', () => setTimeout(() => cluster.fork({ SKIP_INIT: '1' }), 1000));
    console.log('اصلی: ' + WORKERS + ' پردازش — دیتابیس: ' + driver + ' × ' + N + ' شارد — کش: ' + cache.kind);
  }).catch(e => { console.error('خطا در راه‌اندازی:', e); process.exit(1); });
} else {
  (async () => {
    if (!process.env.SKIP_INIT) await initDb();
    server.listen(PORT, () => console.log('فاکتور ساز آنلاین روی پورت ' + PORT + ' — دیتابیس: ' + driver + ' × ' + N + ' شارد — کش: ' + cache.kind));
  })().catch(e => { console.error('خطا در راه‌اندازی:', e); process.exit(1); });
}
