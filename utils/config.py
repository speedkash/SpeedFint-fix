"""
Configuration centralisée du marché FIX.
Toutes les constantes et paramètres sont ici.
"""

# ------------------------------------------------------------------
# Actif
# ------------------------------------------------------------------
SYMBOL = "FIX"
ASSET_NAME = "FIX Token"
INITIAL_PRICE = 0.001  # Prix de référence avant tout échange (USD)
TOTAL_SUPPLY = 1_000_000  # Offre totale fixe

# ------------------------------------------------------------------
# Marché
# ------------------------------------------------------------------
MIN_ORDER_SIZE = 1_000   # Quantité minimale par ordre (FIX)
MAX_ORDER_SIZE = 10_000  # Quantité maximale par ordre (FIX)
TICK_SIZE = None         # Pas de cotation (prix libre)

# ------------------------------------------------------------------
# Frais
# ------------------------------------------------------------------
FEE_RATE = 0.001  # 0.1% par trade, payé par les deux parties
FEE_ACCOUNT = "reserve"  # Les frais vont au compte admin

# ------------------------------------------------------------------
# Bots
# ------------------------------------------------------------------
BOT_COUNT = 2
BOT_SPREAD_PCT = 3.0         # Écart en % autour du prix
BOT_INTERVAL_SECONDS = 50.0  # Délai entre deux cycles
BOT_MIN_QTY = 1_000
BOT_MAX_QTY = 5_000

# ------------------------------------------------------------------
# Répartition initiale des FIX
# ------------------------------------------------------------------
INITIAL_ALLOCATION = {
    "admin": {
        "FIX": 700_000,
        "USD": 0.0
    },
    "reserve": {
        "FIX": 100_000,
        "USD": 0.0
    },
    "bot_1": {
        "FIX": 100_000,
        "USD": 0.0
    },
    "bot_2": {
        "FIX": 100_000,
        "USD": 0.0
    }
}

# ------------------------------------------------------------------
# Serveur
# ------------------------------------------------------------------
HOST = "0.0.0.0"
PORT = 5000
DEBUG = True
SECRET_KEY = "changez-moi-en-production"  # Pour Flask sessions

# ------------------------------------------------------------------
# Carnet d'ordres
# ------------------------------------------------------------------
BOOK_DEPTH = 10  # Nombre de niveaux affichés dans le carnet

# ------------------------------------------------------------------
# Utilisateurs
# ------------------------------------------------------------------
DEFAULT_USER_CASH = 0.0     # Cash donné à la création d'un compte
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "adminalam"  # À changer évidemment
