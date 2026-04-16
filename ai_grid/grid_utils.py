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
fh = logging.FileHandler('grid_utils.log')
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
    'ARENA': '🏟️',
    'SIGACT': '⚡',
    'SIGINT': '📡',
    'GEOINT': '🛰️',
    'HUMINT': '🕵️',
    'RUMINT': '👁️',
    'OSINT': '📜',
    'COMBAT': '⚔️',
    'WEATHER': '🌦️',
    'ECONOMY': '💹',
    'MAINT': '🛠️',
    'Default': '⚙️',
    'Item': '📦',
    'Heal': '💉'
}

def format_text(text: str, color_code: str = None, bold: bool = False, is_machine: bool = False) -> str:
    """
    Applies standard IRC color and bold control codes to a string.
    If is_machine is True, returns plain text.
    """
    if is_machine:
        return str(text)
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

def tag_msg(text: str, tags: list = None, location: str = None, is_machine: bool = False) -> str:
    """
    Builds a structured [GRID] message with tactical intel tags and icons.
    Format: [GRID]<ico>[TAG1][TAG2] text
    """
    if tags is None: tags = []
    
    # Identify primary icon
    icon = ""
    for t in tags:
        if t.upper() in ICONS:
            icon = ICONS[t.upper()]
            break
            
    # Human colors
    c_grid = C_YELLOW
    c_tags = C_CYAN
    
    # Construct tag string
    tag_str = ""
    if location:
        tag_str += f"[{location}]"
    for t in tags:
        tag_str += f"[{t}]"
    
    # Combine
    p_grid = format_text("[GRID]", c_grid, is_machine=is_machine)
    p_tags = format_text(f"{icon}{tag_str}", c_tags, is_machine=is_machine)
    
    return f"{p_grid} {p_tags} {text}"

def build_banner(text: str, is_machine: bool = False) -> str:
    """
    DEPRECATED: Legacy wrapper for [GRID] banner logic. 
    New code should use tag_msg() directly.
    """
    return tag_msg(text, tags=['ARENA'], is_machine=is_machine)

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
