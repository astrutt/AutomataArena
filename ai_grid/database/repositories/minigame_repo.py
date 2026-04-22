# minigame_repo.py - v1.5.0
import datetime
import random
import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from ai_grid.models import Character, Player, NetworkAlias, GridNode, Leaderboard, CipherSession
from ai_grid.database.core import logger, CONFIG

class MiniGameRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    # --- DICE GAMES ---
    async def roll_dice(self, name: str, network: str, bet: int, choice: str) -> dict:
        """Play a game of 2d6 dice."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return {"error": "Character not found."}
            if char.credits < bet: return {"error": f"Insufficient credits. You only have {char.credits}c."}
            if bet < 10: return {"error": "Minimum bet is 10c."}

            d1, d2 = random.randint(1, 6), random.randint(1, 6)
            total = d1 + d2
            win = False
            payout_mult = 0.0

            if choice.lower() == "high" and total >= 8: 
                win = True; payout_mult = 2.0
            elif choice.lower() == "low" and total <= 6: 
                win = True; payout_mult = 2.0
            elif choice.lower() == "seven" and total == 7: 
                win = True; payout_mult = 5.0

            char.credits -= bet
            msg = f"Rolled {d1} and {d2} (Total: {total}). "
            
            if win:
                gain = int(bet * payout_mult)
                char.credits += gain
                msg += f"WIN! You received {gain}c."
                await self._update_leaderboard(session, char.id, "DICE", float(gain - bet))
            else:
                msg += "LOSS. Better luck next time."
            
            await session.commit()
            return {"success": True, "msg": msg, "total": total, "win": win}

    # --- CIPHERLOCK ---
    async def start_cipher(self, name: str, network: str) -> dict:
        """Initialize a CipherLock session at the current node."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"error": "Cannot access logic gates: Location unknown."}
            
            node = char.current_node
            if node.visibility_mode == 'OPEN':
                return {"error": "This node is already decrypted and OPEN."}

            now = datetime.datetime.now(datetime.timezone.utc)
            if char.ice_lockdown_until and char.ice_lockdown_until > now:
                remaining = (char.ice_lockdown_until - now).total_seconds()
                return {"error": f"ICE LOCKDOWN ACTIVE. Backdoor blocked for {int(remaining//60)}m {int(remaining%60)}s."}

            # Check for existing active session
            old_stmt = select(CipherSession).where(CipherSession.character_id == char.id, CipherSession.is_active == True)
            old_sess = (await session.execute(old_stmt)).scalars().first()
            if old_sess:
                return {"success": True, "msg": f"Session resumed. {old_sess.attempts_remaining} attempts left. Submit your guess.", "resumed": True}

            # Generate new session
            target = "".join([str(random.randint(0, 9)) for _ in range(4)])
            new_sess = CipherSession(
                character_id=char.id,
                node_id=node.id,
                target_sequence=target,
                attempts_remaining=5
            )
            session.add(new_sess)
            await session.commit()
            return {"success": True, "msg": "CIPHERLOCK ENGAGED. Guess the 4-digit sequence (0-9). Example: !a guess 1032. You have 5 attempts.", "resumed": False}

    async def submit_guess(self, name: str, network: str, guess: str) -> dict:
        """Submit a guess for the active CipherLock."""
        if not guess.isdigit() or len(guess) != 4:
            return {"error": "Invalid format. Guess must be a 4-digit sequence (0-9)."}

        async with self.async_session() as session:
            stmt = select(CipherSession).join(Character).join(Player).join(NetworkAlias).where(
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network,
                CipherSession.is_active == True
            ).options(selectinload(CipherSession.node), selectinload(CipherSession.character))
            sess = (await session.execute(stmt)).scalars().first()
            if not sess: return {"error": "No active CipherLock session. Use !a cipher to start one."}

            target = sess.target_sequence
            hits = 0 # Right digit, right spot
            near = 0 # Right digit, wrong spot
            
            target_list = list(target)
            guess_list = list(guess)
            
            # Find hits
            for i in range(4):
                if guess_list[i] == target_list[i]:
                    hits += 1
                    target_list[i] = None # Mark as used
                    guess_list[i] = "X"
            
            # Find near matches
            for i in range(4):
                if guess_list[i] != "X":
                    if guess_list[i] in target_list:
                        near += 1
                        target_list[target_list.index(guess_list[i])] = None 

            sess.attempts_remaining -= 1
            char = sess.character
            node = sess.node

            if hits == 4:
                sess.is_active = False
                node.visibility_mode = "OPEN"
                c_reward = node.upgrade_level * 100
                d_reward = 25.0
                char.credits += c_reward
                char.data_units += d_reward
                await session.commit()
                return {
                    "success": True, 
                    "msg": f"ACCESS GRANTED. Sequence matched! Node {node.name} is now OPEN. Rewards: {c_reward}c and {d_reward} data units extracted.",
                    "complete": True
                }
            
            if sess.attempts_remaining <= 0:
                sess.is_active = False
                # ICE Lockdown
                penalty_min = 15
                char.ice_lockdown_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=penalty_min)
                await session.commit()
                return {"success": False, "msg": f"ACCESS DENIED. Attempts exhausted. ICE Lockdown triggered for {penalty_min} minutes.", "complete": True}

            await session.commit()
            return {
                "success": True, 
                "msg": f"Result: {hits} Hits (Correct pos) | {near} Near (Wrong pos). Attempts left: {sess.attempts_remaining}",
                "complete": False
            }

    # --- LEADERBOARD ---
    async def get_leaderboard(self, category: str) -> list:
        """Get top 10 records for a category."""
        async with self.async_session() as session:
            stmt = select(Leaderboard).where(Leaderboard.category == category.upper()).order_by(Leaderboard.score.desc()).limit(10).options(selectinload(Leaderboard.character))
            results = (await session.execute(stmt)).scalars().all()
            return [{"name": r.character.name, "score": r.score} for r in results]

    async def _update_leaderboard(self, session, char_id, category, score_delta):
        stmt = select(Leaderboard).where(Leaderboard.character_id == char_id, Leaderboard.category == category.upper())
        entry = (await session.execute(stmt)).scalars().first()
        if entry:
            entry.score += score_delta
        else:
            entry = Leaderboard(character_id=char_id, category=category.upper(), score=score_delta)
            session.add(entry)
