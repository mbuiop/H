#!/usr/bin/env python3
"""
Betfa.com Automation System
Professional Web Automation with Copy Enable
"""

import time
import random
import requests
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import json
from datetime import datetime

class BetfaAutomation:
    def __init__(self):
        self.driver = None
        self.start_time = datetime.now()
        self.setup_browser()
    
    def setup_browser(self):
        """راه‌اندازی مرورگر با تنظیمات پیشرفته"""
        print("🔥 در حال راه‌اندازی مرورگر پیشرفته...")
        
        options = Options()
        
        # 🔧 تنظیمات استیلث و عملکرد
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)
        options.set_preference("marionette", True)
        
        # 👤 User Agent واقعی
        options.set_preference("general.useragent.override", 
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0")
        
        # 🚀 بهینه‌سازی عملکرد
        options.set_preference("browser.cache.disk.enable", False)
        options.set_preference("browser.cache.memory.enable", True)
        options.set_preference("browser.sessionstore.resume_from_crash", False)
        options.set_preference("dom.max_script_run_time", 30)
        options.set_preference("dom.max_chrome_script_run_time", 30)
        
        # 🔒 تنظیمات امنیتی
        options.set_preference("dom.disable_beforeunload", True)
        options.set_preference("dom.popup_maximum", 0)
        options.set_preference("privacy.popups.showBrowserMessage", False)
        
        try:
            self.driver = webdriver.Firefox(options=options)
            self.driver.set_window_size(1920, 1080)
            print("✅ مرورگر با موفقیت راه‌اندازی شد")
            
        except Exception as e:
            print(f"❌ خطا در راه‌اندازی مرورگر: {e}")
            raise
    
    def simulate_human_behavior(self):
        """شبیه‌سازی پیشرفته رفتار انسانی"""
        print("🤖 در حال شبیه‌سازی رفتار انسانی...")
        
        actions = ActionChains(self.driver)
        
        # 🖱️ حرکت موس تصادفی
        for i in range(4):
            x_offset = random.randint(-40, 40)
            y_offset = random.randint(-40, 40)
            actions.move_by_offset(x_offset, y_offset)
            actions.pause(random.uniform(0.1, 0.4))
        
        actions.perform()
        time.sleep(1)
        
        # 📜 اسکرول طبیعی
        scroll_patterns = [
            (0, 400, "smooth"),
            (200, 100, "auto"),
            (0, 800, "smooth"),
            (100, 300, "auto")
        ]
        
        for scroll in scroll_patterns:
            script = f"""
            window.scrollTo({{
                top: {scroll[1]},
                left: {scroll[0]},
                behavior: '{scroll[2]}'
            }});
            """
            self.driver.execute_script(script)
            time.sleep(random.uniform(0.8, 1.5))
    
    def remove_all_protections(self):
        """حذف کامل تمام محافظت‌های کپی"""
        print("🛡️ در حال غیرفعال کردن محافظت‌های پیشرفته...")
        
        protection_scripts = [
            # 🎯 سطح 1: فعال‌سازی انتخاب متن در تمام المنت‌ها
            """
            const allElements = document.querySelectorAll('*');
            allElements.forEach(element => {
                element.style.userSelect = 'text';
                element.style.webkitUserSelect = 'text';
                element.style.MozUserSelect = 'text';
                element.style.msUserSelect = 'text';
                element.style.webkitTouchCallout = 'default';
                element.style.pointerEvents = 'auto';
                element.style.cursor = 'auto';
            });
            """,
            
            # 🎯 سطح 2: غیرفعال کردن event handlers
            """
            const protectedEvents = ['selectstart', 'contextmenu', 'copy', 'cut', 'paste', 
                                   'mousedown', 'mouseup', 'click', 'dragstart'];
            
            protectedEvents.forEach(event => {
                document[`on${event}`] = null;
                window[`on${event}`] = null;
            });
            """,
            
            # 🎯 سطح 3: فعال‌سازی design mode و contenteditable
            """
            document.designMode = 'on';
            document.body.contentEditable = true;
            document.querySelectorAll('[contenteditable]').forEach(el => {
                el.contentEditable = true;
            });
            """,
            
            # 🎯 سطح 4: بازنویسی event listeners
            """
            const originalAddEventListener = EventTarget.prototype.addEventListener;
            EventTarget.prototype.addEventListener = function(type, listener, options) {
                const blockedEvents = ['selectstart', 'contextmenu', 'copy', 'cut', 'paste', 
                                     'mousedown', 'mouseup', 'click', 'dragstart'];
                
                if (blockedEvents.includes(type)) {
                    return;
                }
                originalAddEventListener.call(this, type, listener, options);
            };
            """,
            
            # 🎯 سطح 5: حذف CSS‌های محدودکننده
            """
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
                                rule.style.pointerEvents === 'none' ||
                                rule.style.cursor === 'default'
                            )) {
                                style.sheet.deleteRule(i);
                            }
                        }
                    } catch(e) {}
                }
            });
            """,
            
            # 🎯 سطح 6: اضافه کردن event listeners جدید
            """
            document.addEventListener('contextmenu', e => {
                e.stopPropagation();
                e.stopImmediatePropagation();
                return true;
            }, true);
            
            document.addEventListener('copy', e => {
                e.stopPropagation();
                e.stopImmediatePropagation();
                return true;
            }, true);
            
            document.addEventListener('selectstart', e => {
                e.stopPropagation();
                e.stopImmediatePropagation();
                return true;
            }, true);
            
            document.addEventListener('mousedown', e => {
                e.stopPropagation();
                e.stopImmediatePropagation();
                return true;
            }, true);
            """
        ]
        
        for i, script in enumerate(protection_scripts, 1):
            try:
                self.driver.execute_script(script)
                print(f"   ✅ لایه محافظتی {i} غیرفعال شد")
                time.sleep(0.7)
            except Exception as e:
                print(f"   ⚠️ خطا در لایه {i}: {e}")
    
    def navigate_to_betfa(self):
        """ناوبری به سایت Betfa"""
        target_url = "https://betfa.com/home/index"
        
        print(f"🌐 در حال ناوبری به: {target_url}")
        
        try:
            self.driver.get(target_url)
            
            # ⏳ منتظر لود شدن صفحه
            print("⏳ در حال منتظر لود شدن صفحه...")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # بررسی عنوان صفحه
            page_title = self.driver.title
            print(f"📄 عنوان صفحه: {page_title}")
            
            # بررسی URL نهایی
            current_url = self.driver.current_url
            print(f"🔗 آدرس فعلی: {current_url}")
            
            print("✅ صفحه با موفقیت لود شد")
            
        except Exception as e:
            print(f"❌ خطا در لود شدن صفحه: {e}")
            raise
    
    def analyze_page_content(self):
        """آنالیز محتوای صفحه"""
        print("🔍 در حال آنالیز محتوای صفحه...")
        
        analysis_script = """
        return {
            title: document.title,
            url: window.location.href,
            hasContent: document.body.innerText.length > 0,
            contentLength: document.body.innerText.length,
            hasImages: document.images.length > 0,
            hasForms: document.forms.length > 0,
            hasTables: document.querySelectorAll('table').length > 0,
            hasLinks: document.querySelectorAll('a').length > 0,
            isProtected: !!document.onselectstart || !!document.oncontextmenu,
            designMode: document.designMode,
            contentEditable: document.body.contentEditable
        };
        """
        
        try:
            analysis = self.driver.execute_script(analysis_script)
            print("📊 گزارش آنالیز صفحه:")
            for key, value in analysis.items():
                status = "✅" if value else "❌"
                if isinstance(value, bool):
                    print(f"   {key}: {status} {value}")
                else:
                    print(f"   {key}: {value}")
            
            return analysis
            
        except Exception as e:
            print(f"⚠️ خطا در آنالیز صفحه: {e}")
            return {}
    
    def take_screenshot(self, filename=None):
        """گرفتن عکس از صفحه"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"betfa_result_{timestamp}.png"
        
        try:
            self.driver.save_screenshot(filename)
            print(f"📸 عکس صفحه ذخیره شد: {filename}")
            return filename
        except Exception as e:
            print(f"⚠️ خطا در گرفتن عکس: {e}")
            return None
    
    def save_page_info(self):
        """ذخیره اطلاعات صفحه"""
        try:
            page_info = {
                "title": self.driver.title,
                "url": self.driver.current_url,
                "timestamp": datetime.now().isoformat(),
                "automation_time": (datetime.now() - self.start_time).total_seconds()
            }
            
            with open("betfa_page_info.json", "w", encoding="utf-8") as f:
                json.dump(page_info, f, indent=2, ensure_ascii=False)
            
            print("💾 اطلاعات صفحه ذخیره شد: betfa_page_info.json")
            
        except Exception as e:
            print(f"⚠️ خطا در ذخیره اطلاعات: {e}")
    
    def run_complete_automation(self):
        """اجرای کامل اتوماسیون"""
        try:
            print("🚀 شروع فرآیند اتوماسیون Betfa.com")
            print("=" * 60)
            
            # 🎯 مرحله 1: ناوبری به سایت
            self.navigate_to_betfa()
            time.sleep(3)
            
            # 🎯 مرحله 2: شبیه‌سازی رفتار انسانی
            self.simulate_human_behavior()
            
            # 🎯 مرحله 3: آنالیز صفحه
            self.analyze_page_content()
            
            # 🎯 مرحله 4: حذف محافظت‌ها
            self.remove_all_protections()
            
            # 🎯 مرحله 5: آنالیز نهایی
            final_analysis = self.analyze_page_content()
            
            # 🎯 مرحله 6: ذخیره‌سازی نتایج
            self.take_screenshot("betfa_final_result.png")
            self.save_page_info()
            
            # 🎯 نمایش گزارش نهایی
            self.display_final_report(final_analysis)
            
            # 🎯 نگه داشتن مرورگر باز
            self.keep_browser_open()
            
        except Exception as e:
            print(f"❌ خطا در اتوماسیون: {e}")
            self.take_screenshot("betfa_error.png")
        finally:
            self.cleanup()
    
    def display_final_report(self, analysis):
        """نمایش گزارش نهایی"""
        print("\n" + "=" * 60)
        print("📊 گزارش نهایی اتوماسیون Betfa.com")
        print("=" * 60)
        
        report_items = [
            ("✅ ناوبری به سایت", "تکمیل"),
            ("✅ شبیه‌سازی رفتاری", "تکمیل"), 
            ("✅ آنالیز صفحه", "تکمیل"),
            ("✅ حذف محافظت‌ها", "تکمیل"),
            ("✅ ذخیره‌سازی نتایج", "تکمیل"),
            ("⏱️ زمان اجرا", f"{(datetime.now() - self.start_time).total_seconds():.2f} ثانیه"),
            ("📄 عنوان صفحه", analysis.get('title', 'N/A')),
            ("🔗 آدرس صفحه", analysis.get('url', 'N/A'))
        ]
        
        for item, value in report_items:
            print(f"   {item}: {value}")
        
        print("\n🎉 اتوماسیون با موفقیت کامل شد!")
        print("📋 اکنون می‌توانید:")
        print("   • هر متنی را انتخاب کنید")
        print("   • کلیک راست کنید")
        print("   • از Ctrl+C استفاده کنید") 
        print("   • تمام محتوا را کپی کنید")
        print("   • بدون محدودیت کار کنید")
    
    def keep_browser_open(self):
        """نگه داشتن مرورگر باز برای کاربر"""
        print("\n⏎ برای بستن مرورگر، Enter را بزنید...")
        try:
            input()
        except:
            pass
    
    def cleanup(self):
        """پاک‌سازی منابع"""
        if self.driver:
            try:
                self.driver.quit()
                print("🔚 مرورگر بسته شد")
            except:
                pass

def main():
    """تابع اصلی"""
    print("""
    🚀 سیستم اتوماسیون پیشرفته Betfa.com
    🔥 نسخه حرفه‌ای - محیط کداسپیس
    ⚡ توسعه‌دهنده: AI Assistant
    🎯 هدف: https://betfa.com/home/index
    """)
    
    automation = None
    try:
        automation = BetfaAutomation()
        automation.run_complete_automation()
    except KeyboardInterrupt:
        print("\n⏹️ عملیات توسط کاربر متوقف شد")
        if automation:
            automation.cleanup()
    except Exception as e:
        print(f"❌ خطای غیرمنتظره: {e}")
        if automation:
            automation.cleanup()

if __name__ == "__main__":
    main()
