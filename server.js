/*
  فاکتور ساز آنلاین — سرور مستقل
  ------------------------------------------------------------
  این یه پروژه‌ی جداست، فقط برای فاکتور + امضای متقابل + گفتگوی
  خصوصی بین فروشنده و خریدار. بدون هیچ کتابخانه‌ی خارجی (npm install
  لازم نداره) — من به رجیستری npm دسترسی ندارم که چیزی نصب/تست کنم،
  برای همین از قابلیت‌های خود Node.js استفاده کردم، ولی این‌بار با
  یه ساختار تمیزتر و شبیه فریمورک (روتر جدا، میان‌افزار جدا) که هم
  خوندنش راحت‌تره هم گسترشش.

  اجرا: node server.js
*/

const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const DATA_FILE = path.join(__dirname, 'data.json');
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 3000;

/* ============================================================
   لایه‌ی داده
   ============================================================ */
function loadDB(){
  try { return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); }
  catch(err){ return { users: [], invoices: [], messages: [], invoiceCounters: {} }; }
}
let db = loadDB();
let saveScheduled = false;
function persist(){
  // نوشتن روی دیسک رو کمی تأخیر می‌ندازیم تا اگه چند تغییر پشت‌سرهم
  // اومد، یکجا نوشته بشه (سریع‌تر و کم‌فشارتر رو دیسک)
  if (saveScheduled) return;
  saveScheduled = true;
  setTimeout(() => { fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2)); saveScheduled = false; }, 50);
}

/* ============================================================
   رمز عبور و نشست
   ============================================================ */
function hashPassword(password, salt){ return crypto.scryptSync(password, salt, 64).toString('hex'); }
function newId(bytes){ return crypto.randomBytes(bytes || 8).toString('hex'); }

const sessions = new Map(); // token -> { userId, expiresAt }
const SESSION_TTL = 30 * 24 * 60 * 60 * 1000; // ۳۰ روز
function makeToken(userId){
  const token = newId(32);
  sessions.set(token, { userId, expiresAt: Date.now() + SESSION_TTL });
  return token;
}
function userFromToken(token){
  if (!token) return null;
  const s = sessions.get(token);
  if (!s) return null;
  if (s.expiresAt < Date.now()){ sessions.delete(token); return null; }
  return db.users.find(u => u.id === s.userId) || null;
}

/* ============================================================
   محدودسازی نرخ درخواست روی ورود/ثبت‌نام (جلوگیری از حدس رمز)
   ============================================================ */
const attempts = new Map(); // ip -> [timestamps]
function rateLimited(ip){
  const now = Date.now();
  const windowMs = 60 * 1000;
  const list = (attempts.get(ip) || []).filter(t => now - t < windowMs);
  list.push(now);
  attempts.set(ip, list);
  return list.length > 15;
}

/* ============================================================
   ابزارهای HTTP پایه (جایگزین دستی چیزی شبیه Express)
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

/* یه روتر خیلی سبک: هر مسیر با متد + الگو (با :param) ثبت می‌شه */
const routes = []; // { method, pattern: [segments], handler, auth }
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
   روت‌های احراز هویت
   ============================================================ */
route('POST', '/api/auth/register', { auth: false }, async (req, res) => {
  const { username, password, businessName } = await readBody(req);
  if (!username || username.length < 3) return send(res, 400, { error: 'نام کاربری حداقل ۳ کاراکتر' });
  if (!password || password.length < 4) return send(res, 400, { error: 'رمز عبور حداقل ۴ کاراکتر' });
  if (db.users.find(u => u.username === username)) return send(res, 409, { error: 'این نام کاربری قبلاً گرفته شده' });
  const salt = newId(16);
  const user = {
    id: newId(8), username, businessName: businessName || username,
    salt, passwordHash: hashPassword(password, salt),
    signature: null, stamp: null, createdAt: Date.now()
  };
  db.users.push(user);
  persist();
  send(res, 200, { token: makeToken(user.id), username: user.username, businessName: user.businessName });
});

route('POST', '/api/auth/login', { auth: false }, async (req, res, params, ip) => {
  if (rateLimited(ip)) return send(res, 429, { error: 'تلاش زیاد — یه دقیقه صبر کن' });
  const { username, password } = await readBody(req);
  const user = db.users.find(u => u.username === username);
  if (!user || hashPassword(password, user.salt) !== user.passwordHash){
    return send(res, 401, { error: 'نام کاربری یا رمز اشتباهه' });
  }
  send(res, 200, { token: makeToken(user.id), username: user.username, businessName: user.businessName });
});

