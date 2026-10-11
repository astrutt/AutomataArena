# economy_repo.py
from sqlalchemy.future import select
import datetime
from sqlalchemy.orm import selectinload
from ai_grid.models import Character, Player, NetworkAlias, ItemTemplate, InventoryItem, GridNode, GlobalMarket, AuctionListing
from ai_grid.database.core import logger

class EconomyRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_craft_menu(self):
        return (
            "CRAFT_MENU: vuln=10 DATA -> 1 Vulnerability | "
            "zeroday T1=50 DATA + 5 Vulns | T2=200 DATA + 15 Vulns | "
            "T3=500 DATA + 35 Vulns | T4=1200 DATA + 80 Vulns"
        )

    async def craft_item(self, name: str, network: str, recipe: str = None, tier: int = None):
        recipe_key = (recipe or "").strip().lower()
        if not recipe_key or recipe_key in {"menu", "help", "list"}:
            menu = await self.get_craft_menu()
            return {"success": True, "item": "MENU", "menu": menu}

        tier_map = {
            1: {"name": "ZeroDay_Chain", "data": 50, "vulns": 5},
            2: {"name": "ZeroDay_Chain", "data": 200, "vulns": 15},
            3: {"name": "ZeroDay_Chain", "data": 500, "vulns": 35},
            4: {"name": "ZeroDay_Chain", "data": 1200, "vulns": 80},
        }

        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return {"success": False, "error": "Character not found."}

            if recipe_key in {"vuln", "vulnerability"}:
                data_needed = 10.0
                if char.data_units < data_needed:
                    return {"success": False, "error": f"Insufficient DATA. Required: {data_needed} | Available: {char.data_units:.1f}"}
                char.data_units -= data_needed
                item_name = "Vulnerability"
                item_template = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == item_name))).scalars().first()
                if not item_template:
                    item_template = ItemTemplate(name=item_name, item_type="hack", base_value=500, effects_json='{"alg_boost": 5}')
                    session.add(item_template)
                    await session.flush()
                existing = next((i for i in char.inventory if i.template and i.template.name == item_name), None)
                if existing:
                    existing.quantity += 1
                else:
                    session.add(InventoryItem(character_id=char.id, template_id=item_template.id, quantity=1))
                await session.commit()
                return {"success": True, "item": item_name, "crafted": 1, "data_spent": data_needed}

            if recipe_key in {"zeroday", "zero-day", "0day", "chain", "zeroday_chain"}:
                try:
                    tier_num = int(tier) if tier is not None else 1
                except (TypeError, ValueError):
                    return {"success": False, "error": "Specify tier 1, 2, 3, or 4."}
                recipe_data = tier_map.get(tier_num)
                if not recipe_data:
                    return {"success": False, "error": "Zero-Day tier must be 1, 2, 3, or 4."}

                vuln_count = sum(i.quantity for i in char.inventory if i.template and i.template.name == "Vulnerability")
                if vuln_count < recipe_data["vulns"]:
                    return {"success": False, "error": f"Insufficient Vulnerabilities. Required: {recipe_data['vulns']} | Available: {vuln_count}"}

                if char.data_units < recipe_data["data"]:
                    return {"success": False, "error": f"Insufficient DATA. Required: {recipe_data['data']} | Available: {char.data_units:.1f}"}

                char.data_units -= float(recipe_data["data"])
                remaining_vulns = recipe_data["vulns"]
                for item in list(char.inventory):
                    if not item.template or item.template.name != "Vulnerability":
                        continue
                    if remaining_vulns <= 0:
                        break
                    used = min(item.quantity, remaining_vulns)
                    item.quantity -= used
                    remaining_vulns -= used
                    if item.quantity <= 0:
                        await session.delete(item)

                item_name = "ZeroDay_Chain"
                item_template = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == item_name))).scalars().first()
                if not item_template:
                    item_template = ItemTemplate(name=item_name, item_type="hack", base_value=2500, is_darknet=True, effects_json='{"alg_boost": 15}')
                    session.add(item_template)
                    await session.flush()
                existing = next((i for i in char.inventory if i.template and i.template.name == item_name), None)
                if existing:
                    existing.quantity += 1
                else:
                    session.add(InventoryItem(character_id=char.id, template_id=item_template.id, quantity=1))

                await session.commit()
                return {"success": True, "item": item_name, "tier": tier_num, "data_spent": recipe_data["data"], "vulns_spent": recipe_data["vulns"]}

            return {"success": False, "error": f"Unknown recipe '{recipe}'. Use !a craft for the recipe menu."}

    async def list_shop_items(self, is_darknet: bool = False):
        async with self.async_session() as session:
            stmt = select(ItemTemplate).where(ItemTemplate.is_darknet == is_darknet).order_by(ItemTemplate.base_value.asc())
            result = await session.execute(stmt)
            return [{'name': t.name, 'type': t.item_type, 'cost': t.base_value} for t in result.scalars().all()]

            await session.commit()

    async def award_credits(self, nick: str, network: str, amt: float):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == nick,
                NetworkAlias.nickname == nick,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if char:
                char.credits += amt
                await session.commit()

    async def award_credits_bulk(self, payouts: dict, network: str):
        """Awards credits to multiple nicknames in a single transaction."""
        async with self.async_session() as session:
            for nick, amt in payouts.items():
                stmt = select(Character).join(Player).join(NetworkAlias).where(
                    Character.name == nick,
                    NetworkAlias.nickname == nick,
                    NetworkAlias.network_name == network
                )
                char = (await session.execute(stmt)).scalars().first()
                if char:
                    char.credits += amt
            await session.commit()

    async def award_data(self, nick: str, network: str, amt: float):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == nick,
                NetworkAlias.nickname == nick,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if char:
                char.data_units += amt
                await session.commit()

    async def process_transaction(self, name: str, network: str, action: str, item_name: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char: return False, "System offline: Player not found."
            
            # Availability Check: Owner bypass
            if char.current_node.availability_mode == "CLOSED" and char.current_node.owner_character_id != char.id:
                return False, "[GRID][SITREP] STATUS=CLOSED | MSG=Grid is CLOSED. Grid exploration, or more may be required to open it."

            if not char.current_node or char.current_node.node_type not in ("merchant", "npc_trade", "trade"):
                return False, "Transaction Failed: No merchant in this node."

            from ai_grid.database.repositories.reputation_repo import rep_status, clean_region_key, _safe_float
            rep_map = {clean_region_key(k): _safe_float(v) for k, v in (char.node_rep or {}).items() if clean_region_key(k)}
            raw_reg = str(char.current_node.region_type or char.current_node.node_type or "")
            region = clean_region_key(raw_reg)
            fallback_key = clean_region_key(char.current_node.node_type) if char.current_node.node_type else ""
            rep_score = _safe_float(rep_map.get(region, rep_map.get(fallback_key, 0.0)))
            if rep_score == 0.0 and region in ("VOD", "", "MERCHANT", "NPC_TRADE", "TRADE"):
                if "MERCHANT" in rep_map:
                    rep_score = _safe_float(rep_map["MERCHANT"])
                elif rep_map:
                    if any(rep_status(_safe_float(v)) == "Hostile" for v in rep_map.values()):
                        rep_score = min(_safe_float(v) for v in rep_map.values())
                    elif any(rep_status(_safe_float(v)) == "Trusted" for v in rep_map.values()):
                        rep_score = max(_safe_float(v) for v in rep_map.values())

            status = rep_status(rep_score)
            if status == "Hostile":
                return False, "Merchant Lockout: Merchants refuse to trade with hostile operatives."
                
            stmt_item = select(ItemTemplate).where(ItemTemplate.name.ilike(item_name))
            result = await session.execute(stmt_item)
            tpl = result.scalars().first()
            if not tpl: return False, f"Unknown item: '{item_name}'"
            
            if action == "buy":
                # Apply market multiplier
                stmt_market = select(GlobalMarket).where(GlobalMarket.item_type == tpl.item_type)
                market = (await session.execute(stmt_market)).scalars().first()
                mult = market.multiplier if market else 1.0
                
                total_cost = int(tpl.base_value * mult)
                if status == "Trusted":
                    total_cost = max(1, int(total_cost * 0.85))
                if char.credits < total_cost:
                    return False, f"Insufficient credits. {tpl.name} currently costs {total_cost}c (Market Mult: {mult:.2f}x)."
                char.credits -= total_cost
                
                existing = next((i for i in char.inventory if i.template_id == tpl.id), None)
                if existing:
                    existing.quantity += 1
                else:
                    new_item = InventoryItem(character_id=char.id, template_id=tpl.id)
                    session.add(new_item)
                
                await session.commit()
                return True, f"Purchased {tpl.name} for {total_cost}c. Balance: {char.credits}c."
            
            elif action == "sell":
                existing = next((i for i in char.inventory if i.template_id == tpl.id and i.quantity > 0), None)
                if not existing:
                    return False, f"You do not possess a {tpl.name}."
                
                # Apply market multiplier
                stmt_market = select(GlobalMarket).where(GlobalMarket.item_type == tpl.item_type)
                market = (await session.execute(stmt_market)).scalars().first()
                mult = market.multiplier if market else 1.0
                
                base_sell = int(tpl.base_value * 0.5 * mult)
                if status == "Trusted":
                    sell_price = max(1, int(base_sell * 1.15))
                else:
                    sell_price = max(1, base_sell)
                char.credits += sell_price
                existing.quantity -= 1
                if existing.quantity <= 0:
                    await session.delete(existing)
                
                await session.commit()
                return True, f"Sold {tpl.name} for {sell_price}c. Balance: {char.credits}c."
            return False, "Invalid action."

    async def use_item(self, name: str, network: str, item_name: str) -> (bool, str):
        """Consume an item for a temporary effect."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Character offline."

            item = next((i for i in char.inventory if i.template.name.lower() == item_name.lower() and i.quantity > 0), None)
            if not item: return False, f"You do not have a '{item_name}'."

            msg = ""
            if item.template.name == "Vulnerability":
                char.alg_bonus = 5
                msg = "Buffer Override Engaged. Hacking systems will be 25% easier for your next attempt (+5 Alg Bonus)."
            elif item.template.name == "ZeroDay_Chain":
                char.alg_bonus = 15
                msg = "ZERO-DAY EXPLOIT ARMED. The next system you touch will surrender immediately (+15 Alg Bonus)."
            else:
                return False, f"Item '{item.template.name}' cannot be consumed."

            item.quantity -= 1
            if item.quantity <= 0:
                await session.delete(item)
            
            await session.commit()
            return True, msg

    # --- DARKNET AUCTIONS ---
    async def list_active_auctions(self, is_darknet: bool = False) -> list:
        async with self.async_session() as session:
            stmt = select(AuctionListing).where(
                AuctionListing.is_active == True,
                AuctionListing.is_darknet == is_darknet
            ).options(
                selectinload(AuctionListing.seller),
                selectinload(AuctionListing.highest_bidder),
                selectinload(AuctionListing.item).selectinload(InventoryItem.template)
            ).order_by(AuctionListing.end_time.asc())
            listings = (await session.execute(stmt)).scalars().all()
            return [{
                "id": l.id,
                "item": l.item.template.name,
                "seller": l.seller.name,
                "current_bid": l.current_bid,
                "high_bidder": l.highest_bidder.name if l.highest_bidder else "None",
                "ends_in_min": int((l.end_time - datetime.datetime.now(datetime.timezone.utc)).total_seconds() // 60)
            } for l in listings]

    async def create_auction(self, name: str, network: str, item_name: str, start_bid: int, dur_mins: int = 1440) -> (bool, str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Character offline."
            
            # DarkNet Check: List as DarkNet if node is DarkNet
            is_darknet_node = char.current_node.is_darknet if char.current_node else False
            
            # Availability Check: Owner bypass
            if char.current_node.availability_mode == "CLOSED" and char.current_node.owner_character_id != char.id:
                return False, "[GRID][SITREP] STATUS=CLOSED | MSG=Grid is CLOSED. Grid exploration, or more may be required to open it."

            item = next((i for i in char.inventory if i.template.name.lower() == item_name.lower() and i.quantity > 0), None)
            if not item: return False, f"Item '{item_name}' not found in your inventory."

            # Move item out of inventory (or mark it? for now we decrement quantity)
            if item.quantity > 1:
                item.quantity -= 1
                # Create a specific instance for the auction
                auction_item = InventoryItem(character_id=None, template_id=item.template_id, quantity=1)
                session.add(auction_item)
                await session.flush()
                item_to_list = auction_item
            else:
                item_to_list = item
                item_to_list.character_id = None # Decouple from player

            end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=dur_mins)
            new_listing = AuctionListing(
                seller_id=char.id,
                item_id=item_to_list.id,
                current_bid=start_bid,
                end_time=end_time,
                is_darknet=is_darknet_node
            )
            session.add(new_listing)
            await session.commit()
            market_type = "Underground" if is_darknet_node else "Public"
            return True, f"Listed {item_name} on {market_type} Auction. Starting Bid: {start_bid}c. Expires in {dur_mins}m."

    async def bid_on_auction(self, name: str, network: str, auction_id: int, bid_amt: int) -> (bool, str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Character offline."

            listing_stmt = select(AuctionListing).where(AuctionListing.id == auction_id, AuctionListing.is_active == True).options(selectinload(AuctionListing.highest_bidder))
            listing = (await session.execute(listing_stmt)).scalars().first()
            if not listing: return False, f"Auction #{auction_id} is not active."
            
            # Context Validation
            if listing.is_darknet and (not char.current_node or not char.current_node.is_darknet):
                return False, "Access Denied: DarkNet auctions require physical presence at an underground terminal."
            
            # Availability Check: Owner bypass (at the bidder's node)
            if char.current_node.availability_mode == "CLOSED" and char.current_node.owner_character_id != char.id:
                return False, "[GRID][SITREP] STATUS=CLOSED | MSG=Grid is CLOSED. Grid exploration, or more may be required to open it."
            
            if listing.seller_id == char.id: return False, "You cannot bid on your own listing."
            if bid_amt <= listing.current_bid: return False, f"Bid must be higher than current bid: {listing.current_bid}c."
            if char.credits < bid_amt: return False, f"Insufficient credits. You only have {char.credits}c."

            # Return credits to old bidder
            if listing.highest_bidder:
                listing.highest_bidder.credits += listing.current_bid
            
            char.credits -= bid_amt
            listing.current_bid = bid_amt
            listing.highest_bidder_id = char.id
            
            await session.commit()
            return True, f"Successfully bid {bid_amt}c on Auction #{auction_id}."

    async def tick_auctions(self) -> list:
        """Process expired auctions. Returns list of notifications."""
        notifications = []
        async with self.async_session() as session:
            now = datetime.datetime.now(datetime.timezone.utc)
            stmt = select(AuctionListing).where(AuctionListing.end_time <= now, AuctionListing.is_active == True).options(
                selectinload(AuctionListing.seller).selectinload(Character.player).selectinload(Player.aliases),
                selectinload(AuctionListing.highest_bidder).selectinload(Character.player).selectinload(Player.aliases),
                selectinload(AuctionListing.item).selectinload(InventoryItem.template)
            )
            expired = (await session.execute(stmt)).scalars().all()
            
            for l in expired:
                l.is_active = False
                item_name = l.item.template.name
                
                if l.highest_bidder:
                    # Success
                    fee = int(l.current_bid * 0.01) # 1% Fee as requested
                    payout = l.current_bid - fee
                    l.seller.credits += payout
                    l.item.character_id = l.highest_bidder_id # Transfer item
                    
                    seller_alias = next((a for a in l.seller.player.aliases if a.nickname == l.seller.name), None)
                    winner_alias = next((a for a in l.highest_bidder.player.aliases if a.nickname == l.highest_bidder.name), None)
                    
                    if seller_alias:
                        notifications.append({"nickname": seller_alias.nickname, "network": seller_alias.network_name, "msg": f"AUCTION: Item {item_name} sold for {l.current_bid}c. Payout: {payout}c (1% fee applied)."})
                    if winner_alias:
                        notifications.append({"nickname": winner_alias.nickname, "network": winner_alias.network_name, "msg": f"AUCTION: You won the bid for {item_name} at {l.current_bid}c. Item delivered to inventory."})
                else:
                    # No bids, return item to seller
                    l.item.character_id = l.seller_id
                    seller_alias = next((a for a in l.seller.player.aliases if a.nickname == l.seller.name), None)
                    if seller_alias:
                        notifications.append({"nickname": seller_alias.nickname, "network": seller_alias.network_name, "msg": f"AUCTION: Listing for {item_name} expired with no bids. Item returned."})
                
            await session.commit()
        return notifications

    async def update_market_rates(self, rates: dict, event_text: str = None):
        """Update global market multipliers."""
        async with self.async_session() as session:
            for item_type, mult in rates.items():
                stmt = select(GlobalMarket).where(GlobalMarket.item_type == item_type)
                market = (await session.execute(stmt)).scalars().first()
                if market:
                    market.multiplier = mult
                    if event_text: market.last_event = event_text
                else:
                    new_m = GlobalMarket(item_type=item_type, multiplier=mult, last_event=event_text)
                    session.add(new_m)
            await session.commit()
            
    async def get_market_status(self) -> dict:
        """Get current market multipliers."""
        async with self.async_session() as session:
            stmt = select(GlobalMarket)
            results = (await session.execute(stmt)).scalars().all()
            return {r.item_type: r.multiplier for r in results}

    async def get_global_economy(self) -> dict:
        """Returns total credits in circulation among all characters."""
        async with self.async_session() as session:
            stmt = select(Character)
            all_chars = (await session.execute(stmt)).scalars().all()
            total_creds = sum(c.credits for c in all_chars)
            total_data = sum(c.data_units for c in all_chars)
            return {
                "total_credits": total_creds,
                "total_data_units": total_data,
                "bot_count": len(all_chars)
            }
