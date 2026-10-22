from __future__ import annotations
import hashlib, hmac, json, math, os, secrets, sqlite3, subprocess, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('TRAINLY_DB', ROOT / 'trainly.sqlite3'))
FILES = Path(os.environ.get('TRAINLY_STORAGE', ROOT / 'storage'))
FILES.mkdir(parents=True, exist_ok=True)
COOKIE_SECURE = os.environ.get('TRAINLY_SECURE_COOKIE', '').lower() in ('1', 'true', 'yes')

def positive_limit(name, default):
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f'{name} must be a positive integer.') from exc
    if value <= 0:
        raise ValueError(f'{name} must be a positive integer.')
    return value

MAX_VIDEO_BYTES = positive_limit('TRAINLY_MAX_VIDEO_BYTES', 1024 * 1024 * 1024)
MAX_VIDEO_SECONDS = positive_limit('TRAINLY_MAX_VIDEO_SECONDS', 120 * 60)

def password_hash(password):
    salt=secrets.token_bytes(16); rounds=310000
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,rounds).hex()
    return f'pbkdf2_sha256${rounds}${salt.hex()}${digest}'

def password_matches(password,stored):
    if not isinstance(password,str): return False
    if not stored.startswith('pbkdf2_sha256$'): return hmac.compare_digest(password,stored)
    try:
        scheme,rounds,salt,digest=stored.split('$',3)
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError): return False

def finite_number(value,default=None):
    try:
        result=float(value)
        return result if math.isfinite(result) else default
    except (ValueError,TypeError): return default

def inspect_video(path,extension):
    return inspect_video_details(path, extension)['duration']

def inspect_video_details(path,extension):
    try:
        result=subprocess.run([os.environ.get('TRAINLY_FFPROBE','ffprobe'),'-v','error','-show_entries','format=duration,format_name','-show_entries','stream=codec_type,codec_name','-of','json',str(path)],capture_output=True,text=True,timeout=30,check=True)
        metadata=json.loads(result.stdout); format_info=metadata.get('format',{}); duration=finite_number(format_info.get('duration')); formats=set(str(format_info.get('format_name','')).split(','))
        streams=metadata.get('streams',[])
        valid_format=bool(formats&({'.mp4':{'mov','mp4','m4a','3gp','3g2','mj2'},'.mov':{'mov','mp4','m4a','3gp','3g2','mj2'},'.webm':{'webm','matroska'}}[extension]))
        if not valid_format or not any(s.get('codec_type')=='video' for s in streams): raise ValueError('The selected file is not a valid video in the chosen format.')
        if duration is None or duration<=0: raise ValueError('The video duration could not be read.')
        if duration>MAX_VIDEO_SECONDS: raise ValueError(f'This video is longer than the {MAX_VIDEO_SECONDS}-second limit.')
        video_stream=next(s for s in streams if s.get('codec_type')=='video')
        audio_stream=next((s for s in streams if s.get('codec_type')=='audio'),None)
        return dict(duration=int(round(duration)), container=sorted(formats), video_codec=video_stream.get('codec_name','unknown'), audio_codec=audio_stream.get('codec_name') if audio_stream else None)
    except FileNotFoundError as e: raise ValueError('Video inspection is unavailable. Install FFprobe or set TRAINLY_FFPROBE.') from e
    except subprocess.TimeoutExpired as e: raise ValueError('Video inspection took too long. Try a shorter or simpler video.') from e
    except subprocess.CalledProcessError as e: raise ValueError('The selected file could not be inspected as a video.') from e

