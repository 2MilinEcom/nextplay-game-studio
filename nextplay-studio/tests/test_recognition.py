import unittest
from studio.recognition_report import card_changes

class RecognitionReportTests(unittest.TestCase):
    def row(self,index,name):
        return {'index':index,'frame_id':f'f{index:04d}','time_seconds':index*.5,'hand':[{'slot':1,'name':name}]}
    def test_adjacent_slot_change_is_bracketed_not_deployment(self):
        result=card_changes([self.row(10,'Tesla'),self.row(11,'Poison')])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['frame_ids'],['f0010','f0011'])
        self.assertIn('not established',result[0]['meaning'])
    def test_unknown_gap_does_not_invent_card_play(self):
        self.assertEqual(card_changes([self.row(10,'Tesla'),self.row(11,None),self.row(12,'Poison')]),[])
    def test_missing_frames_do_not_create_certain_transition(self):
        self.assertEqual(card_changes([self.row(10,'Tesla'),self.row(14,'Poison')]),[])
