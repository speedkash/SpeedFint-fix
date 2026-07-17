"""
Gestion de la base de données (SQLite local / PostgreSQL Supabase)
"""

import sqlite3
import os
import threading
from datetime import datetime
import json

# 🔥 Détection de l'environnement
USE_SUPABASE = os.environ.get('DATABASE_URL') is not None

if USE_SUPABASE:
    # 🔥 Mode Supabase (PostgreSQL)
    import psycopg2
    import psycopg2.extras
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    # Extraire les infos pour les logs
    print(f"📁 Base de données : Supabase (PostgreSQL)")
    print(f"🔗 URL: {DATABASE_URL[:30]}...")
else:
    # 🔥 Mode local (SQLite)
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(BASE_DIR, "database", "market.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    print(f"📁 Base de données : SQLite ({DB_PATH})")

_db_lock = threading.Lock()


def get_connection():
    """Retourne une connexion à la base de données."""
    if USE_SUPABASE:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def init_db():
    """Crée les tables si elles n'existent pas."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()

        if USE_SUPABASE:
            # PostgreSQL syntax
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    is_bot INTEGER DEFAULT 0,
                    cash REAL DEFAULT 0.0,
                    fix_assets INTEGER DEFAULT 0,
                    fix_blocked INTEGER DEFAULT 0,
                    cash_blocked REAL DEFAULT 0.0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    buyer_id INTEGER,
                    seller_id INTEGER,
                    buyer_name TEXT,
                    seller_name TEXT,
                    price REAL,
                    quantity INTEGER,
                    total REAL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    amount REAL NOT NULL,
                    fee REAL NOT NULL,
                    net_amount REAL NOT NULL,
                    address TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL,
                    encoded_data TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transfers (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    recipient_username TEXT NOT NULL,
                    recipient_address TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'completed',
                    date TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deposit_requests (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    method TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payment_links (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    image TEXT,
                    status TEXT DEFAULT 'active',
                    date TEXT NOT NULL,
                    expires_at TEXT
                )
            """)
        else:
            # SQLite syntax
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    is_bot INTEGER DEFAULT 0,
                    cash REAL DEFAULT 0.0,
                    fix_assets INTEGER DEFAULT 0,
                    fix_blocked INTEGER DEFAULT 0,
                    cash_blocked REAL DEFAULT 0.0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    buyer_id INTEGER,
                    seller_id INTEGER,
                    buyer_name TEXT,
                    seller_name TEXT,
                    price REAL,
                    quantity INTEGER,
                    total REAL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    amount REAL NOT NULL,
                    fee REAL NOT NULL,
                    net_amount REAL NOT NULL,
                    address TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL,
                    encoded_data TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    recipient_username TEXT NOT NULL,
                    recipient_address TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'completed',
                    date TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deposit_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    method TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payment_links (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    image TEXT,
                    status TEXT DEFAULT 'active',
                    date TEXT NOT NULL,
                    expires_at TEXT
                )
            """)

        conn.commit()
        conn.close()
        print("✅ Base de données initialisée")


# ============================================================
#  FONCTIONS UTILISATEURS
# ============================================================

def save_user(user):
    """Sauvegarde un utilisateur."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                INSERT INTO users (id, username, password_hash, role, is_bot, 
                                   cash, fix_assets, fix_blocked, cash_blocked)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role,
                    is_bot = EXCLUDED.is_bot,
                    cash = EXCLUDED.cash,
                    fix_assets = EXCLUDED.fix_assets,
                    fix_blocked = EXCLUDED.fix_blocked,
                    cash_blocked = EXCLUDED.cash_blocked
            """, (
                user.user_id,
                user.username,
                user.password_hash,
                user.role,
                1 if user.is_bot else 0,
                user.portfolio.cash,
                user.portfolio.assets.get("FIX", 0),
                user.portfolio.blocked_assets.get("FIX", 0),
                user.portfolio.blocked_cash
            ))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO users (id, username, password_hash, role, is_bot, 
                                              cash, fix_assets, fix_blocked, cash_blocked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user.user_id,
                user.username,
                user.password_hash,
                user.role,
                1 if user.is_bot else 0,
                user.portfolio.cash,
                user.portfolio.assets.get("FIX", 0),
                user.portfolio.blocked_assets.get("FIX", 0),
                user.portfolio.blocked_cash
            ))
        
        conn.commit()
        conn.close()


def load_users():
    """Charge tous les utilisateurs."""
    from users.user import User
    from users.portfolio import Portfolio

    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        rows = cursor.fetchall()
        conn.close()

    users = {}
    max_id = 0
    for row in rows:
        user = User.__new__(User)
        
        if USE_SUPABASE:
            user.user_id = row[0]
            user.username = row[1]
            user.password_hash = row[2]
            user.role = row[3]
            user.is_bot = bool(row[4])
            cash = row[5]
            fix_assets = row[6]
            fix_blocked = row[7]
            cash_blocked = row[8]
        else:
            user.user_id = row["id"]
            user.username = row["username"]
            user.password_hash = row["password_hash"]
            user.role = row["role"]
            user.is_bot = bool(row["is_bot"])
            cash = row["cash"]
            fix_assets = row["fix_assets"]
            fix_blocked = row["fix_blocked"]
            cash_blocked = row["cash_blocked"]

        portfolio = Portfolio(user.user_id, user.username)
        portfolio.cash = cash
        portfolio.assets["FIX"] = fix_assets
        portfolio.blocked_assets["FIX"] = fix_blocked
        portfolio.blocked_cash = cash_blocked
        user.portfolio = portfolio

        users[user.username] = user
        max_id = max(max_id, user.user_id)

    return users, max_id


# ============================================================
#  FONCTIONS TRADES
# ============================================================

def save_trade(trade):
    """Sauvegarde un trade."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                INSERT INTO trades (timestamp, buyer_id, seller_id, buyer_name, seller_name,
                                   price, quantity, total)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                datetime.now().isoformat(),
                trade.buyer_id,
                trade.seller_id,
                trade.buyer_name,
                trade.seller_name,
                trade.price,
                trade.quantity,
                trade.total
            ))
        else:
            cursor.execute("""
                INSERT INTO trades (timestamp, buyer_id, seller_id, buyer_name, seller_name,
                                   price, quantity, total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                trade.buyer_id,
                trade.seller_id,
                trade.buyer_name,
                trade.seller_name,
                trade.price,
                trade.quantity,
                trade.total
            ))
        
        conn.commit()
        conn.close()


def load_trades(limit=None):
    """Charge l'historique des trades."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if limit:
            cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT %s" if USE_SUPABASE else "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
        else:
            cursor.execute("SELECT * FROM trades ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()

    trades = []
    if USE_SUPABASE:
        for row in rows:
            trades.append({
                "id": row[0],
                "timestamp": row[1],
                "buyer_id": row[2],
                "seller_id": row[3],
                "buyer_name": row[4],
                "seller_name": row[5],
                "price": row[6],
                "quantity": row[7],
                "total": row[8]
            })
    else:
        for row in rows:
            trades.append(dict(row))
    
    trades.reverse()
    return trades


# ============================================================
#  FONCTIONS WITHDRAWALS
# ============================================================

def save_withdrawal(user_id, username, amount, fee, net_amount, address, encoded_data):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                INSERT INTO withdrawals (user_id, username, amount, fee, net_amount, address, status, date, encoded_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id,
                username,
                amount,
                fee,
                net_amount,
                address,
                'pending',
                datetime.now().isoformat(),
                encoded_data
            ))
            withdrawal_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO withdrawals (user_id, username, amount, fee, net_amount, address, status, date, encoded_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                username,
                amount,
                fee,
                net_amount,
                address,
                'pending',
                datetime.now().isoformat(),
                encoded_data
            ))
            withdrawal_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return withdrawal_id


