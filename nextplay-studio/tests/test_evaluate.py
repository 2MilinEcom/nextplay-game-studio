import unittest
from studio.evaluate import evaluate


def fixture(values):
    return {'recognition':{'timeline':[{'index':i*2,'gameplay_candidate':True} for i in range(len(values))]},
        'local_timeline':[{'index':i*2,'counters':{'own_left':{'value':v}} if v else {}} for i,v in enumerate(values)],
        'observations':[],'coaching':{'summary':'Scan','priorities':[]}}

class OutcomeTests(unittest.TestCase):
    def test_repeated_damage_has_evidence(self):
        r=evaluate(fixture([4000,4000,3800,3800]))
        self.assertEqual(r['evaluation']['events'][0]['damage'],200)
        self.assertEqual(len(r['evaluation']['events'][0]['frame_ids']),4)
    def test_transient_bad_reading_is_not_damage(self):
        self.assertFalse(evaluate(fixture([4000,4000,1000,4000,4000]))['evaluation']['events'])
    def test_missing_long_interval_not_scored(self):
        self.assertFalse(evaluate(fixture([4000,4000,None,None,None,None,3000,3000]))['evaluation']['events'])
    def test_increase_not_scored(self):
        self.assertFalse(evaluate(fixture([3000,3000,4000,4000]))['evaluation']['events'])
    def test_menu_counters_not_scored(self):
        r=fixture([4000,4000,3000,3000]);r['recognition']['timeline']=[]
        self.assertFalse(evaluate(r)['evaluation']['events'])
    def test_idempotent(self):
        r=evaluate(fixture([4000,4000,3800,3800]));evaluate(r)
        self.assertEqual(len(r['observations']),1)

    def test_banner_occlusion_is_ungraded(self):
        r=fixture([4000,4000,1600,1600])
        for row in r['local_timeline']:
            row['counters']['own_left']['box']=[.17,.618,.105,.027]
            if row['index']>=4:row['text']=[{'text':'Miner','box':[.17,.59,.2,.02]}]
        self.assertFalse(evaluate(r)['evaluation']['events'])
    def test_false_increase_does_not_reset_baseline(self):
        self.assertFalse(evaluate(fixture([3000,3000,4000,4000,3500,3500]))['evaluation']['events'])
