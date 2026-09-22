"""Goal-driven utility for reachable Journey candidates."""

import re


_COMMON = {
    "after", "and", "continue", "defeat", "enter", "from", "go", "in",
    "into", "of", "progress", "reach", "the", "through", "to", "travel",
    "use", "visit", "with",
}
_GENERIC = {"area", "city", "exit", "house", "investigate", "route", "town"}
_OPTIONAL = {"center", "house", "link", "mart", "pokecenter", "trade", "upstairs",
             "dept", "store", "elevator", "radio", "port"}
_BASE_REWARD = {"exit": 25, "talk": 28, "explore": 2}


def _terms(value):
    terms = set()
    for term in re.findall(r"[a-z0-9]+", str(value).casefold()):
        if term in _COMMON:
            continue
        terms.add(term[:-1] if len(term) > 3 and term.endswith("s") else term)
    return terms


def _place_terms(value):
    return {term for term in _terms(value) if not re.fullmatch(r'b?\d+f', term)}


def rank_candidates(candidates, goal, milestone_reward=100, current_area=""):
    """Rank progress opportunities using the configured milestone reward."""
    goal_terms = _terms(goal)
    area_terms = _place_terms(current_area)
    current_optional = bool(area_terms & _OPTIONAL)
    active_gym = "gym" in area_terms and area_terms <= goal_terms
    inside_goal = bool(area_terms - _GENERIC) and area_terms <= goal_terms
    ranked = []
    for order, candidate in enumerate(candidates):
        text = " ".join((candidate.get("label", ""), candidate.get("destination", "")))
        terms = _terms(text)
        overlap = goal_terms & terms
        specific = {term for term in overlap - _GENERIC - area_terms if not term.isdigit()}
        reward = _BASE_REWARD.get(candidate.get("kind"), 0)
        reasons = [f"{candidate.get('kind', 'task')} base {reward}"]
        interaction = candidate.get('kind') == 'talk' or candidate.get('reobserve_interaction')
        if interaction:
            if (active_gym or inside_goal) and candidate.get('category') != 'obstacle':
                reward += milestone_reward
                reasons.append("investigate unfinished interactions in the objective building")
            elif "gym" in area_terms:
                reward -= 20
                reasons.append("gym is not the current goal")
            elif current_optional and not area_terms <= goal_terms:
                reward -= milestone_reward
                reasons.append("unrelated service conversation")
        # Floor suffixes identify rooms within the same objective building.
        # "Aquarium 2F" must retain the value of the "Aquarium" objective.
        destination_terms = _place_terms(candidate.get('destination', ''))
        identified = bool(destination_terms - _GENERIC)
        exact_destination = bool(candidate.get('destination_key') and identified
                                 and destination_terms <= goal_terms)
        if exact_destination:
            reward += milestone_reward
            reasons.append('explicit goal destination')
        elif specific:
            reward += min(20, 5 * len(specific))
            reasons.append('weak text hint: ' + ', '.join(sorted(specific)))
        if candidate.get("source"):
            reward += 10
            reasons.append("verified route evidence")
        optional = terms & _OPTIONAL
        unrequested_optional = optional - goal_terms
        leaving_optional = (current_optional and candidate.get("kind") == "exit"
                            and not destination_terms & {'dept', 'store', 'elevator'})
        if leaving_optional:
            reward += milestone_reward // 2
            reasons.append("leave unrelated optional/service area")
        unrelated = not specific or bool(unrequested_optional & {'dept', 'store', 'elevator'})
        if unrequested_optional and unrelated and not exact_destination and not leaving_optional:
            reward -= milestone_reward
            reasons.append("unrelated optional/service area")
        enriched = {**candidate, "journey_reward": max(0, reward),
                    "goal_destination": exact_destination,
                    "within_goal": exact_destination and inside_goal,
                    "goal_interaction": candidate.get('goal_interaction', False)
                        or (inside_goal and interaction
                            and candidate.get('category') != 'obstacle'),
                    "reward_reason": "; ".join(reasons), "_rank_order": order}
        ranked.append(enriched)
    ranked.sort(key=lambda item: (-item["journey_reward"], item["_rank_order"]))
    for item in ranked:
        item.pop("_rank_order", None)
    return ranked


def rank_interactions(targets, reward):
    """Reachable people and pickups come before experimenting on obstacles."""
    for target in targets:
        if (target['kind'] != 'talk' and not target.get('reobserve_interaction')) or target.get('journey_reward', 0) <= 0:
            continue
        category = target.get('category')
        if category == 'obstacle':
            continue  # A cart is not automatically a prerequisite for every goal.
        target['journey_reward'] = max(target['journey_reward'], reward * 3 if category == 'item' else reward * 0.6)
        if category == 'item':
            target['investigation_priority'] = True
        target['reward_reason'] = 'Reachable observed item' if category == 'item' else 'Reachable unfinished conversation'
    return sorted(targets, key=lambda t: -t.get('journey_reward', 0))
