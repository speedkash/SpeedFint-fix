"""
Point d'entrée principal du marché FIX.
Initialise le marché, les comptes, les bots, et lance Flask + WebSocket.
"""

import time  # Ajoute cette ligne avec les autres imports
import threading
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit
from data.database import init_db, save_user, save_all_users, load_users, save_trade, load_trades, get_connection

from core import (
    Order, OrderSide, OrderType, OrderStatus,
    OrderBook, MatchingEngine, Trade,
    InvalidOrderError, OrderNotFoundError,
    InsufficientFundsError, InsufficientAssetsError,
    UserNotFoundError, AuthenticationError,
    UsernameAlreadyExistsError
)
from users import User, MarketMakerBot
from utils import (
    SYMBOL, INITIAL_PRICE, MIN_ORDER_SIZE, MAX_ORDER_SIZE,
    FEE_RATE, FEE_ACCOUNT, BOT_SPREAD_PCT, BOT_INTERVAL_SECONDS,
    BOT_MIN_QTY, BOT_MAX_QTY, INITIAL_ALLOCATION,
    HOST, PORT, DEBUG, SECRET_KEY, BOOK_DEPTH, DEFAULT_USER_CASH,
    ADMIN_USERNAME, ADMIN_PASSWORD,
    validate_order_params, validate_registration, validate_add_cash,
    log_trade, log_order, log_cancel, log_error
)

# ------------------------------------------------------------------
# Initialisation Flask
# ------------------------------------------------------------------
import os

# Chemin absolu du dossier frontend/static
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'frontend', 'static')
TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'frontend', 'templates')

app = Flask(__name__, 
            static_folder=STATIC_FOLDER, 
            static_url_path='/static',
            template_folder=TEMPLATE_FOLDER)
app.config["SECRET_KEY"] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")

# ------------------------------------------------------------------
# État global du marché
# ------------------------------------------------------------------
users: dict = {}           # username → User
users_by_id: dict = {}     # user_id → User
order_book = OrderBook(SYMBOL)
engine = MatchingEngine(order_book)
bots: list = []
admin_user: User = None
next_user_id = 1

random_bots: dict = {}

# ------------------------------------------------------------------
# Callbacks du moteur
# ------------------------------------------------------------------

def on_trade_callback(trade: Trade):
    """Appelé à chaque trade : log + WebSocket + règlement."""
    log_trade(trade.buyer_name, trade.seller_name,
              trade.price, trade.quantity, trade.total)

    fee_per_party = round(trade.total * FEE_RATE, 6)

    # Règlement acheteur
    buyer = users_by_id.get(trade.buyer_id)
    if buyer:
        # Vérification stricte avant d'appliquer
        total_with_fee = trade.total + fee_per_party
        if buyer.portfolio.cash < total_with_fee:
            log_error(f"Trade annulé : {buyer.username} cash insuffisant "
                      f"({buyer.portfolio.cash:.4f} < {total_with_fee:.4f})")
            return  # Ne pas exécuter ce trade
        buyer.portfolio.apply_buy(trade.price, trade.quantity, fee_per_party)

    # Règlement vendeur
    seller = users_by_id.get(trade.seller_id)
    if seller:
        if seller.portfolio.assets.get("FIX", 0) < trade.quantity:
            log_error(f"Trade annulé : {seller.username} FIX insuffisants")
            return
        seller.portfolio.apply_sell(trade.price, trade.quantity, fee_per_party)

# DEBUG
    print(f"[DEBUG TRADE] SELLER {seller.username} - assets après apply_sell: {seller.portfolio.assets.get('FIX', 0)}")

# Frais → compte réserve
    reserve_user = users.get("reserve")
    if reserve_user:
        reserve_user.portfolio.cash += fee_per_party * 2

    # Sauvegarder le trade
    save_trade(trade)

# Sauvegarder tous les utilisateurs tous les 10 trades
    if len(engine.trades) % 10 == 0:
        save_all_users(users)

    # WebSocket
    socketio.emit("trade", trade.to_dict())
    socketio.emit("book_update", get_market_data())

def on_order_filled_callback(order: Order):
    """Appelé quand un ordre est entièrement exécuté."""
    # Déblocage des fonds restants si nécessaire
    user = users_by_id.get(order.user_id)
    if not user:
        return

    if order.side == OrderSide.BUY:
        # Débloquer le cash restant (prix * quantité restante + frais)
        pass  # Géré par apply_buy
    else:
        # Débloquer les actifs restants
        pass  # Géré par apply_sell


def on_funds_check_callback(order: Order, opposite: Order,
                            price: float, qty: int):
    """
    Vérifie que LES DEUX parties (ordre entrant ET ordre opposé)
    ont les fonds nécessaires avant d'exécuter le trade.
    """
    # --- Vérifier l'ordre OPPOSÉ (celui qui était dans le carnet) ---
    opp_user = users_by_id.get(opposite.user_id)
    if not opp_user:
        raise Exception("Utilisateur opposé introuvable")

    if opposite.side == OrderSide.SELL:
        if opp_user.portfolio.assets.get("FIX", 0) < qty:
            raise InsufficientAssetsError(
                f"{opp_user.username} n'a plus assez de FIX"
            )
    else:
        fee = round(price * qty * FEE_RATE, 6)
        if opp_user.portfolio.cash < (price * qty + fee):
            raise InsufficientFundsError(
                f"{opp_user.username} n'a plus assez de cash"
            )

    # --- Vérifier l'ordre ENTRANT (celui qu'on est en train de traiter) ---
    entrant_user = users_by_id.get(order.user_id)
    if not entrant_user:
        raise Exception("Utilisateur entrant introuvable")

    if order.side == OrderSide.SELL:
        if entrant_user.portfolio.assets.get("FIX", 0) < qty:
            raise InsufficientAssetsError(
                f"{entrant_user.username} n'a plus assez de FIX"
            )
    else:
        fee = round(price * qty * FEE_RATE, 6)
        if entrant_user.portfolio.cash < (price * qty + fee):
            raise InsufficientFundsError(
                f"{entrant_user.username} n'a plus assez de cash"
            )


# Injection des callbacks
engine.on_trade = on_trade_callback
engine.on_order_filled = on_order_filled_callback
engine.on_funds_check = on_funds_check_callback

# ------------------------------------------------------------------
# Fonctions utilitaires
# ------------------------------------------------------------------

def get_market_data() -> dict:
    """Retourne toutes les données publiques du marché."""
    # 🔥 Récupérer les trades depuis la DB
    db_trades = load_trades(20)
    
    recent_trades = []
    for t in db_trades:
        recent_trades.append({
            "timestamp": t["timestamp"],
            "price": t["price"],
            "quantity": t["quantity"],
            "total": t["total"],
            "buyer": t["buyer_name"],
            "seller": t["seller_name"],
            "buyer_id": t["buyer_id"],
            "seller_id": t["seller_id"]
        })
    
    return {
        "symbol": SYMBOL,
        "last_price": engine.get_last_price() or INITIAL_PRICE,
        "book": order_book.get_book_snapshot(BOOK_DEPTH),
        "recent_trades": recent_trades,  # ← Depuis la DB
        "best_bid": order_book.best_bid,
        "best_ask": order_book.best_ask,
        "spread": order_book.spread
    }

def get_current_user() -> User:
    """Récupère l'utilisateur connecté depuis la session."""
    username = session.get("username")
    if not username:
        raise AuthenticationError("Non connecté")
    user = users.get(username)
    if not user:
        raise UserNotFoundError(f"Utilisateur {username} introuvable")
    return user


