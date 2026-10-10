# ai_grid/core/handlers/skills.py
import asyncio
from ai_grid.grid_utils import format_text, tag_msg, C_CYAN, C_GREEN, C_YELLOW, C_RED, C_WHITE
from ai_grid.core.handlers.base import get_action_routing
from ai_grid.database.repositories.skill_repo import ALL_SKILLS, SKILL_DEFINITIONS, MAX_CONCURRENT_SKILLS, MAX_SKILL_LEVEL, SESSIONS_PER_LEVEL


async def handle_skill(node, nick: str, args: list, reply_target: str):
    """
    Main router for player skill commands:
    - skill list: List available and learned skills with levels and bonuses.
    - skill <name>: Display description, level, and current training progress for a specific skill.
    - skill start <name>: Begin learning an available skill (up to 4-slot limit).
    - skill train: Perform a training session (1 session/hr limit, 24 sessions/lvl milestone).
    - skill forget <name>: Remove a skill and free its slot.
    - skill quit: Pause/quit training session without forgetting the learned skill.
    Supports formatted responses for human, text, and narrative modes.
    """
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)

    # Determine mode: human, text (machine), or narrative
    prefs = {}
    if hasattr(node, 'db') and hasattr(node.db, 'get_prefs'):
        try:
            res = node.db.get_prefs(nick, getattr(node, 'net_name', 'default'))
            if asyncio.iscoroutine(res) or hasattr(res, '__await__'):
                prefs = await res
            elif isinstance(res, dict):
                prefs = res
        except Exception:
            prefs = {}

    raw_mode = prefs.get('output_mode', 'human').lower() if isinstance(prefs, dict) else 'human'
    if raw_mode in ['machine', 'text']:
        output_mode = 'text'
    elif raw_mode == 'narrative':
        output_mode = 'narrative'
    else:
        output_mode = 'human'

    if not args or not args[0].strip():
        # Default: show skill list
        await _handle_skill_list(node, nick, private_target, reply_method, output_mode)
        return

    sub = args[0].lower().strip()

    if sub == "list":
        await _handle_skill_list(node, nick, private_target, reply_method, output_mode)
    elif sub == "start":
        target_skill = args[1].lower().strip() if len(args) > 1 else None
        await _handle_skill_start(node, nick, target_skill, private_target, reply_method, output_mode)
    elif sub == "train":
        await _handle_skill_train(node, nick, private_target, reply_method, output_mode)
    elif sub == "forget":
        target_skill = args[1].lower().strip() if len(args) > 1 else None
        await _handle_skill_forget(node, nick, target_skill, private_target, reply_method, output_mode)
    elif sub in ["quit", "pause", "stop"]:
        await _handle_skill_quit(node, nick, private_target, reply_method, output_mode)
    elif sub in ["help", "?"]:
        await _handle_skill_help(node, nick, private_target, reply_method, output_mode)
    elif sub == "info":
        target_skill = args[1].lower().strip() if len(args) > 1 else None
        if target_skill and target_skill in ALL_SKILLS:
            await _handle_skill_info(node, nick, target_skill, private_target, reply_method, output_mode)
        elif target_skill:
            await _send_unknown_command(node, nick, target_skill, private_target, reply_method, output_mode)
        else:
            await _handle_skill_list(node, nick, private_target, reply_method, output_mode)
    elif sub in ALL_SKILLS:
        await _handle_skill_info(node, nick, sub, private_target, reply_method, output_mode)
    else:
        # Unknown sub-verb or unknown skill name
        await _send_unknown_command(node, nick, sub, private_target, reply_method, output_mode)


