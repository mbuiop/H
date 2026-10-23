# -*- coding: utf-8 -*-
# ماژول ساخت خودکار اپلیکیشن اندروید از طریق GitHub Actions
# نیازمندی‌ها:  pip install pynacl pillow httpx   (httpx همراه کتابخانه تلگرام نصب می‌شود)
# روی سرور باید git و JDK (برای keytool) نصب باشد.
import os
import re
import json
import time
import shutil
import base64
import secrets
import zipfile
import subprocess
from xml.sax.saxutils import escape

import httpx
from nacl import encoding, public
from PIL import Image

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
REPO_PRIVATE = True        # مخزن‌ها خصوصی ساخته شوند
WORK = "work"
KEYS = "keystores"         # از این پوشه حتماً بکاپ بگیر! بدون کلید نمی‌شود اپ را آپدیت کرد
BUILD_TIMEOUT = 40 * 60    # ثانیه
# قوانین حذف واترمارک/برندینگ داخل کد: لیستی از (regex، جایگزین). مثال:
# BRANDING_RULES = [(r"Powered by\s+\w+", ""), (r"example\.com/logo", "")]
BRANDING_RULES = []

WORKFLOW = """name: Build APK
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'
      - uses: gradle/actions/setup-gradle@v4
      - name: Build release
        run: |
          if [ -f gradlew ]; then chmod +x gradlew; ./gradlew assembleRelease bundleRelease --no-daemon; else gradle assembleRelease bundleRelease --no-daemon; fi
      - name: Sign APK
        env:
          KS_B64: ${{ secrets.KS_B64 }}
          KS_PASS: ${{ secrets.KS_PASS }}
        run: |
          echo "$KS_B64" | base64 -d > release.jks
          BT=$(ls -d $ANDROID_HOME/build-tools/* | sort -V | tail -1)
          APK=$(find . -path '*outputs/apk/release*' -name '*.apk' | head -1)
          $BT/zipalign -f -p 4 "$APK" aligned.apk
          $BT/apksigner sign --ks release.jks --ks-pass env:KS_PASS --key-pass env:KS_PASS --ks-key-alias key --out app-signed.apk aligned.apk
          AAB=$(find . -path '*outputs/bundle/release*' -name '*.aab' | head -1)
          jarsigner -keystore release.jks -storepass "$KS_PASS" -keypass "$KS_PASS" -signedjar app-signed.aab "$AAB" key
      - uses: actions/upload-artifact@v4
        with:
          name: apk
          path: |
            app-signed.apk
            app-signed.aab
"""


# ---------------- GitHub API ----------------
def _clean(text):
    return str(text).replace(GITHUB_TOKEN, "***") if GITHUB_TOKEN else str(text)


def gh(method, path, **kw):
    r = httpx.request(method, API + path, timeout=90, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub {method} {path} -> {r.status_code}: {_clean(r.text)[:300]}")
    return r


def set_secret(owner, repo, name, value):
    k = gh("GET", f"/repos/{owner}/{repo}/actions/secrets/public-key").json()
    pk = public.PublicKey(k["key"].encode(), encoding.Base64Encoder())
    enc = base64.b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()
    gh("PUT", f"/repos/{owner}/{repo}/actions/secrets/{name}",
       json={"encrypted_value": enc, "key_id": k["key_id"]})


# ---------------- کلید امضا ----------------
def make_keystore(oid):
    os.makedirs(KEYS, exist_ok=True)
    path = os.path.join(KEYS, f"app_{oid}.jks")
    if os.path.exists(path):
        os.remove(path)
    pw = secrets.token_urlsafe(16)
    try:
        subprocess.run(["keytool", "-genkeypair", "-keystore", path, "-alias", "key",
                        "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
                        "-storepass", pw, "-keypass", pw, "-dname", "CN=App,O=AppMaker,C=IR"],
                       check=True, capture_output=True)
    except FileNotFoundError:
        raise RuntimeError("keytool پیدا نشد. JDK نصب کن: sudo apt-get install -y default-jdk-headless")
    with open(os.path.join(KEYS, f"app_{oid}.json"), "w") as f:
        json.dump({"alias": "key", "password": pw}, f)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), pw


# ---------------- پروژه ----------------
def safe_extract(zip_path, dest):
    dest = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = os.path.abspath(os.path.join(dest, m.filename))
            if not target.startswith(dest + os.sep) and target != dest:
                raise RuntimeError("فایل zip نامعتبر است")
        z.extractall(dest)


def find_root(base):
    best = None
    for d, _, files in os.walk(base):
        if "settings.gradle" in files or "settings.gradle.kts" in files:
            if best is None or len(d) < len(best):
                best = d
    return best


