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
    owner_alliance_id = Column(Integer, nullable=True) # For Territory Control
    
    # Relationships
    characters_present = relationship("Character", back_populates="current_node")
    # Connections as source
    exits = relationship("NodeConnection", foreign_keys="[NodeConnection.source_node_id]", back_populates="source_node")

class NodeConnection(Base):
    __tablename__ = 'node_connections'
    
    id = Column(Integer, primary_key=True)
    source_node_id = Column(Integer, ForeignKey('grid_nodes.id'))
    target_node_id = Column(Integer, ForeignKey('grid_nodes.id'))
    direction = Column(String) # e.g., 'north', 'port_80', 'ssh_tunnel'
    
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
    elo = Column(Integer, default=1200) # Arena rating
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    status = Column(String, default='ACTIVE')
    auth_token = Column(String, nullable=True)
    
    # Core Attributes
    cpu = Column(Integer, default=5) # Physical/Kinetic
    ram = Column(Integer, default=5) # Health/Tankiness
    bnd = Column(Integer, default=5) # Speed/Evasion (Bandwidth)
    sec = Column(Integer, default=5) # Defense/Resist
    alg = Column(Integer, default=5) # Magic/Hacking capability
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    player = relationship("Player", back_populates="characters")
    current_node = relationship("GridNode", back_populates="characters_present")
    inventory = relationship("InventoryItem", back_populates="owner", cascade="all, delete-orphan")

# ==========================================
# 3. INVENTORY SYSTEM
# ==========================================
class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    item_type = Column(String) # weapon, consumable, armor, hack
    base_value = Column(Integer, default=0)
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
