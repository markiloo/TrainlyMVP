from test_api import setup_app, sign_in
from concurrent.futures import ThreadPoolExecutor
import json


def test_links_resolve_validate_and_clear_on_segment_removal(setup_app):
    _, client = setup_app
    headers = sign_in(client, 'creator@trainly.local')
    mid = client.post('/api/modules', json={'title': 'Linked tutorial'}, headers=headers).json()['id']
    client.put(f'/api/modules/{mid}', json={'title': 'Linked tutorial', 'description': ''}, headers=headers)
    segments = [dict(start=0, end=3, text='First'), dict(start=3, end=6, text='Second')]
    saved = client.put(f'/api/modules/{mid}/transcript', json={'items': segments}, headers=headers).json()
    ids = [x['id'] for x in saved['transcript']]
    question = dict(prompt='Ready?', options=['Yes', 'No'], answer=0, explanation='Yes', at=10,
                    explanation_link={'segment_ids': ids})
    response = client.put(f'/api/modules/{mid}/questions', json={'items': [question]}, headers=headers)
    assert response.status_code == 400  # no inspected duration for a replay range
    api, _ = setup_app
    with api.connection() as c:
        c.execute('UPDATE modules SET duration=10 WHERE id=?', (mid,))
    response = client.put(f'/api/modules/{mid}/questions', json={'items': [question]}, headers=headers)
    assert response.status_code == 200
    link = response.json()['questions'][0]['explanation_link']
    assert link['text'] == 'First Second'
    assert (link['start'], link['end']) == (0, 6)
    question['explanation_link']['segment_ids'] = list(reversed(ids))
    assert client.put(f'/api/modules/{mid}/questions', json={'items': [question]}, headers=headers).status_code == 400
    saved = client.put(f'/api/modules/{mid}/transcript', json={'items': saved['transcript'][:1]}, headers=headers).json()
    assert saved['cleared_explanation_links']
    assert saved['questions'][0]['explanation_link'] is None


def test_retry_updates_same_completed_attempt_and_reopen(setup_app):
    api, client = setup_app
    headers = sign_in(client, 'learner@trainly.local')
    mid = 'workplace-safety'
    attempt = client.post('/api/attempts', json={'module_id': mid}, headers=headers).json()
    aid = attempt['id']
    with api.connection() as c:
        snapshot = api.attempt_snapshot(c, c.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone())
    q = snapshot['questions'][0]
    retry = f"/api/attempts/{aid}/questions/{q['id']}/retry"
    assert client.post(retry, json={'choice': q['answer']}, headers=headers).status_code == 409
    response = client.post(f'/api/attempts/{aid}', json={'question_id': q['id'], 'choice': (q['answer'] + 1) % len(q['options'])}, headers=headers)
    assert response.status_code == 200
    with api.connection() as c:
        c.execute('UPDATE attempts SET completed=123 WHERE id=?', (aid,))
    assert client.post(retry, json={'choice': True}, headers=headers).status_code == 400
    result = client.post(retry, json={'choice': q['answer']}, headers=headers).json()
    assert result['correct'] and result['score'] == 100 and result['completed']
    assert client.post(retry, json={'choice': q['answer']}, headers=headers).status_code == 409
    with api.connection() as c:
        assert c.execute('SELECT completed FROM attempts WHERE id=?', (aid,)).fetchone()[0] == 123
    state = client.get(f'/api/attempts/{aid}').json()
    assert all('answer' not in item for item in state['module']['questions'])
    assert state['answers'][0]['correct'] == 1
    assert client.post('/api/attempts', json={'module_id': mid}, headers=headers).json()['id'] == aid
    sign_in(client, 'creator@trainly.local')
    row = client.get(f'/api/modules/{mid}/results').json()[0]
    assert row['score'] == 100 and row['passed'] and row['completed_at'] == 123
    assert row['attempt_count'] == 1
    assert client.post(retry, json={'choice':0}).status_code == 403
    headers = sign_in(client, 'learner@trainly.local')
    assert client.post('/api/attempts', json={'module_id': mid, 'new_attempt': True}, headers=headers).json()['id'] != aid
    sign_in(client, 'creator@trainly.local')
    assert client.get(f'/api/attempts/{aid}').status_code == 404


