"""
ربات لاتاری TRON - نسخه نهایی پیشرفته
TRON Lottery Bot - Advanced Final Version
"""

import logging
import sqlite3
import random
import string
import json
import csv
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ==================== تنظیمات / Configuration ====================
class Config:
    # توکن ربات - از @BotFather بگیرید / Bot token - Get from @BotFather
    BOT_TOKEN = "8198774412:AAHphDh2Wo9Nzgomlk9xq9y3aeETsVpkXr0"
    
    # آدرس کیف پول TRON شما / Your TRON wallet address (TRX)
    BUSINESS_TRON_ADDRESS = "TAXB65Gnizfuc486FqycEi3F4Eyg1ArPqN"
    
    # API Key از Tronscan / API Key from Tronscan
    TRONSCAN_API_KEY = "کلید_api_خودت_را_اینجا_قرار_ده"
    
    # آیدی ادمین / Admin ID
    ADMIN_IDS = [327855654]  # آیدی عددی خودت را قرار بده
    
    # تنظیمات لاتاری / Lottery settings
    TICKET_PRICE_USD = 10
    REFERRAL_REWARD_TOKENS = 20

# ==================== مدیریت زبان / Language Management ====================
class LanguageManager:
    @staticmethod
    def get_text(language: str, key: str) -> str:
        """متن مورد نظر را بر اساس زبان برمی‌گرداند / Returns text based on language"""
        texts = {
            'fa': {
                'welcome': "👋 سلام {name}!\nبه ربات لاتاری TRON خوش آمدید 🎰",
                'ticket_price': "💰 هر بلیط: ${price}",
                'click_to_participate': "🎯 برای شرکت در لاتاری روی دکمه زیر کلیک کن",
                'participate': "🎯 شرکت در لاتاری",
                'referral': "📊 رفرال",
                'rules': "📜 قوانین",
                'contact_admin': "📞 تماس با ادمین",
                'lottery_title': "🎯 **شرکت در لاتاری**",
                'wallet_address': "📍 **آدرس کیف پول TRON (TRX):**",
                'copy_address': "📋 روی آدرس زیر کلیک کنید تا کپی شود:",
                'how_to_participate': "📝 **روش شرکت:**",
                'step1': "1. آدرس زیر را کپی کنید",
                'step2': "2. به این آدرس TRX واریز کنید",
                'step3': "3. هش تراکنش را برای ربات بفرستید (اختیاری - تأیید خودکار)",
                'step4': "4. بلیط شما به طور خودکار صادر می‌شود",
                'amount_per_ticket': "💰 **مبلغ هر بلیط:** ${price}",
                'verification_time': "⏰ **تأیید تراکنش:** 2-5 دقیقه (خودکار)",
                'referral_system': "📊 **سیستم معرفی دوستان**",
                'your_referral_link': "🔗 **لینک اختصاصی شما:**",
                'referred_users': "👥 **تعداد کاربران معرفی شده:**",
                'reward_per_referral': "🎁 **پاداش هر معرفی:**",
                'tokens_reward': "✅ {tokens} توکن",
                'token_benefit': "💎 **هر توکن = افزایش شانس برنده شدن**",
                'share_link': "📣 لینک خود را برای دوستانتان بفرستید!",
                'rules_title': "📜 **قوانین و مقررات لاتاری**",
                'conditions': "✅ **شرایط شرکت:**",
                'condition1': "• هر کاربر می‌تواند不限次数 شرکت کند",
                'condition2': "• هر بلیط 10 دلار ارزش دارد",
                'condition3': "• حداقل سن: 18 سال",
                'condition4': "• شرکت برای تمامی کشورها آزاد است",
                'how_it_works': "🎯 **نحوه برگزاری:**",
                'how1': "• قرعه‌کشی هر هفته انجام می‌شود",
                'how2': "• نتایج در کانال رسمی اعلام می‌شود",
                'how3': "• برندگان از طریق ربات مطلع می‌شوند",
                'prizes': "💰 **جوایز:**",
                'prize1': "• جایزه اول: 80% از کل جوایز",
                'prize2': "• جایزه دوم: 15% از کل جوایز",
                'prize3': "• جایزه سوم: 5% از کل جوایز",
                'general_rules': "⚖️ **قوانین عمومی:**",
                'rule1': "• هرگونه تقلب منجر به حذف کاربر می‌شود",
                'rule2': "• تصمیم‌گیری نهایی با مدیریت می‌باشد",
                'rule3': "• قوانین قابل تغییر و به‌روزرسانی است",
                'support': "📞 **پشتیبانی:** @PhotoBazaar_Bot",
                'payment_success': "✅ پرداخت شما تأیید شد!",
                'amount': "💰 مبلغ: ${amount}",
                'ticket_number': "🎫 شماره بلیط: {ticket}",
                'transaction_hash': "📝 هش تراکنش: {hash}",
                'good_luck': "🎉 در لاتاری شرکت کردید! شانس موفقیت!",
                'invalid_hash': "❌ **خطا در فرمت هش تراکنش!**\n\n📋 **فرمت صحیح هش:**\n• باید با `0x` شروع شود\n• باید 66 کاراکتر باشد\n• فقط شامل اعداد 0-9 و حروف a-f باشد\n\n📝 **مثال صحیح:**\n`0xa1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456`\n\n💡 **نکته:** اگر هش تراکنش را ندارید، نگران نباشید! پرداخت شما به طور خودکار تأیید خواهد شد.",
                'duplicate_transaction': "❌ این تراکنش قبلاً پردازش شده است",
                'verification_failed': "❌ تأیید تراکنش ناموفق بود: {error}",
                'payment_error': "❌ خطا در ثبت پرداخت",
                'user_not_found': "❌ کاربر یافت نشد",
                'checking_transaction': "🔍 در حال بررسی تراکنش...",
                'transaction_confirmed': "✅ تراکنش تأیید شد!",
                'auto_verification_started': "🔄 سیستم تأیید خودکار فعال شد! پرداخت شما در حال بررسی است...",
                'people': "نفر",
                'english': "🇺🇸 English",
                'persian': "🇮🇷 فارسی",
                'admin_panel': "👨‍💼 پنل ادمین",
                'users_list': "👥 لیست کاربران",
                'pending_transactions': "⏳ تراکنش‌های در انتظار",
                'broadcast_message': "📢 ارسال پیام همگانی",
                'user_stats': "📊 آمار کاربران",
                'export_data': "💾 خروجی داده‌ها",
                'user_messages': "📨 پیام‌های کاربران",
                'back': "🔙 بازگشت",
                'total_users': "👥 تعداد کل کاربران: {count}",
                'active_today': "📈 کاربران فعال امروز: {count}",
                'total_transactions': "💰 مجموع تراکنش‌ها: {count}",
                'user_id': "🆔 آیدی کاربر: {id}",
                'username': "👤 نام کاربری: {username}",
                'join_date': "📅 تاریخ عضویت: {date}",
                'balance': "💰 موجودی: ${balance}",
                'tickets': "🎫 تعداد بلیط‌ها: {count}",
                'send_message_to_user': "✉️ ارسال پیام به کاربر",
                'enter_user_id': "لطفا آیدی کاربر مورد نظر را وارد کنید:",
                'enter_message': "لطفا پیام خود را وارد کنید:",
                'message_sent': "✅ پیام با موفقیت ارسال شد",
                'broadcast_start': "پیام همگانی شما در حال ارسال است...",
                'broadcast_complete': "✅ ارسال پیام همگانی با موفقیت انجام شد\n\nتعداد کاربران: {total}\nموفق: {success}\nناموفق: {failed}",
                'confirm_transaction': "✅ تأیید تراکنش",
                'transaction_details': "جزئیات تراکنش:",
                'manual_approval': "تأیید دستی",
                'transaction_approved': "✅ تراکنش با موفقیت تأیید شد",
                'no_pending_transactions': "✅ هیچ تراکنش در انتظاری وجود ندارد",
                'wallet_address_message': "📍 **آدرس کیف پول TRON شما:**",
                'contact_admin_message': "📞 **تماس با ادمین**\n\nلطفا پیام خود را وارد کنید:",
                'message_to_admin_sent': "✅ پیام شما به ادمین ارسال شد",
                'new_message_from_user': "📨 **پیام جدید از کاربر**\n\n👤 کاربر: {user_info}\n📝 پیام: {message}",
                'reply_to_user': "✉️ پاسخ به کاربر",
                'enter_reply_message': "لطفا پیام پاسخ را وارد کنید:",
                'reply_sent': "✅ پاسخ با موفقیت ارسال شد",
                'no_user_messages': "📭 هیچ پیام جدیدی از کاربران وجود ندارد"
            },
            'en': {
                'welcome': "👋 Hello {name}!\nWelcome to TRON Lottery Bot 🎰",
                'ticket_price': "💰 Each ticket: ${price}",
                'click_to_participate': "🎯 Click the button below to participate",
                'participate': "🎯 Participate",
                'referral': "📊 Referral",
                'rules': "📜 Rules",
                'contact_admin': "📞 Contact Admin",
                'lottery_title': "🎯 **Participate in Lottery**",
                'wallet_address': "📍 **TRON Wallet Address (TRX):**",
                'copy_address': "📋 Click to copy address:",
                'how_to_participate': "📝 **How to participate:**",
                'step1': "1. Copy the address below",
                'step2': "2. Send TRX to this address",
                'step3': "3. Send transaction hash to bot (Optional - Auto verification)",
                'step4': "4. Your ticket will be issued automatically",
                'amount_per_ticket': "💰 **Amount per ticket:** ${price}",
                'verification_time': "⏰ **Transaction verification:** 2-5 minutes (Auto)",
                'referral_system': "📊 **Referral System**",
                'your_referral_link': "🔗 **Your referral link:**",
                'referred_users': "👥 **Referred users:**",
                'reward_per_referral': "🎁 **Reward per referral:**",
                'tokens_reward': "✅ {tokens} tokens",
                'token_benefit': "💎 **Each token = Increased winning chance**",
                'share_link': "📣 Share your link with friends!",
                'rules_title': "📜 **Lottery Rules and Regulations**",
                'conditions': "✅ **Participation conditions:**",
                'condition1': "• Users can participate unlimited times",
                'condition2': "• Each ticket costs $10",
                'condition3': "• Minimum age: 18 years",
                'condition4': "• Open to all countries",
                'how_it_works': "🎯 **How it works:**",
                'how1': "• Draw takes place every week",
                'how2': "• Results announced in official channel",
                'how3': "• Winners notified through the bot",
                'prizes': "💰 **Prizes:**",
                'prize1': "• First prize: 80% of total prizes",
                'prize2': "• Second prize: 15% of total prizes",
                'prize3': "• Third prize: 5% of total prizes",
                'general_rules': "⚖️ **General rules:**",
                'rule1': "• Any cheating leads to user removal",
                'rule2': "• Final decision is with management",
                'rule3': "• Rules are subject to change and update",
                'support': "📞 **Support:** @PhotoBazaar_Bot",
                'payment_success': "✅ Your payment is confirmed!",
                'amount': "💰 Amount: ${amount}",
                'ticket_number': "🎫 Ticket number: {ticket}",
                'transaction_hash': "📝 Transaction hash: {hash}",
                'good_luck': "🎉 You participated in the lottery! Good luck!",
                'invalid_hash': "❌ **Invalid transaction hash format!**\n\n📋 **Correct hash format:**\n• Must start with `0x`\n• Must be 66 characters long\n• Must contain only numbers 0-9 and letters a-f\n\n📝 **Correct example:**\n`0xa1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456`\n\n💡 **Note:** If you don't have transaction hash, don't worry! Your payment will be verified automatically.",
                'duplicate_transaction': "❌ This transaction was already processed",
                'verification_failed': "❌ Transaction verification failed: {error}",
                'payment_error': "❌ Error processing payment",
                'user_not_found': "❌ User not found",
                'checking_transaction': "🔍 Checking transaction...",
                'transaction_confirmed': "✅ Transaction confirmed!",
                'auto_verification_started': "🔄 Auto verification system activated! Your payment is being checked...",
                'people': "people",
                'english': "🇺🇸 English",
                'persian': "🇮🇷 فارسی",
                'admin_panel': "👨‍💼 Admin Panel",
                'users_list': "👥 Users List",
                'pending_transactions': "⏳ Pending Transactions",
                'broadcast_message': "📢 Broadcast Message",
                'user_stats': "📊 User Statistics",
                'export_data': "💾 Export Data",
                'user_messages': "📨 User Messages",
                'back': "🔙 Back",
                'total_users': "👥 Total users: {count}",
                'active_today': "📈 Active today: {count}",
                'total_transactions': "💰 Total transactions: {count}",
                'user_id': "🆔 User ID: {id}",
                'username': "👤 Username: {username}",
                'join_date': "📅 Join date: {date}",
                'balance': "💰 Balance: ${balance}",
                'tickets': "🎫 Tickets: {count}",
                'send_message_to_user': "✉️ Send message to user",
                'enter_user_id': "Please enter the user ID:",
                'enter_message': "Please enter your message:",
                'message_sent': "✅ Message sent successfully",
                'broadcast_start': "Your broadcast message is being sent...",
                'broadcast_complete': "✅ Broadcast completed successfully\n\nTotal users: {total}\nSuccessful: {success}\nFailed: {failed}",
                'confirm_transaction': "✅ Confirm Transaction",
                'transaction_details': "Transaction details:",
                'manual_approval': "Manual approval",
                'transaction_approved': "✅ Transaction approved successfully",
                'no_pending_transactions': "✅ No pending transactions",
                'wallet_address_message': "📍 **Your TRON Wallet Address:**",
                'contact_admin_message': "📞 **Contact Admin**\n\nPlease enter your message:",
                'message_to_admin_sent': "✅ Your message has been sent to admin",
                'new_message_from_user': "📨 **New message from user**\n\n👤 User: {user_info}\n📝 Message: {message}",
                'reply_to_user': "✉️ Reply to user",
                'enter_reply_message': "Please enter your reply message:",
                'reply_sent': "✅ Reply sent successfully",
                'no_user_messages': "📭 No new messages from users"
            }
        }
        
        return texts.get(language, {}).get(key, key)

