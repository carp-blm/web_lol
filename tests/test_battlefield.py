"""v5 integration: real travel, local fights, draft order, spells and replay."""
import copy
import unittest
from test_engine import CATALOG, CHAMPIONS
from test_progression import game
from test_match_features import draft
from engine import Game
from legacy_engine_v4 import Game as GameV4
from battlefield import BASES, PITS
from summoners import CATALOG as SPELLS


def fresh():
    g = game('spatial-v5-tests')
    g.apply({'type': 'start'})
    return g, g.match


def group(m, roles=('top', 'jng', 'mid', 'bot', 'sup'), point=(50, 50)):
    for side in (0, 1):
        for role in roles:
            u = m.unit(side, role)
            u.update(pos=[point[0]+side*3, point[1]], destination=list(point), location='mid',
                     route=[], moving=False, status='active', hp=100, combo_ready_at=0)


class BattlefieldTests(unittest.TestCase):
    def test_spawns_follow_assigned_lane_paths_and_support_goes_bot(self):
        _, m = fresh()
        for side, team in enumerate(m.s['teams']):
            for u in team:
                self.assertEqual(u['pos'], list(BASES[side]))
                self.assertEqual(u['location'], m.home_lane(u))
            self.assertEqual(m.unit(side, 'sup')['location'], 'bot')
        old = copy.deepcopy(m.s['teams'])
        m.step()
        for side, team in enumerate(m.s['teams']):
            for i, u in enumerate(team):
                self.assertGreater(m.distance(u['pos'], old[side][i]['pos']), 0)
                self.assertLessEqual(m.distance(u['pos'], old[side][i]['pos']), 1.06)
        for _ in range(78): m.step()
        self.assertTrue(all(not u['moving'] for t in m.s['teams'] for u in t if u['role'] != 'jng'))

    def test_distant_units_cannot_fight_or_start_an_objective(self):
        _, m = fresh()
        before = copy.deepcopy(m.s), m.rng.state
        self.assertIsNone(m.encounter('teamfight', 'river', *m.s['teams']))
        self.assertEqual((m.s, m.rng.state), before)
        m.s['time'] = 300
        self.assertFalse(m.start_objective(0, 'dragon'))
        m.unit(0, 'jng')['pos'] = list(PITS['dragon'])
        self.assertTrue(m.start_objective(0, 'dragon'))
        self.assertEqual(m.s['objective_attempt']['roles'], ['jng'])

    def test_spatial_encounter_excludes_remote_allies(self):
        _, m = fresh()
        group(m, ('mid',))
        m.encounter('teamfight', 'mid', *m.s['teams'], rounds=0)
        self.assertEqual(m.s['last_encounter']['sides'], [['mid'], ['mid']])
        self.assertEqual(m.s['last_encounter']['position'], [51.5, 50])

    def test_roaming_support_cannot_participate_until_arrival(self):
        _, m = fresh()
        sup = m.unit(0, 'sup')
        sup['pos'] = sup['destination'][:]
        start = sup['pos'][:]
        m.start_roam(0)
        self.assertEqual(sup['pos'], start)
        self.assertNotIn(sup, m.lane_members(0, 'mid'))
        for _ in range(55):
            m.s['time'] += 1
            m.advance_positions()
        self.assertIn(sup, m.lane_members(0, 'mid'))

    def test_death_recovery_starts_at_base_then_walks_back(self):
        _, m = fresh()
        victim = m.unit(1, 'mid')
        m.kill_unit(m.unit(0, 'mid'), victim, [m.unit(0, 'mid')])
        self.assertFalse(m.present(victim))
        m.s['time'] = victim['return_at']
        m.advance_positions()
        self.assertTrue(m.present(victim))
        self.assertLess(m.distance(victim['pos'], BASES[1]), 2)
        self.assertNotIn(victim, m.lane_members(1, 'mid'))

    def test_contact_events_require_distance_and_report_real_numbers(self):
        _, m = fresh()
        m.s['time'] = 240
        m.make_event()
        self.assertIsNone(m.s['event'])
        group(m, ('mid',))
        m.make_event()
        event = m.s['event']
        self.assertIn('아군 1 / 적군 1', event['context'])
        self.assertEqual(event['position'], m.unit(0, 'mid')['pos'])

    def test_first_blood_and_shutdown_rewards_only_once(self):
        _, m = fresh()
        a, b = m.unit(0, 'mid'), m.unit(1, 'mid')
        b['kill_streak'] = 5
        before = a['gold']
        m.kill_unit(a, b, [a])
        self.assertEqual(a['gold']-before, 700)
        m.kill_unit(a, b, [a])
        self.assertEqual(a['gold']-before, 700)


