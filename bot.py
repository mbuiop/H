"""
ربات لاتاری TRON
"""

import logging
import sqlite3
import random
import string
from typing import Dict, Optional, Tuple
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== تنظیمات ====================
class Config:
    # توکن ربات - از @BotFather بگیرید
    BOT_TOKEN = "8198774412:AAHphDh2Wo9Nzgomlk9xq9y3aeETsVpkXr0"
    
    # آدرس کیف پول TRON شما
    BUSINESS_TRON_ADDRESS = "TAXB65Gnizfuc486FqycEi3F4Eyg1ArPqN"
    
    # تنظیمات لاتاری
    TICKET_PRICE_USD = 10
    REFERRAL_REWARD_TOKENS = 20

# ==================== مدیریت دیتابیس ====================
class DatabaseManager:
    def __init__(self, db_name: str = "lottery_bot.db"):
        self.db_name = db_name
        self.init_database()
    
    def init_database(self):
        """ایجاد جداول دیتابیس"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # جدول کاربران
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                balance_usd REAL DEFAULT 0.0,
                tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول پرداخت‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                transaction_hash TEXT UNIQUE,
                amount_usd REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # جدول بلیط‌های لاتاری
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ticket_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # جدول رفرال‌ها
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
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """دریافت اطلاعات کاربر"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0], 'username': user[1], 'first_name': user[2],
                'referral_code': user[3], 'referred_by': user[4],
                'balance_usd': user[5], 'tokens': user[6], 'created_at': user[7]
            }
        return None
    
    def create_user(self, user_id: int, username: str, first_name: str, referred_by: int = None):
        """ایجاد کاربر جدید"""
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
            
            # اگر کاربر توسط شخص دیگری معرفی شده باشد
            if referred_by:
                self.add_referral(referred_by, user_id)
                
        except Exception as e:
            logging.error(f"خطا در ایجاد کاربر: {e}")
        finally:
            conn.close()
    
    def generate_referral_code(self) -> str:
        """تولید کد رفرال منحصر به فرد"""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not self.is_referral_code_exists(code):
                return code
    
    def is_referral_code_exists(self, code: str) -> bool:
        """بررسی وجود کد رفرال"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (code,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    def add_referral(self, referrer_id: int, referred_id: int):
        """ثبت رفرال جدید"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)',
            (referrer_id, referred_id)
        )
        
        # افزودن توکن به کاربر معرف
        cursor.execute(
            'UPDATE users SET tokens = tokens + ? WHERE user_id = ?',
            (Config.REFERRAL_REWARD_TOKENS, referrer_id)
        )
        
        conn.commit()
        conn.close()
    
    def get_referral_count(self, user_id: int) -> int:
        """تعداد کاربران معرفی شده"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    
    def create_payment(self, user_id: int, transaction_hash: str, amount_usd: float) -> bool:
        """ثبت پرداخت جدید"""
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
        """بروزرسانی موجودی کاربر"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?',
            (amount_usd, user_id)
        )
        conn.commit()
        conn.close()
    
    def create_lottery_ticket(self, user_id: int) -> str:
        """ایجاد بلیط لاتاری"""
        ticket_number = f"T{user_id}{int(sqlite3.datetime('now').timestamp())}"
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO lottery_tickets (user_id, ticket_number) VALUES (?, ?)',
            (user_id, ticket_number)
        )
        conn.commit()
        conn.close()
        
        return ticket_number

# ==================== سرویس TRON ====================
class TronService:
    def __init__(self):
        self.business_address = Config.BUSINESS_TRON_ADDRESS
    
    def verify_transaction(self, transaction_hash: str) -> Dict:
        """
        بررسی تراکنش TRON
        در این نسخه ساده، فرض می‌کنیم تمام تراکنش‌ها معتبر هستند
        در نسخه واقعی باید از API Tronscan استفاده کنید
        """
        try:
            # شبیه‌سازی تأیید تراکنش
            # در نسخه واقعی، اینجا باید با API بلاکچین ارتباط برقرار کنید
            return {
                'success': True,
                'amount_usd': Config.TICKET_PRICE_USD,
                'confirmations': 10
            }
            
        except Exception as e:
            return {'success': False, 'error': f'خطا: {str(e)}'}