def get_user_by_id(user_id: int) -> User:
    """Récupère un utilisateur par son ID."""
    user = users_by_id.get(user_id)
    if not user:
        raise UserNotFoundError(f"Utilisateur ID {user_id} introuvable")
    return user


def cancel_all_user_orders(user_id: int):
    """Annule tous les ordres en attente d'un utilisateur."""
    orders_to_cancel = []
    for o in list(order_book.bids) + list(order_book.asks):
        if o.user_id == user_id and o.is_active:
            orders_to_cancel.append(o)

    user = users_by_id.get(user_id)
    is_bot = user.is_bot if user else False

    for order in orders_to_cancel:
        try:
            # Ne PAS débloquer les fonds pour les bots
            # Leurs ordres sont gérés par place_order_internal qui nettoie tout
            if not is_bot:
                user = users_by_id.get(order.user_id)
                if user:
                    if order.side == OrderSide.BUY and order.order_type == OrderType.LIMIT:
                        price = order.price if order.price else (engine.get_last_price() or 0.001)
                        fee = round(price * order.remaining_qty * FEE_RATE, 6)
                        user.portfolio.release_funds_for_buy(price, order.remaining_qty, fee)
                    elif order.side == OrderSide.SELL:
                        user.portfolio.release_assets_for_sell(SYMBOL, order.remaining_qty)

            # Annuler l'ordre dans le carnet
            order_book.cancel_order(order.order_id)

        except Exception as e:
            log_error(f"Erreur annulation ordre {order.order_id[:8]}: {e}")

# ------------------------------------------------------------------
# Initialisation du système
# ------------------------------------------------------------------

def init_system():
    """Initialise le système : charge depuis la DB ou crée les comptes par défaut."""
    global admin_user, next_user_id, bots, users, users_by_id

    init_db()

    # 🔥 FORCER le rechargement depuis la DB à chaque démarrage
    loaded_users, loaded_max_id = load_users()

    if loaded_users and "admin" in loaded_users:
        # Restaurer depuis la DB
        users.clear()
        users_by_id.clear()
        users.update(loaded_users)
        for u in users.values():
            users_by_id[u.user_id] = u
        next_user_id = loaded_max_id + 1
        admin_user = users.get("admin")
        print(f"[INIT] {len(users)} comptes chargés depuis la DB")
    else:
        # Première initialisation (création des comptes)
        print("[INIT] Aucun compte trouvé, création...")
        admin_user = User(ADMIN_USERNAME, ADMIN_PASSWORD, role="admin", user_id=1)
        users[ADMIN_USERNAME] = admin_user
        users_by_id[admin_user.user_id] = admin_user
        next_user_id = 2

        # Créer bots
        for i in range(1, 3):
            bot_name = f"bot_{i}"
            bot_user = User(bot_name, f"bot{i}_pass", role="user", is_bot=True, user_id=next_user_id)
            users[bot_name] = bot_user
            users_by_id[bot_user.user_id] = bot_user
            next_user_id += 1

        # Créer réserve
        reserve_user = User("reserve", "reserve_pass", role="user", user_id=next_user_id)
        users["reserve"] = reserve_user
        users_by_id[reserve_user.user_id] = reserve_user
        next_user_id += 1

        # Allocations initiales
        for name, alloc in INITIAL_ALLOCATION.items():
            u = users.get(name)
            if u:
                u.portfolio.add_assets(SYMBOL, alloc.get("FIX", 0))
                u.portfolio.add_cash(alloc.get("USD", 0.0))

        # Sauvegarder
        save_all_users(users)
        print(f"[INIT] {len(users)} comptes créés")

    # Restaurer le dernier prix
    db_trades = load_trades()
    if db_trades:
        last_price = db_trades[-1]["price"]
        engine._last_price = last_price
        print(f"[INIT] Dernier prix restauré : {last_price:.6f} $")

    # Démarrer les bots
    for i in range(1, 3):
        bot_name = f"bot_{i}"
        bot_user = users.get(bot_name)
        if bot_user:
            bot = MarketMakerBot(
                user=bot_user,
                spread_pct=BOT_SPREAD_PCT,
                interval_seconds=BOT_INTERVAL_SECONDS,
                min_qty=BOT_MIN_QTY,
                max_qty=BOT_MAX_QTY
            )
            bot.get_last_price = engine.get_last_price
            bot.place_order = place_order_internal
            bot.cancel_all_orders = cancel_all_user_orders
            bots.append(bot)
            bot.start()

    print(f"[INIT] {len(users)} comptes, {len(bots)} bots actifs")