# ==================== مدیریت دیتابیس / Database Management ====================
class DatabaseManager:
    def __init__(self, db_name: str = "lottery_bot.db"):
        self.db_name = db_name
        self.init_database()
        self.ensure_data_directory()
    
    def ensure_data_directory(self):
        """ایجاد پوشه داده / Create data directory"""
        if not os.path.exists('data'):
            os.makedirs('data')
    
    def init_database(self):
        """ایجاد جداول دیتابیس / Create database tables"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # جدول کاربران / Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language TEXT DEFAULT 'fa',
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                balance_usd REAL DEFAULT 0.0,
                tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول پرداخت‌ها / Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                transaction_hash TEXT UNIQUE,
                amount_usd REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # جدول بلیط‌های لاتاری / Lottery tickets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ticket_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # جدول رفرال‌ها / Referrals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_id) REFERENCES users (user_id)
            )
        ''')
        
        # جدول پیام‌های کاربران / User messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_text TEXT,
                is_from_user BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """دریافت اطلاعات کاربر / Get user information"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0], 'username': user[1], 'first_name': user[2],
                'language': user[3], 'referral_code': user[4], 'referred_by': user[5],
                'balance_usd': user[6], 'tokens': user[7], 'created_at': user[8],
                'last_active': user[9]
            }
        return None
    
    def create_user(self, user_id: int, username: str, first_name: str, referred_by: int = None):
        """ایجاد کاربر جدید / Create new user"""
        referral_code = self.generate_referral_code()
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                '''INSERT OR IGNORE INTO users 
                   (user_id, username, first_name, referral_code, referred_by) 
                   VALUES (?, ?, ?, ?, ?)''',
                (user_id, username, first_name, referral_code, referred_by)
            )
            conn.commit()
            
            # اگر کاربر توسط شخص دیگری معرفی شده باشد / If user was referred by someone
            if referred_by:
                self.add_referral(referred_by, user_id)
                
        except Exception as e:
            logging.error(f"Error creating user: {e}")
        finally:
            conn.close()
    
    def update_user_language(self, user_id: int, language: str):
        """بروزرسانی زبان کاربر / Update user language"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET language = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?',
            (language, user_id)
        )
        conn.commit()
        conn.close()
    
    def update_user_activity(self, user_id: int):
        """بروزرسانی زمان فعالیت کاربر / Update user activity time"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?',
            (user_id,)
        )
        conn.commit()
        conn.close()
    
    def generate_referral_code(self) -> str:
        """تولید کد رفرال منحصر به فرد / Generate unique referral code"""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not self.is_referral_code_exists(code):
                return code
    
    def is_referral_code_exists(self, code: str) -> bool:
        """بررسی وجود کد رفرال / Check if referral code exists"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (code,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    def add_referral(self, referrer_id: int, referred_id: int):
        """ثبت رفرال جدید / Add new referral"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)',
            (referrer_id, referred_id)
        )
        
        # افزودن توکن به کاربر معرف / Add tokens to referrer
        cursor.execute(
            'UPDATE users SET tokens = tokens + ? WHERE user_id = ?',
            (Config.REFERRAL_REWARD_TOKENS, referrer_id)
        )
        
        conn.commit()
        conn.close()
    
    def get_referral_count(self, user_id: int) -> int:
        """تعداد کاربران معرفی شده / Number of referred users"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    
    def create_payment(self, user_id: int, transaction_hash: str, amount_usd: float) -> bool:
        """ثبت پرداخت جدید / Create new payment"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                '''INSERT INTO payments (user_id, transaction_hash, amount_usd, status) 
                   VALUES (?, ?, ?, ?)''',
                (user_id, transaction_hash, amount_usd, 'pending')
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def update_user_balance(self, user_id: int, amount_usd: float):
        """بروزرسانی موجودی کاربر / Update user balance"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?',
            (amount_usd, user_id)
        )
        conn.commit()
        conn.close()
    
    def create_lottery_ticket(self, user_id: int) -> str:
        """ایجاد بلیط لاتاری / Create lottery ticket"""
        ticket_number = f"T{user_id}{int(datetime.now().timestamp())}"
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO lottery_tickets (user_id, ticket_number) VALUES (?, ?)',
            (user_id, ticket_number)
        )
        conn.commit()
        conn.close()
        
        return ticket_number
    
    def get_all_users(self) -> List[Dict]:
        """دریافت تمام کاربران / Get all users"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.user_id, u.username, u.first_name, u.balance_usd, u.created_at, u.last_active,
                   COUNT(DISTINCT lt.id) as ticket_count
            FROM users u
            LEFT JOIN lottery_tickets lt ON u.user_id = lt.user_id
            GROUP BY u.user_id
            ORDER BY u.created_at DESC
        ''')
        users = cursor.fetchall()
        conn.close()
        
        return [{
            'user_id': u[0], 'username': u[1], 'first_name': u[2],
            'balance_usd': u[3], 'created_at': u[4], 'last_active': u[5],
            'ticket_count': u[6]
        } for u in users]
    
    def get_pending_payments(self) -> List[Dict]:
        """دریافت پرداخت‌های در انتظار / Get pending payments"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.*, u.username, u.first_name 
            FROM payments p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at ASC
        ''')
        payments = cursor.fetchall()
        conn.close()
        
        return [{
            'id': p[0], 'user_id': p[1], 'transaction_hash': p[2],
            'amount_usd': p[3], 'status': p[4], 'created_at': p[5],
            'username': p[7], 'first_name': p[8]
        } for p in payments]
    
    def approve_payment(self, payment_id: int):
        """تأیید پرداخت / Approve payment"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # دریافت اطلاعات پرداخت
        cursor.execute('SELECT user_id, amount_usd FROM payments WHERE id = ?', (payment_id,))
        payment = cursor.fetchone()
        
        if payment:
            user_id, amount_usd = payment
            
            # بروزرسانی وضعیت پرداخت
            cursor.execute(
                'UPDATE payments SET status = "confirmed", verified_at = CURRENT_TIMESTAMP WHERE id = ?',
                (payment_id,)
            )
            
            # بروزرسانی موجودی کاربر
            cursor.execute(
                'UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?',
                (amount_usd, user_id)
            )
            
            # ایجاد بلیط
            tickets_count = int(amount_usd / Config.TICKET_PRICE_USD)
            for _ in range(tickets_count):
                self.create_lottery_ticket(user_id)
        
        conn.commit()
        conn.close()
    
    def get_user_stats(self) -> Dict:
        """دریافت آمار کاربران / Get user statistics"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # تعداد کل کاربران
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        # کاربران فعال امروز
        cursor.execute('SELECT COUNT(*) FROM users WHERE date(last_active) = date("now")')
        active_today = cursor.fetchone()[0]
        
        # تعداد کل تراکنش‌ها
        cursor.execute('SELECT COUNT(*) FROM payments WHERE status = "confirmed"')
        total_transactions = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_users': total_users,
            'active_today': active_today,
            'total_transactions': total_transactions
        }
    
    def export_users_to_csv(self):
        """خروجی کاربران به CSV / Export users to CSV"""
        users = self.get_all_users()
        filename = f"data/users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['User ID', 'Username', 'First Name', 'Balance USD', 'Tickets', 'Join Date', 'Last Active'])
            
            for user in users:
                writer.writerow([
                    user['user_id'],
                    user['username'] or '',
                    user['first_name'] or '',
                    user['balance_usd'],
                    user['ticket_count'],
                    user['created_at'],
                    user['last_active']
                ])
        
        return filename
    
    def save_user_message(self, user_id: int, message_text: str, is_from_user: bool = True):
        """ذخیره پیام کاربر / Save user message"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO user_messages (user_id, message_text, is_from_user) VALUES (?, ?, ?)',
            (user_id, message_text, is_from_user)
        )
        
        conn.commit()
        conn.close()
    
    def get_user_messages(self, user_id: int = None) -> List[Dict]:
        """دریافت پیام‌های کاربران / Get user messages"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        if user_id:
            cursor.execute('''
                SELECT um.*, u.username, u.first_name 
                FROM user_messages um
                JOIN users u ON um.user_id = u.user_id
                WHERE um.user_id = ?
                ORDER BY um.created_at DESC
                LIMIT 50
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT um.*, u.username, u.first_name 
                FROM user_messages um
                JOIN users u ON um.user_id = u.user_id
                WHERE um.is_from_user = 1
                ORDER BY um.created_at DESC
                LIMIT 50
            ''')
        
        messages = cursor.fetchall()
        conn.close()
        
        return [{
            'id': m[0], 'user_id': m[1], 'message_text': m[2],
            'is_from_user': m[3], 'created_at': m[4],
            'username': m[5], 'first_name': m[6]
        } for m in messages]

# ==================== سرویس TRON / TRON Service ====================
class TronService:
    def __init__(self):
        self.business_address = Config.BUSINESS_TRON_ADDRESS
        self.api_key = Config.TRONSCAN_API_KEY
        self.base_url = "https://apilist.tronscan.org/api"
    
    def verify_transaction(self, transaction_hash: str) -> Dict:
        """بررسی تراکنش با API واقعی / Verify transaction with real API"""
        try:
            # اعتبارسنجی اولیه فرمت هش
            if not self._validate_hash_format(transaction_hash):
                return {'success': False, 'error': 'Invalid hash format'}
            
            headers = {"TRON-PRO-API-KEY": self.api_key}
            url = f"{self.base_url}/transaction-info?hash={transaction_hash}"
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return {'success': False, 'error': f'API Error: {response.status_code}'}
            
            data = response.json()
            
            # بررسی موفقیت تراکنش / Check transaction success
            if data.get('contractRet') != 'SUCCESS':
                return {'success': False, 'error': 'Transaction failed on blockchain'}
            
            # بررسی انتقال TRX / Check TRX transfer
            if data.get('amount'):
                amount_sun = data['amount']
                to_address = data['toAddress']
                
                if to_address == self.business_address:
                    amount_trx = amount_sun / 1_000_000  # تبدیل از SUN به TRX
                    usd_amount = self._trx_to_usd(amount_trx)
                    
                    return {
                        'success': True,
                        'from_address': data['ownerAddress'],
                        'amount_trx': amount_trx,
                        'amount_usd': usd_amount,
                        'currency': 'TRX',
                        'confirmations': data.get('confirmations', 0)
                    }
            
            return {'success': False, 'error': 'No TRX transfer to business address found'}
            
        except Exception as e:
            return {'success': False, 'error': f'Error: {str(e)}'}
    
    def _validate_hash_format(self, tx_hash: str) -> bool:
        """اعتبارسنجی فرمت هش تراکنش / Validate transaction hash format"""
        if not tx_hash.startswith('0x'):
            return False
        if len(tx_hash) != 66:
            return False
        # بررسی اینکه فقط شامل کاراکترهای هگز باشد
        hex_part = tx_hash[2:]
        if not all(c in '0123456789abcdef' for c in hex_part):
            return False
        return True
    
    def _trx_to_usd(self, amount_trx: float) -> float:
        """تبدیل TRX به USD / Convert TRX to USD"""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd"
            response = requests.get(url, timeout=10)
            data = response.json()
            return amount_trx * data['tron']['usd']
        except:
            return amount_trx * 0.11  # قیمت تقریبی

# ==================== سیستم تأیید خودکار / Auto Verification System ====================
class AutoVerificationSystem:
    def __init__(self, db_manager: DatabaseManager, tron_service: TronService):
        self.db = db_manager
        self.tron = tron_service
        self.is_running = False
    
    async def start_auto_verification(self, application):
        """شروع سیستم تأیید خودکار / Start auto verification system"""
        self.is_running = True
        while self.is_running:
            try:
                await self.check_recent_transactions(application)
                await asyncio.sleep(60)  # هر 1 دقیقه چک کن
            except Exception as e:
                logging.error(f"Auto verification error: {e}")
                await asyncio.sleep(30)
    
    async def check_recent_transactions(self, application):
        """بررسی تراکنش‌های اخیر / Check recent transactions"""
        try:
            # بررسی آدرس کیف پول برای تراکنش‌های جدید
            headers = {"TRON-PRO-API-KEY": self.tron.api_key}
            url = f"{self.tron.base_url}/account/tokens"
            params = {
                'address': self.tron.business_address,
                'limit': 50,
                'start': 0
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                transactions = data.get('token_transfers', [])
                
                for tx in transactions:
                    await self.process_transaction(tx, application)
                    
        except Exception as e:
            logging.error(f"Error checking transactions: {e}")
    
    async def process_transaction(self, tx_data, application):
        """پردازش تراکنش / Process transaction"""
        try:
            transaction_hash = tx_data.get('transaction_id')
            amount = tx_data.get('amount', 0)
            from_address = tx_data.get('from_address')
            
            # اگر تراکنش از قبل پردازش شده، نادیده بگیر
            if self._is_duplicate_transaction(transaction_hash):
                return
            
            # محاسبه مقدار دلاری
            amount_trx = amount / 1_000_000
            amount_usd = self.tron._trx_to_usd(amount_trx)
            
            # یافتن کاربر بر اساس آدرس (در نسخه واقعی باید آدرس کاربران را ذخیره کنید)
            # در این نسخه، فرض می‌کنیم کاربر هش تراکنش را ارسال می‌کند یا سیستم به صورت دستی تأیید می‌کند
            
            logging.info(f"New transaction detected: {transaction_hash} - ${amount_usd}")
            
        except Exception as e:
            logging.error(f"Error processing transaction: {e}")
    
    def _is_duplicate_transaction(self, tx_hash: str) -> bool:
        """بررسی تکراری نبودن تراکنش / Check for duplicate transaction"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

