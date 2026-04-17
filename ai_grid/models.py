from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Float
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

# ==========================================
# 1. GRID NODES & TOPOLOGY
# ==========================================
class GridNode(Base):
    __tablename__ = 'grid_nodes'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String)
    node_type = Column(String, default="wilderness")  # wilderness, arena, merchant, safezone
    owner_character_id = Column(Integer, ForeignKey('characters.id', use_alter=True, name="fk_grid_owner"), nullable=True)
    upgrade_level = Column(Integer, default=1)
    
    power_stored = Column(Float, default=0.0)
    power_consumed = Column(Float, default=0.0)
    power_generated = Column(Float, default=0.0)
    durability = Column(Float, default=100.0)
    threat_level = Column(Integer, default=0)  # 0=safe, 1-3=wilderness mob tier
    is_spawn_node = Column(Boolean, default=False, index=True)
    noise = Column(Float, default=0.0) # SIGINT failure tracking (Heat)
    
    # Discovery & Network Mapping
    is_hidden = Column(Boolean, default=False)
    availability_mode = Column(String, default='OPEN') # OPEN, CLOSED
    is_darknet = Column(Boolean, default=False)
    irc_affinity = Column(String, nullable=True) # Mapping to IRC Network (e.g. Rizon)
    local_network = Column(String, nullable=True) # Named subnet for power pooling
    
    # Hardware & Infrastructure
    addons_json = Column(String, default="{}") # JSON storage for AMP, FIREWALL, IDS, NET
    
    # Relationships
    owner = relationship("Character", foreign_keys=[owner_character_id], post_update=True)
    characters_present = relationship("Character", foreign_keys="[Character.node_id]", back_populates="current_node")
    # Connections as source
    exits = relationship("NodeConnection", foreign_keys="[NodeConnection.source_node_id]", back_populates="source_node")

class NodeConnection(Base):
    __tablename__ = 'node_connections'
    
    id = Column(Integer, primary_key=True)
    source_node_id = Column(Integer, ForeignKey('grid_nodes.id'))
    target_node_id = Column(Integer, ForeignKey('grid_nodes.id'))
    direction = Column(String) # e.g., 'north', 'port_80', 'ssh_tunnel'
    is_hidden = Column(Boolean, default=False)
    
    source_node = relationship("GridNode", foreign_keys=[source_node_id], back_populates="exits")
    target_node = relationship("GridNode", foreign_keys=[target_node_id])

# ==========================================
# 2. PLAYER PROGRESSION & IDENTITY
# ==========================================
class Player(Base):
    __tablename__ = 'players'
    
    id = Column(Integer, primary_key=True)
    global_name = Column(String, unique=True)
    is_autonomous = Column(Boolean, default=False) # True if driven by LLM
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    aliases = relationship("NetworkAlias", back_populates="player", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="player", cascade="all, delete-orphan")

class NetworkAlias(Base):
    __tablename__ = 'network_aliases'
    
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'))
    network_name = Column(String, nullable=False) # e.g., '2600net', 'rizon'
    nickname = Column(String, nullable=False)
    
    player = relationship("Player", back_populates="aliases")

class Character(Base):
    __tablename__ = 'characters'
    
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'))
    node_id = Column(Integer, ForeignKey('grid_nodes.id'), nullable=True)
    
    name = Column(String, nullable=False)
    race = Column(String, nullable=False)
    char_class = Column(String, nullable=False)
    bio = Column(String, nullable=True)
    
    # Progression
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    credits = Column(Float, default=0.0)
    current_hp = Column(Integer, default=25)
    elo = Column(Integer, default=1200) # Arena rating
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    status = Column(String, default='ACTIVE')
    auth_token = Column(String, nullable=True)
    daily_tasks = Column(String, default='{}')
    prefs = Column(String, default='{"output_mode":"human","ids_notify":true,"firewall_notify":true,"alert_method":"notice","auto_sell_trash":false,"tutorial_mode":true,"reminders":true}')
    
    # Core Attributes
    cpu = Column(Integer, default=5) # Physical/Kinetic
    ram = Column(Integer, default=5) # Health/Tankiness
    bnd = Column(Integer, default=5) # Speed/Evasion (Bandwidth)
    sec = Column(Integer, default=5) # Defense/Resist
    alg = Column(Integer, default=5) # Magic/Hacking capability
    
    # Resource Stats
    power = Column(Float, default=100.0)
    stability = Column(Float, default=100.0)
    alignment = Column(Integer, default=0) # Ethics: -100 to 100
    data_units = Column(Float, default=0.0) # Raw fodder for The Gibson
    alg_bonus = Column(Integer, default=0) # Temporary boost for next hack
    ice_lockdown_until = Column(DateTime, nullable=True) # CipherLock penalty
    
    # Activity & Retention (IdleRPG)
    total_chat_messages = Column(Integer, default=0)
    total_idle_seconds = Column(Float, default=0.0)
    pending_stat_points = Column(Integer, default=0)
    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    player = relationship("Player", back_populates="characters")
    current_node = relationship("GridNode", foreign_keys=[node_id], back_populates="characters_present")
    inventory = relationship("InventoryItem", back_populates="owner", cascade="all, delete-orphan")