async def _handle_skill_list(node, nick: str, private_target: str, reply_method: str, mode: str):
    data = await node.db.get_character_skills(nick, node.net_name)
    if not data or "error" in data:
        err = data.get("error", "Character not found.") if isinstance(data, dict) else "Character not found."
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"[ERR] {err}", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILLS][RESULT:ERR][NICK:{nick}] MSG:{err.upper().replace(' ', '_')}",
            narrative=f"[GRID][NARRATIVE] System error: {err}"
        )
        return

    learned = data.get("skills", [])
    slots_used = data.get("slots_used", 0)
    slots_max = data.get("slots_max", MAX_CONCURRENT_SKILLS)
    learned_names = {s["skill_name"] for s in learned}
    available_names = [s for s in ALL_SKILLS if s not in learned_names]

    if mode == "text":
        learned_entries = []
        for s in learned:
            active_tag = "MAXED" if s["level"] >= s["max_level"] else ("ACTIVE" if s["is_active"] else "PAUSED")
            learned_entries.append(f"{s['skill_name'].upper()}:L{s['level']}:{s['training_sessions']}/{s['max_sessions']}:{active_tag}")
        learned_str = f"[{','.join(learned_entries)}]" if learned_entries else "[]"
        avail_str = f"[{','.join(s.upper() for s in available_names)}]"
        msg = f"[GRID][ACTION:SKILLS][RESULT:LIST][NICK:{nick}] SLOTS:{slots_used}/{slots_max} LEARNED:{learned_str} AVAILABLE:{avail_str}"
        await node.send(f"{reply_method} {private_target} :{msg}")

    elif mode == "narrative":
        if learned:
            learned_desc = []
            for s in learned:
                state = "mastered" if s["level"] >= s["max_level"] else ("compiling" if s["is_active"] else "idle")
                learned_desc.append(f"{s['display_name']} (Level {s['level']}, {s['training_sessions']}/{s['max_sessions']} sessions, {state})")
            learned_text = ", ".join(learned_desc)
        else:
            learned_text = "No skills learned yet"

        avail_text = ", ".join(available_names) if available_names else "none"
        msg = (
            f"[GRID][NARRATIVE] {nick} queries neural subroutines. "
            f"Active algorithms: {learned_text}. "
            f"{slots_used} of {slots_max} memory banks occupied. "
            f"Available subroutines: {avail_text}."
        )
        await node.send(f"{reply_method} {private_target} :{msg}")

    else:
        # Human mode
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'=== [CHARACTER SKILLS ({slots_used}/{slots_max})] ===', C_CYAN, bold=True), action='SKILL', nick=nick)}")
        if learned:
            for s in learned:
                if s["level"] >= s["max_level"]:
                    status_tag = format_text("[MAX]", C_GREEN, bold=True)
                else:
                    status_tag = format_text("[TRAINING]", C_GREEN) if s["is_active"] else format_text("[PAUSED]", C_YELLOW)
                line = (
                    f"• {format_text(s['display_name'], C_WHITE, bold=True)} ({s['skill_name']}): "
                    f"Level {s['level']}/{s['max_level']} ({s['training_sessions']}/{s['max_sessions']} sess) {status_tag} "
                    f"| {format_text(s['effect'], C_CYAN)}"
                )
                await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='SKILL', nick=nick)}")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg('No skills learned. Use !a skill start <name> to begin.', action='SKILL', nick=nick)}")

        avail_line = f"Available to Learn: {', '.join(available_names)}" if available_names else "All available skills learned."
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(avail_line, C_YELLOW), action='SKILL', nick=nick)}")


