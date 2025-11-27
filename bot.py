"""
TRON Lottery Telegram Bot - Complete Version
"""

import logging
import sqlite3
from typing import Dict, Optional, Tuple
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== CONFIGURATION ====================
class Config:
    # Telegram Bot Token - GET FROM @BotFather
    BOT_TOKEN = "8198774412:AAHphDh2Wo9Nzgomlk9xq9y3aeETsVpkXr0"  # Replace with your token from @BotFather
    
    # TRON API Configuration
    TRONSCAN_API_KEY = "YOUR_TRONSCAN_API_KEY_HERE"
    BUSINESS_TRON_ADDRESS = "YOUR_BUSINESS_TRON_ADDRESS_HERE"
    
    # Bot Settings
    REQUIRED_CONFIRMATIONS = 3
    TICKET_PRICE_USD = 10
    
    # Database
    DATABASE_NAME = "lottery_bot.db"

# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance_usd REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                transaction_hash TEXT UNIQUE,
                amount_usd REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                payment_id INTEGER,
                ticket_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (payment_id) REFERENCES payments (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0], 'username': user[1], 'first_name': user[2],
                'balance_usd': user[3], 'created_at': user[4]
            }
        return None
    
    def create_user(self, user_id: int, username: str, first_name: str):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
            (user_id, username, first_name)
        )
        conn.commit()
        conn.close()
    
    def create_payment(self, user_id: int, transaction_hash: str, amount_usd: float) -> bool:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO payments (user_id, transaction_hash, amount_usd, status) VALUES (?, ?, ?, ?)',
                (user_id, transaction_hash, amount_usd, 'pending')
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def update_payment_status(self, transaction_hash: str, status: str):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE payments SET status = ?, confirmed_at = CURRENT_TIMESTAMP WHERE transaction_hash = ?',
            (status, transaction_hash)
        )
        conn.commit()
        conn.close()
    
    def update_user_balance(self, user_id: int, amount_usd: float):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET balance_usd = balance_usd + ? WHERE user_id = ?',
            (amount_usd, user_id)
        )
        conn.commit()
        conn.close()
    
    def create_lottery_ticket(self, user_id: int, payment_id: int) -> str:
        ticket_number = f"T{user_id}{payment_id}{int(sqlite3.datetime('now').timestamp())}"
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO lottery_tickets (user_id, payment_id, ticket_number) VALUES (?, ?, ?)',
            (user_id, payment_id, ticket_number)
        )
        conn.commit()
        conn.close()
        return ticket_number

# ==================== TRON SERVICE ====================
class TronService:
    def __init__(self, api_key: str, business_address: str):
        self.api_key = api_key
        self.business_address = business_address
        self.base_url = "https://apilist.tronscan.org/api"
    
    def verify_transaction(self, transaction_hash: str) -> Dict:
        try:
            headers = {"TRON-PRO-API-KEY": self.api_key}
            url = f"{self.base_url}/transaction-info?hash={transaction_hash}"
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return {'success': False, 'error': f'API status: {response.status_code}'}
            
            data = response.json()
            
            if data.get('contractRet') != 'SUCCESS':
                return {'success': False, 'error': 'Transaction failed'}
            
            # Check TRX transfers
            if data.get('amount'):
                amount_sun = data['amount']
                to_address = data['toAddress']
                
                if to_address == self.business_address:
                    amount_trx = amount_sun / 1_000_000
                    usd_amount = self._trx_to_usd(amount_trx)
                    
                    return {
                        'success': True,
                        'from_address': data['ownerAddress'],
                        'amount_trx': amount_trx,
                        'amount_usd': usd_amount,
                        'currency': 'TRX',
                        'confirmations': data.get('confirmations', 0)
                    }
            
            # Check TRC20 transfers
            trc20_transfers = data.get('trc20TransferInfo', [])
            for transfer in trc20_transfers:
                if (transfer.get('to_address') == self.business_address and 
                    transfer.get('symbol') == 'USDT'):
                    
                    amount_usdt = int(transfer['amount']) / 1_000_000
                    
                    return {
                        'success': True,
                        'from_address': transfer['from_address'],
                        'amount_usdt': amount_usdt,
                        'amount_usd': amount_usdt,
                        'currency': 'USDT',
                        'confirmations': data.get('confirmations', 0)
                    }
            
            return {'success': False, 'error': 'No valid transfer found'}
            
        except Exception as e:
            return {'success': False, 'error': f'Error: {str(e)}'}
    
    def _trx_to_usd(self, amount_trx: float) -> float:
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd"
            response = requests.get(url, timeout=10)
            data = response.json()
            return amount_trx * data['tron']['usd']
        except:
            return amount_trx * 0.11

