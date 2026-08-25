from datetime import datetime

import logging
import os
import sqlite3
import time
import requests
from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import Application, ContextTypes, InlineQueryHandler

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

request_no = 0

EXCHANGE_API_URL = 'https://api.coinbase.com/v2/exchange-rates?currency=USD'
CACHE_TTL = 3600
TOKEN = os.getenv('TOKEN')
_volume_path = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
DB_PATH = os.getenv('DB_PATH') or (os.path.join(_volume_path, 'stats.db') if _volume_path else 'stats.db')

COIN = '\U0001FA99'
INVALID_QUERY = f'\u26d4 Invalid query, try \'@crcvbot 100 USD BTC\''

CRYPTO = {
	'BTC', 'ETH', 'USDT', 'USDC', 'BNB', 'XRP', 'ADA', 'DOGE', 'SOL', 'LTC',
	'DOT', 'TRX', 'MATIC', 'SHIB', 'AVAX', 'LINK', 'XLM', 'BCH', 'XMR', 'ETC',
	'UNI', 'ATOM', 'FIL', 'APT', 'ARB', 'OP', 'NEAR', 'ALGO', 'VET', 'ICP',
	'HBAR', 'SAND', 'MANA', 'AAVE', 'GRT', 'FTM', 'XTZ', 'EOS', 'CRO', 'MKR',
	'ZEC', 'DASH', 'DAI', 'BUSD',
}

rates_cache: dict = {'rates': None, 'time': 0.0}

os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 0)')
db.commit()


def get_rates() -> dict:
	now = time.time()
	if rates_cache['rates'] is None or now - rates_cache['time'] > CACHE_TTL:
		try:
			response = requests.get(EXCHANGE_API_URL, timeout=10).json()
			rates = response['data']['rates']
			rates.setdefault('USD', '1')
			rates_cache['rates'] = rates
			rates_cache['time'] = now
			log(f'Exchange rates refreshed ({len(rates)} currencies)')
		except Exception as e:
			log(f'Failed to refresh rates: {e}')
			if rates_cache['rates'] is None:
				raise
	return rates_cache['rates']


def record_request(username: str) -> None:
	if not username:
		return
	row = db.execute('SELECT requests FROM users WHERE username = ?', (username,)).fetchone()
	if row is None:
		db.execute('INSERT INTO users (username, requests) VALUES (?, 1)', (username,))
		db.commit()
		total = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
		log(f'New unique user: @{username} | Total unique users: {total}')
	else:
		db.execute('UPDATE users SET requests = requests + 1 WHERE username = ?', (username,))
		db.commit()


def format_amount(value: float) -> str:
	if abs(value) >= 1:
		return f'{value:,.2f}'
	text = f'{value:.8f}'.rstrip('0').rstrip('.')
	return text or '0'


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
	log(f'Error: {context.error}')


async def answer_invalid(update: Update) -> None:
	results = [InlineQueryResultArticle(id='2', title=INVALID_QUERY, input_message_content=InputTextMessageContent(INVALID_QUERY))]
	await update.inline_query.answer(results)


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	global request_no

	query = update.inline_query.query
	user_id = update.inline_query.from_user.id
	username = update.inline_query.from_user.username

	log(f'[#{request_no}] User ID: {user_id} | Username: @{username} | Query: \"{query}\"')
	request_no += 1

	if len(query.split()) != 3:
		await answer_invalid(update)
		return

	try:
		amount, from_currency, to_currency = query.split()
		from_currency = from_currency.upper()
		to_currency = to_currency.upper()
		amount = float(amount)

		rates = get_rates()
		converted_amount = amount * float(rates[to_currency]) / float(rates[from_currency])

		from_currency_emoji = currency_to_emoji(from_currency)
		to_currency_emoji = currency_to_emoji(to_currency)
		message = f'{from_currency_emoji} {format_amount(amount)} {from_currency} \u27A1 {format_amount(converted_amount)} {to_currency} {to_currency_emoji}'
		results = [InlineQueryResultArticle(id='1', title=message, input_message_content=InputTextMessageContent(message))]
		await update.inline_query.answer(results)
		record_request(username)
	except Exception as e:
		log(f'Conversion error for query \"{query}\": {e}')
		await answer_invalid(update)


def currency_to_emoji(currency_code):
	if currency_code in CRYPTO:
		return COIN
	country_code = currency_code[:2]
	flag = ''.join(chr(127397 + ord(letter)) for letter in country_code)
	return flag


def log(str: str) -> None:
	now = datetime.now()
	print(now, " ", str)


if __name__ == '__main__':
	log('Currency Converter bot started!')
	total_users = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
	log(f'Loaded stats for {total_users} unique users')
	application = Application.builder().token(TOKEN).build()
	application.add_handler(InlineQueryHandler(inline_query))
	application.add_error_handler(error_handler)
	application.run_polling(allowed_updates=Update.ALL_TYPES)
	log('Bot is terminated!')
