"""User-authored run rules, independent of ROM family."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re


def _token(value):
    return re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")


@dataclass(frozen=True)
class StarterRule:
    preferred: tuple[str, ...] = ("CHIKORITA", "FLAMBEAR", "CRUIZE")
    fallback: str = "first_legal"


@dataclass(frozen=True)
class GameRules:
    player_name: str = "JEV"
    starter: StarterRule = field(default_factory=StarterRule)
    nickname_starter: bool = False

    def choose_starter(self, options):
        """Choose legal option matching preference; never invent an option."""
        if not options:
            return None
        indexed = {
            token: key
            for key, value in options.items()
            for token in {_token(key), _token(value)}
            if token
        }
        for preferred in self.starter.preferred:
            wanted = _token(preferred)
            for token, key in indexed.items():
                if wanted in token:
                    return key
        if self.starter.fallback == "first_legal":
            return next(iter(options))
        if self.starter.fallback in options:
            return self.starter.fallback
        return None

    def public_context(self):
        return {
            "player_name": self.player_name,
            "starter_preference": list(self.starter.preferred),
            "nickname_starter": self.nickname_starter,
        }

    @classmethod
    def load(cls, path="config/game_rules.json"):
        source = Path(path)
        if not source.is_file():
            return cls()
        raw = json.loads(source.read_text())
        starter = raw.get("starter") or {}
        preferred = tuple(starter.get("preferred") or StarterRule.preferred)
        return cls(
            player_name=str(raw.get("player_name") or "JEV")[:10].upper(),
            starter=StarterRule(preferred=preferred, fallback=str(starter.get("fallback", "first_legal"))),
            nickname_starter=bool(raw.get("nickname_starter", False)),
        )

    def with_overrides(self, player_name=None, starter=None):
        preferred = self.starter.preferred if starter is None else (_token(starter),) + tuple(
            item for item in self.starter.preferred if _token(item) != _token(starter)
        )
        return GameRules(
            player_name=(player_name or self.player_name)[:10].upper(),
            starter=StarterRule(preferred=preferred, fallback=self.starter.fallback),
            nickname_starter=self.nickname_starter,
        )
