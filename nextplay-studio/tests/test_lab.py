import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from lab.engine import Journal, recommend, validate


def state():
    return {'schema_version': 1, 'app': 'clash_royale', 'source': 'synthetic_fixture',
            'coordinate_space': 'arena_normalized', 'evidence_id': 'fixture:balloon',
            'observed_ms': 1000, 'available_ms': 1100, 'confidence': .99,
            'phase': 'battle', 'elixir': 5, 'hand': ['tesla', 'miner'],
            'threats': [{'kind': 'balloon', 'lane': 'left', 'y': .6, 'confidence': .99}]}


class LabTests(unittest.TestCase):
    def test_affordable_defense(self):
        action = recommend(state(), 1100)['action']
        self.assertEqual(action['card'], 'tesla')
        self.assertFalse(action['placement_validated'])

    def test_stale_withheld(self):
        self.assertIsNone(recommend(state(), 1501)['action'])

    def test_uncertain_withheld(self):
        for field, value in [('confidence', .8), ('elixir', None), ('phase', 'menu')]:
            s = state(); s[field] = value
            self.assertIsNone(recommend(s, 1100)['action'])

    def test_unaffordable_or_absent(self):
        for field, value in [('elixir', 3), ('hand', ['miner'])]:
            s = state(); s[field] = value
            self.assertIsNone(recommend(s, 1100)['action'])

    def test_hidden_information_rejected(self):
        for field in ['elixirLeaked', 'enemy_hand', 'enemy_elixir']:
            s = state(); s[field] = 4
            with self.assertRaises(ValueError): validate(s)

    def test_wrong_app_rejected(self):
        s = state(); s['app'] = 'home_screen'
        with self.assertRaises(ValueError): validate(s)

    def test_nonfinite_rejected(self):
        s = state(); s['elixir'] = float('nan')
        with self.assertRaises(ValueError): validate(s)

    def test_uncertain_threat(self):
        s = state(); s['threats'][0]['confidence'] = .7
        self.assertIsNone(recommend(s, 1100)['action'])

    def test_journal_labels_and_null_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d)/'lab.db'); j.import_session('fixture', [state()])
            self.assertIsNone(j.report('fixture')['card_agreement'])
            j.label('fixture', 0, 'tesla', 'human-test')
            self.assertEqual(j.report('fixture')['card_agreement'], 1)
            self.assertFalse(j.report('fixture')['live_input_enabled'])
            with self.assertRaises(sqlite3.IntegrityError):
                j.import_session('fixture', [state()])

    def test_atomic_bad_session(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d)/'lab.db')
            with self.assertRaises(ValueError): j.import_session('bad', [state(), state()])
            with self.assertRaises(ValueError): j.report('bad')

    def test_fixture_separation(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d)/'lab.db'); s = copy.deepcopy(state())
            s.update(source='manual_replay', observed_ms=1200, available_ms=1300)
            with self.assertRaises(ValueError): j.import_session('mixed', [state(), s])

    def test_unknown_label_reference(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d)/'lab.db')
            with self.assertRaises(sqlite3.IntegrityError): j.label('missing', 0, None, 'human')


if __name__ == '__main__': unittest.main()
