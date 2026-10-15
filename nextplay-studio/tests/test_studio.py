import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from pathlib import Path
from studio.core import Store, binary, hash_file
from studio.video import probe, extract, sample_times
from studio.coach import validate_observations, observe, make_coaching, report_markdown
from studio.worker import Engine, Cancelled
from studio.server import Server

class FakeModel:
    def __init__(self, supported=True, game=True):
        self.calls=[]
        self.supported,self.game=supported,game
    def call(self, model, prompt, data, schema, frames=None, max_tokens=1800):
        self.calls.append({'model':'test-double','usage':{},'response_id':'test-only'})
        if 'game_visible' in schema['properties']:
            return {'game_visible':self.game,'quality':'CLEAR' if self.game else 'NOT_GAMEPLAY','observations':[{'statement':'A blue bridge is visible.','visible_evidence':'A blue rectangle crosses the arena.','kind':'scene','confidence':'MEDIUM','frame_ids':[frames[0]['id']]}] if self.game else [],'unknowns':['Actions between samples are unknown.']}
        if 'verdicts' in schema['properties']:
            return {'verdicts':[{'id':o['id'],'supported':self.supported,'reason':'Test evidence verdict.'} for o in data['candidates']]}
        return {'summary':'Review the visible arena before drawing tactical conclusions.','confidence':'LOW','priorities':[{'title':'Review the visible bridge','goal':'Review one full-speed replay.','measurement':'One replay reviewed.','review_question':'What is visible around this sample?','evidence_ids':[data['observations'][0]['id']]}]}

