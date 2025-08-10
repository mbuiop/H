from flask import Flask, render_template, request, redirect, url_for, flash
import json
import os

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Sample job categories
categories = [
    "خیاط", "نجار", "بنّا", "نقاش", "برقکار", "لوله‌کش", "کارگر ساده",
    "برنامه‌نویس", "طراح گرافیک", "حسابدار", "راننده", "آشپز", "مکانیک",
    "پرستار", "معلم", "فروشنده", "مهندس", "پزشک", "وکیل", "مترجم"
]

# File to store job postings
DATA_FILE = 'jobs.json'

def load_jobs():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"seekers": [], "employers": []}

def save_jobs(jobs):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

# Home page with navigation
@app.route('/')
def index():
    return render_template('index.html')

# Job posting form
@app.route('/post_job', methods=['GET', 'POST'])
def post_job():
    if request.method == 'POST':
        user_type = request.form['user_type']
        category = request.form['category']
        description = request.form['description']
        phone = request.form['phone']
        
        jobs = load_jobs()
        job_entry = {
            'category': category,
            'description': description,
            'phone': phone
        }
        
        if user_type == 'seeker':
            jobs['seekers'].append(job_entry)
            # Notify employers in the same category
            for employer in jobs['employers']:
                if employer['category'] == category:
                    flash(f'کارفرمایی در دسته {category} به دنبال کارگر است. توضیحات: {employer["description"]}', 'employer_notification')
        else:
            jobs['employers'].append(job_entry)
            # Notify seekers in the same category
            for seeker in jobs['seekers']:
                if seeker['category'] == category:
                    flash(f'کارگری در دسته {category} به دنبال کار است. توضیحات: {seeker["description"]}', 'seeker_notification')
        
        save_jobs(jobs)
        flash('آگهی شما با موفقیت ثبت شد!', 'success')
        return redirect(url_for('post_job'))
    
    return render_template('index.html', categories=categories, show_form=True)

# List all job postings
@app.route('/job_list')
def job_list():
    jobs = load_jobs()
    return render_template('index.html', seekers=jobs['seekers'], employers=jobs['employers'], show_list=True)

# Hidden do.html for public message
@app.route('/do')
def do():
    with open('templates/do.html', 'r', encoding='utf-8') as f:
        content = f.read()
    flash(content, 'public_message')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