# ==================== پردازشگر پرداخت / Payment Processor ====================
class PaymentProcessor:
    def __init__(self, db_manager: DatabaseManager, tron_service: TronService):
        self.db = db_manager
        self.tron = tron_service
    
    def process_transaction_hash(self, user_id: int, transaction_hash: str, language: str) -> Tuple[bool, str]:
        """پردازش هش تراکنش / Process transaction hash"""
        # نرمال‌سازی هش
        transaction_hash = transaction_hash.strip().lower()
        
        if not self._is_valid_transaction_hash(transaction_hash):
            return False, LanguageManager.get_text(language, 'invalid_hash')
        
        if self._is_duplicate_transaction(transaction_hash):
            return False, LanguageManager.get_text(language, 'duplicate_transaction')
        
        # بررسی تراکنش در بلاکچین / Verify transaction on blockchain
        verification_result = self.tron.verify_transaction(transaction_hash)
        
        if not verification_result['success']:
            error_msg = LanguageManager.get_text(language, 'verification_failed').format(
                error=verification_result['error']
            )
            return False, error_msg
        
        # ثبت پرداخت / Create payment record
        amount_usd = verification_result.get('amount_usd', Config.TICKET_PRICE_USD)
        if not self.db.create_payment(user_id, transaction_hash, amount_usd):
            return False, LanguageManager.get_text(language, 'payment_error')
        
        # تأیید خودکار پرداخت
        payment_id = self._get_payment_id(transaction_hash)
        if payment_id:
            self.db.approve_payment(payment_id)
        
        # ایجاد بلیط لاتاری / Create lottery ticket
        tickets_count = int(amount_usd / Config.TICKET_PRICE_USD)
        ticket_numbers = []
        for _ in range(tickets_count):
            ticket_number = self.db.create_lottery_ticket(user_id)
            ticket_numbers.append(ticket_number)
        
        # پیام موفقیت / Success message
        tickets_list = "\n".join([f"🎫 {ticket}" for ticket in ticket_numbers])
        success_message = (
            f"{LanguageManager.get_text(language, 'payment_success')}\n\n"
            f"{LanguageManager.get_text(language, 'amount').format(amount=amount_usd)}\n"
            f"{LanguageManager.get_text(language, 'ticket_number').format(ticket=ticket_numbers[0])}\n"
            f"{LanguageManager.get_text(language, 'transaction_hash').format(hash=transaction_hash)}\n\n"
            f"{tickets_list}\n\n"
            f"{LanguageManager.get_text(language, 'good_luck')}"
        )
        
        return True, success_message
    
    def _is_valid_transaction_hash(self, tx_hash: str) -> bool:
        """بررسی فرمت هش تراکنش / Validate transaction hash format"""
        return self.tron._validate_hash_format(tx_hash)
    
    def _is_duplicate_transaction(self, tx_hash: str) -> bool:
        """بررسی تکراری نبودن تراکنش / Check for duplicate transaction"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    def _get_payment_id(self, tx_hash: str) -> int:
        """دریافت آیدی پرداخت / Get payment ID"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