class SpellAndComboTests(unittest.TestCase):
    def test_official_base_timers_and_smite_charge_lockout(self):
        self.assertEqual({k:v['cooldown'] for k,v in SPELLS.items()},
                         dict(flash=300, teleport=300, ignite=180, heal=240, barrier=180,
                              cleanse=240, exhaust=240, ghost=240, smite=90))
        _, m = fresh()
        u = m.unit(0, 'jng')
        m.spend_summoner(u, 'smite', 'test')
        self.assertFalse(m.summoner_ready(u, 'smite'))
        m.s['time'] = 15
        m.advance_summoners()
        self.assertTrue(m.summoner_ready(u, 'smite'))
        m.spend_summoner(u, 'smite', 'test')
        self.assertEqual(u['summoners']['smite']['charges'], 0)
        for time, charges in ((89,0),(90,1),(179,1),(180,2)):
            m.s['time'] = time
            m.advance_summoners()
            self.assertEqual(u['summoners']['smite']['charges'], charges)

    def test_flash_recovers_exactly_at_300_and_pause_does_not_charge(self):
        _, m = fresh()
        u = m.unit(0, 'mid')
        m.spend_summoner(u, 'flash', 'test')
        m.s['time'] = 299
        m.advance_summoners()
        self.assertFalse(m.summoner_ready(u, 'flash'))
        group(m, ('mid',))
        m.make_event()
        before = copy.deepcopy(m.s), m.rng.state
        for _ in range(10):m.step()
        self.assertEqual((m.s, m.rng.state), before)
        m.s['time'] = 300
        m.advance_summoners()
        self.assertTrue(m.summoner_ready(u, 'flash'))

    def test_spell_choice_bonus_consumes_only_selected_spell_and_replays(self):
        g, m = fresh()
        while not m.s['event']: g.apply({'type':'tick','steps':6})
        event = g.view()['match']['event']
        offer = next(s for o in event['options'] if o['id']=='commit' for s in o['summoners'])
        original = next(o for o in event['options'] if o['id']=='commit')['chance']
        self.assertGreater(offer['chance'], original)
        before = m.unit(0,offer['role'])['summoners'][offer['id']]['uses']
        g.apply({'type':'choose','option':'commit','summoner':offer['id'],'role':offer['role']})
        self.assertEqual(m.unit(0,offer['role'])['summoners'][offer['id']]['uses'], before+1)
        self.assertEqual(m.s['decisions'][-1]['chance'], offer['chance'])
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())

    def test_invalid_spell_selection_is_atomic(self):
        g, m = fresh()
        group(m, ('mid',));m.make_event()
        before = copy.deepcopy(m.s), m.rng.state
        with self.assertRaises(ValueError):m.choose_with_summoner('vision','mid','smite')
        self.assertEqual((m.s,m.rng.state),before)

    def test_loadout_validation_and_save_replay(self):
        g = game()
        g.apply({'type':'summoner_loadout','role':'mid','spells':['flash','teleport']})
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())
        for role, spells in [('jng',['flash','ignite']),('bot',['smite','heal']),('mid',['flash','flash'])]:
            before = g.view()
            with self.assertRaises(ValueError):g.apply({'type':'summoner_loadout','role':role,'spells':spells})
            self.assertEqual(g.view(),before)
        g.apply({'type':'start'})
        self.assertEqual(list(g.match.unit(0,'mid')['summoners']),['flash','teleport'])

    def test_ahri_control_precedes_damage_and_records_combo_icons(self):
        _, m = fresh();group(m, ('mid',))
        u, enemy = m.unit(0,'mid'), m.unit(1,'mid')
        u['champion'] = 'Ahri';m.initialize_abilities()
        m.hit_chance=lambda *args:1
        m.protect=lambda victim,damage,*args:damage
        casts=m.execute_combo(u,[enemy],[u],'mid')
        self.assertGreater(len(casts),1)
        self.assertEqual([c['skill'].split(':')[-1] for c in casts[:2]],['E','Q'])
        self.assertTrue(all(c['combo']=='매혹 연계' for c in casts))
        self.assertTrue(u['recent_casts'])
        self.assertEqual(m.execute_combo(u,[enemy],[u],'mid'),[])

    def test_leesin_missed_opener_does_not_unlock_mark_dependent_recast(self):
        _, m = fresh();group(m, ('jng',))
        u, enemy=m.unit(0,'jng'),m.unit(1,'jng')
        u['champion']='LeeSin';m.initialize_abilities()
        m.hit_chance=lambda *args:0
        casts=m.execute_combo(u,[enemy],[u],'mid')
        self.assertFalse(any(c['skill'].endswith('Q2') for c in casts))
        self.assertNotIn('Q',u['ability_state']['chains'])

    def test_all_champions_form_states_can_execute_combos(self):
        for cid, champion in CHAMPIONS['champions'].items():
            with self.subTest(champion=cid):
                _,m=fresh();group(m);m.s['time']=1000
                u=m.unit(0,'mid');u['champion']=cid;m.initialize_abilities()
                m.hit_chance=lambda *args:1
                m.protect=lambda victim,damage,*args:damage
                for form in champion['kit']['forms']:
                    m.set_form(u,form);u['cooldowns']={};u['combo_ready_at']=0
                    for enemy in m.s['teams'][1]:enemy.update(hp=100,status='active')
                    casts=m.execute_combo(u,m.s['teams'][1],[u],'mid')
                    self.assertLessEqual(len(casts),4)
                    self.assertTrue(all(c['combo_step']>=1 for c in casts))

    def test_yasuo_ultimate_requires_airborne_target(self):
        _, m=fresh();group(m, ('mid',));m.s['time']=700
        u, enemy=m.unit(0,'mid'),m.unit(1,'mid')
        u['champion']='Yasuo';m.initialize_abilities()
        u['cooldowns'].update(Q=900,W=900,E=900)
        casts=m.execute_combo(u,[enemy],[u],'mid')
        self.assertFalse(any(c['skill'].endswith(':R') for c in casts))

    def test_yasuo_ultimate_cannot_hit_grounded_frontline(self):
        _, m=fresh();group(m);m.s['time']=700
        u=m.unit(0,'mid');u['champion']='Yasuo';m.initialize_abilities()
        u['cooldowns'].update(Q=900,W=900,E=900)
        airborne=m.unit(1,'bot');airborne['airborne_until']=704
        m.hit_chance=lambda *args:1
        m.protect=lambda victim,damage,*args:damage
        casts=m.execute_combo(u,m.s['teams'][1],[u],'mid')
        ultimate=next(c for c in casts if c['skill'].endswith(':R'))
        self.assertEqual([t['card_id'] for t in ultimate['targets']],[airborne['card_id']])


