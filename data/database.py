"""
Gestion de la base de données SQLite (locale ou PythonAnywhere)
"""

import sqlite3
import os
import threading
from datetime import datetime
import json

# 🔥 Détection de l'environnement
# Sur PythonAnywhere, on force SQLite
if os.environ.get('PYTHONANYWHERE'):
    USE_SQLITE = True
    print("🔥 Mode SQLite (PythonAnywhere)")
else:
    # Mode local : SQLite par défaut
    USE_SQLITE = True
    print("📁 Mode SQLite (local)")

# Chemin de la base de données
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "market.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

print(f"📁 Base de données : SQLite ({DB_PATH})")

_db_lock = threading.Lock()

def get_connection():
    """Retourne une connexion SQLite."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """Crée les tables SQLite si elles n'existent pas."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()

        # Utilisateurs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        # Trades
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

        # Withdrawals
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

        # Transfers
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

        # Deposit requests
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

        # Payment links
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
        print("✅ Base SQLite initialisée")

# ============================================================
# FONCTIONS UTILISATEURS
# ============================================================

def save_user(user):
    """Sauvegarde un utilisateur."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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

def save_all_users(users_dict):
    """Sauvegarde tous les utilisateurs."""
    for user in users_dict.values():
        save_user(user)

def load_users():
    """Charge tous les utilisateurs."""
    from users.user import User
    from users.portfolio import Portfolio

    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY id")
        rows = cursor.fetchall()
        conn.close()

    users = {}
    max_id = 0
    for row in rows:
        user = User.__new__(User)
        user.user_id = row["id"]
        user.username = row["username"]
        user.password_hash = row["password_hash"]
        user.role = row["role"]
        user.is_bot = bool(row["is_bot"])
        
        portfolio = Portfolio(user.user_id, user.username)
        portfolio.cash = row["cash"]
        portfolio.assets["FIX"] = row["fix_assets"]
        portfolio.blocked_assets["FIX"] = row["fix_blocked"]
        portfolio.blocked_cash = row["cash_blocked"]
        user.portfolio = portfolio

        users[user.username] = user
        if user.user_id > max_id:
            max_id = user.user_id

    return users, max_id

# ============================================================
# FONCTIONS TRADES
# ============================================================

def save_trade(trade):
    """Sauvegarde un trade."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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
        
        # 🔥 Vérifier si la table trades existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
        if not cursor.fetchone():
            # La table n'existe pas, retourner une liste vide
            conn.close()
            return []
        
        if limit:
            cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
        else:
            cursor.execute("SELECT * FROM trades ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()

    trades = []
    for row in rows:
        trades.append(dict(row))
    
    trades.reverse()
    return trades

# ============================================================
# FONCTIONS WITHDRAWALS
# ============================================================

def save_withdrawal(user_id, username, amount, fee, net_amount, address, encoded_data):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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
        cursor.execute("SELECT * FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    withdrawals = []
    for row in rows:
        withdrawals.append(dict(row))
    return withdrawals

def update_withdrawal_status(withdrawal_id, status):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (status, withdrawal_id))
        conn.commit()
        conn.close()

# ============================================================
# FONCTIONS TRANSFERS
# ============================================================

def save_transfer(user_id, username, recipient_username, recipient_address, amount):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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
        cursor.execute("SELECT * FROM transfers WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    transfers = []
    for row in rows:
        transfers.append(dict(row))
    return transfers

def get_received_transfers(user_id, limit=50):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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
# FONCTIONS DÉPÔTS
# ============================================================

def save_deposit_request(user_id, username, full_name, phone, method, amount):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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
        cursor.execute("SELECT * FROM deposit_requests WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    requests = []
    for row in rows:
        requests.append(dict(row))
    return requests

# ============================================================
# FONCTIONS LIENS DE PAIEMENT
# ============================================================

def save_payment_link(link_data):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
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
        cursor.execute("SELECT * FROM payment_links WHERE user_id = ? ORDER BY date DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

    links = []
    for row in rows:
        links.append(dict(row))
    return links

def get_payment_link(link_id):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payment_links WHERE id = ?", (link_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

def update_payment_link_status(link_id, status):
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE payment_links SET status = ? WHERE id = ?", (status, link_id))
        conn.commit()
        conn.close()
