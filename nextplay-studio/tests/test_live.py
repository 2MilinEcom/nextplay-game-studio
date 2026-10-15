import unittest
from live.readiness import blockers
class LiveTests(unittest.TestCase):
    def good(self):
        return dict(app='clash_royale',phase='battle',replay=False,age_ms=100,
          hand_verified=True,elixir_verified=True,ownership_verified=True,
          placement_calibrated=True,mirror_connected=True)
    def test_missing_evidence_withholds(self):self.assertTrue(blockers({}))
    def test_wrong_app_withholds(self):
        s=self.good();s['app']='other';self.assertTrue(blockers(s))
    def test_stale_withholds(self):
        s=self.good();s['age_ms']=501;self.assertTrue(blockers(s))
    def test_replay_withholds(self):
        s=self.good();s['replay']=True;self.assertTrue(blockers(s))
    def test_valid_contract(self):self.assertEqual(blockers(self.good()),[])
