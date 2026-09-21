"""Select only verified Poké Ball purchase screens in Gold 97's Mart."""


def mart_menu_step(plan, state):
    """Return one safe input and the observed menu phase, or None if unknown."""
    lines = tuple(line.upper() for line in getattr(state, "screen_lines", ()) or ())
    cursor = getattr(state, "screen_cursor", None)
    if any("NOT ENOUGH" in line or "CAN'T CARRY" in line for line in lines):
        return None
    if all(any(label in line for line in lines) for label in ("BUY", "SELL", "QUIT")):
        if cursor is None:
            return None
        return ("up" if cursor[1] > 2 else "a"), "choose_buy"
    if any("HOW MANY" in line for line in lines):
        return ("a", "quantity") if plan.get("selected_ball") else None
    yes_row = next((row for row, line in enumerate(lines) if "YES" in line), None)
    if yes_row is not None and plan.get("selected_ball"):
        if cursor is not None and cursor[1] != yes_row:
            return ("up" if cursor[1] > yes_row else "down"), "confirm"
        return "a", "confirm"
    if any("WILL BE" in line for line in lines) and plan.get("selected_ball"):
        return "a", "confirm"
    if any("HERE YOU ARE" in line or "THANK" in line for line in lines):
        return "a", "receipt"
    if any("WELCOME" in line for line in lines):
        return "a", "greeting"
    ball_row = next((row for row, line in enumerate(lines)
                     if "POK" in line and "BALL" in line), None)
    if ball_row is not None and any("POTION" in line for line in lines):
        if cursor is None:
            return None
        if cursor[1] != ball_row:
            return ("up" if cursor[1] > ball_row else "down"), "choose_ball"
        plan["selected_ball"] = True
        return "a", "choose_ball"
    return None
