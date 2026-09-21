"""Goal-driven utility for reachable Journey candidates."""

import re


_COMMON = {
    "after", "and", "continue", "defeat", "enter", "from", "go", "in",
    "into", "of", "progress", "reach", "the", "through", "to", "travel",
    "use", "visit", "with",
}
_GENERIC = {"area", "city", "exit", "house", "investigate", "route", "town"}
_OPTIONAL = {"center", "house", "link", "mart", "pokecenter", "trade", "upstairs"}
_BASE_REWARD = {"exit": 25, "talk": 8, "explore": 2}


def _terms(value):
    terms = set()
    for term in re.findall(r"[a-z0-9]+", str(value).casefold()):
        if term in _COMMON:
            continue
        terms.add(term[:-1] if len(term) > 3 and term.endswith("s") else term)
    return terms


def rank_candidates(candidates, goal, milestone_reward=100, current_area=""):
    """Rank progress opportunities using the configured milestone reward."""
    goal_terms = _terms(goal)
    current_optional = bool(_terms(current_area) & _OPTIONAL)
    ranked = []
    for order, candidate in enumerate(candidates):
        text = " ".join((candidate.get("label", ""), candidate.get("destination", "")))
        terms = _terms(text)
        overlap = goal_terms & terms
        specific = {term for term in overlap - _GENERIC if not term.isdigit()}
        reward = _BASE_REWARD.get(candidate.get("kind"), 0)
        reasons = [f"{candidate.get('kind', 'task')} base {reward}"]
        if overlap:
            reward += milestone_reward
            reward += 20 * len(specific)
            reasons.append("goal match: " + ", ".join(sorted(overlap)))
        if candidate.get("source"):
            reward += 10
            reasons.append("verified route evidence")
        optional = terms & _OPTIONAL
        unrequested_optional = optional - goal_terms
        leaving_optional = current_optional and candidate.get("kind") == "exit"
        if leaving_optional:
            reward += milestone_reward // 2
            reasons.append("leave unrelated optional/service area")
        if unrequested_optional and not specific and not leaving_optional:
            reward -= milestone_reward
            reasons.append("unrelated optional/service area")
        enriched = {**candidate, "journey_reward": max(0, reward),
                    "reward_reason": "; ".join(reasons), "_rank_order": order}
        ranked.append(enriched)
    ranked.sort(key=lambda item: (-item["journey_reward"], item["_rank_order"]))
    for item in ranked:
        item.pop("_rank_order", None)
    return ranked
