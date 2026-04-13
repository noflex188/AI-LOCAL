"""
Détection automatique du contexte système au démarrage.
Injecté dans le system prompt à chaque session.
"""
import os
import sys
import platform
import locale
from datetime import datetime, timezone

# Correspondances locale → pays/langue lisibles
LOCALE_COUNTRY = {
    "fr_FR": ("France", "français"),
    "fr_BE": ("Belgique", "français"),
    "fr_CH": ("Suisse", "français"),
    "fr_CA": ("Canada", "français"),
    "fr_LU": ("Luxembourg", "français"),
    "en_US": ("États-Unis", "anglais"),
    "en_GB": ("Royaume-Uni", "anglais"),
    "en_AU": ("Australie", "anglais"),
    "en_CA": ("Canada", "anglais"),
    "de_DE": ("Allemagne", "allemand"),
    "de_AT": ("Autriche", "allemand"),
    "de_CH": ("Suisse", "allemand"),
    "es_ES": ("Espagne", "espagnol"),
    "es_MX": ("Mexique", "espagnol"),
    "it_IT": ("Italie", "italien"),
    "pt_BR": ("Brésil", "portugais"),
    "pt_PT": ("Portugal", "portugais"),
    "nl_NL": ("Pays-Bas", "néerlandais"),
    "pl_PL": ("Pologne", "polonais"),
    "ru_RU": ("Russie", "russe"),
    "zh_CN": ("Chine", "chinois"),
    "ja_JP": ("Japon", "japonais"),
    "ko_KR": ("Corée du Sud", "coréen"),
    "ar_SA": ("Arabie Saoudite", "arabe"),
}


def get_context() -> dict:
    """Retourne un dict avec toutes les infos contextuelles détectées."""
    # Langue / pays
    loc_code, encoding = locale.getdefaultlocale()
    if loc_code and loc_code in LOCALE_COUNTRY:
        country, language = LOCALE_COUNTRY[loc_code]
    elif loc_code and "_" in loc_code:
        lang_part = loc_code.split("_")[0]
        country   = loc_code.split("_")[1] if len(loc_code.split("_")) > 1 else "inconnu"
        language  = lang_part
    else:
        country, language = "inconnu", "inconnu"

    # Fuseau horaire
    try:
        tz_name = datetime.now(timezone.utc).astimezone().tzname() or "UTC"
        tz_offset = datetime.now().astimezone().strftime("%z")  # ex: +0200
        tz_str = f"{tz_name} (UTC{tz_offset[:3]}:{tz_offset[3:]})"
    except Exception:
        tz_str = "UTC"

    # OS
    os_name    = platform.system()        # Windows / Linux / Darwin
    os_version = platform.version()
    os_release = platform.release()
    if os_name == "Windows":
        os_str = f"Windows {os_release}"
    elif os_name == "Darwin":
        os_str = f"macOS {platform.mac_ver()[0]}"
    else:
        os_str = f"Linux ({platform.freedesktop_os_release().get('NAME', 'inconnu') if hasattr(platform, 'freedesktop_os_release') else 'inconnu'})"

    # Python
    py_version = sys.version.split()[0]

    # Répertoire de travail
    cwd = os.getcwd()

    return {
        "language":   language,
        "country":    country,
        "locale":     loc_code or "inconnu",
        "timezone":   tz_str,
        "os":         os_str,
        "python":     py_version,
        "cwd":        cwd,
    }


def build_context_block() -> str:
    """Génère le bloc de contexte à injecter dans le system prompt."""
    ctx = get_context()
    return f"""
## Contexte de l'utilisateur
- **Langue**       : {ctx['language']} (locale : {ctx['locale']})
- **Pays**         : {ctx['country']}
- **Fuseau horaire**: {ctx['timezone']}
- **Système**      : {ctx['os']}
- **Python**       : {ctx['python']}
- **Répertoire**   : {ctx['cwd']}

Adapte systématiquement tes réponses à ce contexte : langue, formats de date/heure locaux, chemins de fichiers compatibles avec l'OS, etc.
"""
