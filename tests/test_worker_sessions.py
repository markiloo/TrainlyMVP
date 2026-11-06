import importlib
from concurrent.futures import ThreadPoolExecutor

from test_api import setup_app, sign_in


def upload_job(client):
    headers = sign_in(client, 'creator@trainly.local')
    mid = client.post('/api/modules', json={'title': 'Session isolation'}, headers=headers).json()['id']
    response = client.post(f'/api/modules/{mid}/upload', files={'file': ('training.mp4', b'video data', 'video/mp4')}, headers=headers)
    assert response.status_code == 202
    return mid, headers


def test_concurrent_worker_sessions_cannot_claim_the_same_job(setup_app):
    api, client = setup_app
    mid, headers = upload_job(client)
    worker = importlib.import_module('worker')
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: worker.claim_job(), range(2)))
    claimed = [job for job in claims if job]
    assert len(claimed) == 1
    assert claimed[0]['module_id'] == mid
    assert client.delete(f'/api/modules/{mid}', headers=headers).status_code == 204


def test_media_processing_runs_after_claim_transaction_closes(setup_app, monkeypatch):
    api, client = setup_app
    mid, headers = upload_job(client)
    worker = importlib.import_module('worker')
    def inspect_without_write_lock(path, extension):
        # A second writer can start immediately while FFprobe/provider work runs.
        with api.db() as session:
            session.execute('PRAGMA busy_timeout=1')
            session.execute('BEGIN IMMEDIATE')
            session.rollback()
        return dict(duration=20, container=['mp4'], video_codec='h264', audio_codec=None)
    monkeypatch.setattr(worker, 'inspect_video_details', inspect_without_write_lock)
    monkeypatch.setattr(worker, 'prepare_browser_playback', lambda path, extension, details: (path, False))
    monkeypatch.setattr(worker.providers, 'ai_enabled', lambda: False)
    assert worker.process_one()
    assert client.get(f'/api/modules/{mid}').json()['upload_job']['state'] == 'ready'
    assert client.delete(f'/api/modules/{mid}', headers=headers).status_code == 204