def test_published_links_and_attempts_keep_their_source_version(setup_app):
    api, client = setup_app
    h = sign_in(client, 'creator@trainly.local')
    mid = client.post('/api/modules', json={'title': 'Source version'}, headers=h).json()['id']
    path = api.FILES / f'{mid}-source.mp4'
    path.write_bytes(b'disposable media')
    try:
        with api.connection() as c:
            c.execute('UPDATE modules SET video=?,duration=10 WHERE id=?', (path.name, mid))
        client.put(f'/api/modules/{mid}/lessons', json={'items':[dict(title='First',start=0,end=10)]}, headers=h)
        segments = client.put(f'/api/modules/{mid}/transcript', json={'items':[dict(start=1,end=3,text='Original explanation')]}, headers=h).json()['transcript']
        q = dict(prompt='First?',options=['Yes','No'],answer=0,explanation='Original answer',at=8,
                 explanation_link={'segment_ids':[segments[0]['id']]})
        q = client.put(f'/api/modules/{mid}/questions', json={'items':[q]}, headers=h).json()['questions'][0]
        assert client.patch(f'/api/modules/{mid}/publish', headers=h).status_code == 200
        client.post(f'/api/modules/{mid}/assign', json={'email':'learner@trainly.local'}, headers=h)
        learner = sign_in(client, 'learner@trainly.local')
        aid = client.post('/api/attempts', json={'module_id':mid}, headers=learner).json()['id']
        client.post(f'/api/attempts/{aid}', json={'question_id':q['id'],'choice':1}, headers=learner)
        creator = sign_in(client, 'creator@trainly.local')
        segments[0]['text'] = 'Changed explanation'
        client.put(f'/api/modules/{mid}/transcript', json={'items':segments}, headers=creator)
        q['answer'] = 1
        client.put(f'/api/modules/{mid}/questions', json={'items':[q]}, headers=creator)
        assert client.patch(f'/api/modules/{mid}/publish', headers=creator).json()['version'] == 2
        learner = sign_in(client, 'learner@trainly.local')
        state = client.get(f'/api/attempts/{aid}').json()
        assert state['module']['questions'][0]['explanation_link']['text'] == 'Original explanation'
        assert 'Original explanation' not in client.get(f'/api/modules/{mid}').text
        result = client.post(f"/api/attempts/{aid}/questions/{q['id']}/retry", json={'choice':0}, headers=learner).json()
        assert result['correct']
        assert client.post('/api/attempts', json={'module_id':mid}, headers=learner).json()['version'] == 2
        assert 'Original explanation' in client.get(f'/media/{mid}/captions.vtt?version=1').text
        assert 'Changed explanation' in client.get(f'/media/{mid}/captions.vtt?version=2').text
    finally:
        path.unlink(missing_ok=True)


def test_concurrent_correct_retries_are_serialized(setup_app):
    api, client = setup_app
    h = sign_in(client, 'learner@trainly.local')
    aid = client.post('/api/attempts', json={'module_id':'workplace-safety'}, headers=h).json()['id']
    with api.connection() as c:
        attempt = c.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone()
        q = api.attempt_snapshot(c, attempt)['questions'][0]
    client.post(f'/api/attempts/{aid}', json={'question_id':q['id'],'choice':(q['answer']+1)%len(q['options'])}, headers=h)
    def retry(_):
        return client.post(f"/api/attempts/{aid}/questions/{q['id']}/retry", json={'choice':q['answer']}, headers=h).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(retry, range(2))) == [200,409]
    with api.connection() as c:
        assert c.execute('SELECT COUNT(*) FROM answers WHERE attempt_id=? AND question_id=?', (aid,q['id'])).fetchone()[0] == 1