def place_order_internal(user_id: int, username: str,
                         side: OrderSide, order_type: OrderType,
                         quantity: int, price: float = None) -> dict:
    """
    Place un ordre directement (utilisé par les bots).
    """
    try:
        user = users_by_id.get(user_id)
        if not user:
            return {"success": False, "error": "Utilisateur introuvable"}

        # --- Vérification de solvabilité AVANT ---
        if side == OrderSide.BUY:
            if order_type == OrderType.LIMIT and price:
                fee = round(price * quantity * FEE_RATE, 6)
                total_needed = price * quantity + fee
                if user.portfolio.available_cash < total_needed:
                    raise InsufficientFundsError(
                        f"{user.username} : besoin de {total_needed:.4f} $, "
                        f"disponible : {user.portfolio.available_cash:.4f} $"
                    )
                user.portfolio.block_funds_for_buy(price, quantity, fee)
            else:
                if user.portfolio.available_cash <= 0:
                    raise InsufficientFundsError(
                        f"{user.username} : pas de cash disponible"
                    )
        else:
            if user.portfolio.available_asset(SYMBOL) < quantity:
                raise InsufficientAssetsError(
                    f"{user.username} : besoin de {quantity} FIX, "
                    f"disponible : {user.portfolio.available_asset(SYMBOL)}"
                )
            user.portfolio.block_assets_for_sell(SYMBOL, quantity)

        # Créer l'ordre
        order = Order(
            user_id=user_id,
            username=username,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

        log_order(username, side.value, order_type.value, quantity, price)

        # Traiter via le moteur
        trades = engine.process_order(order)

        # --- Nettoyage des blocages après exécution ---
        if side == OrderSide.BUY:
            # BUY : libérer le blocage cash
            user.portfolio.blocked_cash = 0.0
        else:
            # SELL : libérer le blocage FIX sans toucher aux assets
            user.portfolio.blocked_assets["FIX"] = 0

        return {
            "success": True,
            "order": order.to_dict(),
            "trades": [t.to_dict() for t in trades]
        }

    except (InsufficientFundsError, InsufficientAssetsError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        log_error(str(e))
        return {"success": False, "error": str(e)}

# ------------------------------------------------------------------
# Routes API - Authentification
# ------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def api_register():
    """Création de compte."""
    global next_user_id
    data = request.json or {}

    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    valid, msg = validate_registration(username, password)
    if not valid:
        return jsonify({"success": False, "error": msg}), 400

    if username in users:
        return jsonify({"success": False, "error": "Nom d'utilisateur déjà pris"}), 400

    # Créer l'utilisateur
    user = User(username, password, role="user", user_id=next_user_id)
    user.portfolio.add_cash(DEFAULT_USER_CASH)
    users[username] = user
    users_by_id[user.user_id] = user
    next_user_id += 1

    save_user(user)

    print(f"[REGISTER] Nouvel utilisateur : {username} (ID: {user.user_id})")
    return jsonify({
        "success": True,
        "message": "Compte créé avec succès",
        "user": user.to_dict()
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    """Connexion."""
    data = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    user = users.get(username)
    if not user or not user.check_password(password):
        return jsonify({"success": False, "error": "Identifiants invalides"}), 401

    session["username"] = username
    session["user_id"] = user.user_id

    return jsonify({
        "success": True,
        "message": "Connecté",
        "user": user.to_dict()
    })


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Déconnexion."""
    session.clear()
    return jsonify({"success": True, "message": "Déconnecté"})


@app.route("/api/me", methods=["GET"])
def api_me():
    """Infos de l'utilisateur connecté."""
    try:
        user = get_current_user()
        return jsonify({"success": True, "user": user.to_dict()})
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

# ------------------------------------------------------------------
# Routes API - Marché (publiques)
# ------------------------------------------------------------------

@app.route("/api/market", methods=["GET"])
def api_market():
    """Données publiques du marché."""
    return jsonify(get_market_data())


@app.route("/api/book", methods=["GET"])
def api_book():
    """Carnet d'ordres uniquement."""
    return jsonify(order_book.get_book_snapshot(BOOK_DEPTH))


@app.route("/api/trades", methods=["GET"])
def api_trades():
    """Historique des trades (pour le dashboard et explorateur)."""
    limit = request.args.get("limit", None, type=int)  # None = pas de limite
    
    # 🔥 Charger TOUS les trades
    db_trades = load_trades(limit)  # limit=None = tous
    
    trades = []
    for t in db_trades:
        trades.append({
            "id": t.get("id"),
            "timestamp": t["timestamp"],
            "price": t["price"],
            "quantity": t["quantity"],
            "total": t["total"],
            "buyer": t["buyer_name"],
            "seller": t["seller_name"],
            "buyer_id": t["buyer_id"],
            "seller_id": t["seller_id"]
        })

    return jsonify(trades)

# ------------------------------------------------------------------
# Routes API - Trading
# ------------------------------------------------------------------

@app.route("/api/order", methods=["POST"])
def api_place_order():
    """Passer un ordre."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    data = request.json or {}
    side = data.get("side", "").lower()
    order_type = data.get("order_type", "").lower()
    quantity = data.get("quantity", 0)
    price = data.get("price")

    # Validation
    valid, msg = validate_order_params(
        side, order_type, quantity, price,
        MIN_ORDER_SIZE, MAX_ORDER_SIZE
    )
    if not valid:
        return jsonify({"success": False, "error": msg}), 400

    try:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        order_otype = OrderType.LIMIT if order_type == "limit" else OrderType.MARKET

        # --- Vérification de solvabilité AVANT ---
        if order_side == OrderSide.BUY:
            if order_otype == OrderType.LIMIT and price:
                fee = round(price * quantity * FEE_RATE, 6)
                total_needed = price * quantity + fee
                if user.portfolio.available_cash < total_needed:
                    raise InsufficientFundsError(
                        f"{user.username} : besoin de {total_needed:.4f} $, "
                        f"disponible : {user.portfolio.available_cash:.4f} $"
                    )
                user.portfolio.block_funds_for_buy(price, quantity, fee)
            else:
                if user.portfolio.available_cash <= 0:
                    raise InsufficientFundsError(
                        f"{user.username} : pas de cash disponible"
                    )
        else:
            if user.portfolio.available_asset(SYMBOL) < quantity:
                raise InsufficientAssetsError(
                    f"{user.username} : besoin de {quantity} FIX, "
                    f"disponible : {user.portfolio.available_asset(SYMBOL)}"
                )
            user.portfolio.block_assets_for_sell(SYMBOL, quantity)

        # Créer l'ordre
        order = Order(
            user_id=user.user_id,
            username=user.username,
            side=order_side,
            order_type=order_otype,
            quantity=quantity,
            price=price
        )

        log_order(user.username, side, order_type, quantity, price)

        # Traiter via le moteur
        trades = engine.process_order(order)

        # --- Nettoyage des blocages après exécution ---
        if order_side == OrderSide.BUY:
            # BUY : libérer le blocage cash
            user.portfolio.blocked_cash = 0.0
        else:
            # SELL : libérer le blocage FIX sans toucher aux assets
            user.portfolio.blocked_assets["FIX"] = 0

        # WebSocket
        socketio.emit("book_update", get_market_data())

        return jsonify({
            "success": True,
            "order": order.to_dict(),
            "trades": [t.to_dict() for t in trades]
        })

    except (InsufficientFundsError, InsufficientAssetsError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        log_error(str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/order/<order_id>/cancel", methods=["POST"])
def api_cancel_order(order_id):
    """Annuler un ordre."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    try:
        order = order_book.get_order(order_id)
        if not order:
            raise OrderNotFoundError(f"Ordre {order_id} introuvable")

        if order.user_id != user.user_id and user.role != "admin":
            return jsonify({"success": False, "error": "Pas autorisé"}), 403

        # Débloquer les fonds
        if order.side == OrderSide.BUY and order.order_type == OrderType.LIMIT:
            fee = round(order.price * order.remaining_qty * FEE_RATE, 6)
            user.portfolio.release_funds_for_buy(
                order.price, order.remaining_qty, fee
            )
        elif order.side == OrderSide.SELL:
            user.portfolio.release_assets_for_sell(SYMBOL, order.remaining_qty)

        order_book.cancel_order(order_id)
        log_cancel(user.username, order_id)

        socketio.emit("book_update", get_market_data())

        return jsonify({
            "success": True,
            "message": "Ordre annulé",
            "order": order.to_dict()
        })

    except (OrderNotFoundError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/my/orders", methods=["GET"])
def api_my_orders():
    """Liste les ordres actifs de l'utilisateur connecté."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    active_orders = []
    for o in order_book.bids + order_book.asks:
        if o.user_id == user.user_id and o.is_active:
            active_orders.append(o.to_dict())

    return jsonify({"success": True, "orders": active_orders})

@app.route("/api/my/trades", methods=["GET"])
def api_my_trades():
    try:
        user = get_current_user()
        print(f"🔍 USER: {user.username} (ID: {user.user_id}, TYPE: {type(user.user_id)})")
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    db_trades = load_trades()  # 🔥 Pas de limite
    print(f"🔍 DB TRADES: {len(db_trades)} trades")
    
    # Afficher les 5 premiers trades
    for t in db_trades[:5]:
        print(f"   Trade: buyer_id={t['buyer_id']} ({type(t['buyer_id'])}), seller_id={t['seller_id']} ({type(t['seller_id'])})")
    
    user_id = user.user_id
    my_trades = []
    for t in db_trades:
        if t["buyer_id"] == user_id or t["seller_id"] == user_id:
            my_trades.append(t)

    print(f"🔍 RÉSULTAT: {len(my_trades)} trades pour {user.username}")
    return jsonify({"success": True, "trades": my_trades})

# ------------------------------------------------------------------
# Routes API - Admin
# ------------------------------------------------------------------

@app.route("/api/admin/add_cash", methods=["POST"])
def api_admin_add_cash():
    """Admin : ajouter du cash à un utilisateur."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    data = request.json or {}
    target_username = data.get("username", "").strip().lower()
    amount = data.get("amount", 0)

    valid, msg = validate_add_cash(amount)
    if not valid:
        return jsonify({"success": False, "error": msg}), 400

    target = users.get(target_username)
    if not target:
        return jsonify({"success": False, "error": "Utilisateur introuvable"}), 404

    target.portfolio.add_cash(amount)
    print(f"[ADMIN] {admin.username} a donné {amount:.2f} $ à {target.username}")

    save_user(target)

    return jsonify({
        "success": True,
        "message": f"{amount:.2f} $ ajoutés à {target.username}",
        "user": target.to_dict()
    })


@app.route("/api/admin/add_assets", methods=["POST"])
def api_admin_add_assets():
    """Admin : ajouter des FIX à un utilisateur (depuis sa réserve)."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    data = request.json or {}
    target_username = data.get("username", "").strip().lower()
    quantity = data.get("quantity", 0)

    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({"success": False, "error": "Quantité invalide"}), 400

    if not admin.portfolio.can_sell(SYMBOL, quantity):
        return jsonify({"success": False, "error": "Pas assez de FIX en réserve"}), 400

    target = users.get(target_username)
    if not target:
        return jsonify({"success": False, "error": "Utilisateur introuvable"}), 404

    admin.portfolio.assets[SYMBOL] -= quantity
    target.portfolio.add_assets(SYMBOL, quantity)

    save_user(target)

    return jsonify({
        "success": True,
        "message": f"{quantity} FIX transférés à {target.username}",
        "user": target.to_dict()
    })


@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    """Admin : liste tous les utilisateurs."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    return jsonify({
        "success": True,
        "users": [u.to_dict() for u in users.values()]
    })

# ------------------------------------------------------------------
# WebSocket
# ------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    """Client connecté → lui envoyer l'état du marché."""
    print(f"[WS] Client connecté")
    emit("market_update", get_market_data())


@socketio.on("disconnect")
def handle_disconnect():
    print(f"[WS] Client déconnecté")

# ------------------------------------------------------------------
# Routes Frontend (ordre important : /static d'abord)
# ------------------------------------------------------------------

@app.route("/")
def index():
    """Page d'accueil : connexion/inscription."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "index.html")


@app.route("/dashboard")
def dashboard():
    """Interface de trading."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "dashboard.html")


@app.route("/admin")
def admin_panel():
    """Panneau d'administration."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "admin.html")

# ============================================================
# ROUTES API - PORTEFEUILLE
# ============================================================

@app.route("/wallet")
def wallet_page():
    """Page du portefeuille."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "wallet.html")

@app.route("/api/wallet", methods=["GET"])
def api_wallet():
    """Retourne les informations complètes du portefeuille de l'utilisateur connecté."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    # Récupérer le prix actuel
    last_price = engine.get_last_price() or INITIAL_PRICE

    portfolio = user.portfolio
    fix_balance = portfolio.assets.get(SYMBOL, 0)
    usd_balance = portfolio.cash
    fix_value_usd = fix_balance * last_price
    total_value = usd_balance + fix_value_usd

    # Ordres actifs de l'utilisateur
    active_orders = []
    for o in order_book.bids + order_book.asks:
        if o.user_id == user.user_id and o.is_active:
            active_orders.append(o.to_dict())

    # Trades de l'utilisateur
    user_trades = []
    for t in engine.trades:
        if t.buyer_id == user.user_id or t.seller_id == user.user_id:
            user_trades.append(t.to_dict())

    return jsonify({
        "success": True,
        "wallet": {
            "usd": usd_balance,
            "fix": fix_balance,
            "fix_value_usd": fix_value_usd,
            "total_value": total_value,
            "last_price": last_price
        },
        "orders": active_orders,
        "trades": user_trades[-50:]  # 50 derniers trades
    })


@app.route("/api/wallet/history", methods=["GET"])
def api_wallet_history():
    """Retourne l'historique des transactions de l'utilisateur."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    limit = request.args.get("limit", 50, type=int)
    
    user_trades = []
    for t in engine.trades:
        if t.buyer_id == user.user_id or t.seller_id == user.user_id:
            user_trades.append(t.to_dict())
    
    # Trier par timestamp décroissant
    user_trades.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    return jsonify({
        "success": True,
        "trades": user_trades[:limit],
        "total": len(user_trades)
    })


@app.route("/api/wallet/orders", methods=["GET"])
def api_wallet_orders():
    """Retourne tous les ordres de l'utilisateur (actifs + historiques)."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    # Ordres actifs
    active_orders = []
    for o in order_book.bids + order_book.asks:
        if o.user_id == user.user_id:
            active_orders.append(o.to_dict())

    # Ordres historiques (depuis engine.history si disponible)
    historical_orders = []
    if hasattr(engine, 'order_history'):
        for o in engine.order_history:
            if o.user_id == user.user_id:
                historical_orders.append(o.to_dict())

    return jsonify({
        "success": True,
        "active": active_orders,
        "history": historical_orders[-50:]
    })


# ============================================================
# ROUTES API - PORTEFEUILLE (ADMIN)
# ============================================================

@app.route("/api/admin/wallet/<username>", methods=["GET"])
def api_admin_wallet(username):
    """Admin : consulter le portefeuille d'un utilisateur."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    target = users.get(username.strip().lower())
    if not target:
        return jsonify({"success": False, "error": "Utilisateur introuvable"}), 404

    last_price = engine.get_last_price() or INITIAL_PRICE
    portfolio = target.portfolio
    fix_balance = portfolio.assets.get(SYMBOL, 0)
    usd_balance = portfolio.cash

    return jsonify({
        "success": True,
        "username": target.username,
        "wallet": {
            "usd": usd_balance,
            "fix": fix_balance,
            "fix_value_usd": fix_balance * last_price,
            "total_value": usd_balance + (fix_balance * last_price)
        },
        "role": target.role,
        "is_bot": target.is_bot
    })


@app.route("/api/admin/wallet/<username>/history", methods=["GET"])
def api_admin_wallet_history(username):
    """Admin : consulter l'historique des trades d'un utilisateur."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    target = users.get(username.strip().lower())
    if not target:
        return jsonify({"success": False, "error": "Utilisateur introuvable"}), 404

    user_trades = []
    for t in engine.trades:
        if t.buyer_id == target.user_id or t.seller_id == target.user_id:
            user_trades.append(t.to_dict())
    
    user_trades.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    return jsonify({
        "success": True,
        "username": target.username,
        "trades": user_trades[:50],
        "total": len(user_trades)
    })

# Stockage des bots aléatoires actifs
# ------------------------------------------------------------------
# Routes API - Robots aléatoires
# ------------------------------------------------------------------

# Stockage des bots aléatoires actifs

@app.route("/api/admin/start_random_bot", methods=["POST"])
def api_start_random_bot():
    """Admin : démarre un bot aléatoire sur un compte utilisateur."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except:
        return jsonify({"success": False, "error": "Non connecté"}), 401

    data = request.json or {}
    username = data.get("username", "").strip().lower()
    interval = data.get("interval", 15)

    user = users.get(username)
    if not user:
        return jsonify({"success": False, "error": "Utilisateur introuvable"}), 404

    if username in random_bots and random_bots[username].running:
        return jsonify({"success": False, "error": "Bot déjà actif sur ce compte"}), 400

    from utils.trader_bot import RandomTraderBot
    bot = RandomTraderBot(
        username=username,
        get_user_func=lambda u: users.get(u),
        place_order_func=place_order_internal,
        get_last_price_func=engine.get_last_price,
        interval_seconds=interval,
        min_qty=1000,
        max_qty=5000
    )
    bot.start()
    random_bots[username] = bot

    return jsonify({
        "success": True,
        "message": f"Bot aléatoire démarré sur {username} (interval: {interval}s)"
    })


@app.route("/api/admin/stop_random_bot", methods=["POST"])
def api_stop_random_bot():
    """Admin : arrête le bot aléatoire d'un compte."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except:
        return jsonify({"success": False, "error": "Non connecté"}), 401

    data = request.json or {}
    username = data.get("username", "").strip().lower()

    bot = random_bots.pop(username, None)
    if bot:
        bot.stop()
        return jsonify({"success": True, "message": f"Bot arrêté sur {username}"})
    return jsonify({"success": False, "error": "Aucun bot sur ce compte"}), 404


@app.route("/api/admin/random_bots", methods=["GET"])
def api_list_random_bots():
    """Admin : liste les bots aléatoires actifs."""
    try:
        admin = get_current_user()
        if admin.role != "admin":
            return jsonify({"success": False, "error": "Admin seulement"}), 403
    except:
        return jsonify({"success": False, "error": "Non connecté"}), 401

    bots_list = []
    for username, bot in random_bots.items():
        if bot.running:
            bots_list.append({
                "username": username,
                "interval": bot.interval
            })

    return jsonify({"success": True, "bots": bots_list})

from datetime import datetime, timedelta

@app.route("/api/stats")
def api_stats():
    """Retourne les statistiques complètes du marché."""
    
    # ===== STATS PRIX 24h =====
    now = datetime.now()
    yesterday_ts = (now - timedelta(hours=24)).timestamp()

    current_price = engine.get_last_price() or INITIAL_PRICE
    open_price = None
    high_24h = current_price
    low_24h = current_price
    volume_24h = 0

    db_trades = load_trades()
    for t in db_trades:
        try:
            ts = datetime.fromisoformat(t["timestamp"]).timestamp()
        except:
            continue

        if ts >= yesterday_ts:
            if open_price is None:
                open_price = t["price"]
            high_24h = max(high_24h, t["price"])
            low_24h = min(low_24h, t["price"])
            volume_24h += t["quantity"]

    if open_price is None or open_price == 0:
        open_price = current_price

    change_pct = ((current_price - open_price) / open_price) * 100 if open_price > 0 else 0

    # ===== STATS SUPPLY =====
    TOTAL_SUPPLY = 1_000_000          # Offre totale fixe
    RESERVE_FIX = 100_000              # FIX bloqués dans la réserve (non en circulation)
    
    # FIX en circulation = Total - Réserve
    fix_in_circulation = TOTAL_SUPPLY - RESERVE_FIX
    circulation_pct = (fix_in_circulation / TOTAL_SUPPLY) * 100 if TOTAL_SUPPLY > 0 else 0

    # ===== STATS USD =====
    usd_in_circulation = sum(u.portfolio.cash for u in users.values() if hasattr(u, 'portfolio'))

    # ===== STATS MARKET MAKER =====
    market_maker_active = any(b.running for b in bots) if bots else False
    market_maker_count = len([b for b in bots if b.running]) if bots else 0

    # ===== DÉTAIL DES FIX PAR COMPTE (optionnel) =====
    fix_details = {}
    for username, user in users.items():
        fix_details[username] = user.portfolio.assets.get("FIX", 0)

    return jsonify({
        "success": True,
        # Prix
        "current_price": current_price,
        "open_price": open_price,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "change_pct": round(change_pct, 2),
        "volume_24h": volume_24h,
        # Supply
        "total_supply": TOTAL_SUPPLY,
        "reserve_fix": RESERVE_FIX,
        "fix_in_circulation": fix_in_circulation,
        "circulation_pct": round(circulation_pct, 2),
        "usd_in_circulation": round(usd_in_circulation, 2),
        # Market Maker
        "market_maker_active": market_maker_active,
        "market_maker_count": market_maker_count,
        # Détail (optionnel)
        "fix_details": fix_details
    })

# ============================================================
# ROUTES API - GRAPHIQUE (CANDLES)
# ============================================================
import time
from datetime import datetime

# Cache pour les bougies
candle_cache = {}
CACHE_DURATION = 5  # secondes

@app.route("/chartcandle")
def chart_candle():
    """Page graphique avec chandeliers."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "chartcandle.html")

@app.route("/api/candles/<timeframe>", methods=["GET"])
def api_candles(timeframe):
    """
    Retourne les données de chandelier pour le timeframe demandé.
    Timeframes: M1, M5, M15, H1, H4, D1
    """
    tf_map = {
        "M1": 60,
        "M5": 300,
        "M15": 900,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400
    }
    interval = tf_map.get(timeframe, 60)
    limit = request.args.get("limit", None, type=int)  # Pas de limite par défaut

    # Vérifier le cache
    cache_key = f"{timeframe}_{limit}"
    now = int(time.time())

    if cache_key in candle_cache:
        cached_time, cached_data = candle_cache[cache_key]
        if now - cached_time < CACHE_DURATION:
            return jsonify(cached_data)

    # Charger tous les trades depuis la DB
    db_trades = load_trades()
    
    if not db_trades:
        return jsonify([])

    # Construire les bougies à partir de TOUS les trades
    candles = build_candles_from_trades(db_trades, interval)
    
    # Appliquer la limite si spécifiée (prendre les plus récentes)
    if limit and len(candles) > limit:
        candles = candles[-limit:]

    # Mettre en cache
    candle_cache[cache_key] = (now, candles)

    return jsonify(candles)


def build_candles_from_trades(trades, interval_seconds):
    """
    Construit des bougies à partir de TOUS les trades réels.
    Retourne TOUTES les bougies disponibles.
    """
    if not trades:
        return []

    candles = []
    current_candle = None
    current_time = None

    for trade in trades:
        if isinstance(trade, dict):
            ts = trade.get('timestamp', time.time())
            price = trade.get('price', 0)
            quantity = trade.get('quantity', 0)
        else:
            ts = getattr(trade, 'timestamp', time.time())
            price = getattr(trade, 'price', 0)
            quantity = getattr(trade, 'quantity', 0)

        if price <= 0:
            continue

        # Gérer le cas où ts est une chaîne
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts).timestamp()
            except:
                continue

        candle_time = int(ts // interval_seconds) * interval_seconds

        if current_time is None:
            current_time = candle_time
            current_candle = {
                'time': candle_time,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': quantity
            }
        elif candle_time == current_time:
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += quantity
        else:
            candles.append(current_candle)
            current_time = candle_time
            current_candle = {
                'time': candle_time,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': quantity
            }

    if current_candle:
        candles.append(current_candle)

    # Trier par temps croissant
    candles.sort(key=lambda x: x['time'])
    
    return candles


@app.route("/api/candles/realtime", methods=["GET"])
def api_candles_realtime():
    """
    Retourne la dernière bougie en temps réel (basée sur les vrais trades).
    """
    timeframe = request.args.get("timeframe", "M1")
    tf_map = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
    interval = tf_map.get(timeframe, 60)

    current_price = engine.get_last_price() or INITIAL_PRICE
    now = int(time.time())
    candle_time = int(now // interval) * interval

    db_trades = load_trades()
    candle_trades = []

    for trade in db_trades:
        try:
            if isinstance(trade, dict):
                ts_raw = trade.get('timestamp')
                price = trade.get('price', 0)
                quantity = trade.get('quantity', 0)
            else:
                ts_raw = getattr(trade, 'timestamp', None)
                price = getattr(trade, 'price', 0)
                quantity = getattr(trade, 'quantity', 0)

            if price <= 0:
                continue

            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw).timestamp()
            else:
                ts = ts_raw

            trade_candle_time = int(ts // interval) * interval
            if trade_candle_time == candle_time:
                candle_trades.append({
                    'price': price,
                    'quantity': quantity
                })
        except:
            continue

    if candle_trades:
        open_price = candle_trades[0]['price']
        high_price = max(t['price'] for t in candle_trades)
        low_price = min(t['price'] for t in candle_trades)
        close_price = candle_trades[-1]['price']
        volume = sum(t.get('quantity', 0) for t in candle_trades)
    else:
        # Si pas de trades dans cette bougie, on retourne la dernière connue
        # On cherche la dernière bougie complète
        all_candles = build_candles_from_trades(db_trades, interval)
        if all_candles:
            last_candle = all_candles[-1]
            return jsonify({
                "time": last_candle['time'],
                "open": round(last_candle['open'], 8),
                "high": round(last_candle['high'], 8),
                "low": round(last_candle['low'], 8),
                "close": round(last_candle['close'], 8),
                "volume": last_candle.get('volume', 0)
            })
        else:
            return jsonify({
                "time": candle_time,
                "open": round(current_price, 8),
                "high": round(current_price, 8),
                "low": round(current_price, 8),
                "close": round(current_price, 8),
                "volume": 0
            })

    return jsonify({
        "time": candle_time,
        "open": round(open_price, 8),
        "high": round(high_price, 8),
        "low": round(low_price, 8),
        "close": round(close_price, 8),
        "volume": volume
    })

#============================================================
#ROUTES API - GRAPHIQUE (LINE CHART)
#============================================================

import time
import random
from datetime import datetime, timedelta

@app.route("/api/line/<period>", methods=["GET"])
def api_line_chart(period):
    """
    Retourne les données pour le graphique de ligne.
    Périodes: 1H, 1J, 5J, 1M, 6M, 1AN, 5ANS, MAX
    """
    # Configuration des périodes
    period_config = {
        '1H': {'interval': 60, 'points': 60},           # 1 minute
        '1J': {'interval': 300, 'points': 288},         # 5 minutes
        '5J': {'interval': 3600, 'points': 120},        # 1 heure
        '1M': {'interval': 3600, 'points': 720},        # 1 heure
        '6M': {'interval': 86400, 'points': 180},       # 1 jour
        '1AN': {'interval': 86400, 'points': 365},      # 1 jour
        '5ANS': {'interval': 604800, 'points': 260},    # 1 semaine
        'MAX': {'interval': 2592000, 'points': 120},    # 1 mois
    }

    config = period_config.get(period, period_config['1J'])
    interval = config['interval']
    num_points = config['points']

    # Prix actuel
    current_price = engine.get_last_price() or INITIAL_PRICE
    if current_price <= 0:
        current_price = INITIAL_PRICE

    # Charger les trades réels
    db_trades = load_trades()
    
    # Calculer le timestamp de début
    now = int(time.time())
    start_time = now - (num_points * interval)

    # Construire les points à partir des trades réels
    points = []
    open_price = current_price
    high_price = current_price
    low_price = current_price
    volume = 0

    for i in range(num_points):
        point_time = start_time + (i * interval)
        point_end = point_time + interval

        # Trouver les trades dans cet intervalle
        trades_in_interval = []
        for trade in db_trades:
            try:
                ts = datetime.fromisoformat(trade['timestamp']).timestamp()
                if point_time <= ts < point_end:
                    trades_in_interval.append(trade)
            except:
                continue

        if trades_in_interval:
            # Utiliser le dernier prix de l'intervalle
            price = trades_in_interval[-1]['price']
            volume += sum(t['quantity'] for t in trades_in_interval)
        else:
            # Simuler un mouvement réaliste
            volatility = 0.0008
            change = (random.random() - 0.5) * 2 * volatility * current_price
            price = max(0.0001, current_price + change)

        points.append({
            'time': point_time,
            'value': round(price, 8)
        })

        high_price = max(high_price, price)
        low_price = min(low_price, price)
        if i == 0:
            open_price = price

        current_price = price

    # 🔥 CORRECTION : prev_close est une valeur, pas un dict
    # points[-24] retourne {time: ..., value: ...} donc on prend ['value']
    if len(points) > 24:
        prev_close = points[-24]['value']
    else:
        prev_close = points[0]['value'] if points else current_price

    return jsonify({
        'success': True,
        'period': period,
        'points': points,
        'current_price': points[-1]['value'] if points else current_price,
        'open': round(open_price, 8),
        'high': round(high_price, 8),
        'low': round(low_price, 8),
        'prev_close': round(prev_close, 8),
        'volume': volume
    })

@app.route("/chart")
def chart_page():
    """Page graphique avec chandeliers."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "chart.html")

# ============================================================
# ROUTES API - WALLET (RETRAIT & TRANSFERT)
# ============================================================

# ============================================================
# ROUTES - PAGES
# ============================================================

@app.route("/deposit")
def deposit_page():
    """Page de dépôt."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "deposit.html")


@app.route("/api/deposit/request", methods=["POST"])
def api_deposit_request():
    """Enregistre une demande de dépôt (admin notifié)."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    data = request.json or {}
    full_name = data.get("full_name", "").strip()
    username = data.get("username", "").strip().lower()
    phone = data.get("phone", "").strip()
    method = data.get("method", "")
    amount = data.get("amount", 0)

    # Validations
    if not full_name:
        return jsonify({"success": False, "error": "Nom complet requis"}), 400
    if username != user.username:
        return jsonify({"success": False, "error": "Username invalide"}), 400
    if not phone or len(phone) < 8:
        return jsonify({"success": False, "error": "Numéro de téléphone invalide"}), 400
    if not method:
        return jsonify({"success": False, "error": "Méthode de paiement requise"}), 400
    if not amount or amount < 1:
        return jsonify({"success": False, "error": "Montant minimum : 1 USD"}), 400

    # 🔥 Sauvegarder la demande (dans un fichier ou DB)
    from datetime import datetime
    import json
    import os

    deposit_request = {
        "id": int(datetime.now().timestamp()),
        "user_id": user.user_id,
        "username": user.username,
        "full_name": full_name,
        "phone": phone,
        "method": method,
        "amount": amount,
        "status": "pending",
        "date": datetime.now().isoformat()
    }

    # Sauvegarder dans un fichier JSON (ou DB)
    requests_file = "data/deposit_requests.json"
    try:
        with open(requests_file, "r") as f:
            requests = json.load(f)
    except:
        requests = []

    requests.append(deposit_request)

    with open(requests_file, "w") as f:
        json.dump(requests, f, indent=2)

    # 🔥 Log dans la console pour l'admin
    print(f"\n{'='*60}")
    print(f"📥 NOUVELLE DEMANDE DE DÉPÔT")
    print(f"   Utilisateur : {user.username}")
    print(f"   Nom complet : {full_name}")
    print(f"   Téléphone   : {phone}")
    print(f"   Méthode     : {method}")
    print(f"   Montant     : {amount:.2f} USD")
    print(f"   Date        : {deposit_request['date']}")
    print(f"{'='*60}\n")

    return jsonify({
        "success": True,
        "message": "Demande de dépôt enregistrée",
        "request_id": deposit_request["id"]
    })

@app.route("/api/deposit/history", methods=["GET"])
def api_deposit_history():
    """Historique des dépôts de l'utilisateur."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    import json
    import os

    requests_file = "data/deposit_requests.json"
    try:
        with open(requests_file, "r") as f:
            all_requests = json.load(f)
    except:
        all_requests = []

    user_requests = [r for r in all_requests if r["username"] == user.username]
    user_requests.reverse()

    return jsonify({"success": True, "history": user_requests})


@app.route("/withdraw")
def withdraw_page():
    """Page de retrait."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "withdraw.html")


@app.route("/api/wallet/withdraw", methods=["POST"])
def api_withdraw():
    """Retrait USD : débite le compte avec frais de 1%."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    data = request.json or {}
    address = data.get("address", "").strip()
    amount = data.get("amount", 0)

    if not address:
        return jsonify({"success": False, "error": "Adresse de retrait requise"}), 400
    
    if not amount or amount <= 0:
        return jsonify({"success": False, "error": "Montant invalide"}), 400

    if amount < 10:
        return jsonify({"success": False, "error": "Montant minimum : 10.00 USD"}), 400

    fee = amount * 0.01
    net_amount = amount - fee
    total_deducted = amount + fee

    if user.portfolio.cash < total_deducted:
        return jsonify({
            "success": False, 
            "error": f"Solde insuffisant. Disponible: {user.portfolio.cash:.2f} $, Besoin: {total_deducted:.2f} $"
        }), 400

    # 🔥 Générer les données encodées pour le QR code
    import base64
    import json
    import time
    encoded_data = base64.b64encode(json.dumps({
        "user": user.username,
        "amount": amount,
        "fee": fee,
        "net": net_amount,
        "address": address,
        "timestamp": time.time()
    }).encode()).decode()

    # Débiter le compte
    user.portfolio.cash -= total_deducted
    save_user(user)

    # 🔥 Sauvegarder le retrait dans la base de données avec statut "completed"
    from data.database import save_withdrawal, update_withdrawal_status
    withdrawal_id = save_withdrawal(
        user_id=user.user_id,
        username=user.username,
        amount=amount,
        fee=fee,
        net_amount=net_amount,
        address=address,
        encoded_data=encoded_data
    )

    # 🔥 Marquer directement comme validé
    update_withdrawal_status(withdrawal_id, "completed")

    # Log
    log_order(user.username, "withdraw", "USD", amount, f"{amount} USD (frais: {fee:.2f})")

    return jsonify({
        "success": True,
        "message": f"Retrait de {amount:.2f} $ effectué (frais: {fee:.2f} $)",
        "new_balance": user.portfolio.cash,
        "fee": fee,
        "amount": amount,
        "net": net_amount,
        "address": address,
        "withdrawal_id": withdrawal_id,
        "encoded_data": encoded_data
    })

@app.route("/api/wallet/withdraw/history", methods=["GET"])
def api_withdraw_history():
    """Retourne l'historique des retraits de l'utilisateur."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    limit = request.args.get("limit", 50, type=int)
    
    from data.database import get_withdrawals
    history = get_withdrawals(user.user_id, limit)

    return jsonify({
        "success": True,
        "history": history
    })

# ============================================================
# ROUTES - TRANSFERT
# ============================================================

@app.route("/transfer")
def transfer_page():
    """Page de transfert."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "transfer.html")


import base64  # Ajouter en haut du fichier si ce n'est pas déjà fait

@app.route("/api/wallet/transfer", methods=["POST"])
def api_transfer():
    """Transfert FIX vers une adresse."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    data = request.json or {}
    recipient_address = data.get("recipient_address", "").strip()
    amount = data.get("amount", 0)

    if not recipient_address:
        return jsonify({"success": False, "error": "Adresse du destinataire requise"}), 400

    if not amount or amount <= 0:
        return jsonify({"success": False, "error": "Quantité invalide"}), 400

    # 🔥 Vérifier que le destinataire existe via son adresse
    recipient_user = None
    for u in users.values():
        # Utiliser base64.b64encode au lieu de btoa
        encoded_id = base64.b64encode(str(u.user_id).encode()).decode()[:8]
        addr = 'fix_' + u.username + '_' + encoded_id
        if addr == recipient_address:
            recipient_user = u
            break

    if not recipient_user:
        return jsonify({"success": False, "error": "Adresse de destinataire invalide"}), 404

    if recipient_user.user_id == user.user_id:
        return jsonify({"success": False, "error": "Vous ne pouvez pas vous envoyer à vous-même"}), 400

    # Vérifier le solde FIX
    fix_balance = user.portfolio.assets.get("FIX", 0)
    if fix_balance < amount:
        return jsonify({"success": False, "error": f"Solde FIX insuffisant. Disponible: {fix_balance} FIX"}), 400

    # Effectuer le transfert
    user.portfolio.assets["FIX"] -= amount
    recipient_user.portfolio.assets["FIX"] = recipient_user.portfolio.assets.get("FIX", 0) + amount

    save_user(user)
    save_user(recipient_user)

    # Sauvegarder le transfert dans l'historique
    from data.database import save_transfer
    save_transfer(user.user_id, user.username, recipient_user.username, recipient_address, amount)

    return jsonify({
        "success": True,
        "message": f"{amount} FIX transférés à {recipient_user.username}",
        "new_balance": user.portfolio.assets.get("FIX", 0)
    })


@app.route("/api/wallet/transfer/history", methods=["GET"])
def api_transfer_history():
    """Historique des transferts de l'utilisateur."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    from data.database import get_transfers
    history = get_transfers(user.user_id)

    return jsonify({
        "success": True,
        "history": history
    })

@app.route("/api/wallet/transfer/received", methods=["GET"])
def api_transfer_received():
    """Historique des réceptions de FIX de l'utilisateur."""
    try:
        user = get_current_user()
    except (AuthenticationError, UserNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401

    from data.database import get_received_transfers
    history = get_received_transfers(user.user_id)

    # 🔥 Ajouter le type 'received' à chaque élément
    for item in history:
        item['type'] = 'received'

    return jsonify({
        "success": True,
        "history": history
    })

@app.route("/explorer")
def explorer_page():
    """Page explorateur de transactions."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "explorer.html")

# ============================================================
#  LIENS DE PAIEMENT
# ============================================================

import json
import os
import uuid
from datetime import datetime, timedelta

PAYMENT_LINKS_FILE = "data/payment_links.json"

def load_payment_links():
    try:
        with open(PAYMENT_LINKS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_payment_links(links):
    os.makedirs(os.path.dirname(PAYMENT_LINKS_FILE), exist_ok=True)
    with open(PAYMENT_LINKS_FILE, "w") as f:
        json.dump(links, f, indent=2)


@app.route("/payment-links")
def payment_links_page():
    """Page des liens de paiement."""
    from flask import send_from_directory
    return send_from_directory("frontend/templates", "payment_link.html")


@app.route("/api/payment-link/create", methods=["POST"])
def api_create_payment_link():
    """Crée un lien de paiement."""
    try:
        user = get_current_user()
    except:
        return jsonify({"success": False, "error": "Non connecté"}), 401

    data = request.json or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    amount = data.get("amount", 0)
    expiry = data.get("expiry", "never")
    image = data.get("image", None)

    if not name:
        return jsonify({"success": False, "error": "Nom requis"}), 400
    if not description:
        return jsonify({"success": False, "error": "Description requise"}), 400
    if not amount or amount <= 0:
        return jsonify({"success": False, "error": "Montant invalide"}), 400

    # Générer un ID unique
    link_id = str(uuid.uuid4())[:8]

    # Calculer l'expiration
    expiry_map = {
        "never": None,
        "24h": datetime.now() + timedelta(hours=24),
        "7d": datetime.now() + timedelta(days=7),
        "30d": datetime.now() + timedelta(days=30),
    }
    expires_at = expiry_map.get(expiry)

    link_data = {
        "id": link_id,
        "user_id": user.user_id,
        "username": user.username,
        "name": name,
        "description": description,
        "amount": amount,
        "image": image,
        "status": "active",
        "date": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None
    }

    # Sauvegarder
    links = load_payment_links()
    links.append(link_data)
    save_payment_links(links)

    link_url = f"{request.host_url}pay/{link_id}"

    return jsonify({
        "success": True,
        "link": link_url,
        "link_id": link_id
    })


@app.route("/api/payment-link/list", methods=["GET"])
def api_list_payment_links():
    """Liste les liens de paiement de l'utilisateur."""
    try:
        user = get_current_user()
    except:
        return jsonify({"success": False, "error": "Non connecté"}), 401

    links = load_payment_links()
    user_links = [l for l in links if l["user_id"] == user.user_id]
    user_links.reverse()

    return jsonify({"success": True, "links": user_links})

@app.route("/api/payment-link/<link_id>", methods=["GET"])
def api_get_payment_link(link_id):
    """Récupère les détails d'un lien de paiement."""
    from datetime import datetime
    
    links = load_payment_links()
    
    for link in links:
        if link["id"] == link_id:
            # Vérifier si le lien a expiré
            if link.get("expires_at"):
                expires_at = datetime.fromisoformat(link["expires_at"])
                if datetime.now() > expires_at:
                    link["status"] = "expired"
            
            return jsonify({
                "success": True,
                "link": link
            })
    
    return jsonify({"success": False, "error": "Lien introuvable"}), 404


@app.route("/api/payment-link/<link_id>/pay", methods=["POST"])
def api_pay_payment_link(link_id):
    """Effectue le paiement via un lien."""
    from datetime import datetime
    from data.database import save_transfer
    
    data = request.json or {}
    payer_username = data.get("username", "").strip().lower()
    payer_password = data.get("password", "")
    
    if not payer_username:
        return jsonify({"success": False, "error": "Username requis"}), 400
    
    if not payer_password:
        return jsonify({"success": False, "error": "Mot de passe requis"}), 400
    
    # 1. Récupérer le lien
    links = load_payment_links()
    link = None
    for l in links:
        if l["id"] == link_id:
            link = l
            break
    
    if not link:
        return jsonify({"success": False, "error": "Lien introuvable"}), 404
    
    # 2. Vérifier que le lien est actif
    if link.get("status") == "expired":
        return jsonify({"success": False, "error": "Ce lien a expiré"}), 400
    
    if link.get("expires_at"):
        expires_at = datetime.fromisoformat(link["expires_at"])
        if datetime.now() > expires_at:
            link["status"] = "expired"
            save_payment_links(links)
            return jsonify({"success": False, "error": "Ce lien a expiré"}), 400
    
    # 3. Vérifier que le payeur existe ET que le mot de passe est correct
    payer = users.get(payer_username)
    if not payer:
        return jsonify({"success": False, "error": "Utilisateur introuvable"}), 404
    
    # 🔥 VÉRIFICATION DU MOT DE PASSE
    if not payer.check_password(payer_password):
        return jsonify({"success": False, "error": "Mot de passe incorrect"}), 401
    
    # 4. Vérifier que le payeur n'est pas le vendeur
    seller = users_by_id.get(link["user_id"])
    if not seller:
        return jsonify({"success": False, "error": "Vendeur introuvable"}), 404
    
    if payer.user_id == seller.user_id:
        return jsonify({"success": False, "error": "Vous ne pouvez pas vous payer vous-même"}), 400
    
    # 5. Vérifier le solde FIX du payeur
    amount = link["amount"]
    payer_fix_balance = payer.portfolio.assets.get("FIX", 0)
    
    if payer_fix_balance < amount:
        return jsonify({
            "success": False, 
            "error": f"Solde insuffisant. Vous avez {payer_fix_balance} FIX, besoin de {amount} FIX"
        }), 400
    
    # 6. Effectuer le transfert
    payer.portfolio.assets["FIX"] -= amount
    seller.portfolio.assets["FIX"] = seller.portfolio.assets.get("FIX", 0) + amount
    
    # 7. Sauvegarder dans l'historique (comme les transferts)
    link_address = f"link_{link_id}_{link['name'][:10]}"
    save_transfer(
        user_id=payer.user_id,
        username=payer.username,
        recipient_username=seller.username,
        recipient_address=link_address,
        amount=amount
    )
    
    # 8. Marquer le lien comme payé
    link["status"] = "paid"
    link["paid_at"] = datetime.now().isoformat()
    link["paid_by"] = payer.username
    save_payment_links(links)
    
    # 9. Sauvegarder les utilisateurs
    save_user(payer)
    save_user(seller)
    
    # 10. Log
    print(f"\n{'='*60}")
    print(f"💰 PAIEMENT PAR LIEN")
    print(f"   Lien ID : {link_id}")
    print(f"   Produit : {link['name']}")
    print(f"   Montant : {amount} FIX")
    print(f"   Payeur  : {payer.username}")
    print(f"   Vendeur : {seller.username}")
    print(f"{'='*60}\n")
    
    return jsonify({
        "success": True,
        "message": f"Paiement de {amount} FIX effectué",
        "transaction": {
            "from": payer.username,
            "to": seller.username,
            "amount": amount,
            "product": link["name"]
        }
    })

@app.route("/pay/<link_id>")
def payment_page(link_id):
    """Page de paiement d'un lien."""
    from flask import send_from_directory
    # Passer l'ID du lien à la page
    return send_from_directory("frontend/templates", "payment_page.html")


@app.route("/api/repair-session", methods=["GET"])
def repair_session():
    """Réinitialise uniquement la session Flask, pas la base."""
    session.clear()
    return jsonify({"success": True, "message": "Session réinitialisée"})

@app.route("/api/create-default-users", methods=["GET"])
def create_default_users():
    """Crée les comptes par défaut sans supprimer les existants."""
    global admin_user, next_user_id, users, users_by_id
    
    try:
        # Vérifier si admin existe déjà
        if "admin" in users:
            return jsonify({"success": False, "error": "Les comptes existent déjà"}), 400
        
        # Créer admin
        admin_user = User(ADMIN_USERNAME, ADMIN_PASSWORD, role="admin", user_id=1)
        users[ADMIN_USERNAME] = admin_user
        users_by_id[admin_user.user_id] = admin_user
        next_user_id = 2
        
        # Créer bots
        for i in range(1, 3):
            bot_name = f"bot_{i}"
            bot_user = User(bot_name, f"bot{i}_pass", role="user", is_bot=True, user_id=next_user_id)
            users[bot_name] = bot_user
            users_by_id[bot_user.user_id] = bot_user
            next_user_id += 1
        
        # Créer réserve
        reserve_user = User("reserve", "reserve_pass", role="user", user_id=next_user_id)
        users["reserve"] = reserve_user
        users_by_id[reserve_user.user_id] = reserve_user
        next_user_id += 1
        
        # Allocations initiales
        for name, alloc in INITIAL_ALLOCATION.items():
            u = users.get(name)
            if u:
                u.portfolio.add_assets(SYMBOL, alloc.get("FIX", 0))
                u.portfolio.add_cash(alloc.get("USD", 0.0))
        
        # Sauvegarder
        save_all_users(users)
        
        return jsonify({
            "success": True, 
            "message": f"Comptes créés : {len(users)} utilisateurs",
            "users": list(users.keys())
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================
#  DÉMARRAGE DE L'APPLICATION
# ============================================================

if __name__ == "__main__":
    import os
    
    print("=" * 50)
    print("🚀 Lancement du Marché FIX")
    print("=" * 50)
    
    init_system()
    
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    print(f"📡 Serveur : http://{host}:{port}")
    print(f"👤 Admin  : {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    print("=" * 50)
    
    socketio.run(app, host=host, port=port, debug=False)