def get_withdrawals(user_id, limit=50):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("SELECT * FROM withdrawals WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    withdrawals = []
    for row in rows:
        if USE_SUPABASE:
            withdrawals.append({
                "id": row[0],
                "user_id": row[1],
                "username": row[2],
                "amount": row[3],
                "fee": row[4],
                "net_amount": row[5],
                "address": row[6],
                "status": row[7],
                "date": row[8],
                "encoded_data": row[9]
            })
        else:
            withdrawals.append(dict(row))
    return withdrawals


def update_withdrawal_status(withdrawal_id, status):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("UPDATE withdrawals SET status = %s WHERE id = %s", (status, withdrawal_id))
        else:
            cursor.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (status, withdrawal_id))
        conn.commit()
        conn.close()


# ============================================================
#  FONCTIONS TRANSFERS
# ============================================================

def save_transfer(user_id, username, recipient_username, recipient_address, amount):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                INSERT INTO transfers (user_id, username, recipient_username, recipient_address, amount, status, date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id,
                username,
                recipient_username,
                recipient_address,
                amount,
                'completed',
                datetime.now().isoformat()
            ))
            transfer_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO transfers (user_id, username, recipient_username, recipient_address, amount, status, date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                username,
                recipient_username,
                recipient_address,
                amount,
                'completed',
                datetime.now().isoformat()
            ))
            transfer_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return transfer_id