# ==================== PAYMENT PROCESSOR ====================
class PaymentProcessor:
    def __init__(self, db_manager: DatabaseManager, tron_service: TronService):
        self.db = db_manager
        self.tron = tron_service
        self.config = Config()
    
    def process_transaction_hash(self, user_id: int, transaction_hash: str) -> Tuple[bool, str]:
        if not self._is_valid_transaction_hash(transaction_hash):
            return False, "❌ Invalid transaction hash format. Must start with 0x and be 66 characters long."
        
        if self._is_duplicate_transaction(transaction_hash):
            return False, "❌ This transaction has already been processed."
        
        verification_result = self.tron.verify_transaction(transaction_hash)
        
        if not verification_result['success']:
            return False, f"❌ Transaction verification failed: {verification_result['error']}"
        
        amount_usd = verification_result.get('amount_usd', 0)
        if amount_usd < self.config.TICKET_PRICE_USD:
            return False, f"❌ Amount too small. Minimum: ${self.config.TICKET_PRICE_USD}"
        
        if not self.db.create_payment(user_id, transaction_hash, amount_usd):
            return False, "❌ Error processing payment"
        
        tickets_count = int(amount_usd / self.config.TICKET_PRICE_USD)
        total_ticket_value = tickets_count * self.config.TICKET_PRICE_USD
        
        self.db.update_user_balance(user_id, total_ticket_value)
        
        payment_id = self._get_payment_id(transaction_hash)
        ticket_numbers = []
        for _ in range(tickets_count):
            ticket_number = self.db.create_lottery_ticket(user_id, payment_id)
            ticket_numbers.append(ticket_number)
        
        self.db.update_payment_status(transaction_hash, 'confirmed')
        
        tickets_list = "\n".join([f"🎫 {ticket}" for ticket in ticket_numbers])
        
        return True, (
            f"✅ Payment confirmed!\n"
            f"💰 Amount: ${amount_usd:.2f}\n"
            f"🎫 Tickets received: {tickets_count}\n"
            f"📝 Transaction: `{transaction_hash}`\n\n"
            f"{tickets_list}\n\n"
            f"🎲 Good luck in the lottery!"
        )
    
    def _is_valid_transaction_hash(self, tx_hash: str) -> bool:
        return tx_hash.startswith('0x') and len(tx_hash) == 66
    
    def _is_duplicate_transaction(self, tx_hash: str) -> bool:
        conn = sqlite3.connect(self.config.DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    def _get_payment_id(self, tx_hash: str) -> int:
        conn = sqlite3.connect(self.config.DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM payments WHERE transaction_hash = ?', (tx_hash,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

# ==================== TELEGRAM BOT ====================
class TronLotteryBot:
    def __init__(self):
        self.config = Config()
        self.db = DatabaseManager(self.config.DATABASE_NAME)
        self.tron = TronService(self.config.TRONSCAN_API_KEY, self.config.BUSINESS_TRON_ADDRESS)
        self.processor = PaymentProcessor(self.db, self.tron)
        
        # Setup logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        self.db.create_user(user.id, user.username, user.first_name)
        
        welcome_text = (
            f"👋 Welcome {user.first_name} to TRON Lottery Bot! 🎰\n\n"
            "💰 How to participate:\n"
            "1. Send USDT (TRC20) or TRX to our address\n"
            "2. Copy the transaction hash\n"
            "3. Send the hash to this bot\n"
            "4. Get lottery tickets automatically!\n\n"
            f"🎫 Each ticket: ${self.config.TICKET_PRICE_USD}\n"
            f"📍 Our TRON address:\n`{self.config.BUSINESS_TRON_ADDRESS}`\n\n"
            "📨 Send your transaction hash to get started!"
        )
        
        keyboard = [
            [KeyboardButton("💰 Check Balance"), KeyboardButton("🎫 My Tickets")],
            [KeyboardButton("📞 Support"), KeyboardButton("ℹ️ Help")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def handle_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle balance check"""
        user = update.effective_user
        user_data = self.db.get_user(user.id)
        
        if not user_data:
            await update.message.reply_text("❌ User not found. Please use /start first.")
            return
        
        tickets_count = self._get_user_tickets_count(user.id)
        
        balance_text = (
            f"👤 Account Summary for {user.first_name}\n"
            f"💰 Balance: ${user_data['balance_usd']:.2f}\n"
            f"🎫 Active Tickets: {tickets_count}\n"
            f"📅 Member since: {user_data['created_at'][:10]}"
        )
        
        await update.message.reply_text(balance_text)
    
    async def handle_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle transaction hash from user"""
        user = update.effective_user
        transaction_hash = update.message.text.strip()
        
        # Show typing action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Process transaction
        success, message = self.processor.process_transaction_hash(user.id, transaction_hash)
        
        await update.message.reply_text(message)
    
    async def handle_tickets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's tickets"""
        user = update.effective_user
        tickets = self._get_user_tickets(user.id)
        
        if not tickets:
            await update.message.reply_text("🎫 You don't have any lottery tickets yet.")
            return
        
        tickets_text = f"🎫 Your Lottery Tickets ({len(tickets)}):\n\n"
        for ticket in tickets:
            tickets_text += f"• {ticket['ticket_number']} - {ticket['created_at'][:10]}\n"
        
        tickets_text += f"\n💰 Total value: ${len(tickets) * self.config.TICKET_PRICE_USD}"
        
        await update.message.reply_text(tickets_text)
    
    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message"""
        help_text = (
            "ℹ️ Bot Help Guide\n\n"
            "🎯 How to buy tickets:\n"
            "1. Send USDT/TRX to our address\n"
            "2. Copy transaction hash from your wallet\n"
            "3. Paste hash here\n\n"
            "📋 Available commands:\n"
            "/start - Start the bot\n"
            "/balance - Check your balance\n"
            "/tickets - View your tickets\n"
            "/help - Show this help\n\n"
            f"📍 Our address: `{self.config.BUSINESS_TRON_ADDRESS}`\n"
            "📞 Support: @YourSupportUsername"
        )
        
        await update.message.reply_text(help_text)
    
    def _get_user_tickets_count(self, user_id: int) -> int:
        conn = sqlite3.connect(self.config.DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    
    def _get_user_tickets(self, user_id: int):
        conn = sqlite3.connect(self.config.DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT ticket_number, created_at FROM lottery_tickets WHERE user_id = ?', (user_id,))
        tickets = cursor.fetchall()
        conn.close()
        
        return [{'ticket_number': t[0], 'created_at': t[1]} for t in tickets]
    
    def run(self):
        """Start the bot"""
        application = Application.builder().token(self.config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("balance", self.handle_balance))
        application.add_handler(CommandHandler("tickets", self.handle_tickets))
        application.add_handler(CommandHandler("help", self.handle_help))
        
        # Handle transaction hashes (any text message that looks like a hash)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_transaction
        ))
        
        # Start the bot
        print("🤖 TRON Lottery Bot is running...")
        application.run_polling()

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    print("🚀 TRON Lottery Telegram Bot")
    print("=" * 50)
    
    # Check if token is set
    if Config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: You need to set your bot token!")
        print("\n📝 How to get bot token:")
        print("1. Search for @BotFather in Telegram")
        print("2. Send /newbot command")
        print("3. Follow instructions to create bot")
        print("4. Copy the token and replace in Config class")
        print(f"\n🔧 Current token: {Config.BOT_TOKEN}")
    else:
        bot = TronLotteryBot()
        bot.run()