async def _handle_skill_info(node, nick: str, skill_name: str, private_target: str, reply_method: str, mode: str):
    info = await node.db.get_skill_info(nick, node.net_name, skill_name)
    if not info or "error" in info:
        err = info.get("error", "Skill info unavailable.") if isinstance(info, dict) else "Skill info unavailable."
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"[ERR] {err}", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:{err.upper().replace(' ', '_')}",
            narrative=f"[GRID][NARRATIVE] Telemetry query failed: {err}"
        )
        return

    name = info["skill_name"]
    display = info["display_name"]
    level = info["level"]
    max_level = info["max_level"]
    sessions = info["training_sessions"]
    max_sessions = info["max_sessions"]
    is_active = info["is_active"]
    effect = info["effect"]
    desc = info["description"]
    cd = info["cooldown_remaining"]
    is_learned = info["is_learned"]

    status_str = "MAX" if (is_learned and level >= max_level) else ("TRAINING" if is_active else ("LEARNED" if is_learned else "AVAILABLE"))

    if mode == "text":
        sign = "-" if name == "stealth" else "+"
        bonus_pct = int(level * info.get("bonus_per_level", 0.10) * 100)
        msg = (
            f"[GRID][ACTION:SKILL][RESULT:INFO][NICK:{nick}] SKILL:{name.upper()} "
            f"LEVEL:{level} MAX_LEVEL:{max_level} PROGRESS:{sessions}/{max_sessions} "
            f"STATUS:{status_str} ACTIVE:{str(is_active).upper()} BONUS:{sign}{bonus_pct}% "
            f"COOLDOWN:{cd} DESC:{desc.replace(' ', '_')}"
        )
        await node.send(f"{reply_method} {private_target} :{msg}")

    elif mode == "narrative":
        if is_learned and level >= max_level:
            learned_phrase = f"Subroutine is fully compiled at maximum Level {level}/{max_level}."
        elif is_learned:
            learned_phrase = (
                f"Subroutine is active at Level {level}/{max_level}, with {sessions} of {max_sessions} training cycles compiled."
            )
        else:
            learned_phrase = "Subroutine is currently uncompiled and available for acquisition."
        msg = f"[GRID][NARRATIVE] Telemetry diagnostics for '{name}': {learned_phrase} Effect: {effect}. System notes: {desc}"
        await node.send(f"{reply_method} {private_target} :{msg}")

    else:
        # Human mode
        if is_learned and level >= max_level:
            status_badge = format_text("[MAX]", C_GREEN, bold=True)
            prog = f"Level {level}/{max_level} (MAX)"
        else:
            status_badge = format_text("[TRAINING]", C_GREEN) if is_active else (format_text("[LEARNED]", C_CYAN) if is_learned else format_text("[AVAILABLE]", C_YELLOW))
            prog = f"Level {level}/{max_level} ({sessions}/{max_sessions} sessions)" if is_learned else "Not learned"
        line1 = f"{format_text(display, C_WHITE, bold=True)} ({name}) {status_badge} | {prog}"
        line2 = f"Effect: {format_text(effect, C_GREEN)} | {desc}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(line1, action='SKILL', nick=nick)}")
        await node.send(f"{reply_method} {private_target} :{tag_msg(line2, action='SKILL', nick=nick)}")


async def _handle_skill_start(node, nick: str, skill_name: str, private_target: str, reply_method: str, mode: str):
    if not skill_name:
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text("Syntax: !a skill start <name>. Use '!a skill list' to view available skills.", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:SYNTAX_START_NAME_REQUIRED",
            narrative="[GRID][NARRATIVE] Syntax error: 'skill start' requires a skill name. Example: !a skill start attack."
        )
        return

    res = await node.db.start_skill(nick, node.net_name, skill_name)
    if not res.get("success"):
        err = res.get("error", "Failed to start skill.")
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"[ERR] {err}", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:{err.upper().replace(' ', '_').replace('/', '_')}",
            narrative=f"[GRID][NARRATIVE] Skill start rejected: {err}"
        )
        return

    name = res["skill"]
    level = res["level"]
    sessions = res["sessions"]
    resumed = res.get("resumed", False)
    slots = res.get("slots_used", 1)

    if resumed:
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"Resumed training for '{name}' (Level {level}, {sessions}/{SESSIONS_PER_LEVEL} sessions).", C_GREEN), action="SKILL", result="SUCCESS", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:RESUME][NICK:{nick}] SKILL:{name.upper()} LEVEL:{level} PROGRESS:{sessions}/{SESSIONS_PER_LEVEL} STATUS:ACTIVE",
            narrative=f"[GRID][NARRATIVE] {nick} reactivates active compilation of '{name}'. Resuming progress at Level {level} ({sessions}/{SESSIONS_PER_LEVEL} cycles)."
        )
    else:
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"Initiated learning for '{name}' (Level {level}, 0/{SESSIONS_PER_LEVEL} sessions). Slot {slots}/{MAX_CONCURRENT_SKILLS}.", C_GREEN), action="SKILL", result="SUCCESS", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:START][NICK:{nick}] SKILL:{name.upper()} LEVEL:{level} PROGRESS:0/{SESSIONS_PER_LEVEL} STATUS:ACTIVE SLOTS:{slots}/{MAX_CONCURRENT_SKILLS}",
            narrative=f"[GRID][NARRATIVE] {nick} commits neural core cycles to '{name}'. Subroutine compilation initiated at Level {level} (0/{SESSIONS_PER_LEVEL} cycles), occupying slot {slots} of {MAX_CONCURRENT_SKILLS}."
        )


