"""
ربات لاتاری TRON - دو زبانه
TRON Lottery Bot - Bilingual
"""

import logging
import sqlite3
import random
import string
from typing import Dict, Optional, Tuple
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== تنظیمات / Configuration ====================
class Config:
    # توکن ربات - از @BotFather بگیرید / Bot token - Get from @BotFather
    BOT_TOKEN = "8198774412:AAHphDh2Wo9Nzgomlk9xq9y3aeETsVpkXr0"
    
    # آدرس کیف پول TRON شما / Your TRON wallet address
    BUSINESS_TRON_ADDRESS = "TAXB65Gnizfuc486FqycEi3F4Eyg1ArPqN"
    
    # API Key از Tronscan / API Key from Tronscan
    TRONSCAN_API_KEY = "کلید_api_خودت_را_اینجا_قرار_ده"
    
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
                'lottery_title': "🎯 **شرکت در لاتاری**",
                'wallet_address': "📍 **آدرس کیف پول TRON:**",
                'copy_address': "📋 آدرس را کپی کنید:",
                'how_to_participate': "📝 **روش شرکت:**",
                'step1': "1. آدرس بالا را کپی کنید",
                'step2': "2. به این آدرس USDT (TRC20) واریز کنید",
                'step3': "3. هش تراکنش را برای ربات بفرستید",
                'step4': "4. بلیط شما به طور خودکار صادر می‌شود",
                'amount_per_ticket': "💰 **مبلغ هر بلیط:** ${price}",
                'verification_time': "⏰ **تأیید تراکنش:** 2-5 دقیقه",
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
                'invalid_hash': "❌ فرمت هش تراکنش نامعتبر است",
                'duplicate_transaction': "❌ این تراکنش قبلاً پردازش شده است",
                'verification_failed': "❌ تأیید تراکنش ناموفق بود: {error}",
                'payment_error': "❌ خطا در ثبت پرداخت",
                'user_not_found': "❌ کاربر یافت نشد",
                'checking_transaction': "🔍 در حال بررسی تراکنش...",
                'transaction_confirmed': "✅ تراکنش تأیید شد!",
                'people': "نفر",
                'english': "🇺🇸 English",
                'persian': "🇮🇷 فارسی"
            },
            'en': {
                'welcome': "👋 Hello {name}!\nWelcome to TRON Lottery Bot 🎰",
                'ticket_price': "💰 Each ticket: ${price}",
                'click_to_participate': "🎯 Click the button below to participate",
                'participate': "🎯 Participate",
                'referral': "📊 Referral",
                'rules': "📜 Rules",
                'lottery_title': "🎯 **Participate in Lottery**",
                'wallet_address': "📍 **TRON Wallet Address:**",
                'copy_address': "📋 Copy address:",
                'how_to_participate': "📝 **How to participate:**",
                'step1': "1. Copy the address above",
                'step2': "2. Send USDT (TRC20) to this address",
                'step3': "3. Send the transaction hash to the bot",
                'step4': "4. Your ticket will be issued automatically",
                'amount_per_ticket': "💰 **Amount per ticket:** ${price}",
                'verification_time': "⏰ **Transaction verification:** 2-5 minutes",
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
                'invalid_hash': "❌ Invalid transaction hash format",
                'duplicate_transaction': "❌ This transaction was already processed",
                'verification_failed': "❌ Transaction verification failed: {error}",
                'payment_error': "❌ Error processing payment",
                'user_not_found': "❌ User not found",
                'checking_transaction': "🔍 Checking transaction...",
                'transaction_confirmed': "✅ Transaction confirmed!",
                'people': "people",
                'english': "🇺🇸 English",
                'persian': "🇮🇷 فارسی"
            }
        }
        
        return texts.get(language, {}).get(key, key)

# ==================== مدیریت دیتابیس / Database Management ====================
class DatabaseManager:
    def __init__(self, db_name: str = "lottery_bot.db"):
        self.db_name = db_name
        self.init_database()
    
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                'balance_usd': user[6], 'tokens': user[7], 'created_at': user[8]
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
            'UPDATE users SET language = ? WHERE user_id = ?',
            (language, user_id)
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

