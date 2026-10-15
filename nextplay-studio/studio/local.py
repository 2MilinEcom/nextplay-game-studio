"""Offline recording scan. Text is evidence to inspect, not a game-state oracle."""
import json
import math
import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from .core import binary, hash_file, write_json
from .video import probe
from .coach import finish_report


def wait_process(proc, check, timeout):
    started = time.monotonic()
    try:
        while proc.poll() is None:
            check()
            if time.monotonic() - started > timeout:
                raise ValueError('Local processing timed out. Try a shorter recording.')
            time.sleep(.2)
        if proc.returncode:
            raise ValueError('Local processing failed. See the local diagnostic log in the recording folder.')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def prepare_playback(source, directory, info, check):
    if Path(source).suffix.lower() == '.mp4' and info['codec'] == 'h264':
        return
    temporary = directory / 'preview.partial.mp4'
    with (directory / 'preview-diagnostics.log').open('w') as log:
        proc = subprocess.Popen([binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-i', str(source), '-an', '-vf', 'scale=-2:960,fps=30', '-c:v', 'libx264',
            '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-y', str(temporary)], stdout=log, stderr=log)
        wait_process(proc, check, 600)
    temporary.replace(directory / 'preview.mp4')


def landmarks(rows):
    """Rank visual changes; never describe them as card plays or mistakes."""
    if not rows:
        return []
    chosen = {0, len(rows)-1}
    for row in sorted(rows, key=lambda r: r.get('change', 0), reverse=True):
        index = row['index']
        if all(abs(index-other) >= 4 for other in chosen):
            chosen.add(index)
        if len(chosen) >= max(40, math.ceil(len(rows)/20)+2):
            break
    chosen.update(range(0, len(rows), 20))
    return sorted(chosen)