class TournamentAndMigrationTests(unittest.TestCase):
    def test_official_order_and_flexible_role_selection(self):
        g=game();g.apply({'type':'begin_draft'})
        while g.s['banpick']['phase']!='ready':
            d=g.s['banpick'];kind=d['phase']
            action={'type':kind+'_champion','champion':next(c for c in sorted(g.champions) if c not in g.draft_taken())}
            if kind=='pick':action['role']=next(r for r in reversed(('top','jng','mid','bot','sup')) if r not in d['picks'][0])
            g.apply(action)
            self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())
        history=g.s['banpick']['history']
        self.assertEqual(''.join('A' if h['side']==0 else 'B' for h in history),'ABABABABBAABBABABAAB')
        self.assertEqual([h['kind'] for h in history],['ban']*6+['pick']*6+['ban']*4+['pick']*4)
        self.assertEqual(history[6]['role'],'sup')

    def test_v4_active_match_and_campaign_are_preserved(self):
        old=game('old-campaign',cls=GameV4);old.apply({'type':'start'});old.apply({'type':'tick','steps':100})
        migrated=Game.import_save(old.export_save(),CATALOG,CHAMPIONS)
        self.assertEqual(old.match.s,migrated.match.s)
        self.assertEqual(old.s['roster'],migrated.s['roster'])
        self.assertEqual(migrated.view(),Game.import_save(migrated.export_save(),CATALOG,CHAMPIONS).view())

    def test_v4_partial_draft_can_finish_and_start_new_spatial_match(self):
        old=game('old-draft',cls=GameV4)
        old.apply({'type':'begin_draft'});old.apply({'type':'ban_champion','champion':'Ahri'})
        g=Game.import_save(old.export_save(),CATALOG,CHAMPIONS)
        while g.s['banpick']['phase']!='ready':
            kind=g.s['banpick']['phase'];cid=next(c for c in sorted(g.champions) if c not in g.draft_taken())
            g.apply({'type':kind+'_champion','champion':cid})
        g.apply({'type':'start'})
        self.assertEqual(g.match.s['rules'],'spatial-v5')
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())


if __name__=='__main__':unittest.main()