def get_transfers(user_id, limit=50):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("SELECT * FROM transfers WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM transfers WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    transfers = []
    for row in rows:
        if USE_SUPABASE:
            transfers.append({
                "id": row[0],
                "user_id": row[1],
                "username": row[2],
                "recipient_username": row[3],
                "recipient_address": row[4],
                "amount": row[5],
                "status": row[6],
                "date": row[7]
            })
        else:
            transfers.append(dict(row))
    return transfers


def get_received_transfers(user_id, limit=50):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                SELECT 
                    t.id, t.user_id, u.username as sender_username,
                    t.recipient_username, t.recipient_address,
                    t.amount, t.status, t.date
                FROM transfers t
                JOIN users u ON u.id = t.user_id
                WHERE t.recipient_username = (SELECT username FROM users WHERE id = %s)
                ORDER BY t.id DESC 
                LIMIT %s
            """, (user_id, limit))
        else:
            cursor.execute("""
                SELECT 
                    t.id, t.user_id, u.username as sender_username,
                    t.recipient_username, t.recipient_address,
                    t.amount, t.status, t.date
                FROM transfers t
                JOIN users u ON u.id = t.user_id
                WHERE t.recipient_username = (SELECT username FROM users WHERE id = ?)
                ORDER BY t.id DESC 
                LIMIT ?
            """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()

        transfers = []
        for row in rows:
            if USE_SUPABASE:
                transfers.append({
                    "id": row[0],
                    "user_id": row[1],
                    "sender_username": row[2],
                    "recipient_username": row[3],
                    "recipient_address": row[4],
                    "amount": row[5],
                    "status": row[6],
                    "date": row[7]
                })
            else:
                transfers.append({
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "sender_username": row["sender_username"],
                    "recipient_username": row["recipient_username"],
                    "recipient_address": row["recipient_address"],
                    "amount": row["amount"],
                    "status": row["status"],
                    "date": row["date"]
                })
    return transfers


# ============================================================
#  FONCTIONS DÉPÔTS
# ============================================================

def save_deposit_request(user_id, username, full_name, phone, method, amount):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                INSERT INTO deposit_requests (user_id, username, full_name, phone, method, amount, status, date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id,
                username,
                full_name,
                phone,
                method,
                amount,
                'pending',
                datetime.now().isoformat()
            ))
            request_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO deposit_requests (user_id, username, full_name, phone, method, amount, status, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                username,
                full_name,
                phone,
                method,
                amount,
                'pending',
                datetime.now().isoformat()
            ))
            request_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return request_id


def get_deposit_requests(user_id, limit=50):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("SELECT * FROM deposit_requests WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM deposit_requests WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    requests = []
    for row in rows:
        if USE_SUPABASE:
            requests.append({
                "id": row[0],
                "user_id": row[1],
                "username": row[2],
                "full_name": row[3],
                "phone": row[4],
                "method": row[5],
                "amount": row[6],
                "status": row[7],
                "date": row[8]
            })
        else:
            requests.append(dict(row))
    return requests


# ============================================================
#  FONCTIONS LIENS DE PAIEMENT
# ============================================================

def save_payment_link(link_data):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        if USE_SUPABASE:
            cursor.execute("""
                INSERT INTO payment_links (id, user_id, username, name, description, amount, image, status, date, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    amount = EXCLUDED.amount,
                    image = EXCLUDED.image,
                    status = EXCLUDED.status,
                    expires_at = EXCLUDED.expires_at
            """, (
                link_data["id"],
                link_data["user_id"],
                link_data["username"],
                link_data["name"],
                link_data["description"],
                link_data["amount"],
                link_data.get("image"),
                link_data.get("status", "active"),
                link_data["date"],
                link_data.get("expires_at")
            ))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO payment_links (id, user_id, username, name, description, amount, image, status, date, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                link_data["id"],
                link_data["user_id"],
                link_data["username"],
                link_data["name"],
                link_data["description"],
                link_data["amount"],
                link_data.get("image"),
                link_data.get("status", "active"),
                link_data["date"],
                link_data.get("expires_at")
            ))
        
        conn.commit()
        conn.close()


def get_payment_links(user_id, limit=50):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("SELECT * FROM payment_links WHERE user_id = %s ORDER BY date DESC LIMIT %s", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM payment_links WHERE user_id = ? ORDER BY date DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    links = []
    for row in rows:
        if USE_SUPABASE:
            links.append({
                "id": row[0],
                "user_id": row[1],
                "username": row[2],
                "name": row[3],
                "description": row[4],
                "amount": row[5],
                "image": row[6],
                "status": row[7],
                "date": row[8],
                "expires_at": row[9]
            })
        else:
            links.append(dict(row))
    return links


def get_payment_link(link_id):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("SELECT * FROM payment_links WHERE id = %s", (link_id,))
        else:
            cursor.execute("SELECT * FROM payment_links WHERE id = ?", (link_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            if USE_SUPABASE:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "username": row[2],
                    "name": row[3],
                    "description": row[4],
                    "amount": row[5],
                    "image": row[6],
                    "status": row[7],
                    "date": row[8],
                    "expires_at": row[9]
                }
            else:
                return dict(row)
        return None


def update_payment_link_status(link_id, status):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if USE_SUPABASE:
            cursor.execute("UPDATE payment_links SET status = %s WHERE id = %s", (status, link_id))
        else:
            cursor.execute("UPDATE payment_links SET status = ? WHERE id = ?", (status, link_id))
        conn.commit()
        conn.close()