# ==================== ربات تلگرام / Telegram Bot ====================
class TronLotteryBot:
    def __init__(self):
        self.config = Config()
        self.db = DatabaseManager()
        self.tron = TronService()
        self.processor = PaymentProcessor(self.db, self.tron)
        self.auto_verification = AutoVerificationSystem(self.db, self.tron)
        self.lang = LanguageManager()
        
        # تنظیم لاگ / Setup logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
    
    def is_admin(self, user_id: int) -> bool:
        """بررسی ادمین بودن کاربر / Check if user is admin"""
        return user_id in self.config.ADMIN_IDS
    
    def get_user_language(self, user_id: int) -> str:
        """دریافت زبان کاربر / Get user language"""
        user = self.db.get_user(user_id)
        return user['language'] if user else 'fa'
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        self.db.update_user_activity(user.id)
        
        # بررسی اگر کاربر از طریق لینک رفرال آمده / Check if user came through referral link
        referred_by = None
        if context.args:
            referral_code = context.args[0]
            referred_by = self._get_user_id_by_referral_code(referral_code)
        
        self.db.create_user(user.id, user.username, user.first_name, referred_by)
        
        await self.show_main_menu(update, language, user)
    
    async def show_main_menu(self, update: Update, language: str, user=None):
        """نمایش منوی اصلی / Show main menu"""
        if user is None:
            user = update.effective_user
        
        welcome_text = (
            f"{self.lang.get_text(language, 'welcome').format(name=user.first_name)}\n\n"
            f"{self.lang.get_text(language, 'ticket_price').format(price=self.config.TICKET_PRICE_USD)}\n"
            f"{self.lang.get_text(language, 'click_to_participate')}"
        )
        
        keyboard = [
            [KeyboardButton(self.lang.get_text(language, 'participate')), 
             KeyboardButton(self.lang.get_text(language, 'referral'))],
            [KeyboardButton(self.lang.get_text(language, 'rules')),
             KeyboardButton(self.lang.get_text(language, 'contact_admin'))],
            [KeyboardButton("🌐 زبان / Language")]
        ]
        
        # افزودن دکمه ادمین برای ادمین‌ها / Add admin button for admins (مخفی)
        if self.is_admin(user.id):
            # دکمه ادمین به صورت مخفی - فقط در صورت نیاز نمایش داده می‌شود
            pass
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def handle_language_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """انتخاب زبان / Language selection"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        keyboard = [
            [KeyboardButton("🇮🇷 فارسی"), KeyboardButton("🇺🇸 English")],
            [KeyboardButton(self.lang.get_text(language, 'back'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        text_fa = "🌐 لطفا زبان خود را انتخاب کنید:"
        text_en = "🌐 Please select your language:"
        
        text = text_fa if language == 'fa' else text_en
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    async def handle_language_change(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تغییر زبان / Change language"""
        user = update.effective_user
        selected_language = update.message.text
        
        if selected_language == "🇮🇷 فارسی":
            self.db.update_user_language(user.id, 'fa')
            language = 'fa'
        elif selected_language == "🇺🇸 English":
            self.db.update_user_language(user.id, 'en')
            language = 'en'
        else:
            return await self.show_main_menu(update, self.get_user_language(user.id))
        
        await self.show_main_menu(update, language)
    
    async def handle_lottery(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شرکت در لاتاری / Participate in lottery"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        self.db.update_user_activity(user.id)
        
        # ارسال آدرس کیف پول به صورت خالص
        await update.message.reply_text(Config.BUSINESS_TRON_ADDRESS)
        
        # سپس راهنما را بفرست
        lottery_text = (
            f"{self.lang.get_text(language, 'lottery_title')}\n\n"
            f"{self.lang.get_text(language, 'copy_address')}\n\n"
            f"{self.lang.get_text(language, 'how_to_participate')}\n"
            f"{self.lang.get_text(language, 'step1')}\n"
            f"{self.lang.get_text(language, 'step2')}\n"
            f"{self.lang.get_text(language, 'step3')}\n"
            f"{self.lang.get_text(language, 'step4')}\n\n"
            f"{self.lang.get_text(language, 'amount_per_ticket').format(price=self.config.TICKET_PRICE_USD)}\n"
            f"{self.lang.get_text(language, 'verification_time')}\n\n"
            f"💡 **تأیید خودکار فعال است!**\n"
            f"پس از واریز، نیازی به ارسال هش تراکنش نیست."
        )
        
        await update.message.reply_text(lottery_text)
    
    async def handle_referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """سیستم رفرال / Referral system"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        self.db.update_user_activity(user.id)
        user_data = self.db.get_user(user.id)
        
        if not user_data:
            await update.message.reply_text(self.lang.get_text(language, 'user_not_found'))
            return
        
        referral_count = self.db.get_referral_count(user.id)
        referral_link = f"https://t.me/PhotoBazaar_Bot?start={user_data['referral_code']}"
        
        referral_text = (
            f"{self.lang.get_text(language, 'referral_system')}\n\n"
            f"{self.lang.get_text(language, 'your_referral_link')}\n"
            f"`{referral_link}`\n\n"
            f"{self.lang.get_text(language, 'referred_users')}\n"
            f"📈 {referral_count} {self.lang.get_text(language, 'people')}\n\n"
            f"{self.lang.get_text(language, 'reward_per_referral')}\n"
            f"{self.lang.get_text(language, 'tokens_reward').format(tokens=self.config.REFERRAL_REWARD_TOKENS)}\n\n"
            f"{self.lang.get_text(language, 'token_benefit')}\n\n"
            f"{self.lang.get_text(language, 'share_link')}"
        )
        
        await update.message.reply_text(referral_text)
    
    async def handle_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قوانین لاتاری / Lottery rules"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        self.db.update_user_activity(user.id)
        
        rules_text = (
            f"{self.lang.get_text(language, 'rules_title')}\n\n"
            f"{self.lang.get_text(language, 'conditions')}\n"
            f"{self.lang.get_text(language, 'condition1')}\n"
            f"{self.lang.get_text(language, 'condition2')}\n"
            f"{self.lang.get_text(language, 'condition3')}\n"
            f"{self.lang.get_text(language, 'condition4')}\n\n"
            f"{self.lang.get_text(language, 'how_it_works')}\n"
            f"{self.lang.get_text(language, 'how1')}\n"
            f"{self.lang.get_text(language, 'how2')}\n"
            f"{self.lang.get_text(language, 'how3')}\n\n"
            f"{self.lang.get_text(language, 'prizes')}\n"
            f"{self.lang.get_text(language, 'prize1')}\n"
            f"{self.lang.get_text(language, 'prize2')}\n"
            f"{self.lang.get_text(language, 'prize3')}\n\n"
            f"{self.lang.get_text(language, 'general_rules')}\n"
            f"{self.lang.get_text(language, 'rule1')}\n"
            f"{self.lang.get_text(language, 'rule2')}\n"
            f"{self.lang.get_text(language, 'rule3')}\n\n"
            f"{self.lang.get_text(language, 'support')}"
        )
        
        await update.message.reply_text(rules_text)
    
    async def handle_contact_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تماس با ادمین / Contact admin"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        self.db.update_user_activity(user.id)
        
        context.user_data['awaiting_admin_message'] = True
        await update.message.reply_text(self.lang.get_text(language, 'contact_admin_message'))
    
    async def handle_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش پیام کاربر به ادمین / Process user message to admin"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        message_text = update.message.text
        
        if 'awaiting_admin_message' in context.user_data and context.user_data['awaiting_admin_message']:
            context.user_data['awaiting_admin_message'] = False
            
            # ذخیره پیام کاربر
            self.db.save_user_message(user.id, message_text, is_from_user=True)
            
            # ارسال پیام به تمام ادمین‌ها
            for admin_id in self.config.ADMIN_IDS:
                try:
                    user_info = f"{user.first_name} (@{user.username})" if user.username else user.first_name
                    admin_message = self.lang.get_text('fa', 'new_message_from_user').format(
                        user_info=user_info,
                        message=message_text
                    )
                    
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message
                    )
                except Exception as e:
                    logging.error(f"Failed to send message to admin {admin_id}: {e}")
            
            await update.message.reply_text(self.lang.get_text(language, 'message_to_admin_sent'))
    
    async def handle_admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستورات ادمین / Admin commands"""
        user = update.effective_user
        
        if not self.is_admin(user.id):
            return
        
        command = update.message.text
        
        if command == "/admin":
            await self.show_admin_panel(update, context)
    
    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش پنل ادمین / Show admin panel"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        keyboard = [
            [KeyboardButton(self.lang.get_text(language, 'users_list')), 
             KeyboardButton(self.lang.get_text(language, 'pending_transactions'))],
            [KeyboardButton(self.lang.get_text(language, 'user_messages')),
             KeyboardButton(self.lang.get_text(language, 'broadcast_message'))],
            [KeyboardButton(self.lang.get_text(language, 'user_stats')),
             KeyboardButton(self.lang.get_text(language, 'export_data'))],
            [KeyboardButton(self.lang.get_text(language, 'back'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text("👨‍💼 پنل مدیریت / Admin Panel", reply_markup=reply_markup)
    
    async def handle_users_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """لیست کاربران / Users list"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        users = self.db.get_all_users()
        
        if not users:
            await update.message.reply_text("📭 هیچ کاربری وجود ندارد")
            return
        
        # ایجاد فایل CSV
        filename = self.db.export_users_to_csv()
        
        # ارسال فایل به ادمین
        with open(filename, 'rb') as file:
            await update.message.reply_document(
                document=file,
                filename=os.path.basename(filename),
                caption=f"📊 لیست کامل کاربران (تعداد: {len(users)} کاربر)\n\n"
                       f"💾 این فایل را برای قرعه‌کشی ذخیره کنید."
            )
    
    async def handle_user_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پیام‌های کاربران / User messages"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        messages = self.db.get_user_messages()
        
        if not messages:
            await update.message.reply_text(self.lang.get_text(language, 'no_user_messages'))
            return
        
        # نمایش 10 پیام آخر
        for i, msg in enumerate(messages[:10]):
            message_text = (
                f"{self.lang.get_text(language, 'new_message_from_user').format(user_info=f'{msg['first_name']} (@{msg['username']})', message=msg['message_text'])}\n\n"
                f"🆔 User ID: {msg['user_id']}\n"
                f"📅 Time: {msg['created_at'][:19]}"
            )
            
            keyboard = [
                [InlineKeyboardButton(
                    self.lang.get_text(language, 'reply_to_user'),
                    callback_data=f"reply_{msg['user_id']}"
                )]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message_text, reply_markup=reply_markup)
    
    async def handle_reply_to_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پاسخ به کاربر / Reply to user"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        target_user_id = int(query.data.split('_')[1])
        context.user_data['replying_to'] = target_user_id
        context.user_data['awaiting_reply'] = True
        
        await query.message.reply_text(self.lang.get_text(language, 'enter_reply_message'))
    
    async def handle_admin_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش پاسخ ادمین / Process admin reply"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        if 'awaiting_reply' in context.user_data and context.user_data['awaiting_reply']:
            target_user_id = context.user_data['replying_to']
            reply_message = update.message.text
            
            # ذخیره پیام ادمین
            self.db.save_user_message(target_user_id, reply_message, is_from_user=False)
            
            try:
                # ارسال پیام به کاربر
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"📨 **پاسخ از مدیریت:**\n\n{reply_message}"
                )
                
                await update.message.reply_text(self.lang.get_text(language, 'reply_sent'))
            except Exception as e:
                await update.message.reply_text(f"❌ خطا در ارسال پاسخ: {e}")
            
            # پاکسازی وضعیت
            context.user_data.pop('awaiting_reply', None)
            context.user_data.pop('replying_to', None)
    
    async def handle_pending_transactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تراکنش‌های در انتظار / Pending transactions"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        payments = self.db.get_pending_payments()
        
        if not payments:
            await update.message.reply_text(self.lang.get_text(language, 'no_pending_transactions'))
            return
        
        for payment in payments:
            keyboard = [
                [InlineKeyboardButton(
                    self.lang.get_text(language, 'confirm_transaction'),
                    callback_data=f"approve_{payment['id']}"
                )]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_text = (
                f"{self.lang.get_text(language, 'transaction_details')}\n\n"
                f"🆔 آیدی: {payment['id']}\n"
                f"👤 کاربر: {payment['first_name']} (@{payment['username']})\n"
                f"💰 مبلغ: ${payment['amount_usd']}\n"
                f"📝 هش: `{payment['transaction_hash']}`\n"
                f"📅 تاریخ: {payment['created_at'][:19]}"
            )
            
            await update.message.reply_text(message_text, reply_markup=reply_markup)
    
    async def handle_approve_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تأیید تراکنش / Approve transaction"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        payment_id = int(query.data.split('_')[1])
        self.db.approve_payment(payment_id)
        
        await query.edit_message_text(self.lang.get_text(language, 'transaction_approved'))
    
    async def handle_user_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """آمار کاربران / User statistics"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        stats = self.db.get_user_stats()
        
        stats_text = (
            f"📊 آمار کاربران\n\n"
            f"{self.lang.get_text(language, 'total_users').format(count=stats['total_users'])}\n"
            f"{self.lang.get_text(language, 'active_today').format(count=stats['active_today'])}\n"
            f"{self.lang.get_text(language, 'total_transactions').format(count=stats['total_transactions'])}"
        )
        
        await update.message.reply_text(stats_text)
    
    async def handle_export_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """خروجی داده‌ها / Export data"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        filename = self.db.export_users_to_csv()
        
        with open(filename, 'rb') as file:
            await update.message.reply_document(
                document=file,
                filename=os.path.basename(filename),
                caption="📊 خروجی داده کاربران / Users data export"
            )
    
    async def handle_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ارسال پیام همگانی / Broadcast message"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        context.user_data['awaiting_broadcast'] = True
        await update.message.reply_text("📢 لطفا پیام همگانی خود را وارد کنید:")
    
    async def handle_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش هش تراکنش / Process transaction hash"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        self.db.update_user_activity(user.id)
        transaction_hash = update.message.text.strip()
        
        # بررسی اگر در حالت انتظار برای پیام همگانی هستیم
        if 'awaiting_broadcast' in context.user_data and context.user_data['awaiting_broadcast']:
            context.user_data['awaiting_broadcast'] = False
            await self.send_broadcast_message(update, context, transaction_hash)
            return
        
        # بررسی اگر در حالت انتظار برای پاسخ به کاربر هستیم
        if 'awaiting_reply' in context.user_data and context.user_data['awaiting_reply']:
            await self.handle_admin_reply(update, context)
            return
        
        # بررسی اگر در حالت انتظار برای پیام به ادمین هستیم
        if 'awaiting_admin_message' in context.user_data and context.user_data['awaiting_admin_message']:
            await self.handle_admin_message(update, context)
            return
        
        # اگر متن یک دستور ادمین است
        if self.is_admin(user.id):
            if transaction_hash == self.lang.get_text(language, 'users_list'):
                await self.handle_users_list(update, context)
                return
            elif transaction_hash == self.lang.get_text(language, 'pending_transactions'):
                await self.handle_pending_transactions(update, context)
                return
            elif transaction_hash == self.lang.get_text(language, 'user_messages'):
                await self.handle_user_messages(update, context)
                return
            elif transaction_hash == self.lang.get_text(language, 'broadcast_message'):
                await self.handle_broadcast_message(update, context)
                return
            elif transaction_hash == self.lang.get_text(language, 'user_stats'):
                await self.handle_user_stats(update, context)
                return
            elif transaction_hash == self.lang.get_text(language, 'export_data'):
                await self.handle_export_data(update, context)
                return
            elif transaction_hash == self.lang.get_text(language, 'back'):
                await self.show_main_menu(update, language, user)
                return
        
        # نرمال‌سازی هش تراکنش / Normalize transaction hash
        transaction_hash = transaction_hash.lower()
        
        # نشان دادن تایپینگ / Show typing action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # اطلاع به کاربر / Notify user
        await update.message.reply_text(self.lang.get_text(language, 'checking_transaction'))
        
        # پردازش تراکنش / Process transaction
        success, message = self.processor.process_transaction_hash(user.id, transaction_hash, language)
        
        await update.message.reply_text(message)
    
    async def send_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
        """ارسال پیام همگانی / Send broadcast message"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        if not self.is_admin(user.id):
            return
        
        users = self.db.get_all_users()
        total = len(users)
        success = 0
        failed = 0
        
        await update.message.reply_text(self.lang.get_text(language, 'broadcast_start'))
        
        for user_data in users:
            try:
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=f"📢 پیام همگانی:\n\n{message}"
                )
                success += 1
            except Exception as e:
                failed += 1
                logging.error(f"Failed to send message to {user_data['user_id']}: {e}")
        
        result_text = self.lang.get_text(language, 'broadcast_complete').format(
            total=total, success=success, failed=failed
        )
        
        await update.message.reply_text(result_text)
    
    def _get_user_id_by_referral_code(self, referral_code: str) -> Optional[int]:
        """یافتن کاربر با کد رفرال / Find user by referral code"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def run(self):
        """اجرای ربات / Run the bot"""
        application = Application.builder().token(self.config.BOT_TOKEN).build()
        
        # افزودن هندلرها / Add handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("admin", self.handle_admin_command))
        application.add_handler(CallbackQueryHandler(self.handle_approve_transaction, pattern="^approve_"))
        application.add_handler(CallbackQueryHandler(self.handle_reply_to_user, pattern="^reply_"))
        
        # هندلرهای دکمه‌ها / Button handlers
        application.add_handler(MessageHandler(filters.Regex("🎯 شرکت در لاتاری|🎯 Participate"), self.handle_lottery))
        application.add_handler(MessageHandler(filters.Regex("📊 رفرال|📊 Referral"), self.handle_referral))
        application.add_handler(MessageHandler(filters.Regex("📜 قوانین|📜 Rules"), self.handle_rules))
        application.add_handler(MessageHandler(filters.Regex("📞 تماس با ادمین|📞 Contact Admin"), self.handle_contact_admin))
        application.add_handler(MessageHandler(filters.Regex("🌐 زبان / Language"), self.handle_language_selection))
        application.add_handler(MessageHandler(filters.Regex("🇮🇷 فارسی|🇺🇸 English"), self.handle_language_change))
        application.add_handler(MessageHandler(filters.Regex("🔙 بازگشت|🔙 Back"), self.start))
        
        # هندلر هش تراکنش / Transaction hash handler
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_transaction))
        
        # شروع سیستم تأیید خودکار
        asyncio.create_task(self.auto_verification.start_auto_verification(application))
        
        # اجرای ربات / Run the bot
        print("🤖 ربات لاتاری TRON در حال اجراست... / TRON Lottery Bot is running...")
        application.run_polling()

# ==================== اجرای اصلی / Main Execution ====================
if __name__ == "__main__":
    print("🚀 ربات لاتاری TRON / TRON Lottery Bot")
    print("=" * 50)
    
    if Config.BOT_TOKEN == "توکن_ربات_خودت_را_اینجا_قرار_ده":
        print("❌ خطا: باید توکن ربات را تنظیم کنید! / Error: You must set bot token!")
        print("\n📝 روش دریافت توکن / How to get token:")
        print("1. در تلگرام @BotFather را پیدا کنید / Find @BotFather in Telegram")
        print("2. دستور /newbot را ارسال کنید / Send /newbot command")
        print("3. نام و یوزرنیم ربات را وارد کنید / Enter bot name and username")
        print("4. توکن را کپی و در خط 14 جایگزین کنید / Copy token and replace in line 14")
        print("\n🔧 همچنین آیدی ادمین را در خط 19 تنظیم کنید / Also set admin ID in line 19")
        print("\n💡 **دستورات ادمین:** /admin")
    else:
        bot = TronLotteryBot()
        bot.run()
