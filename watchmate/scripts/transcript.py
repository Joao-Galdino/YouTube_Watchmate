#!/usr/bin/env python3
"""YouTube Watchmate: reuse saved captions, try bounded yt-dlp, then optional SerpApi."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = 'https://serpapi.com/search'
ID_RE = re.compile(r'[A-Za-z0-9_-]{11}\Z')
LANG_RE = re.compile(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z')
MAX_RESPONSE = 20 * 1024 * 1024
YTDLP_TIMEOUT = 25


class TranscriptError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def video_id(value):
    value = value.strip()
    if ID_RE.fullmatch(value):
        return value
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('https', 'http') or parts.username or parts.password or parts.port:
            raise ValueError()
        host = (parts.hostname or '').lower()
        path = parts.path.strip('/').split('/')
        candidate = ''
        if host == 'youtu.be' and len(path) == 1:
            candidate = path[0]
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
            if parts.path == '/watch':
                values = parse_qs(parts.query).get('v', [])
                if len(values) == 1:
                    candidate = values[0]
            elif len(path) == 2 and path[0] in ('shorts', 'live', 'embed'):
                candidate = path[1]
        if ID_RE.fullmatch(candidate):
            return candidate
    except ValueError:
        pass
    raise TranscriptError('invalid_video', 'Provide a YouTube video URL or an 11-character video ID.')


def default_key_file(platform=None):
    platform = platform or os.name
    if platform == 'nt':
        root = Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming')
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'watchmate/api_key'


def legacy_key_file(platform=None):
    platform = platform or os.name
    if platform == 'nt':
        root = Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming')
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'codex-youtube-transcript/api_key'


def key_file(path=None):
    configured = path or os.environ.get('SERPAPI_API_KEY_FILE')
    if configured:
        return Path(configured).expanduser()
    current = default_key_file()
    if current.is_file():
        return current
    legacy = legacy_key_file()
    return legacy if legacy.is_file() else current


def load_key(path=None):
    key = os.environ.get('SERPAPI_API_KEY', '').strip()
    if not key:
        path = key_file(path)
        try:
            info = path.stat()
            if os.name != 'nt' and info.st_mode & 0o077:
                raise TranscriptError('insecure_key_file', 'The API token file must be readable only by its owner (mode 600).')
            key = path.read_text(encoding='utf-8').strip()
        except (FileNotFoundError, PermissionError, OSError):
            raise TranscriptError('missing_api_key', 'Save the bare SerpApi token in the configured private file or set SERPAPI_API_KEY.') from None
    if not key:
        raise TranscriptError('missing_api_key', 'Save the bare SerpApi token in the configured private file or set SERPAPI_API_KEY.')
    if '=' in key or any(c.isspace() for c in key):
        raise TranscriptError('invalid_api_key_format', 'The credential must contain only the token, with no variable-name prefix or internal whitespace.')
    return key


def provider_error(message, http_status=None):
    lower = str(message).lower()
    if http_status in (401, 403) or any(s in lower for s in ('invalid api key', 'api key is invalid', 'unauthorized', 'authentication')):
        return TranscriptError('authentication_error', 'SerpApi rejected the credential or its access permissions.')
    if 'quota' in lower or 'run out' in lower or 'exhaust' in lower or 'plan limit' in lower:
        return TranscriptError('quota_exhausted', 'SerpApi reports that the account quota is exhausted.')
    if http_status == 429 or 'rate limit' in lower or 'too many' in lower:
        return TranscriptError('rate_limited', 'SerpApi rate-limited the request; no automatic retry was made.')
    if any(s in lower for s in ('transcript not available', 'no transcript', 'transcripts disabled', 'subtitles disabled')):
        return TranscriptError('transcript_unavailable', 'SerpApi reports that the requested transcript is unavailable.')
    if any(s in lower for s in ('video unavailable', 'private video', 'video is unavailable', 'video not found')):
        return TranscriptError('video_unavailable', 'SerpApi reports that the video is unavailable.')
    return TranscriptError('provider_error', 'SerpApi could not complete this request; no raw provider response or credentials were saved.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_payload(vid, language, caption_type, title, key, timeout=45):
    params = {'engine': 'youtube_video_transcript', 'v': vid, 'api_key': key,
              'language_code': language, 'output': 'json'}
    if caption_type:
        params['type'] = caption_type
    if title:
        params['title'] = title
    request = Request(ENDPOINT + '?' + urlencode(params), headers={'Accept': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        # Never interpolate exc: urllib errors may include the authenticated URL.
        message = ''
        try:
            payload = json.loads(exc.read(65536))
            message = payload.get('error', '') if isinstance(payload, dict) else ''
        except (ValueError, OSError):
            pass
        raise provider_error(message, exc.code) from None
    except (URLError, TimeoutError, socket.timeout, OSError):
        raise TranscriptError('network_error', 'The SerpApi request failed or timed out; no automatic retry was made.') from None
    if not raw.strip():
        raise TranscriptError('empty_response', 'SerpApi returned an empty response, not a transcript.')
    if len(raw) > MAX_RESPONSE:
        raise TranscriptError('response_too_large', 'The provider response exceeded the helper size limit.')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise TranscriptError('invalid_response', 'SerpApi did not return valid JSON.') from None
    if not isinstance(data, dict):
        raise TranscriptError('invalid_response', 'SerpApi returned an unexpected response structure.')
    return data


def timestamp(ms):
    seconds = ms // 1000
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def timing(item):
    start, end = item.get('start_ms'), item.get('end_ms')
    if type(start) is not int or start < 0 or (end is not None and (type(end) is not int or end < start)):
        raise TranscriptError('invalid_timing', 'A transcript segment has missing or invalid millisecond timing.')
    return start, end


def normalize(data, vid, requested_language, requested_type):
    if data.get('error'):
        raise provider_error(data['error'])
    metadata = data.get('search_metadata') or {}
    status = metadata.get('status') if isinstance(metadata, dict) else None
    if status == 'Processing':
        raise TranscriptError('processing', 'The provider is still processing the request; no transcript is available yet.')
    if status != 'Success':
        raise TranscriptError('provider_error', 'The provider did not report a successful completed search.')
    rows = data.get('transcript')
    if not isinstance(rows, list) or not rows:
        raise TranscriptError('empty_transcript', 'The provider reported success but returned no transcript segments.')
    segments = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('snippet'), str):
            raise TranscriptError('invalid_response', 'A transcript segment is missing its text.')
        start, end = timing(row)
        if not row['snippet'].strip():
            continue
        segments.append({'start_ms': start, 'end_ms': end, 'start_time_text': timestamp(start), 'text': row['snippet'].strip()})
    if not segments:
        raise TranscriptError('empty_transcript', 'The transcript contained no nonempty text segments.')
    segments.sort(key=lambda row: row['start_ms'])
    tracks = []
    for track in data.get('available_transcripts', []) or []:
        if not isinstance(track, dict):
            continue
        cleaned = {k: track[k] for k in ('language_name', 'language_code', 'type', 'title') if isinstance(track.get(k), str)}
        cleaned['selected'] = track.get('selected') is True
        tracks.append(cleaned)
    selected = next((track for track in tracks if track['selected']), None)
    actual_language = selected.get('language_code') if selected else None
    generated = selected.get('type') == 'asr' if selected else None
    warnings = []
    if any(row['end_ms'] is None for row in segments):
        warnings.append('The provider omitted some segment end times; they are preserved as null rather than estimated.')
    if actual_language is None:
        warnings.append('The selected transcript language/type was not reported; the requested language is not proof of the actual track.')
    elif actual_language != requested_language:
        warnings.append('SerpApi selected a different language than requested.')
    if generated:
        warnings.append('Automatic captions may misrecognize names or technical terms.')
    chapters = []
    for chapter in data.get('chapters', []) or []:
        if isinstance(chapter, dict) and isinstance(chapter.get('chapter'), str):
            start, end = timing(chapter)
            chapters.append({'title': chapter['chapter'], 'start_ms': start, 'end_ms': end})
    return {'schema_version': 1, 'provider': 'serpapi', 'video_id': vid,
            'video_url': 'https://www.youtube.com/watch?v=' + vid,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'requested_language': requested_language, 'requested_type': requested_type,
            'language_code': actual_language, 'is_generated': generated,
            'available_transcripts': tracks, 'chapters': chapters,
            'warnings': warnings, 'segments': segments}


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, '[REDACTED]')
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secret) for key, item in value.items()}
    return value


def choose_track(info, language, caption_type):
    groups = [('automatic_captions', True)] if caption_type == 'asr' else [('subtitles', False), ('automatic_captions', True)]
    for group, generated in groups:
        tracks = info.get(group) or {}
        candidates = [language]
        # yt-dlp disambiguates manually uploaded tracks with a YouTube track ID.
        # Do not accidentally interpret another regional language (en-US) as en.
        if not generated:
            candidates += sorted(k for k in tracks if k.startswith(language + '-') and ID_RE.fullmatch(k[len(language)+1:]))
        for key in candidates:
            if any(entry.get('ext') == 'json3' for entry in tracks.get(key, []) if isinstance(entry, dict)):
                return key, generated
    raise TranscriptError('ytdlp_no_matching_track', 'yt-dlp found no supported caption track for the requested language/type.')


def normalize_json3(payload, vid, language, generated, requested_type):
    segments = []
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise TranscriptError('ytdlp_empty', 'yt-dlp returned no usable JSON3 caption events.')
    for event in payload['events']:
        if not isinstance(event, dict):
            continue
        text = ''.join(part.get('utf8', '') for part in event.get('segs', []) if isinstance(part, dict)).strip()
        if not text:
            continue
        start, duration = event.get('tStartMs'), event.get('dDurationMs')
        if type(start) is not int or start < 0 or (duration is not None and (type(duration) is not int or duration < 0)):
            raise TranscriptError('ytdlp_invalid_timing', 'yt-dlp captions have invalid timing.')
        segments.append({'start_ms':start, 'end_ms':start+duration if duration is not None else None,
                         'start_time_text':timestamp(start), 'text':text})
    if not segments:
        raise TranscriptError('ytdlp_empty', 'yt-dlp returned an empty caption track.')
    segments.sort(key=lambda s:s['start_ms'])
    return {'schema_version':1,'provider':'yt-dlp','video_id':vid,
            'video_url':'https://www.youtube.com/watch?v='+vid,
            'retrieved_at':datetime.now(timezone.utc).isoformat(),
            'requested_language':language,'requested_type':requested_type,'requested_title':None,
            'language_code':language,'is_generated':generated,'chapters':[],
            'available_transcripts':[{'language_code':language,'type':'asr' if generated else 'manual','selected':True}],
            'warnings':['Automatic captions may misrecognize names or technical terms.'] if generated else [],
            'segments':segments}


def find_ytdlp():
    relative = 'Scripts/yt-dlp.exe' if os.name == 'nt' else 'bin/yt-dlp'
    local = Path(__file__).resolve().parents[1] / '.venv' / relative
    if local.is_file():
        return str(local)
    installed = shutil.which('yt-dlp')
    if installed:
        return installed
    raise TranscriptError('ytdlp_missing', 'yt-dlp is not installed in this skill environment or on PATH.')


def run_ytdlp(command, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TranscriptError('ytdlp_timeout', 'The bounded yt-dlp attempt timed out.')
    env = os.environ.copy()
    for name in ('SERPAPI_API_KEY','SERPAPI_API_KEY_FILE','PYTHONPATH','PYTHONHOME'):
        env.pop(name, None)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=remaining, env=env, check=False)
    except subprocess.TimeoutExpired:
        raise TranscriptError('ytdlp_timeout', 'The bounded yt-dlp attempt timed out.') from None
    except (OSError, UnicodeError):
        raise TranscriptError('ytdlp_failed', 'yt-dlp could not run successfully.') from None
    if result.returncode:
        # Never expose stderr: it can contain signed caption URLs or proxy details.
        raise TranscriptError('ytdlp_failed', 'yt-dlp failed; no raw download log was retained.')
    if len(result.stdout) > MAX_RESPONSE:
        raise TranscriptError('ytdlp_invalid_response', 'yt-dlp metadata exceeded the helper size limit.')
    return result.stdout


def fetch_ytdlp(vid, language, caption_type, title):
    if title:
        raise TranscriptError('ytdlp_unsupported_selector', 'Named transcript selection is delegated to SerpApi.')
    command = [find_ytdlp(), '--ignore-config', '--no-config-locations', '--no-plugin-dirs',
               '--no-js-runtimes', '--no-remote-components', '--no-playlist', '--skip-download',
               '--socket-timeout', '8', '--retries', '0', '--fragment-retries', '0',
               '--extractor-retries', '0', '--file-access-retries', '0', '--no-cache-dir',
               '--quiet', '--no-warnings']
    deadline = time.monotonic() + YTDLP_TIMEOUT
    try:
        raw = run_ytdlp(command + ['--dump-single-json', '--', 'https://www.youtube.com/watch?v='+vid], deadline)
        info = json.loads(raw)
        if not isinstance(info, dict) or info.get('id') != vid or info.get('_type') in ('playlist','multi_video'):
            raise TranscriptError('ytdlp_invalid_response', 'yt-dlp returned metadata for an unexpected video.')
        track, generated = choose_track(info, language, caption_type)
        with tempfile.TemporaryDirectory(prefix='watchmate-captions-') as tmp:
            work = Path(tmp)
            metadata = work/'video.info.json'
            metadata.write_text(json.dumps(info),encoding='utf-8')
            os.chmod(metadata,0o600)
            options = ['--no-write-subs', '--write-auto-subs'] if generated else ['--write-subs','--no-write-auto-subs']
            run_ytdlp(command + options + ['--sub-langs', '^'+re.escape(track)+'$', '--sub-format','json3',
                      '--output', str(work/'captions.%(ext)s'), '--load-info-json', str(metadata)],deadline)
            files=list(work.glob('captions.*.json3'))
            if len(files)!=1 or files[0].stat().st_size == 0:
                raise TranscriptError('ytdlp_empty', 'yt-dlp did not produce one nonempty caption track.')
            if files[0].stat().st_size > MAX_RESPONSE:
                raise TranscriptError('ytdlp_invalid_response', 'The caption file exceeded the helper size limit.')
            return normalize_json3(json.loads(files[0].read_text(encoding='utf-8')),vid,language,generated,caption_type)
    except TranscriptError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise TranscriptError('ytdlp_invalid_response', 'yt-dlp returned unusable caption data.') from None


def output_paths(vid, output_dir, language, caption_type, title=None):
    # The generated filename uses validated ID/language/type only, never an arbitrary URL or track title.
    stem = f"{vid}.{language}.{caption_type or 'default'}"
    if title:
        import hashlib
        stem += '.' + hashlib.sha256(title.encode()).hexdigest()[:10]
    return {'json': output_dir / (stem + '.json'), 'text': output_dir / (stem + '.txt')}


def ensure_new_output(paths):
    if any(path.exists() for path in paths.values()):
        raise TranscriptError('output_exists', 'Output already exists. Reuse it or choose another output directory; no existing file was overwritten.')


def save_transcript(data, output_dir, language, caption_type, title=None):
    paths = output_paths(data['video_id'], output_dir, language, caption_type, title)
    ensure_new_output(paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    texts = {'json': json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'text': render_text(data)}
    written = []
    try:
        for kind, path in paths.items():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            written.append(path)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(texts[kind])
    except OSError:
        for path in written:
            path.unlink(missing_ok=True)
        raise TranscriptError('output_error', 'Could not create the transcript files; existing files were not overwritten.') from None
    return {kind: str(path.resolve()) for kind, path in paths.items()}


def render_text(data):
    provider = 'SerpApi' if data['provider']=='serpapi' else 'yt-dlp'
    return (data['video_url'] + '\nProvider: '+provider+'\nLanguage: ' + str(data['language_code']) +
            '\nAutomatic captions: ' + str(data['is_generated']) + '\n\n' +
            '\n'.join(f"[{s['start_time_text']}] {s['text']}" for s in data['segments']) + '\n')


def cached_transcript(paths, vid, language, caption_type, title):
    if not any(p.exists() for p in paths.values()):
        return None
    try:
        if not all(p.is_file() and p.stat().st_size <= MAX_RESPONSE for p in paths.values()):
            raise ValueError()
        data = json.loads(paths['json'].read_text(encoding='utf-8'))
        if (data.get('schema_version') != 1 or data.get('video_id') != vid or
            data.get('video_url') != 'https://www.youtube.com/watch?v='+vid or
            data.get('requested_language') != language or data.get('requested_type') != caption_type or
            data.get('requested_title') != title or data.get('provider') not in ('serpapi','yt-dlp') or
            not isinstance(data.get('segments'),list) or not data['segments']):
            raise ValueError()
        for row in data['segments']:
            start, _ = timing(row)
            if not isinstance(row.get('text'),str) or not row['text'].strip() or row.get('start_time_text') != timestamp(start):
                raise ValueError()
        if paths['text'].read_text(encoding='utf-8') != render_text(data):
            raise ValueError()
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError, TranscriptError):
        raise TranscriptError('cache_conflict', 'Existing output is incomplete or does not match this video, language, track, or format. Choose a new output directory; no file was overwritten.') from None


def search_segments(data, terms, context=2, limit=10):
    rows = data.get('segments')
    if not isinstance(rows, list) or not ID_RE.fullmatch(str(data.get('video_id', ''))):
        raise TranscriptError('invalid_transcript_file', 'The file is not a normalized YouTube transcript.')
    needles = [term.casefold() for term in terms if term.strip()]
    matches = []
    for i, row in enumerate(rows):
        if any(term in row.get('text', '').casefold() for term in needles):
            matches.append({'start_ms': row['start_ms'], 'timestamp': timestamp(row['start_ms']),
                            'url': f"https://www.youtube.com/watch?v={data['video_id']}&t={row['start_ms']//1000}s",
                            'segments': rows[max(0, i-context):i+context+1]})
            if len(matches) >= limit:
                break
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch')
    fetch.add_argument('video')
    fetch.add_argument('--output-dir', type=Path, required=True)
    fetch.add_argument('--language', default='en')
    fetch.add_argument('--type', dest='caption_type', choices=['asr'])
    fetch.add_argument('--title')
    fetch.add_argument('--provider', choices=['auto','yt-dlp','serpapi'], default='auto')
    fetch.add_argument('--fallback', choices=['auto','off'], default=os.environ.get('YOUTUBE_TRANSCRIPT_FALLBACK','auto'))
    fetch.add_argument('--key-file', type=Path)
    status = commands.add_parser('status', help='Check availability without reading tokens or making requests.')
    status.add_argument('--key-file', type=Path)
    search = commands.add_parser('search')
    search.add_argument('file', type=Path)
    search.add_argument('--terms', nargs='+', required=True)
    search.add_argument('--context', type=int, choices=range(0, 6), default=2)
    search.add_argument('--limit', type=int, choices=range(1, 21), default=10)
    args = parser.parse_args()
    try:
        if args.command == 'status':
            try:
                find_ytdlp()
                available = True
            except TranscriptError:
                available = False
            # Presence is not validation: never read the credential for a status check.
            credential = bool(os.environ.get('SERPAPI_API_KEY','').strip())
            if not credential:
                try:
                    candidate = key_file(args.key_file)
                    credential = candidate.is_file() and candidate.stat().st_size > 0
                except OSError:
                    credential = False
            result = {'status':'success','yt_dlp_available':available,
                      'credential_configured':credential,'credential_validated':False,
                      'fallback':os.environ.get('YOUTUBE_TRANSCRIPT_FALLBACK','auto')}
        elif args.command == 'fetch':
            if args.fallback not in ('auto','off'):
                raise TranscriptError('invalid_fallback','YOUTUBE_TRANSCRIPT_FALLBACK must be auto or off.')
            if args.provider == 'serpapi' and args.fallback == 'off':
                raise TranscriptError('conflicting_options','Explicit SerpApi mode conflicts with fallback off; choose a single provider policy.')
            vid = video_id(args.video)
            if not LANG_RE.fullmatch(args.language):
                raise TranscriptError('invalid_language', 'Use a language code such as en, pt, pt-BR, or zh-Hans.')
            if args.title and (len(args.title) > 250 or any(ord(c) < 32 for c in args.title)):
                raise TranscriptError('invalid_title', 'Use a short transcript title without control characters.')
            planned = output_paths(vid, args.output_dir, args.language, args.caption_type, args.title)
            data = cached_transcript(planned,vid,args.language,args.caption_type,args.title)
            cache_hit = data is not None
            if cache_hit:
                paths = {kind:str(path.resolve()) for kind,path in planned.items()}
            else:
                failure = None
                if args.provider != 'serpapi':
                    try:
                        data = fetch_ytdlp(vid,args.language,args.caption_type,args.title)
                    except TranscriptError as local_failure:
                        failure = local_failure
                if args.provider == 'serpapi' or failure:
                    if failure and (args.fallback == 'off' or args.provider == 'yt-dlp'):
                        raise TranscriptError(failure.code, str(failure)+' SerpApi fallback is disabled.') from None
                    try:
                        key = load_key(args.key_file)
                        payload = fetch_payload(vid, args.language, args.caption_type, args.title, key)
                        data = redact(normalize(payload, vid, args.language, args.caption_type), key)
                    except TranscriptError as api_failure:
                        if failure and api_failure.code == 'missing_api_key':
                            raise TranscriptError('local_extraction_unavailable','yt-dlp attempt: '+failure.code+'. The optional SerpApi fallback is not configured. Install yt-dlp in the skill environment, provide saved captions, or configure your own API token.') from None
                        prefix = 'yt-dlp attempt: '+failure.code+'. SerpApi fallback: ' if failure else ''
                        raise TranscriptError(api_failure.code,prefix+str(api_failure)) from None
                    if failure:
                        data['fallback_reason'] = failure.code
                        data['warnings'].append('yt-dlp did not provide a usable transcript; SerpApi fallback reason: '+failure.code+'.')
                data['requested_title'] = args.title
                paths = save_transcript(data, args.output_dir, args.language, args.caption_type, args.title)
            result = {'status':'success','provider':data['provider'],'cache_hit':cache_hit,
                      'fallback_reason':data.get('fallback_reason'),'video_id':vid,'segments':len(data['segments']),
                      'language_code':data['language_code'],'is_generated':data['is_generated'],
                      'warnings':data['warnings'],'files':paths}
        else:
            data = json.loads(args.file.read_text(encoding='utf-8'))
            result = {'status':'success','matches':search_segments(data,args.terms,args.context,args.limit)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except TranscriptError as exc:
        print(json.dumps({'status':'error','code':exc.code,'message':str(exc)}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(json.dumps({'status':'error','code':'invalid_input_or_response','message':'The input file or provider response could not be processed safely.'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
