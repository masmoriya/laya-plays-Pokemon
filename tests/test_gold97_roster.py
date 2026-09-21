from dataclasses import replace
from types import SimpleNamespace as NS

from jpp.decode import Mon, Battle
from jpp.agent.gold97_pc import PCTransfer
from jpp.agent.gold97_party import PartyReorder
from jpp.agent.gold97_roster import roster_plan
from jpp.agent.gold97_sacrifice import sacrifice_line
from jpp.agent.gold97_battle import BattleAction


def mon(identity, **values):
    return replace(Mon(1, 'VOLBEAR', 20, 60, 60, 'none', ('FIRE',),
                       identity=identity, moves=('TACKLE',), pp=(20,),
                       stats=(50, 40, 50, 40, 40), stages=(0,) * 7), **values)


def state(party, boxes=(), **kw):
    return NS(party=party, box_roster=boxes, mechanics_verified=True,
              storage_verified=True, current_box=0, in_battle=False,
              screen_lines=(), screen_cursor=None, **kw)


def test_transfer_requires_exact_membership_delta_and_never_release():
    a, b, c = mon('a'), mon('b'), mon('c')
    s = state((a, b))
    ex = PCTransfer()
    assert ex.start(s, {'kind':'deposit', 'identity':'b', 'box':0})
    s.party = (c,); s.box_roster = (replace(b, storage_box=0),)
    ex.step(s, False)
    assert not ex.completed
    s.party = (a,)
    assert ex.step(s, True) is None and ex.completed
    s = state((a, b)); ex = PCTransfer()
    assert ex.start(s, {'kind':'deposit', 'identity':'b', 'box':0})
    s.screen_lines = ('Really RELEASE this POK MON?', 'YES', 'NO')
    s.screen_cursor = (1, 1)
    assert ex.step(s, False) == 'b' and not ex.completed
    assert not PCTransfer().start(s, {'kind':'release', 'identity':'b', 'box':0})


def test_pc_and_party_reject_ambiguous_identities_and_last_battler():
    a = mon('a')
    assert not PCTransfer().start(state((a,)), {'kind':'deposit', 'identity':'a', 'box':0})
    assert not PCTransfer().start(state((a, a)), {'kind':'deposit', 'identity':'a', 'box':0})
    assert not PartyReorder().start(state((a, a)), 1)
    s = state((a, mon('b'))); ex = PartyReorder()
    assert ex.start(s, 1)
    s.party = tuple(reversed(s.party))
    assert ex.step(s, True) is None
    assert not ex.start(state((a, mon('b'))), 1)


def test_roster_fills_slots_and_preserves_field_user_and_trainee():
    leader, trainee = mon('leader'), mon('trainee', level=5)
    swimmer = mon('surf', moves=('SURF',), types=('WATER',))
    incoming = mon('incoming', level=30, types=('ELECTRIC',), storage_box=3)
    s = state((leader, trainee, swimmer), (incoming,))
    assert roster_plan(s) == {'kind':'withdraw','identity':'incoming','box':3}
    s.party = (leader, trainee, swimmer, mon('d'), mon('e'), mon('f'))
    plan = roster_plan(s)
    assert plan['kind'] == 'deposit'
    assert plan['identity'] not in {'leader', 'trainee', 'surf'}


def test_box_scrolling_uses_observed_names_only():
    s = state((mon('a'), mon('b')), box_names=tuple(f'BOX{i}' for i in range(1,15)))
    ex = PCTransfer(); ex.start(s, {'kind':'deposit','identity':'b','box':5}); ex.phase='box'
    s.screen_lines=('BOX1','BOX2','BOX3','BOX4'); s.screen_cursor=(1,3)
    assert ex.step(s, False) == 'down'
    s.screen_lines=('unidentified menu',)
    assert ex.step(s, False) is None


def test_sacrifice_requires_verified_damage_and_finisher():
    active = mon('a', hp=1, moves=('DRAGON RAGE',), stats=(50,40,100,40,40))
    foe = mon('foe', hp=70, moves=('DRAGON RAGE',), stats=(50,40,20,40,40))
    finisher = mon('b', hp=1, moves=('DRAGON RAGE',), stats=(50,40,90,40,40))
    s = NS(battle=Battle('trainer',active,foe), active_slot=0,party=(active,finisher))
    assert sacrifice_line(s, BattleAction('move',0)).reason.startswith('Tactical sacrifice')
    s.battle=Battle('trainer',active,replace(foe,moves=('COUNTER',), pp=(20,)))
    assert sacrifice_line(s, BattleAction('move',0)) is None
    s.battle=Battle('wild',active,foe)
    assert sacrifice_line(s, BattleAction('move',0)) is None
