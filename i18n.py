import json
import os
from flask import session, request

_TRANSLATIONS = {}
_DEFAULT_LANG = "en"
_AVAILABLE = ("en", "ar")


def load_translations(app):
    base = os.path.join(app.root_path, "translations")
    for lang in _AVAILABLE:
        path = os.path.join(base, f"{lang}.json")
        with open(path, encoding="utf-8") as fh:
            _TRANSLATIONS[lang] = json.load(fh)


def current_lang():
    lang = request.args.get("lang") or session.get("lang") or _DEFAULT_LANG
    if lang not in _AVAILABLE:
        lang = _DEFAULT_LANG
    if request.args.get("lang"):
        session["lang"] = lang
    return lang


def t(key, **kwargs):
    lang = current_lang()
    val = _TRANSLATIONS.get(lang, {}).get(key) or _TRANSLATIONS.get(_DEFAULT_LANG, {}).get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


def is_rtl():
    return current_lang() == "ar"
