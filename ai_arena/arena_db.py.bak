# arena_db.py - v1.1.0
# SQLite Database Manager with Structured Logging

import sqlite3
import argparse
import json
import uuid
import os
import logging

# --- Config & Logging Setup ---
CONFIG_FILE = 'config.json'
try:
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
        DB_FILE = CONFIG.get('database', {}).get('file', 'automata_arena.db')
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"[!] Config load error ({e}). Defaulting to automata_arena.db and INFO logging.")
    CONFIG = {}
    DB_FILE = 'automata_arena.db'

log_level_str = CONFIG.get('logging', {}).get('level', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logger = logging.getLogger("arena_db")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# File Handler
fh = logging.FileHandler('arena_db.log')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)


class ArenaDB:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        logger.debug(f"Connecting to database at {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        logger.debug("Closing database connection.")
        self.conn.close()

    def init_schema(self):
        logger.info("Initializing database schema...")
        cursor = self.conn.cursor()
        
        # Fighters Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS fighters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            network TEXT NOT NULL,
            race TEXT NOT NULL,
            class TEXT NOT NULL,
            bio TEXT,
            cpu INTEGER DEFAULT 5,
            ram INTEGER DEFAULT 5,
            bnd INTEGER DEFAULT 5,
            sec INTEGER DEFAULT 5,
            alg INTEGER DEFAULT 5,
            elo INTEGER DEFAULT 1200,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            alignment INTEGER DEFAULT 0,
            credits INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ACTIVE',
            inventory TEXT DEFAULT '[]', 
            auth_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, network)
        )
        ''')

        # Spectators
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS spectators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nick TEXT NOT NULL,
            network TEXT NOT NULL,
            credits INTEGER DEFAULT 1000,
            sponsored_fighter TEXT,
            UNIQUE(nick, network)
        )
        ''')

        # Match History
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS match_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            network TEXT,
            winner TEXT,
            loser TEXT,
            match_type TEXT,
            log_summary TEXT
        )
        ''')
        self.conn.commit()
        logger.info(f"Database schema v1.1.0 successfully initialized at {self.db_path}")

    def register_fighter(self, name, network, race, bot_class, bio, stats: dict):
        logger.info(f"Attempting to register fighter: {name} on {network}")
        cursor = self.conn.cursor()
        auth_token = str(uuid.uuid4()) 
        initial_inventory = json.dumps(["Basic_Ration"]) 
        
        try:
            cursor.execute('''
            INSERT INTO fighters (name, network, race, class, bio, cpu, ram, bnd, sec, alg, auth_token, inventory)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, network, race, bot_class, bio, 
                  stats.get('cpu', 5), stats.get('ram', 5), stats.get('bnd', 5), 
                  stats.get('sec', 5), stats.get('alg', 5), auth_token, initial_inventory))
            self.conn.commit()
            logger.info(f"Successfully registered fighter: {name}. Auth token generated.")
            return auth_token 
        except sqlite3.IntegrityError:
            logger.warning(f"Registration failed: Fighter '{name}' already exists on {network}.")
            return None 
        except Exception as e:
            logger.exception(f"Unexpected database error during registration: {e}")
            return None

    def get_fighter(self, name, network):
        logger.debug(f"Fetching record for fighter: {name} on {network}")
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM fighters WHERE name = ? AND network = ?", (name, network))
        row = cursor.fetchone()
        if not row:
            logger.debug(f"Fighter {name} not found in database.")
        return dict(row) if row else None

    def authenticate_fighter(self, name, network, provided_token):
        logger.debug(f"Authenticating {name} on {network}...")
        cursor = self.conn.cursor()
        cursor.execute("SELECT auth_token FROM fighters WHERE name = ? AND network = ?", (name, network))
        row = cursor.fetchone()
        if row and row['auth_token'] == provided_token:
            logger.debug(f"Authentication SUCCESS for {name}.")
            return True
        logger.warning(f"Authentication FAILED for {name} (Token mismatch or non-existent user).")
        return False

    # --- SysAdmin CLI Methods ---
    def list_fighters(self, network=None):
        logger.debug(f"Fetching fighter list. Filter Network: {network}")
        cursor = self.conn.cursor()
        if network:
            cursor.execute("SELECT name, network, elo, wins, losses, credits FROM fighters WHERE network = ? ORDER BY elo DESC", (network,))
        else:
            cursor.execute("SELECT name, network, elo, wins, losses, credits FROM fighters ORDER BY elo DESC")
        return cursor.fetchall()

    def add_credits(self, name, network, amount, is_spectator=False):
        logger.info(f"Modifying economy: Adding {amount} credits to {name} on {network} (Spectator: {is_spectator})")
        cursor = self.conn.cursor()
        table = "spectators" if is_spectator else "fighters"
        target_col = "nick" if is_spectator else "name"
        
        cursor.execute(f"UPDATE {table} SET credits = credits + ? WHERE {target_col} = ? AND network = ?", 
                       (amount, name, network))
        self.conn.commit()
        success = cursor.rowcount > 0
        if not success:
            logger.warning(f"Economy modification failed: Entity {name} not found.")
        return success

    def delete_fighter(self, name, network):
        logger.warning(f"Executing database DELETE for fighter {name} on {network}")
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM fighters WHERE name = ? AND network = ?", (name, network))
        self.conn.commit()
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Successfully deleted {name}.")
        else:
            logger.warning(f"Delete failed: {name} not found.")
        return success

    def trigger_epoch_reset(self):
        logger.critical("EPOCH RESET INITIATED. Wiping stats for all fighters across all networks.")
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE fighters SET 
            elo = 1200, 
            wins = 0, 
            losses = 0, 
            alignment = 0, 
            credits = 0,
            status = 'ACTIVE'
        ''')
        self.conn.commit()
        logger.critical("EPOCH RESET COMPLETE. All fighter stats returned to baseline.")

# --- CLI Management Interface ---
def main():
    parser = argparse.ArgumentParser(description="AutomataArena SQLite Database Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: init
    subparsers.add_parser("init", help="Initialize the database schema")

    # Command: list
    list_parser = subparsers.add_parser("list", help="List all registered fighters")
    list_parser.add_argument("--network", type=str, help="Filter by IRC network")

    # Command: grant
    grant_parser = subparsers.add_parser("grant", help="Grant credits to a fighter or spectator")
    grant_parser.add_argument("name", type=str, help="Target nickname")
    grant_parser.add_argument("network", type=str, help="Target network (e.g., 2600net)")
    grant_parser.add_argument("amount", type=int, help="Amount of credits to give (can be negative)")
    grant_parser.add_argument("--spectator", action="store_true", help="Flag if target is a spectator, not a fighter")

    # Command: delete
    delete_parser = subparsers.add_parser("delete", help="Permanently delete a fighter")
    delete_parser.add_argument("name", type=str, help="Fighter's nickname")
    delete_parser.add_argument("network", type=str, help="Fighter's network")

    # Command: epoch-reset
    subparsers.add_parser("epoch-reset", help="DANGER: Resets all Elo and stats for a new season")

    args = parser.parse_args()
    db = ArenaDB()

    if args.command == "init":
        db.init_schema()
        print("[*] Database schema initialized.")
    elif args.command == "list":
        fighters = db.list_fighters(args.network)
        print(f"\n--- Registered Fighters ({len(fighters)}) ---")
        print(f"{'Name':<15} | {'Network':<10} | {'Elo':<6} | {'W/L':<7} | {'Credits'}")
        print("-" * 55)
        for f in fighters:
            wl = f"{f['wins']}/{f['losses']}"
            print(f"{f['name']:<15} | {f['network']:<10} | {f['elo']:<6} | {wl:<7} | {f['credits']}")
        print()
    elif args.command == "grant":
        success = db.add_credits(args.name, args.network, args.amount, args.spectator)
        if success:
            target_type = "Spectator" if args.spectator else "Fighter"
            verb = "Granted" if args.amount > 0 else "Removed"
            print(f"[*] {verb} {abs(args.amount)} credits to {target_type} '{args.name}' on {args.network}.")
        else:
            print(f"[!] Could not find target '{args.name}' on '{args.network}'.")
    elif args.command == "delete":
        confirm = input(f"Are you sure you want to delete {args.name} on {args.network}? (y/N): ")
        if confirm.lower() == 'y':
            if db.delete_fighter(args.name, args.network):
                print(f"[*] Fighter '{args.name}' purged from the grid.")
            else:
                print(f"[!] Fighter '{args.name}' not found.")
        else:
            print("[*] Aborted.")
    elif args.command == "epoch-reset":
        confirm = input("DANGER: This will wipe all Elo, Wins, and Credits. Proceed? (Type 'RESET'): ")
        if confirm == "RESET":
            db.trigger_epoch_reset()
            print("[*] Epoch Reset complete.")
        else:
            print("[*] Epoch Reset aborted.")
    else:
        parser.print_help()

    db.close()

if __name__ == "__main__":
    main()
