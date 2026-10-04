/*
  لایه‌ی کش — Redis برای چند سرور/پردازش، با جایگزین حافظه‌ای (LRU) برای توسعه.
  • get/set/del با JSON و TTL
  • wrap(key, ttl, loader): cache-aside با «single-flight» (چند درخواست هم‌زمان برای یک کلید
    فقط یک بار دیتابیس رو می‌زنن) و jitter روی TTL (انقضای هم‌زمان کلیدها = طوفان درخواست ندارن)
  • incr(key, windowSec): شمارنده‌ی اتمیک برای محدودسازی نرخ، مشترک بین همه‌ی سرورها
  • هر خطای Redis فقط «miss» حساب می‌شه؛ سایت با افتادن Redis از کار نمی‌افته.
*/
const PREFIX = process.env.CACHE_PREFIX || 'inv:';
const MAX_MEM = Number(process.env.CACHE_MAX_ENTRIES) || 50000;

const mem = new Map(); // key -> { v, exp }  (ترتیب درج = LRU)
const memApi = {
  async get(k){ const e = mem.get(k); if (!e) return null; if (e.exp < Date.now()){ mem.delete(k); return null; } mem.delete(k); mem.set(k, e); return e.v; },
  async set(k, v, ttl){ mem.delete(k); mem.set(k, { v, exp: Date.now() + ttl * 1000 }); while (mem.size > MAX_MEM) mem.delete(mem.keys().next().value); },
  async del(keys){ keys.forEach(k => mem.delete(k)); },
  async incr(k, win){ const e = mem.get(k); if (e && e.exp > Date.now()){ e.v = String(+e.v + 1); return +e.v; } mem.set(k, { v: '1', exp: Date.now() + win * 1000 }); return 1; },
};

let backend = memApi, kind = 'memory';
if (process.env.REDIS_URL){
  const { createClient } = require('redis');
  const client = createClient({ url: process.env.REDIS_URL, socket: { reconnectStrategy: n => Math.min(n * 200, 3000) } });
  client.on('error', e => console.error('redis:', e.message));
  client.connect().catch(e => console.error('redis connect:', e.message));
  kind = 'redis';
  backend = {
    get: k => client.get(k),
    set: (k, v, ttl) => client.set(k, v, { EX: Math.max(1, Math.round(ttl)) }),
    del: keys => client.del(keys),
    async incr(k, win){ const n = await client.incr(k); if (n === 1) await client.expire(k, win); return n; },
  };
}

const inflight = new Map();
const K = k => PREFIX + k;
const safe = async (fn, fallback) => { try { return await fn(); } catch(e){ return fallback; } };

const cache = {
  kind,
  async get(k){ const raw = await safe(() => backend.get(K(k)), null); if (raw == null) return undefined; try { return JSON.parse(raw); } catch(e){ return undefined; } },
  async set(k, v, ttl){ if (v === undefined || v === null) return; await safe(() => backend.set(K(k), JSON.stringify(v), ttl * (0.9 + Math.random() * 0.2))); },
  async del(...keys){ keys = keys.flat().filter(Boolean).map(K); if (keys.length) await safe(() => backend.del(keys)); },
  async wrap(k, ttl, loader){
    const hit = await cache.get(k);
    if (hit !== undefined) return hit;
    if (inflight.has(k)) return inflight.get(k);
    const p = (async () => { try { const v = await loader(); await cache.set(k, v, ttl); return v; } finally { inflight.delete(k); } })();
    inflight.set(k, p);
    return p;
  },
  async incr(k, windowSec){ return safe(() => backend.incr(K(k), windowSec), 0); },
};
module.exports = cache;
