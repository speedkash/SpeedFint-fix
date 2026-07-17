"""
Système de logging simple pour le marché FIX.
"""

import logging
from datetime import datetime

# Configuration du logger
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

logger = logging.getLogger("FIX")


def log_trade(buyer: str, seller: str, price: float, qty: int, total: float):
    """Log un trade exécuté."""
    logger.info(
        f"TRADE | {buyer} ← {seller} | "
        f"{qty} FIX @ {price:.6f} $ | Total: {total:.4f} $"
    )


def log_order(username: str, side: str, order_type: str,
              qty: int, price=None):
    """
    Log un ordre reçu.
    price peut être un float (prix) ou une chaîne (ex: "USD" pour les retraits)
    """
    # 🔥 Gérer le cas où price est une chaîne
    if isinstance(price, str):
        price_str = price
    elif price is not None and isinstance(price, (int, float)):
        price_str = f"@ {price:.6f}"
    else:
        price_str = "MARKET"
    
    logger.info(
        f"ORDER | {username} | {side} {order_type} | "
        f"{qty} FIX {price_str}"
    )


def log_cancel(username: str, order_id: str):
    """Log une annulation."""
    logger.info(f"CANCEL | {username} | Order {order_id[:8]}...")


def log_error(message: str):
    """Log une erreur."""
    logger.error(f"ERROR | {message}")
