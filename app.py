from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

def enable_copy():
    print("🔄 در حال راه‌اندازی مرورگر...")
    
    # تنظیمات ساده و کارآمد
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    try:
        # راه‌اندازی مرورگر
        driver = webdriver.Chrome(options=options)
        
        # باز کردن سایت
        url = "https://share.google.com/kqWvwMZuhdCk2tgAS"
        print(f"🌐 در حال باز کردن: {url}")
        driver.get(url)
        
        # منتظر لود شدن
        time.sleep(5)
        
        # غیرفعال کردن محافظت‌های کپی
        print("🛡️ در حال غیرفعال کردن محافظت‌ها...")
        driver.execute_script("""
            // فعال کردن انتخاب متن
            var allElements = document.querySelectorAll('*');
            for (var i = 0; i < allElements.length; i++) {
                allElements[i].style.userSelect = 'text';
                allElements[i].style.webkitUserSelect = 'text';
            }
            
            // غیرفعال کردن eventهای جلوگیری کننده
            document.onselectstart = null;
            document.oncontextmenu = null;
            document.oncopy = null;
            
            // اجازه دادن به کلیک راست و کپی
            document.addEventListener('contextmenu', function(e) {
                e.stopPropagation();
            }, true);
            
            document.addEventListener('copy', function(e) {
                e.stopPropagation();
            }, true);
        """)
        
        print("✅ سایت باز شد!")
        print("✅ محافظت‌های کپی غیرفعال شدند")
        print("📋 حالا می‌توانید متن‌ها را کپی کنید")
        print("⏎ برای بستن مرورگر، Enter را بزنید...")
        
        input()
        
    except Exception as e:
        print(f"❌ خطا: {e}")
    finally:
        try:
            driver.quit()
            print("🔚 مرورگر بسته شد")
        except:
            pass

# اجرای برنامه
if __name__ == "__main__":
    enable_copy()
