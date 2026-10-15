import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio.core import Store
from studio.worker import Engine
from studio.local import landmarks

class LocalTests(unittest.TestCase):
    def test_default_and_mode_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            self.assertEqual(store.settings['processing_mode'], 'local')
            with self.assertRaises(ValueError): store.save_settings({'processing_mode':'invalid'})
    def test_local_path_does_not_construct_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            def forbidden(): raise AssertionError('Paid model must not be constructed')
            engine = Engine(store, model_factory=forbidden, start=False)
            job = store.create_job('video', 'offline')
            with patch('studio.local.scan', return_value={'provenance': {'calls': []}}) as scan:
                engine.review_video(job['id'])
                scan.assert_called_once()
            self.assertEqual(store.get_job(job['id'])['state'], 'completed')
            with self.assertRaises(ValueError): engine.begin_live()
            engine.stop.set()
    def test_local_api_refresh_skips_coaching(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp);store = Store(project);engine = Engine(store, start=False)
            (project/'nextplay-clash-review.json').write_text('{}')
            for name in ['test_clash_api.py', 'nextplay-clash-v2.py']: (project/name).write_text('')
            with patch('studio.worker.subprocess.run') as run:
                run.return_value.returncode = 0
                engine.refresh_api(None)
                self.assertEqual(run.call_count, 2)
            self.assertFalse(store.meta('api_refresh')['new_coaching']);engine.stop.set()
    def test_bookmarks_cover_full_timeline(self):
        rows = [{'index':i,'change': .9 if i==123 else .01} for i in range(572)]
        chosen = landmarks(rows)
        self.assertIn(0,chosen);self.assertIn(571,chosen);self.assertIn(123,chosen)
        self.assertLessEqual(len(chosen), 72)