async def _handle_skill_train(node, nick: str, private_target: str, reply_method: str, mode: str):
    res = await node.db.train_skill(nick, node.net_name)
    if not res.get("success"):
        err = res.get("error", "Training failed.")
        cd_rem = res.get("cooldown_remaining", 0)
        if cd_rem > 0:
            await _send_msg(node, private_target, reply_method, mode,
                human=tag_msg(format_text(f"[COOLDOWN] {err}", C_YELLOW), action="SKILL", result="COOLDOWN", nick=nick),
                text=f"[GRID][ACTION:SKILL][RESULT:COOLDOWN][NICK:{nick}] STATUS:COOLDOWN REMAINING:{cd_rem}",
                narrative=f"[GRID][NARRATIVE] {nick} attempts training, but core compilers are recharging. {err}"
            )
        else:
            await _send_msg(node, private_target, reply_method, mode,
                human=tag_msg(format_text(f"[ERR] {err}", C_RED), action="SKILL", result="ERR", nick=nick),
                text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:{err.upper().replace(' ', '_')}",
                narrative=f"[GRID][NARRATIVE] Training protocol rejected: {err}"
            )
        return

    name = res["skill"]
    level = res["level"]
    sessions = res["sessions"]
    max_sess = res.get("max_sessions", SESSIONS_PER_LEVEL)
    leveled_up = res.get("leveled_up", False)

    if leveled_up:
        meta = SKILL_DEFINITIONS.get(name, {})
        sign = "-" if name == "stealth" else "+"
        bonus_pct = int(level * meta.get("bonus_per_level", 0.10) * 100)
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"🏆 BREAKTHROUGH! '{name}' advanced to Level {level}/{MAX_SKILL_LEVEL}! Total Bonus: {sign}{bonus_pct}%.", C_GREEN, bold=True), action="SKILL", result="LEVELUP", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:LEVELUP][NICK:{nick}] SKILL:{name.upper()} LEVEL:{level} PROGRESS:0/{max_sess} STATUS:LEVELED_UP BONUS:{sign}{bonus_pct}%",
            narrative=f"[GRID][NARRATIVE] Threshold reached! {nick}'s neural subroutines recompile with breakthrough performance: '{name}' advances to Level {level}!"
        )
    else:
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"Training session complete for '{name}'. Progress: {sessions}/{max_sess} sessions towards Level {level + 1}. Cooldown: 1 hour.", C_GREEN), action="SKILL", result="SUCCESS", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:TRAIN][NICK:{nick}] SKILL:{name.upper()} LEVEL:{level} PROGRESS:{sessions}/{max_sess} STATUS:ADVANCED COOLDOWN:3600",
            narrative=f"[GRID][NARRATIVE] Neural training cycle complete. {nick} advances '{name}' to {sessions}/{max_sess} sessions towards Level {level + 1}. Core capacitors enter a 1-hour cooldown."
        )


