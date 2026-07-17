"""
Système de traduction multilingue
"""

import json
import os
from flask import request, session

# Dossier des fichiers de traduction
LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                           "frontend", "templates", "locales")

# Langues disponibles
LANGUAGES = {
    "fr": "Français",
    "en": "English",
    "ln": "Lingala",
    "sw": "Swahili"
}

# Langue par défaut
DEFAULT_LANGUAGE = "fr"

# Cache des traductions
_translations_cache = {}


def load_translations(lang_code):
    """Charge les traductions pour une langue donnée."""
    if lang_code in _translations_cache:
        return _translations_cache[lang_code]
    
    file_path = os.path.join(LOCALES_DIR, f"{lang_code}.json")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            translations = json.load(f)
            _translations_cache[lang_code] = translations
            return translations
    except FileNotFoundError:
        # Fallback sur le français
        if lang_code != "fr":
            return load_translations("fr")
        return {}


def get_current_language():
    """Récupère la langue actuelle de l'utilisateur."""
    # 1. Vérifier la session
    if "lang" in session:
        return session["lang"]
    
    # 2. Vérifier le cookie
    lang = request.cookies.get("lang")
    if lang in LANGUAGES:
        return lang
    
    # 3. Vérifier le header Accept-Language
    if request.headers.get("Accept-Language"):
        preferred = request.headers.get("Accept-Language").split(",")[0].split("-")[0]
        if preferred in LANGUAGES:
            return preferred
    
    return DEFAULT_LANGUAGE


def set_language(lang_code):
    """Définit la langue de l'utilisateur."""
    if lang_code in LANGUAGES:
        session["lang"] = lang_code
        return True
    return False


def get_text(key, lang=None, **kwargs):
    """
    Récupère un texte traduit.
    
    Exemple:
        get_text("welcome_message", name="Jean")
        → "Bienvenue Jean" ou "Welcome Jean"
    """
    if lang is None:
        lang = get_current_language()
    
    translations = load_translations(lang)
    
    # Chercher la clé (support des points pour la hiérarchie)
    parts = key.split(".")
    value = translations
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            # Clé non trouvée, fallback en anglais puis français
            if lang != "en":
                return get_text(key, "en", **kwargs)
            elif lang != "fr":
                return get_text(key, "fr", **kwargs)
            return key
    
    # Formater avec les paramètres
    if kwargs:
        try:
            return value.format(**kwargs)
        except:
            return value
    
    return value


def get_language_selector():
    """Retourne le HTML du sélecteur de langue."""
    current = get_current_language()
    options = ""
    for code, name in LANGUAGES.items():
        selected = "selected" if code == current else ""
        options += f'<option value="{code}" {selected}>{name}</option>'
    
    return f"""
    <select id="langSelect" onchange="changeLanguage(this.value)" style="
        background: #0a0a0a;
        border: 1px solid #2a2a2a;
        color: #ccc;
        padding: 6px 12px;
        border-radius: 6px;
        font-family: inherit;
        font-size: 12px;
        cursor: pointer;
        outline: none;
    ">
        {options}
    </select>
    <script>
        function changeLanguage(lang) {{
            document.cookie = "lang=" + lang + "; path=/; max-age=31536000";
            fetch("/api/set_language", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{lang: lang}})
            }}).then(() => location.reload());
        }}
    </script>
    """
