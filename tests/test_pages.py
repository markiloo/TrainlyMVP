"""Server-rendered pages use the API's authorization and escape stored content."""
from test_api import setup_app, sign_in


def test_initial_pages_render_without_waiting_for_javascript(setup_app):
    api, client = setup_app
    assert 'id="login"' in client.get('/').text
    assert 'Admin sign in' in client.get('/admin').text
    sign_in(client, 'creator@trainly.local')
    creator = client.get('/')
    assert creator.status_code == 200
    assert 'My modules' in creator.text
    assert 'Workplace safety essentials' in creator.text
    assert '{{' not in creator.text
    sign_in(client, 'learner@trainly.local')
    assert 'Your learning' in client.get('/').text
    assert 'data-learn="workplace-safety"' in client.get('/').text
    sign_in(client, 'admin@trainly.local')
    assert 'Account management' in client.get('/admin').text


def test_template_fragments_enforce_roles_and_module_ownership(setup_app):
    api, client = setup_app
    for path in ('/views/home', '/views/modules', '/views/results'):
        assert client.get(path).status_code == 401
    sign_in(client, 'learner@trainly.local')
    assert client.get('/views/home').status_code == 200
    assert client.get('/views/modules').status_code == 403
    assert client.get('/views/results?mid=workplace-safety').status_code == 403
    sign_in(client, 'creator@trainly.local')
    assert client.get('/views/results?mid=missing').status_code == 404
    assert client.get('/views/results?mid=workplace-safety').status_code == 200
    assert client.get('/views/modules').status_code == 200


def test_stored_names_titles_and_attribute_values_are_escaped(setup_app):
    api, client = setup_app
    attack = '<img src=x onerror="alert(1)">'
    creator = sign_in(client, 'creator@trainly.local')
    created = client.post('/api/modules', json={'title': attack, 'description': attack}, headers=creator)
    assert created.status_code == 201
    with api.connection() as session:
        session.execute('UPDATE users SET name=? WHERE email=?', (attack, 'creator@trainly.local'))
    for path in ('/', '/views/home', '/views/modules'):
        response = client.get(path)
        assert response.status_code == 200
        assert attack not in response.text
        assert '&lt;img src=x onerror=' in response.text
    admin = sign_in(client, 'admin@trainly.local')
    created = client.post('/api/admin/accounts', json={'name': attack, 'email': 'escaping@example.com', 'role': 'creator', 'workspace_id': 'local'}, headers=admin)
    token = created.json()['token']
    response = client.post('/views/account-setup', json={'token': token})
    assert response.status_code == 200
    assert attack not in response.text
    assert 'value="&lt;img' in response.text
    assert token not in response.text
    assert 'pbkdf2_sha256' not in client.get('/admin').text
    assert client.post('/views/account-setup', json={'token': 'invalid'}).status_code == 404
    assert client.post('/views/invitation', json={'token': 'invalid'}).status_code == 404


def test_editor_and_player_render_saved_content_and_keep_access_checks(setup_app):
    api, client = setup_app
    assert client.get('/views/editor/workplace-safety').status_code == 401
    creator = sign_in(client, 'creator@trainly.local')
    response = client.get('/views/editor/workplace-safety')
    assert response.status_code == 200
    assert 'id="mtitle" value="Workplace safety essentials"' in response.text
    assert 'data-l="0" data-k="title"' in response.text
    assert 'data-q="0" data-k="prompt"' in response.text
    assert 'data-answer="0"' in response.text
    assert 'id="add-question"' in response.text
    assert 'id="check-timeline-panel"' in response.text
    assert 'id="video-file"' in response.text
    assert 'id="publish"' in response.text
    learner = sign_in(client, 'learner@trainly.local')
    assert client.get('/views/editor/workplace-safety').status_code == 403
    attempt = client.post('/api/attempts', json={'module_id': 'workplace-safety'}, headers=learner).json()
    response = client.get('/views/player/workplace-safety', params={'attempt_id': attempt['id']})
    assert response.status_code == 200
    assert 'Workplace safety essentials' in response.text
    assert 'id="quiz-area"' in response.text
    assert 'data-jump="0"' in response.text
    assert 'id="call-creator"' in response.text
    assert 'id="reset-progress"' in response.text
    assert client.get('/views/player/workplace-safety?attempt_id=missing').status_code == 404
    sign_in(client, 'creator@trainly.local')
    assert client.get('/views/player/workplace-safety', params={'attempt_id': attempt['id']}).status_code == 404