async def _handle_skill_forget(node, nick: str, skill_name: str, private_target: str, reply_method: str, mode: str):
    if not skill_name:
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text("Syntax: !a skill forget <name>.", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:SYNTAX_FORGET_NAME_REQUIRED",
            narrative="[GRID][NARRATIVE] Syntax error: specify which subroutine to forget with !a skill forget <name>."
        )
        return

    res = await node.db.forget_skill(nick, node.net_name, skill_name)
    if not res.get("success"):
        err = res.get("error", "Failed to forget skill.")
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"[ERR] {err}", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:{err.upper().replace(' ', '_')}",
            narrative=f"[GRID][NARRATIVE] Subroutine purge rejected: {err}"
        )
        return

    name = res["skill"]
    await _send_msg(node, private_target, reply_method, mode,
        human=tag_msg(format_text(f"Skill '{name}' has been forgotten. Slot freed.", C_GREEN), action="SKILL", result="SUCCESS", nick=nick),
        text=f"[GRID][ACTION:SKILL][RESULT:FORGET][NICK:{nick}] SKILL:{name.upper()} STATUS:REMOVED SLOTS_FREED:1",
        narrative=f"[GRID][NARRATIVE] {nick} purges the '{name}' subroutine from memory banks. Neural slot reclaimed."
    )


async def _handle_skill_quit(node, nick: str, private_target: str, reply_method: str, mode: str):
    res = await node.db.quit_training(nick, node.net_name)
    if not res.get("success"):
        err = res.get("error", "No active training session.")
        await _send_msg(node, private_target, reply_method, mode,
            human=tag_msg(format_text(f"[ERR] {err}", C_RED), action="SKILL", result="ERR", nick=nick),
            text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:{err.upper().replace(' ', '_')}",
            narrative=f"[GRID][NARRATIVE] {err}"
        )
        return

    name = res["skill"]
    level = res["level"]
    sessions = res["sessions"]
    await _send_msg(node, private_target, reply_method, mode,
        human=tag_msg(format_text(f"Training session for '{name}' paused. Level {level} ({sessions}/{SESSIONS_PER_LEVEL}) preserved.", C_YELLOW), action="SKILL", result="PAUSED", nick=nick),
        text=f"[GRID][ACTION:SKILL][RESULT:QUIT][NICK:{nick}] SKILL:{name.upper()} STATUS:PAUSED LEVEL:{level} PROGRESS:{sessions}/{SESSIONS_PER_LEVEL}",
        narrative=f"[GRID][NARRATIVE] {nick} halts active training of '{name}'. Level {level} ({sessions}/{SESSIONS_PER_LEVEL} cycles) safely stored."
    )


async def _handle_skill_help(node, nick: str, private_target: str, reply_method: str, mode: str):
    await _send_msg(node, private_target, reply_method, mode,
        human=tag_msg(f"Skill Commands: {format_text('!a skill list', C_CYAN)} | {format_text('!a skill <name>', C_CYAN)} | {format_text('!a skill start <name>', C_CYAN)} | {format_text('!a skill train', C_CYAN)} | {format_text('!a skill forget <name>', C_CYAN)} | {format_text('!a skill quit', C_CYAN)}", action="SKILL", nick=nick),
        text=f"[GRID][ACTION:SKILL][RESULT:HELP][NICK:{nick}] COMMANDS:[LIST,<NAME>,START,TRAIN,FORGET,QUIT]",
        narrative="[GRID][NARRATIVE] Neural skill commands available: skill list (view skills), skill <name> (inspect subroutine), skill start <name> (commence compilation), skill train (advance training), skill forget <name> (purge subroutine), skill quit (pause training)."
    )


async def _send_unknown_command(node, nick: str, sub: str, private_target: str, reply_method: str, mode: str):
    await _send_msg(node, private_target, reply_method, mode,
        human=tag_msg(format_text(f"Unknown skill command or skill '{sub}'. Valid: list, <name>, start <name>, train, forget <name>, quit.", C_RED), action="SKILL", result="ERR", nick=nick),
        text=f"[GRID][ACTION:SKILL][RESULT:ERR][NICK:{nick}] MSG:UNKNOWN_SKILL_OR_SUBCOMMAND:{sub.upper()}",
        narrative=f"[GRID][NARRATIVE] Unrecognized skill protocol '{sub}'. Consult skill list for recognized subroutines."
    )


async def _send_msg(node, private_target: str, reply_method: str, mode: str, human: str, text: str, narrative: str):
    if mode == "text":
        out = text
    elif mode == "narrative":
        out = narrative
    else:
        out = human
    await node.send(f"{reply_method} {private_target} :{out}")
