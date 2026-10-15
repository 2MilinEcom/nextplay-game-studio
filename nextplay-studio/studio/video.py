import json
import math
import subprocess
from pathlib import Path
from .core import binary, hash_file, write_json


def probe(path, max_minutes=20):
    result = subprocess.run([binary('ffprobe'), '-v', 'error', '-show_entries',
                             'format=duration:stream=codec_type,width,height,codec_name', '-of', 'json', str(path)],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('This file is not a readable video. Use an MP4, MOV, M4V, WebM, or MKV recording.')
    data = json.loads(result.stdout)
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('No video track found in this recording.')
    try:
        duration = float(data['format']['duration'])
    except (ValueError, KeyError, TypeError):
        raise ValueError('The video duration is unavailable. Export the recording as MP4 and retry.') from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Empty or invalid recording.')
    if duration > max_minutes * 60:
        raise ValueError(f'Recording is longer than {max_minutes} minutes. Split it into matches or raise the limit in Settings.')
    width, height = video.get('width', 0), video.get('height', 0)
    if not 32 <= width <= 16384 or not 32 <= height <= 16384:
        raise ValueError('Unsupported video dimensions.')
    return {'duration_seconds': round(duration, 3), 'width': width, 'height': height,
            'codec': video.get('codec_name', 'unknown')}


def sample_times(duration, interval, maximum):
    count = min(maximum, max(1, math.ceil(duration / interval)))
    if count == 1:
        return [0.0]
    end = max(0, duration - min(0.15, duration / 10))
    return [round(i * end / (count - 1), 3) for i in range(count)]


def extract(path, directory, settings, check_cancel=lambda: None, progress=lambda _: None):
    info = probe(path, settings['max_minutes'])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    frames = []
    times = sample_times(info['duration_seconds'], settings['sample_interval'], settings['max_frames'])
    for i, timestamp in enumerate(times):
        check_cancel()
        frame_id = f'f{i:04d}'
        target = directory / f'{frame_id}.jpg'
        # Accurate seek requests a decoded image at the requested video-relative time.
        proc = subprocess.run([binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                               '-ss', str(timestamp), '-i', str(path), '-frames:v', '1',
                               '-vf', "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                               '-q:v', '3', '-y', str(target)], capture_output=True, timeout=45)
        if proc.returncode or not target.exists() or target.stat().st_size < 100:
            if i == len(times) - 1 and frames:
                continue
            raise ValueError(f'Could not decode the recording near {timestamp:.1f}s. Try exporting as MP4.')
        frames.append({'id': frame_id, 'time_seconds': timestamp, 'path': str(target),
                       'sha256': hash_file(target)})
        progress(round((i + 1) / len(times) * 100))
    info['sampled_frames'] = len(frames)
    info['sampling_gap_seconds'] = round(max((b['time_seconds'] - a['time_seconds'] for a, b in zip(frames, frames[1:])), default=0), 3)
    info['timestamp_basis'] = 'Requested decoded sample time relative to recording start; not an in-game clock or mistake timestamp.'
    write_json(directory / 'manifest.json', {'video': info, 'frames': frames})
    return info, frames


def normalize_jpeg(source, target):
    if source.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Screen frame exceeds 4 MB.')
    result = subprocess.run([binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                             '-i', str(source), '-frames:v', '1',
                             '-vf', "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                             '-q:v', '3', '-y', str(target)], capture_output=True, timeout=15)
    if result.returncode or not target.exists():
        raise ValueError('Invalid screen frame.')


def browser_preview(source, directory, info):
    """Convert phone MOV/HEVC and other incompatible containers to a local H.264 preview."""
    if Path(source).suffix.lower() == '.mp4' and info['codec'] == 'h264':
        return None
    target = Path(directory) / 'preview.mp4'
    temporary = target.with_name('preview.partial.mp4')
    result = subprocess.run([binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                             '-i', str(source), '-an', '-vf',
                             "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p',
                             '-movflags', '+faststart', '-y', str(temporary)], capture_output=True, timeout=600)
    if result.returncode:
        temporary.unlink(missing_ok=True)
        raise ValueError('Could not prepare browser playback. Export your recording as H.264 MP4 and retry.')
    temporary.replace(target)
    target.chmod(0o600)
    return str(target)