# ==================== سرویس TRON / TRON Service ====================
class TronService:
    def __init__(self):
        self.business_address = Config.BUSINESS_TRON_ADDRESS
        self.api_key = Config.TRONSCAN_API_KEY
        self.base_url = "https://apilist.tronscan.org/api"
    
    def verify_transaction(self, transaction_hash: str) -> Dict:
        """بررسی تراکنش با API واقعی / Verify transaction with real API"""
        try:
            headers = {"TRON-PRO-API-KEY": self.api_key}
            url = f"{self.base_url}/transaction-info?hash={transaction_hash}"
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return {'success': False, 'error': f'API Error: {response.status_code}'}
            
            data = response.json()
            
            # بررسی موفقیت تراکنش / Check transaction success
            if data.get('contractRet') != 'SUCCESS':
                return {'success': False, 'error': 'Transaction failed on blockchain'}
            
            # بررسی انتقال USDT / Check USDT transfer
            trc20_transfers = data.get('trc20TransferInfo', [])
            for transfer in trc20_transfers:
                if (transfer.get('to_address') == self.business_address and 
                    transfer.get('symbol') == 'USDT'):
                    
                    amount_usdt = int(transfer['amount']) / 1_000_000  # USDT has 6 decimals
                    
                    return {
                        'success': True,
                        'from_address': transfer['from_address'],
                        'amount_usdt': amount_usdt,
                        'amount_usd': amount_usdt,
                        'currency': 'USDT',
                        'confirmations': data.get('confirmations', 0)
                    }
            
            return {'success': False, 'error': 'No USDT transfer to business address found'}
            
        except Exception as e:
            return {'success': False, 'error': f'Error: {str(e)}'}

# ==================== پردازشگر پرداخت / Payment Processor ====================
class PaymentProcessor:
    def __init__(self, db_manager: DatabaseManager, tron_service: TronService):
        self.db = db_manager
        self.tron = tron_service
    
    def process_transaction_hash(self, user_id: int, transaction_hash: str, language: str) -> Tuple[bool, str]:
        """پردازش هش تراکنش / Process transaction hash"""
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
        
        # ایجاد بلیط لاتاری / Create lottery ticket
        ticket_number = self.db.create_lottery_ticket(user_id)
        
        # بروزرسانی موجودی کاربر / Update user balance
        self.db.update_user_balance(user_id, amount_usd)
        
        # پیام موفقیت / Success message
        success_message = (
            f"{LanguageManager.get_text(language, 'payment_success')}\n\n"
            f"{LanguageManager.get_text(language, 'amount').format(amount=amount_usd)}\n"
            f"{LanguageManager.get_text(language, 'ticket_number').format(ticket=ticket_number)}\n"
            f"{LanguageManager.get_text(language, 'transaction_hash').format(hash=transaction_hash)}\n\n"
            f"{LanguageManager.get_text(language, 'good_luck')}"
        )
        
        return True, success_message
    
    def _is_valid_transaction_hash(self, tx_hash: str) -> bool:
        """بررسی فرمت هش تراکنش / Validate transaction hash format"""
        tx_hash = tx_hash.strip()
        return (tx_hash.startswith('0x') and len(tx_hash) == 66) or len(tx_hash) == 64
    
    def _is_duplicate_transaction(self, tx_hash: str) -> bool:
        """بررسی تکراری نبودن تراکنش / Check for duplicate transaction"""
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

