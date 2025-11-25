from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

def enable_copy():
    print("🔄 در حال راه‌اندازی مرورگر برای محیط کداسپیس...")
    
    # تنظیمات مخصوص کداسپیس
    options = Options()
    options.add_argument("--headless")  # ضروری در کداسپیس
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    
    try:
        # نصب و راه‌اندازی خودکار ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # باز کردن سایت
        url = "https://share.google.com/kqWvwMZuhdCk2tgAS"
        print(f"🌐 در حال باز کردن: {url}")
        driver.get(url)
        
        # منتظر لود شدن
        time.sleep(8)
        
        # بررسی اینکه سایت لود شده
        print(f"📄 عنوان صفحه: {driver.title}")
        
        # غیرفعال کردن محافظت‌های کپی
        print("🛡️ در حال غیرفعال کردن محافظت‌ها...")
        protection_script = """
            try {
                // فعال کردن انتخاب متن
                var elements = document.querySelectorAll('body, div, p, span, td');
                for (var i = 0; i < elements.length; i++) {
                    elements[i].style.userSelect = 'text';
                    elements[i].style.webkitUserSelect = 'text';
                    elements[i].style.MozUserSelect = 'text';
                }
                
                // غیرفعال کردن eventهای جلوگیری کننده
                document.onselectstart = null;
                document.oncontextmenu = null;
                document.oncopy = null;
                document.oncut = null;
                
                // فعال کردن design mode
                document.designMode = 'on';
                
                console.log('✅ محافظت‌ها غیرفعال شدند');
                return 'success';
            } catch(e) {
                return 'error: ' + e.message;
            }
        """
        
        result = driver.execute_script(protection_script)
        print(f"🔧 نتیجه اسکریپت: {result}")
        
        # ذخیره صفحه برای بررسی
        driver.save_screenshot("page_screenshot.png")
        print("📸 از صفحه عکس گرفته شد: page_screenshot.png")
        
        print("✅ عملیات کامل شد!")
        print("📋 اگر سایت محتوای قابل کپی دارد، اکنون قابل دسترسی است")
        
    except Exception as e:
        print(f"❌ خطا: {e}")
        print("💡 راه‌حل: ممکن است نیاز به تنظیمات اضافه باشد")
    
    finally:
        try:
            driver.quit()
            print("🔚 مرورگر بسته شد")
        except:
            pass

# اجرای برنامه
if __name__ == "__main__":
    enable_copy()