# ==================== پردازشگر پرداخت ====================
class PaymentProcessor:
    def __init__(self, db_manager: DatabaseManager, tron_service: TronService):
        self.db = db_manager
        self.tron = tron_service
    
    def process_transaction_hash(self, user_id: int, transaction_hash: str) -> Tuple[bool, str]:
        """پردازش هش تراکنش"""
        if not self._is_valid_transaction_hash(transaction_hash):
            return False, "❌ فرمت هش تراکنش نامعتبر است"
        
        if self._is_duplicate_transaction(transaction_hash):
            return False, "❌ این تراکنش قبلاً پردازش شده است"
        
        # بررسی تراکنش در بلاکچین
        verification_result = self.tron.verify_transaction(transaction_hash)
        
        if not verification_result['success']:
            return False, f"❌ تأیید تراکنش ناموفق بود: {verification_result['error']}"
        
        # ثبت پرداخت
        amount_usd = verification_result.get('amount_usd', Config.TICKET_PRICE_USD)
        if not self.db.create_payment(user_id, transaction_hash, amount_usd):
            return False, "❌ خطا در ثبت پرداخت"
        
        # ایجاد بلیط لاتاری
        ticket_number = self.db.create_lottery_ticket(user_id)
        
        # بروزرسانی موجودی کاربر
        self.db.update_user_balance(user_id, amount_usd)
        
        return True, (
            f"✅ پرداخت شما تأیید شد!\n\n"
            f"💰 مبلغ: ${amount_usd}\n"
            f"🎫 شماره بلیط: {ticket_number}\n"
            f"📝 هش تراکنش: {transaction_hash}\n\n"
            f"🎉 در لاتاری شرکت کردید! شانس موفقیت!"
        )
    
    def _is_valid_transaction_hash(self, tx_hash: str) -> bool:
        """بررسی فرمت هش تراکنش"""
        tx_hash = tx_hash.strip()
        return (tx_hash.startswith('0x') and len(tx_hash) == 66) or len(tx_hash) == 64
    
    def _is_duplicate_transaction(self, tx_hash: str) -> bool:
        """بررسی تکراری نبودن تراکنش"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

# ==================== ربات تلگرام ====================
class TronLotteryBot:
    def __init__(self):
        self.config = Config()
        self.db = DatabaseManager()
        self.tron = TronService()
        self.processor = PaymentProcessor(self.db, self.tron)
        
        # تنظیم لاگ
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # بررسی اگر کاربر از طریق لینک رفرال آمده
        referred_by = None
        if context.args:
            referral_code = context.args[0]
            referred_by = self._get_user_id_by_referral_code(referral_code)
        
        self.db.create_user(user.id, user.username, user.first_name, referred_by)
        
        welcome_text = (
            f"👋 سلام {user.first_name}!\n"
            f"به ربات لاتاری TRON خوش آمدید 🎰\n\n"
            f"💰 هر بلیط: ${self.config.TICKET_PRICE_USD}\n"
            f"🎯 برای شرکت در لاتاری روی دکمه زیر کلیک کن"
        )
        
        keyboard = [
            [KeyboardButton("🎯 شرکت در لاتاری"), KeyboardButton("📊 رفرال")],
            [KeyboardButton("📜 قوانین")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def handle_lottery(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شرکت در لاتاری"""
        user = update.effective_user
        
        lottery_text = (
            "🎯 **شرکت در لاتاری**\n\n"
            "📍 **آدرس کیف پول TRON:**\n"
            f"`{self.config.BUSINESS_TRON_ADDRESS}`\n\n"
            "📝 **روش شرکت:**\n"
            "1. آدرس بالا را کپی کنید\n"
            "2. به این آدرس USDT (TRC20) واریز کنید\n"
            "3. هش تراکنش را برای ربات بفرستید\n"
            "4. بلیط شما به طور خودکار صادر می‌شود\n\n"
            f"💰 **مبلغ هر بلیط:** ${self.config.TICKET_PRICE_USD}\n"
            "⏰ **تأیید تراکنش:** 2-5 دقیقه"
        )
        
        await update.message.reply_text(lottery_text)
    
    async def handle_referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """سیستم رفرال"""
        user = update.effective_user
        user_data = self.db.get_user(user.id)
        
        if not user_data:
            await update.message.reply_text("❌ کاربر یافت نشد")
            return
        
        referral_count = self.db.get_referral_count(user.id)
        referral_link = f"https://t.me/PhotoBazaar_Bot?start={user_data['referral_code']}"
        
        referral_text = (
            "📊 **سیستم معرفی دوستان**\n\n"
            "🔗 **لینک اختصاصی شما:**\n"
            f"`{referral_link}`\n\n"
            "👥 **تعداد کاربران معرفی شده:**\n"
            f"📈 {referral_count} نفر\n\n"
            "🎁 **پاداش هر معرفی:**\n"
            f"✅ {self.config.REFERRAL_REWARD_TOKENS} توکن\n\n"
            "💎 **هر توکن = افزایش شانس برنده شدن**\n\n"
            "📣 لینک خود را برای دوستانتان بفرستید!"
        )
        
        await update.message.reply_text(referral_text)
    
    async def handle_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قوانین لاتاری"""
        rules_text = (
            "📜 **قوانین و مقررات لاتاری**\n\n"
            "✅ **شرایط شرکت:**\n"
            "• هر کاربر می‌تواند不限次数 شرکت کند\n"
            "• هر بلیط 10 دلار ارزش دارد\n"
            "• حداقل سن: 18 سال\n"
            "• شرکت برای تمامی کشورها آزاد است\n\n"
            "🎯 **نحوه برگزاری:**\n"
            "• قرعه‌کشی هر هفته انجام می‌شود\n"
            "• نتایج در کانال رسمی اعلام می‌شود\n"
            "• برندگان از طریق ربات مطلع می‌شوند\n\n"
            "💰 **جوایز:**\n"
            "• جایزه اول: 80% از کل جوایز\n"
            "• جایزه دوم: 15% از کل جوایز\n"
            "• جایزه سوم: 5% از کل جوایز\n\n"
            "⚖️ **قوانین عمومی:**\n"
            "• هرگونه تقلب منجر به حذف کاربر می‌شود\n"
            "• تصمیم‌گیری نهایی با مدیریت می‌باشد\n"
            "• قوانین قابل تغییر و به‌روزرسانی است\n\n"
            "📞 **پشتیبانی:** @PhotoBazaar_Bot"
        )
        
        await update.message.reply_text(rules_text)
    
    async def handle_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش هش تراکنش"""
        user = update.effective_user
        transaction_hash = update.message.text.strip()
        
        # نرمال‌سازی هش تراکنش
        if len(transaction_hash) == 64 and not transaction_hash.startswith('0x'):
            transaction_hash = '0x' + transaction_hash
        
        # نشان دادن تایپینگ
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # پردازش تراکنش
        success, message = self.processor.process_transaction_hash(user.id, transaction_hash)
        
        await update.message.reply_text(message)
    
    def _get_user_id_by_referral_code(self, referral_code: str) -> Optional[int]:
        """یافتن کاربر با کد رفرال"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def run(self):
        """اجرای ربات"""
        application = Application.builder().token(self.config.BOT_TOKEN).build()
        
        # افزودن هندلرها
        application.add_handler(CommandHandler("start", self.start))
        
        # هندلرهای دکمه‌ها
        application.add_handler(MessageHandler(filters.Regex("🎯 شرکت در لاتاری"), self.handle_lottery))
        application.add_handler(MessageHandler(filters.Regex("📊 رفرال"), self.handle_referral))
        application.add_handler(MessageHandler(filters.Regex("📜 قوانین"), self.handle_rules))
        
        # هندلر هش تراکنش
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_transaction))
        
        # اجرای ربات
        print("🤖 ربات لاتاری TRON در حال اجراست...")
        application.run_polling()

# ==================== اجرای اصلی ====================
if __name__ == "__main__":
    print("🚀 ربات لاتاری TRON")
    print("=" * 40)
    
    if Config.BOT_TOKEN == "توکن_ربات_خودت_را_اینجا_قرار_ده":
        print("❌ خطا: باید توکن ربات را تنظیم کنید!")
        print("\n📝 روش دریافت توکن:")
        print("1. در تلگرام @BotFather را پیدا کنید")
        print("2. دستور /newbot را ارسال کنید")
        print("3. نام و یوزرنیم ربات را وارد کنید")
        print("4. توکن را کپی و در خط 14 جایگزین کنید")
    else:
        bot = TronLotteryBot()
        bot.run()
