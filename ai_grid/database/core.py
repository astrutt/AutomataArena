# core.py
import os
import json
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

try:
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
        db_name = CONFIG.get('database', {}).get('file', 'automata_grid.db')
        DB_FILE = os.path.join(BASE_DIR, db_name)
except (FileNotFoundError, json.JSONDecodeError):
    CONFIG = {}
    DB_FILE = os.path.join(BASE_DIR, 'automata_grid.db')

# Shared Logger
logger = logging.getLogger("grid_db")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

if not logger.handlers:
    fh = logging.FileHandler(os.path.join(BASE_DIR, 'grid_db.log'))
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# Game Constants
MOB_ROSTER = {
    1: {"name": "Rogue_Process",  "cpu": 2, "ram": 2, "bnd": 2, "sec": 1, "alg": 1, "xp": 15, "credits": 10},
    2: {"name": "ICE_Drone",      "cpu": 3, "ram": 3, "bnd": 2, "sec": 2, "alg": 2, "xp": 25, "credits": 20},
    3: {"name": "Phantom_Script", "cpu": 4, "ram": 4, "bnd": 3, "sec": 3, "alg": 3, "xp": 40, "credits": 35},
    0: {"name": "Grid_Bug",       "cpu": 1, "ram": 1, "bnd": 1, "sec": 1, "alg": 0, "xp": 5,  "credits": 5},
}

LOOT_TABLE = ["Data_Shard", "Memory_Fragment", "Corrupted_Bit"]

GRID_EXPANSION = [
    ("Neural_Nexus",        "A secondary uplink hub. Neon architecture hums with safe traffic.", "safezone",   0),
    ("Memory_Heap",         "Scattered RAM towers leak stray processes. Weak rogues lurk here.", "wilderness", 1),
    ("Kernel_Deep",         "The OS core. Deeper processes patrol this sector.",                  "wilderness", 2),
    ("Null_Space",          "Unallocated void. Corrupted scripts dwell at maximum density.",      "wilderness", 3),
    ("Shadow_Sector",       "Dark subnet. Freelance ICE patrols the western edge.",               "wilderness", 1),
    ("Void_Sector",         "Signal degrades to near-zero. Dangerous static.",                    "wilderness", 2),
    ("Stack_Overflow",      "Recursive loops fill this dead-end with unstable daemons.",          "wilderness", 3),
    ("Cache_Cluster",       "Hot cache banks. ICE drones guard the processing lanes.",            "wilderness", 2),
    ("Datacore_Alpha",      "Corporate safezone. Clean architecture, strict access.",              "safezone",   0),
    ("Firewall_Perimeter",  "The edge of the mapped grid. Hostile ICE wall ahead.",               "wilderness", 3),
    ("Dark_Web_Exchange",   "A second black market node. Riskier, deeper in the south.",          "merchant",   0),
    ("Logic_Gate",          "Automated logic processors gone feral. Mid-level threat.",            "wilderness", 2),
    ("Gladiator_Pit",       "A second combat arena — rawer, less regulated than The_Arena.",      "arena",      0),
]

GRID_CONNECTIONS = [
    ("UpLink", "Neural_Nexus",   "north"), ("Neural_Nexus",   "UpLink", "south"),
    ("Neural_Nexus",    "Memory_Heap",    "north"), ("Memory_Heap",    "Neural_Nexus",    "south"),
    ("Memory_Heap",     "Kernel_Deep",    "north"), ("Kernel_Deep",    "Memory_Heap",     "south"),
    ("Kernel_Deep",     "Null_Space",     "north"), ("Null_Space",     "Kernel_Deep",     "south"),
    ("UpLink", "Shadow_Sector",  "west"),  ("Shadow_Sector",  "UpLink", "east"),
    ("Shadow_Sector",   "Void_Sector",    "west"),  ("Void_Sector",    "Shadow_Sector",   "east"),
    ("Void_Sector",     "Stack_Overflow", "west"),  ("Stack_Overflow", "Void_Sector",     "east"),
    ("The_CPU_Socket",  "Cache_Cluster",  "east"),  ("Cache_Cluster",  "The_CPU_Socket",  "west"),
    ("Cache_Cluster",   "Datacore_Alpha", "east"),  ("Datacore_Alpha", "Cache_Cluster",   "west"),
    ("Datacore_Alpha",  "Firewall_Perimeter", "east"), ("Firewall_Perimeter", "Datacore_Alpha", "west"),
    ("Black_Market_Port",   "Dark_Web_Exchange", "south"), ("Dark_Web_Exchange", "Black_Market_Port",   "north"),
    ("Dark_Web_Exchange",   "Logic_Gate",        "south"), ("Logic_Gate",        "Dark_Web_Exchange",   "north"),
    ("The_Arena",      "Gladiator_Pit",  "east"),  ("Gladiator_Pit",  "The_Arena",       "west"),
]

LOOT_TEMPLATES = [
    {"name": "Data_Shard",      "item_type": "junk", "base_value": 5,  "effects_json": "{}"},
    {"name": "Memory_Fragment", "item_type": "junk", "base_value": 8,  "effects_json": "{}"},
    {"name": "Corrupted_Bit",   "item_type": "junk", "base_value": 3,  "effects_json": "{}"},
]

DEFAULT_PREFS = {
    "output_mode": "human",
    "auto_sell_trash": False,
    "tutorial_mode": True,
    "reminders": True
}