# ==========================================
# 3. DISCOVERY & MAPPING
# ==========================================
class DiscoveryRecord(Base):
    __tablename__ = 'discovery_records'
    
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'), index=True)
    node_id = Column(Integer, ForeignKey('grid_nodes.id'), index=True)
    intel_level = Column(String) # 'EXPLORE' (Topological), 'PROBE' (Deep)
    discovered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    character = relationship("Character", foreign_keys=[character_id])
    node = relationship("GridNode", foreign_keys=[node_id])

class BreachRecord(Base):
    __tablename__ = 'breach_records'
    
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'), index=True)
    node_id = Column(Integer, ForeignKey('grid_nodes.id'), index=True)
    breached_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    character = relationship("Character", foreign_keys=[character_id])
    node = relationship("GridNode", foreign_keys=[node_id])

# ==========================================
# 4. INVENTORY SYSTEM
# ==========================================
class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    item_type = Column(String) # weapon, consumable, armor, hack
    base_value = Column(Integer, default=0)
    is_darknet = Column(Boolean, default=False)
    effects_json = Column(String, default="{}") # e.g., '{"heal": 15}'

class InventoryItem(Base):
    __tablename__ = 'inventory_items'
    
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'))
    template_id = Column(Integer, ForeignKey('item_templates.id'))
    quantity = Column(Integer, default=1)
    durability = Column(Float, default=100.0)
    
    owner = relationship("Character", back_populates="inventory")
    template = relationship("ItemTemplate")

# ==========================================
# 4. MAINFRAME MANUFACTURING (THE GIBSON)
# ==========================================
class MainframeTask(Base):
    __tablename__ = 'mainframe_tasks'
    
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=False)
    task_type = Column(String, nullable=False) # COMPILE, ASSEMBLE
    amount = Column(Integer, default=1) # Target yield
    completion_time = Column(DateTime, nullable=False)
    is_collected = Column(Boolean, default=False)
    
    owner = relationship("Character")

# ==========================================
# 5. GLOBAL ECONOMY & MINI-GAMES
# ==========================================
class AuctionListing(Base):
    __tablename__ = 'auction_listings'
    
    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey('characters.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('inventory_items.id'), nullable=False)
    current_bid = Column(Integer, default=0)
    highest_bidder_id = Column(Integer, ForeignKey('characters.id'), nullable=True)
    end_time = Column(DateTime, nullable=False)
    is_darknet = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    seller = relationship("Character", foreign_keys=[seller_id])
    highest_bidder = relationship("Character", foreign_keys=[highest_bidder_id])
    item = relationship("InventoryItem")

class Leaderboard(Base):
    __tablename__ = 'leaderboards'
    
    id = Column(Integer, primary_key=True)
    category = Column(String, nullable=False) # DICE, ARENA, GIBSON, WEALTH
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=False)
    score = Column(Float, default=0.0)
    
    character = relationship("Character")

class CipherSession(Base):
    __tablename__ = 'cipher_sessions'
    
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=False)
    target_sequence = Column(String, nullable=False)
    attempts_remaining = Column(Integer, default=5)
    node_id = Column(Integer, ForeignKey('grid_nodes.id'), nullable=False)
    is_active = Column(Boolean, default=True)
    
    character = relationship("Character")
    node = relationship("GridNode")

class GlobalMarket(Base):
    __tablename__ = 'global_market'
    
    id = Column(Integer, primary_key=True)
    item_type = Column(String, nullable=False) # junk, hack, weapon, gear
    multiplier = Column(Float, default=1.0)
    last_event = Column(String) # For flavor news

class Memo(Base):
    __tablename__ = 'memos'
    
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('characters.id'), nullable=True) # Null = System
    recipient_id = Column(Integer, ForeignKey('characters.id'), nullable=False)
    message = Column(String, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_read = Column(Boolean, default=False)
    source_node_id = Column(Integer, ForeignKey('grid_nodes.id'), nullable=True)
    
    recipient = relationship("Character", foreign_keys=[recipient_id])
    sender = relationship("Character", foreign_keys=[sender_id])
    source_node = relationship("GridNode")
