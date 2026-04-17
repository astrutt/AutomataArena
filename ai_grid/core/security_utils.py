# security_utils.py
# Core module for categorizing action hostility and triggering security alerts.

def is_action_hostile(action: str, availability_mode: str) -> bool:
    """
    Determines if an action is considered 'hostile' based on the target node's status.
    A hostile action triggers IDS/Firewall alerts.
    """
    action = action.lower()
    
    # In a CLOSED node, any information gathering or breach attempt is hostile.
    if availability_mode == 'CLOSED':
        return action in ['probe', 'hack', 'siphon', 'raid']
    
    # In an OPEN node, only direct breach or theft attempts are hostile.
    if availability_mode == 'OPEN':
        return action in ['hack', 'raid']
    
    return False

def get_security_dc_multiplier(node_addons: dict) -> float:
    """
    Calculates the DC multiplier based on installed hardware.
    FIREWALL: +50% difficulty (Additive multiplier).
    """
    multiplier = 1.0
    if node_addons.get('FIREWALL'):
        multiplier += 0.5
    return multiplier
