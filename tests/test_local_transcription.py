import sys
from types import SimpleNamespace

import pytest
import providers
from test_api import setup_app


def test_local_transcription_uses_cpu_and_consumes_segments(monkeypatch):
    calls = {}
    class FakeModel:
        def __init__(self, model, **kwargs):
            calls.update(model=model, **kwargs)
        def transcribe(self, path, **kwargs):
            calls.update(kwargs)
            def segments():
                calls['consumed'] = True
                yield SimpleNamespace(start=0, end=2, text='English tutorial')
            return segments(), None
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setenv('TRAINLY_TRANSCRIPTION_BACKEND', 'local')
    monkeypatch.setenv('TRAINLY_AI_BASE_URL', 'https://unused.invalid')
    result = providers.transcribe_audio('example.wav', 3)
    assert result == [dict(start=0, end=2, text='English tutorial')]
    assert calls == dict(model='small.en',device='cpu',compute_type='int8',cpu_threads=4,language='en',vad_filter=True,consumed=True)
    assert providers.ai_status()['draft_model'] is None
    assert providers.ai_status()['transcription_model'] == 'small.en'


def test_missing_local_dependency_is_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules, 'faster_whisper', None)
    with pytest.raises(providers.ProviderError, match='requirements-transcription.txt'):
        providers.transcribe_local('example.wav', 3)


def test_local_failure_does_not_expose_paths(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('secret/private/file.wav')
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=fail))
    with pytest.raises(providers.ProviderError, match='Check model availability') as error:
        providers.transcribe_local('secret/private/file.wav', 3)
    assert 'secret' not in str(error.value)


def test_explicit_disabled_overrides_legacy_url(monkeypatch):
    monkeypatch.setenv('TRAINLY_AI_BASE_URL', 'https://unused.invalid')
    monkeypatch.setenv('TRAINLY_TRANSCRIPTION_BACKEND', 'disabled')
    assert not providers.ai_enabled()
    with pytest.raises(providers.ProviderNotConfigured):
        providers.transcribe_audio('example.wav', 3)


def test_local_worker_creates_transcript_only_draft(setup_app, monkeypatch):
    import importlib
    from test_api import sign_in
    api, client = setup_app
    monkeypatch.setenv('TRAINLY_TRANSCRIPTION_BACKEND', 'local')
    worker = importlib.import_module('worker')
    h = sign_in(client, 'creator@trainly.local')
    mid = client.post('/api/modules', json={'title':'Local transcript'}, headers=h).json()['id']
    response = client.post(f'/api/modules/{mid}/upload', files={'file':('sample.mp4',b'mocked media','video/mp4')}, headers=h)
    job_id = response.json()['job_id']
    monkeypatch.setattr(worker, 'inspect_video_details', lambda *args:dict(duration=10,container=['mp4'],video_codec='h264',audio_codec='aac'))
    monkeypatch.setattr(worker, 'prepare_browser_playback', lambda path,*args:(path,False))
    monkeypatch.setattr(worker, 'extract_audio', lambda path:path)
    def transcribe(*args):
        with api.connection() as c:
            c.execute('PRAGMA busy_timeout=1')
            c.execute('BEGIN IMMEDIATE')
        return [dict(start=0,end=4,text='Local source')]
    monkeypatch.setattr(worker.providers, 'transcribe_audio', transcribe)
    monkeypatch.setattr(worker.providers, 'generate_draft', lambda *args,**kwargs:pytest.fail('Local mode must not call text generation'))
    assert worker.process_one()
    job = client.get(f'/api/modules/{mid}/uploads/{job_id}').json()
    assert job['transcript_state'] == 'ready' and job['draft_state'] == 'skipped'
    draft = client.get(f'/api/modules/{mid}/draft').json()['draft']
    assert draft['state'] == 'transcript_ready' and draft['lessons'] == [] and draft['questions'] == []
    assert 'Local source' not in client.get(f'/api/modules/{mid}').text
    applied = client.post(f'/api/modules/{mid}/draft/apply', json={'sections':['transcript']}, headers=h)
    assert applied.status_code == 200
    assert applied.json()['module']['transcript'][0]['text'] == 'Local source'
    assert client.delete(f'/api/modules/{mid}', headers=h).status_code == 204


def test_invalid_transcription_backend_leaves_the_job_ready_for_manual_work(setup_app, monkeypatch):
    import importlib
    from test_api import sign_in
    api, client = setup_app
    monkeypatch.setenv('TRAINLY_TRANSCRIPTION_BACKEND', 'bogus')
    assert client.get('/api/config').json()['transcription_backend'] == 'invalid'
    worker = importlib.import_module('worker')
    h = sign_in(client, 'creator@trainly.local')
    mid = client.post('/api/modules', json={'title': 'Misconfigured backend'}, headers=h).json()['id']
    response = client.post(f'/api/modules/{mid}/upload', files={'file': ('sample.mp4', b'mocked media', 'video/mp4')}, headers=h)
    job_id = response.json()['job_id']
    monkeypatch.setattr(worker, 'inspect_video_details',
                        lambda *args: dict(duration=10, container=['mp4'], video_codec='h264', audio_codec='aac'))
    monkeypatch.setattr(worker, 'prepare_browser_playback', lambda path, *args: (path, False))
    assert worker.process_one()
    job = client.get(f'/api/modules/{mid}/uploads/{job_id}').json()
    assert job['state'] == 'ready'
    assert job['transcript_state'] == 'not_configured' and job['draft_state'] == 'not_configured'
    assert 'TRAINLY_TRANSCRIPTION_BACKEND' in job['message']
    assert client.delete(f'/api/modules/{mid}', headers=h).status_code == 204
