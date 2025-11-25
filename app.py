#!/usr/bin/env python3
"""
Betfa.com Opener - GitHub Codespace Version
Using requests + BeautifulSoup (No Browser Needed)
"""

import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime

def get_website_content(url):
    """دریافت محتوای سایت با requests"""
    print(f"🌐 در حال دریافت محتوای: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        print(f"✅ وضعیت: {response.status_code}")
        return response.text
        
    except requests.exceptions.RequestException as e:
        print(f"❌ خطا در دریافت سایت: {e}")
        return None

def extract_content(html_content):
    """استخراج محتوا از HTML"""
    print("🔍 در حال استخراج محتوا...")
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # حذف اسکریپت‌ها و استایل‌ها
    for script in soup(["script", "style", "meta", "link"]):
        script.decompose()
    
    # استخراج اطلاعات مهم
    page_data = {
        'title': soup.title.string if soup.title else 'No Title',
        'text_content': soup.get_text(separator='\n', strip=True),
        'links': [a.get('href') for a in soup.find_all('a', href=True)],
        'images': [img.get('src') for img in soup.find_all('img', src=True)]
    }
    
    return page_data

def save_content(page_data, url):
    """ذخیره محتوا در فایل"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # ذخیره متن خالص
    with open(f"betfa_content_{timestamp}.txt", "w", encoding="utf-8") as f:
        f.write(f"URL: {url}\n")
        f.write(f"Title: {page_data['title']}\n")
        f.write(f"Time: {datetime.now()}\n")
        f.write("=" * 50 + "\n")
        f.write(page_data['text_content'])
    
    # ذخیره لینک‌ها
    with open(f"betfa_links_{timestamp}.txt", "w", encoding="utf-8") as f:
        for link in page_data['links']:
            f.write(link + "\n")
    
    # ذخیره اطلاعات JSON
    with open(f"betfa_data_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(page_data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 محتوا ذخیره شد:")
    print(f"   📄 betfa_content_{timestamp}.txt")
    print(f"   🔗 betfa_links_{timestamp}.txt")
    print(f"   📊 betfa_data_{timestamp}.json")

def display_preview(page_data):
    """نمایش پیش‌نمایش محتوا"""
    print("\n" + "=" * 60)
    print("📊 پیش‌نمایش محتوای سایت")
    print("=" * 60)
    
    print(f"📄 عنوان: {page_data['title']}")
    print(f"📏 طول متن: {len(page_data['text_content'])} کاراکتر")
    print(f"🔗 تعداد لینک‌ها: {len(page_data['links'])}")
    print(f"🖼️ تعداد تصاویر: {len(page_data['images'])}")
    
    print("\n📝 بخشی از محتوا:")
    lines = page_data['text_content'].split('\n')
    for line in lines[:20]:  # 20 خط اول
        if line.strip() and len(line.strip()) > 10:
            print(f"   {line[:100]}..." if len(line) > 100 else f"   {line}")
    
    print("\n🔗 لینک‌های مهم:")
    for link in page_data['links'][:10]:  # 10 لینک اول
        if link and not link.startswith(('javascript:', '#')):
            print(f"   {link}")

def main():
    """تابع اصلی"""
    print("🚀 سیستم دریافت محتوای Betfa.com")
    print("🔥 نسخه مخصوص GitHub Codespace")
    print("=" * 50)
    
    # آدرس سایت
    target_url = "https://betfa.com/home/index"
    
    # دریافت محتوا
    html_content = get_website_content(target_url)
    
    if html_content:
        # استخراج محتوا
        page_data = extract_content(html_content)
        
        # نمایش پیش‌نمایش
        display_preview(page_data)
        
        # ذخیره محتوا
        save_content(page_data, target_url)
        
        print("\n🎉 عملیات با موفقیت کامل شد!")
        print("📋 اکنون می‌توانید:")
        print("   • از فایل‌های txt کپی کنید")
        print("   • تمام محتوا را ببینید")
        print("   • لینک‌ها را بررسی کنید")
        print("   • بدون محدودیت کار کنید")
        
    else:
        print("❌ نمی‌توان به سایت دسترسی پیدا کرد")
        print("💡 راهنمایی: ممکن است سایت مسدود کرده باشد")

if __name__ == "__main__":
    main()