route('GET', '/api/me', {}, (req, res, params, ip, user) => {
  send(res, 200, {
    username: user.username, businessName: user.businessName,
    hasSignature: !!user.signature, hasStamp: !!user.stamp,
  });
});

route('PUT', '/api/me', {}, async (req, res, params, ip, user) => {
  const { businessName } = await readBody(req);
  if (businessName) user.businessName = businessName;
  persist();
  send(res, 200, { ok: true });
});

/* مهر و امضای ذخیره‌شده — یه‌بار ذخیره می‌کنی، رو همه‌ی فاکتورهای بعدی خودکار میاد */
route('POST', '/api/me/signature', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image) return send(res, 400, { error: 'تصویری نیومد' });
  user.signature = image;
  persist();
  send(res, 200, { ok: true });
});
route('POST', '/api/me/stamp', {}, async (req, res, params, ip, user) => {
  const { image } = await readBody(req);
  if (!image) return send(res, 400, { error: 'تصویری نیومد' });
  user.stamp = image;
  persist();
  send(res, 200, { ok: true });
});
route('GET', '/api/me/signature', {}, (req, res, params, ip, user) => {
  send(res, 200, { signature: user.signature, stamp: user.stamp });
});

/* پیدا کردن یه کاربر با نام کاربری (برای صدور فاکتور/شروع گفتگو) */
route('GET', '/api/users/:username', {}, (req, res, params, ip, user) => {
  const target = db.users.find(u => u.username === params.username);
  if (!target) return send(res, 404, { error: 'همچین کاربری پیدا نشد' });
  if (target.id === user.id) return send(res, 400, { error: 'نمی‌تونی خودت رو انتخاب کنی' });
  send(res, 200, { username: target.username, businessName: target.businessName });
});

/* ============================================================
   فاکتورها — یک رکورد، دو نما (فروشنده می‌بینه «فروش»، خریدار می‌بینه «خرید»)
   ============================================================ */
route('POST', '/api/invoices', {}, async (req, res, params, ip, user) => {
  const body = await readBody(req);
  const buyer = db.users.find(u => u.username === body.buyerUsername);
  if (!buyer) return send(res, 404, { error: 'خریدار با این نام کاربری پیدا نشد' });
  if (buyer.id === user.id) return send(res, 400, { error: 'نمی‌تونی برای خودت فاکتور بزنی' });
  if (!Array.isArray(body.lines) || !body.lines.length) return send(res, 400, { error: 'حداقل یک قلم لازمه' });

  db.invoiceCounters[user.id] = (db.invoiceCounters[user.id] || 0) + 1;
  const invoice = {
    id: newId(10),
    number: db.invoiceCounters[user.id],
    sellerId: user.id, buyerId: buyer.id,
    lines: body.lines, subtotal: body.subtotal || 0, discount: body.discount || 0,
    taxRate: body.taxRate || 0, tax: body.tax || 0, total: body.total || 0,
    terms: body.terms || '', paymentMethod: body.paymentMethod || '',
    sellerSignature: user.signature || null, sellerStamp: user.stamp || null,
    buyerSignature: null,
    status: 'pending_buyer',
    createdAt: Date.now(), sellerSignedAt: Date.now(), buyerSignedAt: null,
  };
  db.invoices.push(invoice);
  persist();
  send(res, 200, { id: invoice.id, number: invoice.number });
});

function invoiceView(inv, forUserId){
  const isSeller = inv.sellerId === forUserId;
  const seller = db.users.find(u => u.id === inv.sellerId);
  const buyer = db.users.find(u => u.id === inv.buyerId);
  return {
    id: inv.id, number: inv.number,
    role: isSeller ? 'seller' : 'buyer',
    label: isSeller ? 'فاکتور فروش' : 'فاکتور خرید',
    counterpartName: isSeller ? (buyer && buyer.businessName) : (seller && seller.businessName),
    counterpartUsername: isSeller ? (buyer && buyer.username) : (seller && seller.username),
    sellerName: seller && seller.businessName, buyerName: buyer && buyer.businessName,
    lines: inv.lines, subtotal: inv.subtotal, discount: inv.discount,
    taxRate: inv.taxRate, tax: inv.tax, total: inv.total,
    terms: inv.terms, paymentMethod: inv.paymentMethod,
    sellerSignature: inv.sellerSignature, sellerStamp: inv.sellerStamp, buyerSignature: inv.buyerSignature,
    status: inv.status, createdAt: inv.createdAt,
  };
}