def clean_project(root):
    for d, dirs, files in os.walk(root, topdown=True):
        for x in list(dirs):
            if x in ("build", ".gradle", ".idea", ".git"):
                shutil.rmtree(os.path.join(d, x), ignore_errors=True)
                dirs.remove(x)
        for f in files:
            if f == "local.properties" or f.endswith(".iml"):
                os.remove(os.path.join(d, f))


TEXT = (".java", ".kt", ".xml", ".gradle", ".kts", ".html", ".js", ".json", ".properties")


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def patch_project(root, link, name, app_id):
    rep = []
    files = []
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(TEXT):
                files.append(os.path.join(d, f))
    xml_name = escape(name).replace("'", "\\'")
    url_done = name_done = False

    # 1) جای‌نگهدارها
    for p in files:
        s = _read(p)
        if s is None:
            continue
        o = s
        if "{{APP_URL}}" in s:
            s = s.replace("{{APP_URL}}", link)
            url_done = True
        if "{{APP_NAME}}" in s:
            s = s.replace("{{APP_NAME}}", xml_name if p.endswith(".xml") else name)
            name_done = True
        s = s.replace("{{APP_ID}}", app_id)
        if s != o:
            _write(p, s)
            rep.append(f"جای‌نگهدار → {os.path.relpath(p, root)}")

    # 1b) حذف واترمارک/برندینگ
    if BRANDING_RULES:
        for p in files:
            s = _read(p)
            if s is None:
                continue
            o = s
            for pat, r_ in BRANDING_RULES:
                s = re.sub(pat, r_, s, flags=re.I)
            if s != o:
                _write(p, s)
                rep.append(f"برندینگ حذف شد → {os.path.relpath(p, root)}")

    # 2) تشخیص خودکار لینک
    if not url_done:
        pats = [
            (r'(loadUrl\(\s*)"https?://[^"]*"', (".java", ".kt")),
            (r'(\b\w*(?:URL|Url|url|LINK|Link|SITE|Site|HOME|Home)\w*\s*=\s*)"https?://[^"]*"', (".java", ".kt")),
        ]
        for p in files:
            s = _read(p)
            if s is None:
                continue
            o = s
            for pat, exts in pats:
                if p.endswith(exts):
                    s = re.sub(pat, lambda m: f'{m.group(1)}"{link}"', s)
            if p.endswith(".xml"):
                s = re.sub(r'(<string\s+name="[^"]*(?:url|link|site|home)[^"]*"[^>]*>)\s*https?://[^<]*(</string>)',
                           lambda m: f"{m.group(1)}{link}{m.group(2)}", s, flags=re.I)
            if s != o:
                _write(p, s)
                url_done = True
                rep.append(f"لینک → {os.path.relpath(p, root)}")

    # 3) تشخیص خودکار نام اپ
    if not name_done:
        for p in files:
            if p.endswith("strings.xml"):
                s = _read(p)
                if s and 'name="app_name"' in s:
                    n = re.sub(r'(<string\s+name="app_name"[^>]*>)[^<]*(</string>)',
                               lambda m: f"{m.group(1)}{xml_name}{m.group(2)}", s)
                    if n != s:
                        _write(p, n)
                        name_done = True
                        rep.append(f"نام → {os.path.relpath(p, root)}")

    # 4) شناسه یکتای اپ
    for p in files:
        if p.endswith((".gradle", ".kts")):
            s = _read(p)
            if s and "applicationId" in s:
                n = re.sub(r'(applicationId\s*=?\s*)["\'][^"\']+["\']',
                           lambda m: f'{m.group(1)}"{app_id}"', s)
                if n != s:
                    _write(p, n)
                    rep.append(f"applicationId → {app_id}")

    if not url_done:
        rep.append("⚠️ لینک پیدا نشد! جای‌نگهدار {{APP_URL}} را در کد بگذار")
    if not name_done:
        rep.append("⚠️ نام اپ پیدا نشد! جای‌نگهدار {{APP_NAME}} را بگذار")
    return rep


SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def patch_icons(root, icon_path):
    manifest = None
    for d, dirs, fs in os.walk(root):
        if "AndroidManifest.xml" in fs:
            s = _read(os.path.join(d, "AndroidManifest.xml"))
            if s and "<application" in s:
                manifest = os.path.join(d, "AndroidManifest.xml")
                break
    if not manifest:
        return ["⚠️ AndroidManifest پیدا نشد؛ آیکون عوض نشد"]
    s = _read(manifest)
    res = os.path.join(os.path.dirname(manifest), "res")
    img = Image.open(icon_path).convert("RGBA")
    w, h = img.size
    m = min(w, h)
    img = img.crop(((w - m) // 2, (h - m) // 2, (w - m) // 2 + m, (h - m) // 2 + m))

    targets = []
    for attr in ("icon", "roundIcon"):
        mt = re.search(rf'android:{attr}="@(mipmap|drawable)/(\w+)"', s)
        if mt:
            targets.append((mt.group(1), mt.group(2)))
    if not targets:
        return ["⚠️ android:icon در Manifest پیدا نشد؛ آیکون عوض نشد"]

    rep = []
    for typ, name in set(targets):
        if os.path.isdir(res):
            for d in os.listdir(res):
                if d.startswith(("mipmap", "drawable")):
                    for f in os.listdir(os.path.join(res, d)):
                        if f.rsplit(".", 1)[0] == name:
                            os.remove(os.path.join(res, d, f))
        for dens, px in SIZES.items():
            dd = os.path.join(res, f"{typ}-{dens}")
            os.makedirs(dd, exist_ok=True)
            img.resize((px, px), Image.LANCZOS).save(os.path.join(dd, f"{name}.png"))
        rep.append(f"آیکون → {typ}/{name}")
    return rep


# ---------------- گیت‌هاب ----------------
def git_push(root, owner, repo):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def run(*a):
        try:
            subprocess.run(a, cwd=root, check=True, capture_output=True, text=True, env=env)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(_clean(e.stderr or e.stdout)[:400])
        except FileNotFoundError:
            raise RuntimeError("git روی سرور نصب نیست")

    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "bot@example.com")
    run("git", "config", "user.name", "AppMaker")
    run("git", "add", "-A")
    run("git", "commit", "-m", "init")
    run("git", "push", f"https://x-access-token:{GITHUB_TOKEN}@github.com/{owner}/{repo}.git", "main")


def wait_run(owner, repo):
    t0 = time.time()
    while time.time() - t0 < BUILD_TIMEOUT:
        runs = gh("GET", f"/repos/{owner}/{repo}/actions/runs?per_page=1").json().get("workflow_runs", [])
        if runs and runs[0]["status"] == "completed":
            return runs[0]
        time.sleep(20)
    raise RuntimeError("زمان ساخت بیش از حد طول کشید")


def download_apk(owner, repo, run_id, out_base):
    arts = gh("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts").json()["artifacts"]
    if not arts:
        raise RuntimeError("فایل خروجی پیدا نشد")
    r = httpx.get(arts[0]["archive_download_url"], timeout=300, follow_redirects=True,
                  headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
    r.raise_for_status()
    tmp = out_base + ".zip"
    with open(tmp, "wb") as f:
        f.write(r.content)
    res = {}
    with zipfile.ZipFile(tmp) as z:
        for ext in ("apk", "aab"):
            n = next((x for x in z.namelist() if x.endswith("." + ext)), None)
            if n:
                res[ext] = f"{out_base}.{ext}"
                with open(res[ext], "wb") as f:
                    f.write(z.read(n))
    os.remove(tmp)
    if "apk" not in res:
        raise RuntimeError("APK داخل خروجی نبود")
    return res["apk"], res.get("aab")


# ---------------- ورودی اصلی ----------------
def build_app(oid, template_zip, link, name, icon_path, progress):
    if not GITHUB_TOKEN:
        raise RuntimeError("متغیر GITHUB_TOKEN تنظیم نشده")
    os.makedirs(WORK, exist_ok=True)
    base = os.path.join(WORK, f"order_{oid}")
    shutil.rmtree(base, ignore_errors=True)
    safe_extract(template_zip, base)
    root = find_root(base)
    if not root:
        raise RuntimeError("settings.gradle در پروژه پیدا نشد؛ پروژه اندروید (Gradle) نیست")
    clean_project(root)

    app_id = f"com.appmaker.app{oid}"
    report = patch_project(root, link, name, app_id) + patch_icons(root, icon_path)
    progress("🔧 گزارش اصلاح کد:\n" + "\n".join(report))

    ks_b64, pw = make_keystore(oid)
    owner = gh("GET", "/user").json()["login"]
    repo = f"app-{oid}-{secrets.token_hex(3)}"
    gh("POST", "/user/repos", json={"name": repo, "private": REPO_PRIVATE, "auto_init": False})
    set_secret(owner, repo, "KS_B64", ks_b64)
    set_secret(owner, repo, "KS_PASS", pw)

    wf = os.path.join(root, ".github", "workflows")
    os.makedirs(wf, exist_ok=True)
    _write(os.path.join(wf, "build.yml"), WORKFLOW)
    git_push(root, owner, repo)
    progress(f"📤 کد در مخزن {repo} قرار گرفت. در حال کامپایل (چند دقیقه)...")

    run = wait_run(owner, repo)
    if run["conclusion"] != "success":
        raise RuntimeError(f"ساخت ناموفق بود: {run['html_url']}")
    out = os.path.join(WORK, f"app_{oid}")
    apk, aab = download_apk(owner, repo, run["id"], out)
    return apk, aab, f"https://github.com/{owner}/{repo}"