class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nextplay-tests-')
        self.project=Path(self.temp.name)
        self.store=Store(self.project)
        self.store.save_settings({'processing_mode':'cloud'})
        self.engine=Engine(self.store,model_factory=FakeModel,start=False)
    def tearDown(self):
        self.engine.stop.set();self.temp.cleanup()
    def clip(self,name='test.mp4'):
        path=self.project/name
        subprocess.run([binary('ffmpeg'),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=160x284:d=1','-c:v','libx264','-pix_fmt','yuv420p','-y',str(path)],check=True,capture_output=True)
        return path

class EvidenceTests(Base):
    def test_only_supplied_frame_ids_are_accepted(self):
        output={'game_visible':True,'observations':[{'statement':'A tower is visible.','visible_evidence':'Visible tower.','frame_ids':['invented'],'confidence':'MEDIUM'}]}
        with self.assertRaises(ValueError):validate_observations(output,[{'id':'f0000'}])
    def test_non_gameplay_cannot_have_observations(self):
        output={'game_visible':False,'observations':[{'statement':'Troops attacking.','visible_evidence':'Troops.','frame_ids':['f0000'],'confidence':'MEDIUM'}]}
        with self.assertRaises(ValueError):validate_observations(output,[{'id':'f0000'}])
    def test_banned_tactical_claim_is_rejected(self):
        output={'game_visible':True,'observations':[{'statement':'You overcommitted.','visible_evidence':'A troop.','frame_ids':['f0000'],'confidence':'MEDIUM'}]}
        with self.assertRaises(ValueError):validate_observations(output,[{'id':'f0000'}])
    def test_checker_can_withhold_unsupported_claim(self):
        output=observe([{'id':'f0000','time_seconds':3.2}],FakeModel(supported=False),self.store.settings,'batch')
        self.assertEqual(output['observations'],[]);self.assertEqual(len(output['withheld']),1)
    def test_timestamps_are_generated_from_manifest(self):
        output=observe([{'id':'f0000','time_seconds':12.25}],FakeModel(),self.store.settings,'batch')
        self.assertEqual(output['observations'][0]['sample_start_seconds'],12.25)
        self.assertEqual(output['observations'][0]['verification']['status'],'AI_REVIEWED')
    def test_no_evidence_means_no_tactical_coaching(self):
        model=FakeModel();result=make_coaching([],model,self.store.settings,{})
        self.assertEqual(result['priorities'],[]);self.assertEqual(model.calls,[])
    def test_selected_api_context_removes_leak_fields(self):
        (self.project/'nextplay-clash-review.json').write_text(json.dumps({'battles':[{'time':'battle1','result':'WIN','your_deck':['Elixir Golem'],'your_elixir_leaked_raw':99}]}))
        context=self.store.context('battle1');self.assertNotIn('your_elixir_leaked_raw',context['battle']);self.assertEqual(context['battle']['your_deck'],['Elixir Golem']);self.assertEqual(context['link_method'],'user_selected');self.assertEqual(self.store.context(None),{})

class PipelineTests(Base):
    def test_cleared_inbox_error_does_not_stay_visible(self):
        self.store.meta('watch_error', {'error':'old error'})
        self.store.meta('watch_error', None)
        self.assertIsNone(self.store.meta('watch_error'))

    def test_unchanged_api_facts_do_not_trigger_ai_call(self):
        for name in ['test_clash_api.py','nextplay-clash-v2.py','nextplay-clash-ai.py']:
            (self.project/name).write_text('# test fixture')
        review=self.project/'nextplay-clash-review.json';review.write_text('{}')
        (self.project/'nextplay-clash-ai-review.json').write_text(json.dumps({'metadata':{'deterministic_sha256':hash_file(review)}}))
        with patch('studio.worker.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            self.engine.refresh_api(None)
        self.assertEqual(run.call_count,2)
        self.assertFalse(self.store.meta('api_refresh')['new_coaching'])
    def test_changed_api_facts_trigger_ai_call(self):
        for name in ['test_clash_api.py','nextplay-clash-v2.py','nextplay-clash-ai.py']:
            (self.project/name).write_text('# test fixture')
        (self.project/'nextplay-clash-review.json').write_text('{}')
        with patch('studio.worker.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            self.engine.refresh_api(None)
        self.assertEqual(run.call_count,3)
        self.assertTrue(self.store.meta('api_refresh')['new_coaching'])
    def test_restart_releases_interrupted_api_refresh(self):
        self.store.meta('api_refresh',{'state':'running'})
        restarted=Store(self.project)
        self.assertEqual(restarted.meta('api_refresh')['state'],'failed')
    def test_video_pipeline_saves_matching_exports(self):
        path=self.clip();job,duplicate=self.engine.ingest(path,demo=True);self.assertFalse(duplicate);self.engine.review_video(job['id'])
        completed=self.store.get_job(job['id']);self.assertEqual(completed['state'],'completed');report=completed['result']
        self.assertTrue(report['demo']);self.assertEqual(report['provenance']['source_sha256'],hash_file(path));self.assertNotIn('path',report['frames'][0]);self.assertFalse(report['provenance']['elixir_coaching_allowed'])
        self.assertEqual((self.store.data/'reports'/(job['id']+'.md')).read_text(),report_markdown(report));self.assertTrue(report['coaching']['priorities'][0]['evidence_ids'])
    def test_duplicate_upload_is_not_reprocessed(self):
        path=self.clip();first,_=self.engine.ingest(path);second,duplicate=self.engine.ingest(path)
        self.assertTrue(duplicate);self.assertEqual(first['id'],second['id']);self.assertEqual(self.engine.queue.qsize(),1)
    def test_non_video_fails_decoding(self):
        path=self.project/'broken.mp4';path.write_bytes(b'not a video')
        with self.assertRaises(ValueError):probe(path)
    def test_frame_limit_spans_entire_recording(self):
        times=sample_times(600,6,24);self.assertEqual(len(times),24);self.assertEqual(times[0],0);self.assertGreater(times[-1],599);self.assertEqual(sample_times(.1,6,24),[0])
    def test_restart_marks_in_flight_jobs_interrupted(self):
        job=self.store.create_job('video','test');self.store.update(job['id'],state='processing');restarted=Store(self.project);self.assertEqual(restarted.get_job(job['id'])['state'],'interrupted')
    def test_cancel_stops_future_processing(self):
        job,_=self.engine.ingest(self.clip());self.engine.cancel(job['id'])
        with self.assertRaises(Cancelled):self.engine.review_video(job['id'])
        self.assertEqual(self.store.get_job(job['id'])['state'],'cancelled')
    def test_live_session_stops_at_check_limit(self):
        self.store.save_settings({'live_batch_frames':2,'live_max_checks':1});_,frames=extract(self.clip(),self.project/'test-frames',self.store.settings);data=Path(frames[0]['path']).read_bytes();job=self.engine.begin_live();self.engine.push_live(job['id'],data,0);self.engine.push_live(job['id'],data,5)
        kind,payload=self.engine.live_queue.get_nowait();self.assertEqual(kind,'live');self.engine.review_live(payload);result=self.store.get_job(job['id']);self.assertEqual(result['state'],'completed');self.assertEqual(result['result']['video']['checks_completed'],1)
        with self.assertRaises(ValueError):self.engine.push_live(job['id'],data,10)
    def test_immediate_screen_stop_makes_no_model_calls(self):
        job=self.engine.begin_live();self.engine.end_live(job['id'])
        self.assertEqual(self.store.get_job(job['id'])['state'],'cancelled')
        self.assertEqual(self.engine.live[job['id']]['model'].calls,[])
    def test_stop_flushes_partial_live_batch(self):
        _,frames=extract(self.clip(),self.project/'test-frames',self.store.settings);job=self.engine.begin_live();self.engine.push_live(job['id'],Path(frames[0]['path']).read_bytes(),0);self.engine.end_live(job['id']);_,payload=self.engine.live_queue.get_nowait();self.engine.review_live(payload);self.assertEqual(self.store.get_job(job['id'])['state'],'completed')
    def test_settings_reject_unbounded_or_invalid_values(self):
        for value in [{'max_frames':10000},{'watch_enabled':'true'},{'vision_model':'../bad'},{'unknown':1}]:
            with self.assertRaises(ValueError):self.store.save_settings(value)
        self.store.save_settings({'verify_observations':False});self.assertTrue(self.store.settings['verify_observations'])

class HttpTests(Base):
    def setUp(self):
        super().setUp();self.server=Server(('127.0.0.1',0),self.store,self.engine);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base=f'http://127.0.0.1:{self.server.server_address[1]}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();super().tearDown()
    def request(self,path,data=None,headers=None,auth=False):
        headers=dict(headers or {})
        if auth:headers['X-NextPlay-Token']=self.server.token
        return urllib.request.urlopen(urllib.request.Request(self.base+path,data=data,headers=headers),timeout=10)
    def test_host_and_origin_guard(self):
        with self.assertRaises(urllib.error.HTTPError) as context:self.request('/api/bootstrap',headers={'Host':'attacker.example'})
        self.assertEqual(context.exception.code,403);context.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as context:self.request('/api/settings',b'{}',{'Origin':'https://attacker.example'},True)
        self.assertEqual(context.exception.code,403);context.exception.close()
    def test_api_requires_local_session(self):
        with self.assertRaises(urllib.error.HTTPError) as context:self.request('/api/jobs')
        self.assertEqual(context.exception.code,403);context.exception.close();response=self.request('/api/bootstrap');self.assertIn('HttpOnly',response.headers['Set-Cookie']);self.assertIn('SameSite=Strict',response.headers['Set-Cookie']);response.close()
    def test_upload_and_range_playback(self):
        clip=self.clip();response=self.request('/api/uploads',clip.read_bytes(),{'X-File-Name':'my-match.mp4'},True);job=json.load(response)['job'];response.close();response=self.request('/media/'+job['id'],headers={'Range':'bytes=0-99'},auth=True)
        self.assertEqual(response.status,206);self.assertEqual(len(response.read()),100);response.close();self.assertNotIn('source',self.store.get_job(job['id']))
    def test_path_traversal_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as context:self.request('/../../.env',auth=True)
        self.assertEqual(context.exception.code,404);context.exception.close()
    def test_notes_persist_unicode_without_becoming_html(self):
        job=self.store.create_job('video','test');text='<script>alert("x")</script> — 练习';self.request('/api/jobs/'+job['id']+'/notes',json.dumps({'text':text}).encode(),auth=True).close();self.assertEqual(self.store.get_job(job['id'])['notes'],text)
        self.assertNotIn('innerHTML',(Path(__file__).parents[1]/'studio/static/app.js').read_text())

if __name__=='__main__':unittest.main()
