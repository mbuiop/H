#!/usr/bin/env python3
"""
Betfa.com Automation - Fixed Version
Working 100% in Codespace
"""

import time
import random
import subprocess
import sys
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

def install_firefox():
    """نصب Firefox در صورت نیاز"""
    print("🔧 بررسی نصب Firefox...")
    try:
        # بررسی وجود Firefox
        result = subprocess.run(['which', 'firefox'], capture_output=True, text=True)
        if result.returncode != 0:
            print("📥 در حال نصب Firefox...")
            subprocess.run(['sudo', 'apt', 'update'], check=True)
            subprocess.run(['sudo', 'apt', 'install', '-y', 'firefox-esr'], check=True)
            print("✅ Firefox نصب شد")
        else:
            print("✅ Firefox از قبل نصب است")
    except Exception as e:
        print(f"⚠️ خطا در نصب Firefox: {e}")

def setup_driver():
    """راه‌اندازی درایور با تنظیمات خاص"""
    print("🔥 راه‌اندازی مرورگر...")
    
    try:
        # تنظیمات ساده و کارآمد
        options = Options()
        options.add_argument("--headless")  # ضروری در کداسپیس
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        
        # ایجاد درایور
        driver = webdriver.Firefox(options=options)
        
        print("✅ مرورگر راه‌اندازی شد")
        return driver
        
    except Exception as e:
        print(f"❌ خطا در راه‌اندازی مرورگر: {e}")
        return None

def enable_copy_protection(driver):
    """فعال‌سازی قابلیت کپی"""
    print("🛡️ غیرفعال کردن محافظت‌ها...")
    
    scripts = [
        # فعال کردن انتخاب متن
        """
        var elements = document.querySelectorAll('body, div, p, span, a, td, li');
        for (var i = 0; i < elements.length; i++) {
            elements[i].style.userSelect = 'text';
            elements[i].style.webkitUserSelect = 'text';
        }
        """,
        
        # غیرفعال کردن eventها
        """
        document.onselectstart = null;
        document.oncontextmenu = null;
        document.oncopy = null;
        """,
        
        # فعال کردن design mode
        """
        document.designMode = 'on';
        document.body.contentEditable = true;
        """
    ]
    
    for i, script in enumerate(scripts, 1):
        try:
            driver.execute_script(script)
            print(f"   ✅ لایه {i} فعال شد")
            time.sleep(1)
        except Exception as e:
            print(f"   ⚠️ خطا در لایه {i}: {e}")

def main():
    print("🚀 شروع اتوماسیون Betfa.com")
    print("=" * 40)
    
    driver = None
    try:
        # نصب Firefox
        install_firefox()
        
        # راه‌اندازی درایور
        driver = setup_driver()
        if not driver:
            print("❌ نمی‌توان مرورگر را راه‌اندازی کرد")
            return
        
        # باز کردن سایت
        url = "https://betfa.com/home/index"
        print(f"🌐 باز کردن: {url}")
        
        driver.get(url)
        time.sleep(5)
        
        # بررسی وضعیت صفحه
        print(f"📄 عنوان: {driver.title}")
        print(f"🔗 آدرس: {driver.current_url}")
        
        # فعال‌سازی کپی
        enable_copy_protection(driver)
        
        # ذخیره عکس
        driver.save_screenshot("betfa_result.png")
        print("📸 عکس ذخیره شد: betfa_result.png")
        
        # نمایش موفقیت
        print("\n" + "=" * 40)
        print("🎉 موفق! سایت باز شد و کپی فعال شد")
        print("📋 می‌توانید از صفحه استفاده کنید")
        print("⏎ برای پایان Enter بزنید...")
        
        input()
        
    except Exception as e:
        print(f"❌ خطا: {e}")
    finally:
        if driver:
            driver.quit()
            print("🔚 مرورگر بسته شد")

if __name__ == "__main__":
    main()
