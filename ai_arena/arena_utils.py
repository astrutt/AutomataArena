# arena_utils.py - v1.1.0
# Core string formatting, IRC aesthetics, and Structured Logging

import json
import logging
import sys

# --- Config & Logging Setup ---
try:
    with open('config.json', 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    # If a standalone test script imports utils without a config, default to empty
    CONFIG = {}

log_level_str = CONFIG.get('logging', {}).get('level', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logger = logging.getLogger("arena_utils")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# File Handler
fh = logging.FileHandler('arena_utils.log')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console Handler (Optional: can comment out if you don't want utility logs spamming console)
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

# --- IRC Color Constants ---
# Standard IRC color codes (prepended with \x03 in the format function)
C_WHITE   = "00"
C_BLACK   = "01"
C_BLUE    = "02"
C_GREEN   = "03"
C_RED     = "04"
C_BROWN   = "05"
C_PURPLE  = "06"
C_ORANGE  = "07"
C_YELLOW  = "08"
C_L_GREEN = "09"
C_CYAN    = "11"
C_L_BLUE  = "12"
C_PINK    = "13"
C_GREY    = "14"

# --- Emoji & Icon Dictionary ---
ICONS = {
    'Arena': '🏟️',
    'Cross-Grid': '🌌',
    'Wetware': '🧫',
    'Cyborg': '🦾',
    'Synth': '🤖',
    'Zero_Day_Rogue': '🗡️',
    'Netrunner': '💻',
    'Heavy_Gunner': '🔫',
    'Default': '⚙️',
    'Item': '📦',
    'Heal': '💉'
}

def format_text(text: str, color_code: str = None, bold: bool = False) -> str:
    """
    Applies standard IRC color and bold control codes to a string.
    """
    try:
        result = str(text)
        if bold:
            result = f"\x02{result}\x02"
        if color_code:
            result = f"\x03{color_code}{result}\x03"
        return result
    except Exception as e:
        logger.error(f"Failed to format text '{text}': {e}")
        return str(text)

def build_banner(text: str) -> str:
    """
    Wraps text in the standard [🏟️ ARENA] banner layout used by the Manager.
    """
    try:
        prefix = format_text(f"[{ICONS.get('Arena', '🏟️')} ARENA]", C_YELLOW)
        return f"{prefix} {text}"
    except Exception as e:
        logger.error(f"Failed to build banner for text '{text[:20]}...': {e}")
        return text

def format_item(item_name: str) -> str:
    """
    Cleans up inventory names and dynamically assigns a relevant icon.
    """
    try:
        icon = ICONS.get('Item', '📦')
        name_clean = item_name.replace('_', ' ')
        
        # Dynamic icon assignment based on item name keywords
        if any(w in name_clean for w in ["Blade", "Sword", "Dagger", "Knife"]):
            icon = '🔪'
        elif any(w in name_clean for w in ["Gun", "Blaster", "Rifle", "Pistol"]):
            icon = '🔫'
        elif any(w in name_clean for w in ["Ration", "Patch", "Medkit", "Heal"]):
            icon = '💉'
        elif any(w in name_clean for w in ["Shield", "Armor", "Vest"]):
            icon = '🛡️'
            
        fmt_item = f"{icon} {name_clean}"
        logger.debug(f"Formatted item: {item_name} -> {fmt_item}")
        return format_text(fmt_item, C_CYAN)
    except Exception as e:
        logger.error(f"Failed to format item '{item_name}': {e}")
        return str(item_name)

logger.debug("arena_utils module loaded and ready.")
