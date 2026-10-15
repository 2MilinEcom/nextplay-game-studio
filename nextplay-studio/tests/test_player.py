import unittest,tempfile
from pathlib import Path
from live.policy import Policy,PressureLearner
class PolicyTests(unittest.TestCase):
    def state(self):return {'battle':True,'elixir_verified':True,'elixir':10,'age_ms':80,'hand':[{'name':'Miner','slot':1},{'name':'Tesla','slot':2}],'objects':[]}
    def test_stale_has_no_action(self):
        s=self.state();s['age_ms']=501;self.assertIsNone(Policy().choose(s,10))
    def test_unreadable_resource_has_no_action(self):
        s=self.state();s['elixir_verified']=False;self.assertIsNone(Policy().choose(s,10))
    def test_menu_has_no_action(self):
        s=self.state();s['battle']=False;self.assertIsNone(Policy().choose(s,10))
    def test_no_unaffordable_action(self):
        s=self.state();s['elixir']=2;self.assertIsNone(Policy().choose(s,10))
    def test_defense_precedes_pressure(self):
        s=self.state();s['objects']=[{'label':'prince','side':'enemy','track_hits':3,'box':[.1,.47,.3,.59]}]
        self.assertEqual(Policy().choose(s,10)['card'],'Tesla')
    def test_friendly_detection_not_a_threat(self):
        s=self.state();s['objects']=[{'label':'prince','side':'own','track_hits':3,'box':[.1,.47,.3,.59]}]
        self.assertEqual(Policy().choose(s,10)['card'],'Miner')
    def test_cooldown_after_input_only(self):
        p=Policy();s=self.state();a=p.choose(s,10);p.committed(a,10);self.assertIsNone(p.choose(s,10.5))
    def test_unknown_result_never_trains(self):
        with tempfile.TemporaryDirectory() as t:
            p=PressureLearner(Path(t)/'policy.json');p.finish(9,'unknown');self.assertEqual(p.data['9']['games'],0)
    def test_verified_result_persists(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'policy.json';p=PressureLearner(path);p.finish(9,'win');self.assertEqual(PressureLearner(path).data['9']['wins'],1)

class ManagerTests(unittest.TestCase):
    def test_control_without_input_grant_never_spawns(self):
        from live.manager import Manager
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as t:
            manager=Manager(Path(t),Path(t)/'data')
            with patch.object(manager,'permissions',return_value={'screen_permission':True,'input_permission':False}),patch('live.manager.subprocess.Popen') as spawn:
                with self.assertRaises(ValueError):manager.start(control=True)
                spawn.assert_not_called()
    def test_missing_screen_grant_never_spawns(self):
        from live.manager import Manager
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as t:
            manager=Manager(Path(t),Path(t)/'data')
            with patch.object(manager,'permissions',return_value={'screen_permission':False}),patch('live.manager.subprocess.Popen') as spawn:
                with self.assertRaises(ValueError):manager.start()
                spawn.assert_not_called()