def scan(store, job, settings, check, progress):
    info = probe(job['source'], settings['max_minutes'])
    directory = store.data / 'frames' / job['id']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = directory / 'local-diagnostics.log'
    source = Path(__file__).with_name('local_vision.swift')
    helper_dir = store.data / 'helpers'
    helper_dir.mkdir(exist_ok=True, mode=0o700)
    helper = helper_dir / ('vision-' + hash_file(source)[:16])
    with log.open('w') as diagnostics:
        if not helper.exists():
            progress(4, 'Preparing Apple’s on-device text recognition.')
            proc = subprocess.Popen(['/usr/bin/swiftc', '-O', '-module-cache-path', str(helper_dir / 'module-cache'), str(source), '-o', str(helper)], stdout=diagnostics, stderr=diagnostics)
            wait_process(proc, check, 180)
        for old in directory.glob('f[0-9][0-9][0-9][0-9].jpg'):
            old.unlink()
        progress(10, 'Decoding the full recording locally at two samples per second.')
        proc = subprocess.Popen([binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', job['source'], '-an', '-vf', 'fps=2,scale=-2:960', '-q:v', '4', '-start_number', '0', '-y', str(directory / 'f%04d.jpg')], stdout=diagnostics, stderr=diagnostics)
        wait_process(proc, check, settings['max_minutes']*60+120)
        paths = sorted(directory.glob('f[0-9][0-9][0-9][0-9].jpg'))
        if not paths:
            raise ValueError('No frames decoded.')
        manifest = directory / 'local-input.txt'
        manifest.write_text('\n'.join(str(p) for p in paths))
        progress(30, f'Scanning {len(paths)} frames locally; recognizing text once per second.')
        output = directory / 'local-timeline.ndjson'
        with output.open('w') as result:
            proc = subprocess.Popen([str(helper), str(manifest)], stdout=result, stderr=diagnostics)
            wait_process(proc, check, settings['max_minutes']*120+180)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    if any('error' in row for row in rows) or len(rows) != len(paths):
        raise ValueError('Some local frames could not be analyzed. Retry this recording.')
    frames = [{'id': p.stem, 'time_seconds': round((i+.5)/2, 3), 'path': str(p), 'sha256': hash_file(p)} for i,p in enumerate(paths)]
    observations = []
    for index in landmarks(rows):
        row, frame = rows[index], frames[index]
        # A readable clock is only a candidate gameplay marker, never proof of app identity.
        clocks = [t['text'] for t in row['text'] if re.fullmatch(r'\d{1,2}:\d{2}', t['text']) and t['box'][1] < .3]
        observations.append({'id': f'local-{index:04d}', 'kind': 'local_review_bookmark', 'confidence': 'LOW',
            'sample_start_seconds': frame['time_seconds'], 'frame_ids': [frame['id']],
            'statement': 'Review bookmark: visible text and scene change.',
            'visible_evidence': 'Local image-change score %.3f. %s' % (row['change'], ('Clock-like text: '+', '.join(clocks)+'. ' if clocks else '') + 'OCR candidates (may be wrong): '+ '; '.join(t['text'] for t in row['text'])[:240]),
            'text_candidates': row['text'], 'verification': 'Unverified local OCR; inspect the screenshot.'})
    info.update({'sampled_frames': len(frames), 'sampling_gap_seconds': .5, 'local_ocr_interval_seconds': 1,
                 'timestamp_basis': 'Centers of ffmpeg two-per-second sampling bins relative to recording; approximate, not in-game action times.',
                 'scan_method': 'Apple Vision local OCR and pixel changes', 'timeline_file': 'local-timeline.ndjson'})
    check()
    progress(65, 'Recognizing card icons and arena units entirely on this Mac.')
    app = Path(__file__).resolve().parent.parent
    runtime = app / '.vision-venv' / 'bin' / 'python'
    if not runtime.exists():
        raise ValueError('The local recognition runtime is missing. Restore the NextPlay vision environment; no cloud fallback is used.')
    with log.open('a') as diagnostics:
        proc = subprocess.Popen([str(runtime), str(app / 'studio' / 'recognize.py'), '--directory', str(directory), '--models', str(app / 'models')], stdout=diagnostics, stderr=diagnostics)
        wait_process(proc, check, settings['max_minutes']*120+180)
    recognition = json.loads((directory / 'local-recognition.json').read_text())
    check()
    progress(85, 'Preparing local replay playback.')
    prepare_playback(job['source'], directory, info, check)
    check()
    coaching = {'summary': f'Local scan complete: {len(frames)} frames across {info["duration_seconds"]:.1f} seconds. No OpenAI calls. Bookmarks identify visual changes for replay review; they do not establish tactical mistakes.', 'confidence': 'LOW', 'priorities': []}
    progress(95, 'Saving the local timeline and screenshot evidence.')
    report = finish_report(store, job, frames, info, observations,
        ['Troop identity, exact hand/elixir, placements and optimal moves are not established by this local scanner.', 'Text recognition can misread counters. Visual change can reflect animations rather than a player action.', 'Events between half-second samples remain unobserved.'], [], coaching, SimpleNamespace(calls=[]), settings)
    report['data_limits'] = [x for x in report['data_limits'] if not x.startswith('Observations are AI') and not x.startswith('No audio is sent.')] + ['Processing stays on this Mac. No OpenAI calls or audio analysis.', 'Local OCR and visual changes are unverified; counter readings and unit predictions require screenshot verification.']
    report['local_timeline'] = [dict(row, time_seconds=frames[row['index']]['time_seconds']) for row in rows]
    report['provenance'].update({'processing_mode': 'local', 'api_cost_usd': 0, 'observation_basis': 'Local pixel changes and Apple Vision OCR; unverified text candidates'})
    from .recognition_report import enrich
    report = enrich(report, recognition)
    from .evaluate import evaluate
    report = evaluate(report)
    write_json(directory / 'manifest.json', {'video': info, 'frames': frames})
    from .coach import report_markdown
    write_json(store.data / 'reports' / (job['id']+'.json'), report)
    (store.data / 'reports' / (job['id']+'.md')).write_text(report_markdown(report))
    return report
