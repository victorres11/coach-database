POSITION_MAP = {
    "HC":  ["head coach"],
    "OC":  ["offensive coord", "offensive coordinator", "play caller", "co-offensive coord"],
    "DC":  ["defensive coord", "defensive coordinator"],
    "QB":  ["quarterbacks", "quarterback coach"],
    "OL":  ["offensive line"],
    "DL":  ["defensive line"],
    "TE":  ["tight end"],
    "WR":  ["wide receiver", "passing coord"],
    "RB":  ["running back", "run game coord"],
    "LB":  ["linebacker"],
    "DB":  ["defensive back", "secondary", "safeties", "cornerback"],
    "STC": ["special teams coord", "co-special teams"],
    "SC":  ["strength", "conditioning", "strength and conditioning"],
}

def match_position_code(text):
    """Given a position string, return the first matching code from POSITION_MAP, or None."""
    text = (text or '').lower()
    for code, keywords in POSITION_MAP.items():
        if any(k in text for k in keywords):
            return code
    return None