def prepare_browser_playback(path, extension, details):
    video_codec=details['video_codec'].lower()
    audio_codec=(details['audio_codec'] or '').lower()
    formats=set(details['container'])
    playable_mp4=extension=='.mp4' and 'mp4' in formats and video_codec=='h264' and audio_codec in ('', 'aac')
    playable_webm=extension=='.webm' and video_codec in ('vp8','vp9','av1') and audio_codec in ('','opus','vorbis')
    if playable_mp4 or playable_webm:
        return Path(path), False
    destination=Path(path).with_name(f'{Path(path).stem}-playback.mp4')
    temporary=destination.with_name(f'{destination.stem}-{uuid.uuid4().hex[:8]}.tmp.mp4')
    command=[os.environ.get('TRAINLY_FFMPEG','ffmpeg'),'-v','error','-y','-i',str(path),'-map','0:v:0','-map','0:a:0?','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',str(temporary)]
    try:
        subprocess.run(command,capture_output=True,text=True,timeout=4*60*60,check=True)
        temporary.replace(destination)
        return destination, True
    except FileNotFoundError as e:
        raise ValueError('Video conversion is unavailable. Install FFmpeg or set TRAINLY_FFMPEG.') from e
    except subprocess.TimeoutExpired as e:
        raise ValueError('Video conversion took too long. Try a shorter or simpler video.') from e
    except subprocess.CalledProcessError as e:
        raise ValueError('Video conversion failed. Check that the uploaded video can be decoded.') from e
    finally:
        temporary.unlink(missing_ok=True)

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, password TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(workspace_id TEXT NOT NULL, user_id INTEGER NOT NULL UNIQUE, role TEXT NOT NULL CHECK(role IN ('creator','learner')), PRIMARY KEY(workspace_id,user_id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS invitations(token_hash TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('creator','learner')), module_id TEXT, created_by INTEGER NOT NULL, expires INTEGER NOT NULL, accepted INTEGER, FOREIGN KEY(workspace_id) REFERENCES workspaces(id), FOREIGN KEY(module_id) REFERENCES modules(id), FOREIGN KEY(created_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, csrf TEXT, expires INTEGER, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS modules(id TEXT PRIMARY KEY, owner INTEGER, workspace_id TEXT NOT NULL DEFAULT 'local', title TEXT, description TEXT DEFAULT '', video TEXT DEFAULT '', duration INTEGER DEFAULT 0, status TEXT DEFAULT 'draft', published_at INTEGER, published_version INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(owner) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS media_assets(id TEXT PRIMARY KEY, module_id TEXT NOT NULL, source_path TEXT NOT NULL, playback_path TEXT, container TEXT, video_codec TEXT, audio_codec TEXT, duration INTEGER, state TEXT NOT NULL, created_at INTEGER NOT NULL, FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY, module_id TEXT, ord INTEGER, title TEXT, summary TEXT, start REAL, end REAL, FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, module_id TEXT, ord INTEGER, prompt TEXT, options TEXT, answer INTEGER, explanation TEXT, at REAL, FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, module_id TEXT, learner INTEGER, started INTEGER, completed INTEGER, score INTEGER DEFAULT 0, version INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(module_id) REFERENCES modules(id));
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, attempt_id TEXT, question_id TEXT, choice INTEGER, correct INTEGER, FOREIGN KEY(attempt_id) REFERENCES attempts(id));
CREATE TABLE IF NOT EXISTS attempt_progress(attempt_id TEXT PRIMARY KEY, position REAL NOT NULL DEFAULT 0, completed_lessons TEXT NOT NULL DEFAULT '[]', FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS module_versions(module_id TEXT NOT NULL, version INTEGER NOT NULL, snapshot TEXT NOT NULL, video TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, playback_video TEXT NOT NULL DEFAULT '', media_asset_id TEXT, PRIMARY KEY(module_id,version), FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE, FOREIGN KEY(media_asset_id) REFERENCES media_assets(id));
CREATE TABLE IF NOT EXISTS assignments(module_id TEXT NOT NULL, learner INTEGER NOT NULL, assigned_at INTEGER NOT NULL, PRIMARY KEY(module_id,learner), FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE, FOREIGN KEY(learner) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS processing_jobs(id TEXT PRIMARY KEY, module_id TEXT NOT NULL, workspace_id TEXT NOT NULL, asset TEXT NOT NULL, filename TEXT NOT NULL, extension TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'inspection', state TEXT NOT NULL DEFAULT 'queued', retry_count INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, claimed_at INTEGER, duration INTEGER, error TEXT, FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE, FOREIGN KEY(workspace_id) REFERENCES workspaces(id));
CREATE INDEX IF NOT EXISTS processing_jobs_state_created ON processing_jobs(state,created_at);
'''
def db():
    c=sqlite3.connect(DB, timeout=20); c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=20000')
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON'); c.executescript(SCHEMA)
    for table,column,definition in [('modules','published_version','INTEGER NOT NULL DEFAULT 0'),('modules','workspace_id',"TEXT NOT NULL DEFAULT 'local'"),('modules','upload_job_id','TEXT'),('modules','playback_video',"TEXT NOT NULL DEFAULT ''"),('modules','media_asset_id','TEXT'),('module_versions','playback_video',"TEXT NOT NULL DEFAULT ''"),('module_versions','media_asset_id','TEXT'),('attempts','version','INTEGER NOT NULL DEFAULT 0')]:
        if column not in {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}: c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    return c

def seed():
    c=db()
    for email,name,pwd,role in [('creator@trainly.local','Alex Morgan','trainly','creator'),('learner@trainly.local','Jamie Lee','trainly','learner')]:
        c.execute('INSERT OR IGNORE INTO users(email,name,password,role) VALUES(?,?,?,?)',(email,name,password_hash(pwd),role))
    if not c.execute('SELECT 1 FROM modules').fetchone():
        owner=c.execute("SELECT id FROM users WHERE role='creator'").fetchone()[0]; mid='workplace-safety'
        c.execute('INSERT INTO modules(id,owner,title,description,duration,status,published_at) VALUES(?,?,?,?,?,?,?)',(mid,owner,'Workplace safety essentials','A practical introduction to safer, more confident work.',568,'published',int(time.time())))
        lessons=[('Start with awareness','Notice hazards early and make safety part of every decision.',0,180),('Protect yourself and your team','Use protective equipment and keep shared spaces clear.',180,390),('Respond with confidence','Know how to report an incident and get help quickly.',390,568)]
        for i,(t,s,a,b) in enumerate(lessons): c.execute('INSERT INTO lessons VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),mid,i,t,s,a,b))
        qs=[('What should you do when you notice a new hazard?',['Ignore it if no one is hurt','Make the area safe and report it','Wait until the end of your shift'],1,'Act early: make the situation safe and let the right person know.',170),('When should protective equipment be used?',['Whenever the task or site requires it','Only when a manager is nearby','Only after an incident'],0,'Follow the requirements for the task and the work area.',380),('What is the best first step after an incident?',['Keep it to yourself','Report it promptly and get help','Post about it online'],1,'Prompt reporting helps the team respond and prevent repeat incidents.',568)]
        for i,(p,o,a,e,t) in enumerate(qs): c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),mid,i,p,json.dumps(o),a,e,t))
    c.commit(); c.close()
seed()

def ensure_workspace():
    c=db()
    first_install=not c.execute("SELECT 1 FROM workspaces WHERE id='local'").fetchone()
    c.execute("INSERT OR IGNORE INTO workspaces(id,name) VALUES('local','Trainly workspace')")
    if first_install:
        c.execute("INSERT OR IGNORE INTO memberships(workspace_id,user_id,role) SELECT 'local',id,role FROM users WHERE role IN ('creator','learner')")
    c.commit();c.close()

ensure_workspace()

def ensure_seed_assignment():
    c=db(); learner=c.execute("SELECT id FROM users WHERE role='learner' ORDER BY id LIMIT 1").fetchone()
    if learner and c.execute('SELECT 1 FROM modules WHERE id=?',('workplace-safety',)).fetchone():
        c.execute('INSERT OR IGNORE INTO assignments(module_id,learner,assigned_at) VALUES(?,?,?)',('workplace-safety',learner['id'],int(time.time())))
    c.commit();c.close()

ensure_seed_assignment()

def module_row(c, mid): return c.execute('SELECT * FROM modules WHERE id=?',(mid,)).fetchone()
def attempt_state(c, attempt):
    progress=c.execute('SELECT position,completed_lessons FROM attempt_progress WHERE attempt_id=?',(attempt['id'],)).fetchone()
    answered=[r['question_id'] for r in c.execute('SELECT DISTINCT question_id FROM answers WHERE attempt_id=?',(attempt['id'],))]
    return dict(id=attempt['id'],version=attempt['version'],position=progress['position'] if progress else 0,completed_lessons=json.loads(progress['completed_lessons']) if progress else [],answered_questions=answered,completed=bool(attempt['completed']))
def package(c,m,include_answers=False):
    questions=[]
    for x in c.execute('SELECT * FROM questions WHERE module_id=? ORDER BY ord',(m['id'],)):
        item=dict(id=x['id'],prompt=x['prompt'],options=json.loads(x['options']),explanation=x['explanation'],at=x['at'])
        if include_answers:item['answer']=x['answer']
        questions.append(item)
    return dict(id=m['id'],title=m['title'],description=m['description'],video=bool(m['video']),duration=m['duration'],status=m['status'],version=m['published_version'],lessons=[dict(id=x['id'],title=x['title'],summary=x['summary'],start=x['start'],end=x['end']) for x in c.execute('SELECT * FROM lessons WHERE module_id=? ORDER BY ord',(m['id'],))],questions=questions)

def published_package(c,m,include_answers=False):
    row=c.execute('SELECT snapshot FROM module_versions WHERE module_id=? AND version=?',(m['id'],m['published_version'])).fetchone()
    if not row:return package(c,m,include_answers)
    data=json.loads(row['snapshot']); data['status']='published'; data['version']=m['published_version']
    if not include_answers:
        for question in data['questions']: question.pop('answer',None)
    return data

def attempt_snapshot(c,attempt):
    row=c.execute('SELECT snapshot FROM module_versions WHERE module_id=? AND version=?',(attempt['module_id'],attempt['version'])).fetchone()
    if row:return json.loads(row['snapshot'])
    m=module_row(c,attempt['module_id'])
    return package(c,m,True)

def ensure_published_versions():
    c=db()
    for m in c.execute("SELECT * FROM modules WHERE status='published' AND published_version=0").fetchall():
        version=1; snapshot=package(c,m,True)
        c.execute('INSERT OR IGNORE INTO module_versions(module_id,version,snapshot,video,created_at) VALUES(?,?,?,?,?)',(m['id'],version,json.dumps(snapshot),m['video'],int(time.time())))
        c.execute('UPDATE modules SET published_version=? WHERE id=?',(version,m['id']))
        c.execute('UPDATE attempts SET version=? WHERE module_id=? AND version=0',(version,m['id']))
    c.commit();c.close()

ensure_published_versions()
