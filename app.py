from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# فایل‌های ذخیره داده
DATA_FILE = 'jobs.json'
NOTIFICATION_FILE = 'notifications.json'

# دسته‌بندی مشاغل
JOB_CATEGORIES = [
    'خیاط', 'برق‌کار', 'نجار', 'نقاش', 'لوله‌کش', 'تایل‌کار', 'کارگر ساده',
    'راننده', 'آشپز', 'مکانیک', 'تعمیرکار موبایل', 'باغبان', 'خانه‌دار', 
    'فروشنده', 'نگهبان', 'پاکبان', 'بنا', 'تعمیرکار لوازم خانگی', 'آرایشگر', 'دلاک'
]

def load_data():
    """بارگذاری داده‌های ذخیره شده"""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'job_seekers': [], 'employers': []}

def save_data(data):
    """ذخیره داده‌ها"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_notifications():
    """بارگذاری اعلان‌ها"""
    try:
        with open(NOTIFICATION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'job_seeker_notifications': [], 'employer_notifications': []}

def save_notifications(notifications):
    """ذخیره اعلان‌ها"""
    with open(NOTIFICATION_FILE, 'w', encoding='utf-8') as f:
        json.dump(notifications, f, ensure_ascii=False, indent=2)

def clean_old_jobs():
    """پاک کردن آگهی‌های قدیمی (بیش از یک هفته)"""
    data = load_data()
    current_time = datetime.now()
    
    # پاک کردن جویای کار قدیمی
    data['job_seekers'] = [
        job for job in data['job_seekers'] 
        if datetime.strptime(job['date'], '%Y-%m-%d %H:%M:%S') > current_time - timedelta(days=7)
    ]
    
    # پاک کردن کارفرما قدیمی
    data['employers'] = [
        job for job in data['employers'] 
        if datetime.strptime(job['date'], '%Y-%m-%d %H:%M:%S') > current_time - timedelta(days=7)
    ]
    
    save_data(data)

def create_notification(job_type, category, description, phone):
    """ایجاد اعلان جدید"""
    notifications = load_notifications()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if job_type == 'job_seeker':
        # اعلان برای کارفرماها
        notification = {
            'message': f'کارگر جدید در دسته {category}: {description}',
            'phone': phone,
            'category': category,
            'date': timestamp
        }
        notifications['employer_notifications'].append(notification)
    else:
        # اعلان برای جویای کار
        notification = {
            'message': f'کارفرمای جدید در دسته {category}: {description}',
            'phone': phone,
            'category': category,
            'date': timestamp
        }
        notifications['job_seeker_notifications'].append(notification)
    
    save_notifications(notifications)

@app.route('/')
def index():
    """صفحه اصلی"""
    # بررسی پیام همگانی
    global_message = None
    if os.path.exists('templates/do.html'):
        try:
            with open('templates/do.html', 'r', encoding='utf-8') as f:
                global_message = f.read().strip()
            # حذف فایل بعد از نمایش
            os.remove('templates/do.html')
        except:
            pass
    
    # پاک کردن آگهی‌های قدیمی
    clean_old_jobs()
    
    return render_template('index.html', global_message=global_message)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """ثبت آگهی"""
    if request.method == 'POST':
        job_type = request.form['job_type']
        category = request.form['category']
        description = request.form['description']
        phone = request.form['phone']
        
        data = load_data()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        job_entry = {
            'category': category,
            'description': description,
            'phone': phone,
            'date': timestamp
        }
        
        if job_type == 'job_seeker':
            data['job_seekers'].append(job_entry)
        else:
            data['employers'].append(job_entry)
        
        save_data(data)
        create_notification(job_type, category, description, phone)
        
        flash('آگهی شما با موفقیت ثبت شد!', 'success')
        return redirect(url_for('index'))
    
    return render_template('register.html', categories=JOB_CATEGORIES)

@app.route('/jobs')
def jobs():
    """نمایش آگهی‌های موجود"""
    data = load_data()
    search_query = request.args.get('search', '').strip()
    
    job_seekers = data.get('job_seekers', [])
    employers = data.get('employers', [])
    
    # فیلتر کردن بر اساس جستجو
    if search_query:
        job_seekers = [job for job in job_seekers if search_query.lower() in job['category'].lower() or search_query.lower() in job['description'].lower()]
        employers = [job for job in employers if search_query.lower() in job['category'].lower() or search_query.lower() in job['description'].lower()]
    
    return render_template('jobs.html', job_seekers=job_seekers, employers=employers, search_query=search_query)

@app.route('/notifications')
def notifications():
    """نمایش اعلان‌ها"""
    user_type = request.args.get('type', 'job_seeker')
    notifications = load_notifications()
    
    if user_type == 'job_seeker':
        user_notifications = notifications.get('job_seeker_notifications', [])
    else:
        user_notifications = notifications.get('employer_notifications', [])
    
    return render_template('notifications.html', notifications=user_notifications, user_type=user_type)

@app.route('/clear_notifications')
def clear_notifications():
    """پاک کردن اعلان‌ها"""
    user_type = request.args.get('type', 'job_seeker')
    notifications = load_notifications()
    
    if user_type == 'job_seeker':
        notifications['job_seeker_notifications'] = []
    else:
        notifications['employer_notifications'] = []
    
    save_notifications(notifications)
    return redirect(url_for('notifications', type=user_type))

if __name__ == '__main__':
    app.run(debug=True)
