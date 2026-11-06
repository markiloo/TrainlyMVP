from __future__ import annotations
import hashlib, hmac, json, math, os, secrets, shutil, subprocess, time, uuid
from pathlib import Path
from database import TrainlySession, make_engine, unit_of_work
from migrations import upgrade_database
from models import (
    TrainingModule, Lesson, Question, TranscriptSegment, AttemptProgress,
    Answer, GeneratedDraft, ModuleVersion, Event, User, Workspace, Membership,
    Assignment, Attempt,
)
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert


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


def extract_audio(path):
    """Extract a mono 16 kHz WAV for transcription. Returns the derived path."""
    destination = Path(path).with_name(f'{Path(path).stem}-audio.wav')
    temporary = destination.with_name(f'{destination.stem}-{uuid.uuid4().hex[:8]}.tmp.wav')
    command = [
        os.environ.get('TRAINLY_FFMPEG', 'ffmpeg'), '-v', 'error', '-y', '-i', str(path),
        '-vn', '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(temporary),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=4 * 60 * 60, check=True)
        temporary.replace(destination)
        return destination
    except FileNotFoundError as e:
        raise ValueError('Audio extraction is unavailable. Install FFmpeg or set TRAINLY_FFMPEG.') from e
    except subprocess.TimeoutExpired as e:
        raise ValueError('Audio extraction took too long. Try a shorter or simpler video.') from e
    except subprocess.CalledProcessError as e:
        raise ValueError('Audio extraction failed. Check that the uploaded video has usable audio.') from e
    finally:
        temporary.unlink(missing_ok=True)


def vtt_timestamp(seconds):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3600 * 1000)
    minutes, milliseconds = divmod(milliseconds, 60 * 1000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'


def captions_vtt(segments):
    """Build WebVTT captions from reviewed transcript segments."""
    lines = ['WEBVTT', '']
    for item in segments or []:
        start = finite_number(item.get('start'))
        end = finite_number(item.get('end'))
        text = item.get('text')
        if start is None or end is None or end <= start or not isinstance(text, str) or not text.strip():
            continue
        # A blank line ends a cue, and "-->" would be parsed as a cue timing.
        cue = text.replace('\r\n', '\n').replace('\r', '\n').replace('-->', '\u2192').strip()
        lines.extend([f'{vtt_timestamp(start)} --> {vtt_timestamp(end)}', cue, ''])
    return '\n'.join(lines)

engine = make_engine(DB)
upgrade_database(engine)


def db():
    """Open an explicit SQLAlchemy unit of work; the caller commits and closes it."""
    return TrainlySession(engine, expire_on_commit=False)


def seed():
    with unit_of_work(engine) as c:
        for email,name,pwd,role in [('admin@trainly.local','Workspace Admin','trainly','admin'),('creator@trainly.local','Alex Morgan','trainly','creator'),('learner@trainly.local','Jamie Lee','trainly','learner')]:
            c.execute(insert(User).values(email=email, name=name, password=password_hash(pwd), role=role).on_conflict_do_nothing())
        if not c.scalar(select(TrainingModule.id).limit(1)):
            owner=c.scalar(select(User.id).where(User.role == 'creator').limit(1)); mid='workplace-safety'
            c.execute(insert(TrainingModule).values(id=mid, owner=owner, title='Workplace safety essentials', description='A practical introduction to safer, more confident work.', duration=568, status='published', published_at=int(time.time())))
            lessons=[('Start with awareness','Notice hazards early and make safety part of every decision.',0,180),('Protect yourself and your team','Use protective equipment and keep shared spaces clear.',180,390),('Respond with confidence','Know how to report an incident and get help quickly.',390,568)]
            for i,(t,s,a,b) in enumerate(lessons): c.execute(insert(Lesson).values(id=str(uuid.uuid4()), module_id=mid, ord=i, title=t, summary=s, start=a, end=b, origin='manual'))
            qs=[('What should you do when you notice a new hazard?',['Ignore it if no one is hurt','Make the area safe and report it','Wait until the end of your shift'],1,'Act early: make the situation safe and let the right person know.',170),('When should protective equipment be used?',['Whenever the task or site requires it','Only when a manager is nearby','Only after an incident'],0,'Follow the requirements for the task and the work area.',380),('What is the best first step after an incident?',['Keep it to yourself','Report it promptly and get help','Post about it online'],1,'Prompt reporting helps the team respond and prevent repeat incidents.',568)]
            for i,(p,o,a,e,t) in enumerate(qs): c.execute(insert(Question).values(id=str(uuid.uuid4()), module_id=mid, ord=i, prompt=p, options=json.dumps(o), answer=a, explanation=e, at=t, origin='manual'))

seed()

def ensure_workspace():
    with unit_of_work(engine) as session:
        session.execute(insert(Workspace).values(id='local', name='Trainly workspace').on_conflict_do_nothing())
        for user in session.scalars(select(User).where(~User.id.in_(select(Membership.user_id)))):
            session.execute(insert(Membership).values(workspace_id='local', user_id=user.id, role=user.role).on_conflict_do_nothing())


ensure_workspace()


def ensure_seed_assignment():
    with unit_of_work(engine) as session:
        learner = session.scalar(select(User.id).where(User.role == 'learner').order_by(User.id).limit(1))
        if learner and session.get(TrainingModule, 'workplace-safety'):
            session.execute(insert(Assignment).values(module_id='workplace-safety', learner=learner, assigned_at=int(time.time())).on_conflict_do_nothing())


ensure_seed_assignment()


def model_record(model):
    from database import Record
    return Record({column.key: getattr(model, column.key) for column in model.__table__.columns}) if model else None


def module_row(session, mid):
    return model_record(session.get(TrainingModule, mid))


def attempt_state(session, attempt):
    progress = session.get(AttemptProgress, attempt['id'])
    answered = list(session.scalars(select(Answer.question_id).where(Answer.attempt_id == attempt['id']).distinct()))
    module = session.get(TrainingModule, attempt['module_id'])
    pass_score = int(module.pass_score or 70) if module else 70
    score = int(attempt['score'] or 0)
    return dict(id=attempt['id'], version=attempt['version'], position=progress.position if progress else 0,
                completed_lessons=json.loads(progress.completed_lessons) if progress else [],
                answered_questions=answered, completed=bool(attempt['completed']), score=score,
                pass_score=pass_score, passed=bool(attempt['completed'] and score >= pass_score))


def package(session, module, include_answers=False):
    questions = []
    for item in session.scalars(select(Question).where(Question.module_id == module['id']).order_by(Question.ord)):
        question = dict(id=item.id, prompt=item.prompt, options=json.loads(item.options),
                        explanation=item.explanation, at=item.at, origin=item.origin)
        if include_answers:
            question['answer'] = item.answer
        questions.append(question)
    transcript = [dict(id=item.id, start=item.start, end=item.end, text=item.text,
                       origin=item.origin, edited=bool(item.edited))
                  for item in session.scalars(select(TranscriptSegment).where(TranscriptSegment.module_id == module['id']).order_by(TranscriptSegment.ord))]
    lessons = [dict(id=item.id, title=item.title, summary=item.summary, start=item.start, end=item.end, origin=item.origin)
               for item in session.scalars(select(Lesson).where(Lesson.module_id == module['id']).order_by(Lesson.ord))]
    return dict(id=module['id'], title=module['title'], description=module['description'], video=bool(module['video']),
                duration=module['duration'], status=module['status'], version=module['published_version'],
                pass_score=int(module['pass_score'] or 70), lessons=lessons, questions=questions, transcript=transcript)

def published_package(c,m,include_answers=False):
    version = c.get(ModuleVersion, (m['id'], m['published_version']))
    row = {'snapshot': version.snapshot} if version else None
    if not row:return package(c,m,include_answers)
    data=json.loads(row['snapshot']); data['status']='published'; data['version']=m['published_version']; data['pass_score']=int(m['pass_score'] or 70); data.setdefault('transcript',[])
    if not include_answers:
        for question in data['questions']: question.pop('answer',None)
    return data

def record_event(session, name, workspace_id=None, user_id=None, module_id=None, meta=None):
    """Store product metadata without video or transcript content."""
    session.add(Event(name=name, workspace_id=workspace_id, user_id=user_id, module_id=module_id,
                      created_at=int(time.time()), meta=json.dumps(meta or {})))
    session.flush()


def save_generated_draft(session, module_id, transcript, lessons, questions, title='', description='', provider=None, state='ready', error=None):
    values = dict(module_id=module_id, transcript=json.dumps(transcript or []), lessons=json.dumps(lessons or []),
                  questions=json.dumps(questions or []), title=title or '', description=description or '',
                  provider=provider, state=state, created_at=int(time.time()), error=error)
    statement = insert(GeneratedDraft).values(**values)
    session.execute(statement.on_conflict_do_update(index_elements=['module_id'], set_={key: value for key, value in values.items() if key != 'module_id'}))


def generated_draft(session, module_id):
    draft = session.get(GeneratedDraft, module_id)
    if not draft:
        return None
    return dict(module_id=draft.module_id, transcript=json.loads(draft.transcript), lessons=json.loads(draft.lessons),
                questions=json.loads(draft.questions), title=draft.title, description=draft.description,
                provider=draft.provider, state=draft.state, created_at=draft.created_at, error=draft.error)

def attempt_snapshot(c,attempt):
    version = c.get(ModuleVersion, (attempt['module_id'], attempt['version']))
    row = {'snapshot': version.snapshot} if version else None
    if row:
        data=json.loads(row['snapshot'])
    else:
        m=module_row(c,attempt['module_id'])
        data=package(c,m,True)
    data.setdefault('transcript',[])
    module = module_row(c, attempt['module_id'])
    if module:
        data['pass_score'] = int(module['pass_score'] or 70)
    else:
        data.setdefault('pass_score', 70)
    return data

def ensure_published_versions():
    with unit_of_work(engine) as session:
        for module in session.scalars(select(TrainingModule).where(TrainingModule.status == 'published', TrainingModule.published_version == 0)):
            snapshot = package(session, model_record(module), True)
            session.execute(insert(ModuleVersion).values(module_id=module.id, version=1, snapshot=json.dumps(snapshot), video=module.video, created_at=int(time.time())).on_conflict_do_nothing())
            module.published_version = 1
            session.execute(update(Attempt).where(Attempt.module_id == module.id, Attempt.version == 0).values(version=1))


ensure_published_versions()


def ensure_video_demo():
    """Make the bundled video a ready-to-play module in existing and fresh demos."""
    source = ROOT / 'vids' / 'sample vid.mp4'
    if not source.is_file():
        return
    target = FILES / 'ltspice-models-demo.mp4'
    if not target.is_file() or target.stat().st_size != source.stat().st_size:
        shutil.copyfile(source, target)
    c = db()
    try:
        mid = 'ltspice-models-demo'
        if c.get(TrainingModule, mid):
            return
        owner = c.scalar(select(User).where(User.email == 'creator@trainly.local'))
        learner = c.scalar(select(User).where(User.email == 'learner@trainly.local'))
        if not owner:
            return
        duration = 634
        now = int(time.time())
        c.execute(insert(TrainingModule).values(id=mid, owner=owner.id, workspace_id='local', title='LTspice model walkthrough', description='Follow a hands-on walkthrough of finding and using component simulation models.', video=target.name, playback_video=target.name, duration=duration, status='published', published_at=now, published_version=1))
        lessons = [
            ('Find the model', 'Locate a component simulation model from the manufacturer.', 0, 190),
            ('Add model files', 'Place and inspect the downloaded model files.', 190, 380),
            ('Run the simulation', 'Connect the model in LTspice and inspect the waveform.', 380, 510),
            ('Review the model', 'Open the model text and check its subcircuit definition.', 510, duration),
        ]
        for i, (title, summary, start, end) in enumerate(lessons):
            c.execute(insert(Lesson).values(id=f'{mid}-lesson-{i+1}', module_id=mid, ord=i, title=title, summary=summary, start=start, end=end, origin='manual'))
        questions = [
            ('What is the presenter looking for on the manufacturer site?', ['A simulation model', 'A purchase receipt', 'A firmware update'], 0, 'The walkthrough starts by locating a component simulation model.', 125),
            ('Why keep the downloaded model file accessible?', ['So LTspice can reference it', 'To change the screen resolution', 'To remove the circuit ground'], 0, 'The simulator needs access to the model file used by the circuit.', 275),
            ('What does the plotted trace help you inspect?', ['The simulated circuit response', 'The file manager layout', 'The browser download history'], 0, 'The waveform shows the circuit response produced by the simulation.', 425),
            ('What text identifies a reusable circuit model definition?', ['A .SUBCKT declaration', 'A browser cookie notice', 'A video timestamp'], 0, 'A .SUBCKT declaration begins a SPICE subcircuit model.', 560),
        ]
        for i, (prompt, options, answer, explanation, at) in enumerate(questions):
            c.execute(insert(Question).values(id=f'{mid}-question-{i+1}', module_id=mid, ord=i, prompt=prompt, options=json.dumps(options), answer=answer, explanation=explanation, at=at, origin='manual'))
        snapshot = package(c, module_row(c, mid), True)
        c.execute(insert(ModuleVersion).values(module_id=mid, version=1, snapshot=json.dumps(snapshot), video=target.name, created_at=now, playback_video=target.name))
        if learner:
            c.execute(insert(Assignment).values(module_id=mid, learner=learner.id, assigned_at=now).on_conflict_do_nothing())
        c.commit()
    finally:
        c.close()

ensure_video_demo()