route('GET', '/api/invoices', {}, (req, res, params, ip, user) => {
  const sales = db.invoices.filter(i => i.sellerId === user.id).map(i => invoiceView(i, user.id));
  const purchases = db.invoices.filter(i => i.buyerId === user.id).map(i => invoiceView(i, user.id));
  send(res, 200, { sales, purchases });
});

route('GET', '/api/invoices/:id', {}, (req, res, params, ip, user) => {
  const inv = db.invoices.find(i => i.id === params.id);
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.sellerId !== user.id && inv.buyerId !== user.id) return send(res, 403, { error: 'اجازه‌ی دیدن این فاکتور رو نداری' });
  send(res, 200, invoiceView(inv, user.id));
});

route('POST', '/api/invoices/:id/sign', {}, async (req, res, params, ip, user) => {
  const inv = db.invoices.find(i => i.id === params.id);
  if (!inv) return send(res, 404, { error: 'فاکتور پیدا نشد' });
  if (inv.buyerId !== user.id) return send(res, 403, { error: 'فقط خریدار می‌تونه امضا کنه' });
  if (inv.status === 'complete') return send(res, 409, { error: 'قبلاً امضا شده' });
  const body = await readBody(req);
  // اگه امضای ذخیره‌شده داره همونو استفاده کن، وگرنه امضایی که همین الان کشیده رو بگیر
  const signature = user.signature || body.signature;
  if (!signature) return send(res, 400, { error: 'امضایی موجود نیست' });
  if (body.saveAsDefault && body.signature && !user.signature){ user.signature = body.signature; }
  inv.buyerSignature = signature;
  inv.status = 'complete';
  inv.buyerSignedAt = Date.now();
  persist();
  send(res, 200, { ok: true });
});

/* ============================================================
   گفتگوی خصوصی — فقط بین دو نفر، نه عمومی
   ============================================================ */
route('GET', '/api/messages/:username', {}, (req, res, params, ip, user) => {
  const other = db.users.find(u => u.username === params.username);
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const thread = db.messages
    .filter(m => (m.from === user.id && m.to === other.id) || (m.from === other.id && m.to === user.id))
    .sort((a, b) => a.createdAt - b.createdAt)
    .map(m => ({ from: m.from === user.id ? 'me' : 'them', text: m.text, createdAt: m.createdAt }));
  send(res, 200, { messages: thread, businessName: other.businessName });
});

route('POST', '/api/messages/:username', {}, async (req, res, params, ip, user) => {
  const other = db.users.find(u => u.username === params.username);
  if (!other) return send(res, 404, { error: 'کاربر پیدا نشد' });
  const { text } = await readBody(req);
  if (!text || !text.trim()) return send(res, 400, { error: 'متن خالیه' });
  db.messages.push({ id: newId(8), from: user.id, to: other.id, text: text.trim().slice(0, 2000), createdAt: Date.now() });
  persist();
  send(res, 200, { ok: true });
});

route('GET', '/api/conversations', {}, (req, res, params, ip, user) => {
  const partnerIds = new Set();
  db.messages.forEach(m => {
    if (m.from === user.id) partnerIds.add(m.to);
    if (m.to === user.id) partnerIds.add(m.from);
  });
  db.invoices.forEach(i => {
    if (i.sellerId === user.id) partnerIds.add(i.buyerId);
    if (i.buyerId === user.id) partnerIds.add(i.sellerId);
  });
  const list = Array.from(partnerIds).map(id => {
    const u = db.users.find(x => x.id === id);
    if (!u) return null;
    const thread = db.messages.filter(m => (m.from === id && m.to === user.id) || (m.to === id && m.from === user.id));
    const last = thread.sort((a,b) => b.createdAt - a.createdAt)[0];
    return { username: u.username, businessName: u.businessName, lastMessage: last ? last.text : null, lastAt: last ? last.createdAt : 0 };
  }).filter(Boolean).sort((a, b) => b.lastAt - a.lastAt);
  send(res, 200, { conversations: list });
});

/* ============================================================
   بررسی سلامت سرور (برای سرویس‌های هاستینگ)
   ============================================================ */
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

  try {
    await matched.route.handler(req, res, matched.params, ip, user);
  } catch(err){
    send(res, 500, { error: 'خطای سرور' });
  }
});

server.listen(PORT, () => {
  console.log('فاکتور ساز آنلاین رو پورت ' + PORT + ' روشن شد');
});
