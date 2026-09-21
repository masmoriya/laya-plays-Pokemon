"""Conversation evidence validation and a reversible legacy migration."""
import re

VERSION = 3
BATTLE_TEXT = ('GOT AWAY', 'WILD ', 'BROKE FREE', 'GAINED', 'GREW TO', 'FAINTED',
               'USED ', 'GO!', 'CRITICAL HIT', 'SUPER EFFECTIVE', 'GOTCHA', 'WANTS TO')
MENU_TEXT = ('FIGHT', 'PACK', 'CANCEL', 'WITHDRAW', 'DEPOSIT', 'SAVE', 'OPTION')


def dialogue_text(text):
    text = ' '.join(text.split())
    upper = text.upper()
    return bool(len(text) >= 5 and sum(c.isalpha() for c in text) >= 5
                and sum(c.isdigit() for c in text) <= max(3, len(text) // 10)
                and not re.search(r'(.)\1{7}', text)
                and not re.search(r'THERE.{0,8}NOTHING(?: HERE)?', upper)
                and not any(word in upper for word in BATTLE_TEXT)
                and not any(word == upper or f' {word} ' in f' {upper} ' for word in MENU_TEXT))


def migrate(data):
    if data.get('version', 1) >= VERSION:
        return
    archived = {'clues': [], 'pages': []}
    valid = []
    for clue in data['clues']:
        if dialogue_text(clue['text']):
            valid.append(clue)
        else:
            archived['clues'].append(clue)
    data['clues'] = valid
    for npc in data['npcs'].values():
        bad = [p for p in npc['pages'] if not dialogue_text(p)]
        if bad:
            archived['pages'].append({'id': npc['id'], 'pages': bad})
            npc['pages'] = [p for p in npc['pages'] if p not in bad]
            npc.update(status='pending', attempts=0)
        npc['visible'] = False
    data.setdefault('archive', []).append(archived)
    data['version'] = VERSION
