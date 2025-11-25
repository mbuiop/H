from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

# لینک سایت مورد نظر
website_url = "https://share.google/kqWvwMZuhdCk2tgAS"

# تنظیمات مرورگر
chrome_options = Options()
chrome_options.add_argument('--disable-blink-features=AutomationControlled')
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', False)

# راه‌اندازی مرورگر
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

print("در حال باز کردن سایت...")
driver.get(website_url)

# صبر برای بارگذاری کامل صفحه
time.sleep(3)

# اجرای کدهای JavaScript برای غیرفعال کردن محدودیت‌های کپی
js_code = """
// غیرفعال کردن منوی کلیک راست
document.addEventListener('contextmenu', function(e) {
    e.stopPropagation();
}, true);

// غیرفعال کردن جلوگیری از انتخاب متن
document.body.style.userSelect = 'auto';
document.body.style.webkitUserSelect = 'auto';
document.body.style.mozUserSelect = 'auto';
document.body.style.msUserSelect = 'auto';

// اعمال به تمام المان‌های صفحه
var allElements = document.getElementsByTagName('*');
for(var i = 0; i < allElements.length; i++) {
    allElements[i].style.userSelect = 'auto';
    allElements[i].style.webkitUserSelect = 'auto';
    allElements[i].style.mozUserSelect = 'auto';
    allElements[i].style.msUserSelect = 'auto';
    
    // حذف event listener های کپی و انتخاب
    allElements[i].oncopy = null;
    allElements[i].oncut = null;
    allElements[i].onselectstart = null;
    allElements[i].onmousedown = null;
}

// غیرفعال کردن محافظت‌های احتمالی دیگر
document.oncopy = null;
document.oncut = null;
document.onselectstart = null;
document.oncontextmenu = null;
document.onmousedown = null;
document.ondragstart = null;

// حذف کلاس‌های احتمالی که مانع کپی می‌شوند
var noSelectClasses = document.querySelectorAll('.no-select, .noselect, .disable-select');
noSelectClasses.forEach(function(el) {
    el.classList.remove('no-select', 'noselect', 'disable-select');
});

console.log('محدودیت کپی غیرفعال شد!');
return 'تمام محدودیت‌ها برداشته شد';
"""

# اجرای کد JavaScript
result = driver.execute_script(js_code)
print(f"✅ {result}")
print("✅ حالا می‌تونی متن‌ها رو انتخاب و کپی کنی!")
print("\n⚠️ برای بستن برنامه، پنجره مرورگر رو ببند یا Ctrl+C بزن")

# نگه داشتن مرورگر باز
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n🔴 برنامه بسته شد")
    driver.quit()