# ==================== ربات تلگرام / Telegram Bot ====================
class TronLotteryBot:
    def __init__(self):
        self.config = Config()
        self.db = DatabaseManager()
        self.tron = TronService()
        self.processor = PaymentProcessor(self.db, self.tron)
        self.lang = LanguageManager()
        
        # تنظیم لاگ / Setup logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
    
    def get_user_language(self, user_id: int) -> str:
        """دریافت زبان کاربر / Get user language"""
        user = self.db.get_user(user_id)
        return user['language'] if user else 'fa'
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        # بررسی اگر کاربر از طریق لینک رفرال آمده / Check if user came through referral link
        referred_by = None
        if context.args:
            referral_code = context.args[0]
            referred_by = self._get_user_id_by_referral_code(referral_code)
        
        self.db.create_user(user.id, user.username, user.first_name, referred_by)
        
        welcome_text = (
            f"{self.lang.get_text(language, 'welcome').format(name=user.first_name)}\n\n"
            f"{self.lang.get_text(language, 'ticket_price').format(price=self.config.TICKET_PRICE_USD)}\n"
            f"{self.lang.get_text(language, 'click_to_participate')}"
        )
        
        keyboard = [
            [KeyboardButton(self.lang.get_text(language, 'participate')), 
             KeyboardButton(self.lang.get_text(language, 'referral'))],
            [KeyboardButton(self.lang.get_text(language, 'rules')),
             KeyboardButton("🌐 زبان / Language")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def handle_language_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """انتخاب زبان / Language selection"""
        user = update.effective_user
        current_language = self.get_user_language(user.id)
        
        keyboard = [
            [KeyboardButton("🇮🇷 فارسی"), KeyboardButton("🇺🇸 English")],
            [KeyboardButton("🔙 بازگشت / Back")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        text_fa = "🌐 لطفا زبان خود را انتخاب کنید:"
        text_en = "🌐 Please select your language:"
        
        text = text_fa if current_language == 'fa' else text_en
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
            return await self.show_main_menu(update, language=self.get_user_language(user.id))
        
        await self.show_main_menu(update, language)
    
    async def show_main_menu(self, update: Update, language: str):
        """نمایش منوی اصلی / Show main menu"""
        keyboard = [
            [KeyboardButton(self.lang.get_text(language, 'participate')), 
             KeyboardButton(self.lang.get_text(language, 'referral'))],
            [KeyboardButton(self.lang.get_text(language, 'rules')),
             KeyboardButton("🌐 زبان / Language")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_text = (
            f"{self.lang.get_text(language, 'welcome').format(name=update.effective_user.first_name)}\n\n"
            f"{self.lang.get_text(language, 'ticket_price').format(price=self.config.TICKET_PRICE_USD)}"
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def handle_lottery(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شرکت در لاتاری / Participate in lottery"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        
        lottery_text = (
            f"{self.lang.get_text(language, 'lottery_title')}\n\n"
            f"{self.lang.get_text(language, 'wallet_address')}\n"
            f"`{self.config.BUSINESS_TRON_ADDRESS}`\n\n"
            f"{self.lang.get_text(language, 'copy_address')}\n\n"
            f"{self.lang.get_text(language, 'how_to_participate')}\n"
            f"{self.lang.get_text(language, 'step1')}\n"
            f"{self.lang.get_text(language, 'step2')}\n"
            f"{self.lang.get_text(language, 'step3')}\n"
            f"{self.lang.get_text(language, 'step4')}\n\n"
            f"{self.lang.get_text(language, 'amount_per_ticket').format(price=self.config.TICKET_PRICE_USD)}\n"
            f"{self.lang.get_text(language, 'verification_time')}"
        )
        
        await update.message.reply_text(lottery_text)
    
    async def handle_referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """سیستم رفرال / Referral system"""
        user = update.effective_user
        language = self.get_user_language(user.id)
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
    
    async def handle_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش هش تراکنش / Process transaction hash"""
        user = update.effective_user
        language = self.get_user_language(user.id)
        transaction_hash = update.message.text.strip()
        
        # نرمال‌سازی هش تراکنش / Normalize transaction hash
        if len(transaction_hash) == 64 and not transaction_hash.startswith('0x'):
            transaction_hash = '0x' + transaction_hash
        
        # نشان دادن تایپینگ / Show typing action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # اطلاع به کاربر / Notify user
        await update.message.reply_text(self.lang.get_text(language, 'checking_transaction'))
        
        # پردازش تراکنش / Process transaction
        success, message = self.processor.process_transaction_hash(user.id, transaction_hash, language)
        
        await update.message.reply_text(message)
    
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
        
        # هندلرهای دکمه‌ها / Button handlers
        application.add_handler(MessageHandler(filters.Regex("🎯 شرکت در لاتاری|🎯 Participate"), self.handle_lottery))
        application.add_handler(MessageHandler(filters.Regex("📊 رفرال|📊 Referral"), self.handle_referral))
        application.add_handler(MessageHandler(filters.Regex("📜 قوانین|📜 Rules"), self.handle_rules))
        application.add_handler(MessageHandler(filters.Regex("🌐 زبان / Language"), self.handle_language_selection))
        application.add_handler(MessageHandler(filters.Regex("🇮🇷 فارسی|🇺🇸 English"), self.handle_language_change))
        application.add_handler(MessageHandler(filters.Regex("🔙 بازگشت / Back"), self.start))
        
        # هندلر هش تراکنش / Transaction hash handler
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_transaction))
        
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
    else:
        bot = TronLotteryBot()
        bot.run()
