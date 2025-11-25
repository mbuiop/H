from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import time
import random
import undetected_chromedriver as uc
import pyautogui
import requests
import json

class AdvancedCopyEnabler:
    def __init__(self):
        self.driver = None
        self.setup_stealth_browser()
    
    def setup_stealth_browser(self):
        """تنظیمات مرورگر استیلث پیشرفته"""
        print("🔄 در حال راه‌اندازی مرورگر استیلث...")
        
        try:
            # استفاده از undetected-chromedriver برای دور زدن تشخیص بات
            self.driver = uc.Chrome(
                options=self.get_chrome_options(),
                driver_executable_path=self.get_chrome_driver_path()
            )
            
            # اجرای اسکریپت‌های استیلث
            self.execute_stealth_scripts()
            
        except Exception as e:
            print(f"❌ خطا در راه‌اندازی مرورگر استیلث: {e}")
            self.setup_fallback_browser()
    
    def get_chrome_options(self):
        """تنظیمات پیشرفته Chrome"""
        options = Options()
        
        # حذف نشانگر اتوماسیون
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # تنظیمات کاربر واقعی
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--remote-debugging-port=0")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--window-size=1920,1080")
        
        # غیرفعال کردن WebRTC
        options.add_argument("--disable-webrtc")
        
        return options
    
    def get_chrome_driver_path(self):
        """مسیر Chrome Driver"""
        # می‌توانید مسیر خاصی قرار دهید یا auto-detect شود
        return None  # auto-detect
    
    def execute_stealth_scripts(self):
        """اجرای اسکریپت‌های استیلث برای مخفی کردن اتوماسیون"""
        stealth_scripts = [
            # پاک کردن webdriver flag
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            
            # تغییر زبان
            "Object.defineProperty(navigator, 'language', {get: () => 'en-US'})",
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})",
            
            # تغییر پلتفرم
            "Object.defineProperty(navigator, 'platform', {get: () => 'Win32'})",
            
            # مخفی کردن Chrome Runtime
            "window.chrome = {runtime: {}}",
            
            # تغییر permissions
            "const originalQuery = window.navigator.permissions.query; window.navigator.permissions.query = (parameters) => (parameters.name === 'notifications' ? Promise.resolve({state: Notification.permission}) : originalQuery(parameters))",
            
            # مخفی کردن WebDriver
            "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})"
        ]
        
        for script in stealth_scripts:
            try:
                self.driver.execute_script(script)
            except:
                pass
    
    def setup_fallback_browser(self):
        """راه‌اندازی مرورگر جایگزین"""
        print("🔄 در حال راه‌اندازی مرورگر جایگزین...")
        options = self.get_chrome_options()
        self.driver = webdriver.Chrome(options=options)
        self.execute_stealth_scripts()
    
    def human_like_behavior(self):
        """شبیه‌سازی رفتار انسانی"""
        try:
            # حرکت موس تصادفی
            actions = ActionChains(self.driver)
            for _ in range(3):
                x_offset = random.randint(-100, 100)
                y_offset = random.randint(-100, 100)
                actions.move_by_offset(x_offset, y_offset)
                actions.pause(random.uniform(0.1, 0.5))
            actions.perform()
            
            # اسکرول تصادفی
            scroll_amount = random.randint(200, 800)
            self.driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            time.sleep(random.uniform(0.5, 2))
            
        except:
            pass
    
    def remove_all_protections(self):
        """حذف تمام محافظت‌های کپی و انتخاب"""
        print("🛡️ در حال غیرفعال کردن محافظت‌های پیشرفته...")
        
        protection_removal_scripts = [
            # حذف event listeners برای تمام المنت‌ها
            """
            function removeAllEventListeners(element) {
                const clone = element.cloneNode(true);
                element.parentNode.replaceChild(clone, element);
                return clone;
            }
            document.querySelectorAll('*').forEach(removeAllEventListeners);
            """,
            
            # بازنویسی تمام event handlers
            """
            Object.defineProperty(document, 'onselectstart', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'oncontextmenu', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'oncopy', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'oncut', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'onpaste', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'onmousedown', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'onmouseup', {get: () => null, set: () => {}});
            Object.defineProperty(document, 'onclick', {get: () => null, set: () => {}});
            """,
            
            # فعال کردن انتخاب متن در تمام سطوح
            """
            const enableSelection = (element) => {
                element.style.userSelect = 'text';
                element.style.webkitUserSelect = 'text';
                element.style.MozUserSelect = 'text';
                element.style.msUserSelect = 'text';
                element.style.webkitTouchCallout = 'default';
                element.style.webkitUserDrag = 'element';
                element.style.cursor = 'auto';
            };
            document.querySelectorAll('*').forEach(enableSelection);
            """,
            
            # حذف CSS‌های جلوگیری کننده
            """
            const disablePreventionStyles = () => {
                const styles = document.querySelectorAll('style, link[rel="stylesheet"]');
                styles.forEach(style => {
                    if (style.sheet) {
                        try {
                            const rules = style.sheet.cssRules || style.sheet.rules;
                            for (let i = rules.length - 1; i >= 0; i--) {
                                const rule = rules[i];
                                if (rule.style && (
                                    rule.style.userSelect === 'none' ||
                                    rule.style.webkitUserSelect === 'none' ||
                                    rule.style.pointerEvents === 'none'
                                )) {
                                    style.sheet.deleteRule(i);
                                }
                            }
                        } catch (e) {}
                    }
                });
            };
            disablePreventionStyles();
            """,
            
            # اضافه کردن event listeners جدید برای اجازه کپی
            """
            document.addEventListener('copy', e => {
                e.stopImmediatePropagation();
            }, true);
            document.addEventListener('cut', e => {
                e.stopImmediatePropagation();
            }, true);
            document.addEventListener('contextmenu', e => {
                e.stopImmediatePropagation();
            }, true);
            document.addEventListener('selectstart', e => {
                e.stopImmediatePropagation();
            }, true);
            """
        ]
        
        for i, script in enumerate(protection_removal_scripts):
            try:
                self.driver.execute_script(script)
                print(f"✅ اسکریپت محافظتی {i+1} اجرا شد")
                time.sleep(0.5)
            except Exception as e:
                print(f"⚠️ خطا در اسکریپت {i+1}: {e}")
    
    def bypass_advanced_protections(self):
        """دور زدن محافظت‌های پیشرفته"""
        print("🔓 در حال دور زدن محافظت‌های پیشرفته...")
        
        # روش‌های مختلف برای دور زدن محافظت
        bypass_methods = [
            # روش ۱: تغییر propertyهای document
            "delete document.__defineGetter__; delete document.__defineSetter__;",
            
            # روش ۲: بازنویسی console.log برای جلوگیری از تشخیص
            "console.log = function() {}; console.warn = function() {};",
            
            # روش ۳: غیرفعال کردن debugger
            "window.ondevtoolsopen = function() {};",
            
            # روش ۴: تغییر focus و blur events
            "window.onfocus = null; window.onblur = null;",
            
            # روش ۵: غیرفعال کردن keyboard events جلوگیری کننده
            "document.onkeydown = null; document.onkeyup = null; document.onkeypress = null;"
        ]
        
        for method in bypass_methods:
            try:
                self.driver.execute_script(method)
            except:
                pass
    
    def open_website_with_protection_bypass(self, url):
        """باز کردن سایت با دور زدن کامل محافظت‌ها"""
        try:
            print(f"🌐 در حال باز کردن سایت: {url}")
            
            # باز کردن سایت
            self.driver.get(url)
            
            # منتظر لود شدن صفحه
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # شبیه‌سازی رفتار انسانی
            self.human_like_behavior()
            
            # دور زدن محافظت‌های پیشرفته
            self.bypass_advanced_protections()
            
            # حذف تمام محافظت‌ها
            self.remove_all_protections()
            
            # تأخیر برای اطمینان
            time.sleep(3)
            
            # اجرای نهایی برای فعال‌سازی کپی
            self.finalize_copy_enable()
            
            print("🎉 عملیات با موفقیت انجام شد!")
            print("✅ تمام محافظت‌ها غیرفعال شدند")
            print("📋 حالا می‌توانید هر متنی را کپی کنید")
            print("⏎ برای بستن مرورگر، Enter را بزنید...")
            
            input()
            
        except Exception as e:
            print(f"❌ خطا: {e}")
        finally:
            if self.driver:
                self.driver.quit()
                print("🔚 مرورگر بسته شد")
    
    def finalize_copy_enable(self):
        """فعال‌سازی نهایی قابلیت کپی"""
        final_scripts = [
            # فعال‌سازی کامل انتخاب متن
            """
            document.designMode = 'on';
            document.body.contentEditable = true;
            """,
            
            # حذف نهایی تمام محدودیت‌ها
            """
            const allElements = document.getElementsByTagName('*');
            for (let el of allElements) {
                el.setAttribute('oncopy', '');
                el.setAttribute('oncut', '');
                el.setAttribute('onpaste', '');
                el.setAttribute('oncontextmenu', '');
                el.setAttribute('onselectstart', '');
            }
            """
        ]
        
        for script in final_scripts:
            try:
                self.driver.execute_script(script)
            except:
                pass

# اجرای اصلی برنامه
if __name__ == "__main__":
    print("🚀 راه‌اندازی سیستم پیشرفته فعال‌سازی کپی...")
    print("=" * 60)
    
    # 🔗 لینک سایت شما
    TARGET_URL = "https://share.google.com/kqWvwMZuhdCk2tgAS"
    
    enabler = AdvancedCopyEnabler()
    enabler.open_website_with_protection_bypass(TARGET_URL)
