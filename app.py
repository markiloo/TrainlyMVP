from __future__ import annotations
import json, os, re, secrets, sqlite3, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('TRAINLY_DB', ROOT / 'trainly.sqlite3'))
FILES = Path(os.environ.get('TRAINLY_STORAGE', ROOT / 'storage'))
FILES.mkdir(parents=True, exist_ok=True)

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, password TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, csrf TEXT, expires INTEGER, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS modules(id TEXT PRIMARY KEY, owner INTEGER, title TEXT, description TEXT DEFAULT '', video TEXT DEFAULT '', duration INTEGER DEFAULT 0, status TEXT DEFAULT 'draft', published_at INTEGER, FOREIGN KEY(owner) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY, module_id TEXT, ord INTEGER, title TEXT, summary TEXT, start REAL, end REAL, FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, module_id TEXT, ord INTEGER, prompt TEXT, options TEXT, answer INTEGER, explanation TEXT, at REAL, FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, module_id TEXT, learner INTEGER, started INTEGER, completed INTEGER, score INTEGER DEFAULT 0, FOREIGN KEY(module_id) REFERENCES modules(id));
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, attempt_id TEXT, question_id TEXT, choice INTEGER, correct INTEGER, FOREIGN KEY(attempt_id) REFERENCES attempts(id));
'''
def db():
    c=sqlite3.connect(DB, timeout=20); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.executescript(SCHEMA); return c

def seed():
    c=db()
    for email,name,pwd,role in [('creator@trainly.local','Alex Morgan','trainly','creator'),('learner@trainly.local','Jamie Lee','trainly','learner')]:
        c.execute('INSERT OR IGNORE INTO users(email,name,password,role) VALUES(?,?,?,?)',(email,name,pwd,role))
    if not c.execute('SELECT 1 FROM modules').fetchone():
        owner=c.execute("SELECT id FROM users WHERE role='creator'").fetchone()[0]; mid='workplace-safety'
        c.execute('INSERT INTO modules(id,owner,title,description,duration,status,published_at) VALUES(?,?,?,?,?,?,?)',(mid,owner,'Workplace safety essentials','A practical introduction to safer, more confident work.',568,'published',int(time.time())))
        lessons=[('Start with awareness','Notice hazards early and make safety part of every decision.',0,180),('Protect yourself and your team','Use protective equipment and keep shared spaces clear.',180,390),('Respond with confidence','Know how to report an incident and get help quickly.',390,568)]
        for i,(t,s,a,b) in enumerate(lessons): c.execute('INSERT INTO lessons VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),mid,i,t,s,a,b))
        qs=[('What should you do when you notice a new hazard?',['Ignore it if no one is hurt','Make the area safe and report it','Wait until the end of your shift'],1,'Act early: make the situation safe and let the right person know.',170),('When should protective equipment be used?',['Whenever the task or site requires it','Only when a manager is nearby','Only after an incident'],0,'Follow the requirements for the task and the work area.',380),('What is the best first step after an incident?',['Keep it to yourself','Report it promptly and get help','Post about it online'],1,'Prompt reporting helps the team respond and prevent repeat incidents.',568)]
        for i,(p,o,a,e,t) in enumerate(qs): c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),mid,i,p,json.dumps(o),a,e,t))
    c.commit(); c.close()
seed()

def module_row(c, mid): return c.execute('SELECT * FROM modules WHERE id=?',(mid,)).fetchone()
def package(c,m,include_answers=False):
    questions=[]
    for x in c.execute('SELECT * FROM questions WHERE module_id=? ORDER BY ord',(m['id'],)):
        item=dict(id=x['id'],prompt=x['prompt'],options=json.loads(x['options']),explanation=x['explanation'],at=x['at'])
        if include_answers:item['answer']=x['answer']
        questions.append(item)
    return dict(id=m['id'],title=m['title'],description=m['description'],video=bool(m['video']),duration=m['duration'],status=m['status'],lessons=[dict(id=x['id'],title=x['title'],summary=x['summary'],start=x['start'],end=x['end']) for x in c.execute('SELECT * FROM lessons WHERE module_id=? ORDER BY ord',(m['id'],))],questions=questions)

class Handler(BaseHTTPRequestHandler):
    server_version='Trainly/0.1'
    def log_message(self,*args): pass
    def send(self,status,body,typ='application/json; charset=utf-8',headers=None):
        raw=body.encode() if isinstance(body,str) else body
        self.send_response(status); self.send_header('Content-Type',typ); self.send_header('Content-Length',str(len(raw))); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','same-origin'); self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)
    def body(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>1_100_000_000: raise ValueError('Request exceeds the upload size limit.')
        return self.rfile.read(n)
    def auth(self):
        jar=SimpleCookie(self.headers.get('Cookie','')); token=jar.get('trainly')
        if not token: return None
        c=db(); row=c.execute('SELECT users.*,sessions.token,sessions.csrf,sessions.expires FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=?',(token.value,)).fetchone(); c.close()
        if not row or row['expires']<int(time.time()): return None
        return row
    def json(self,status,obj,headers=None): self.send(status,json.dumps(obj),headers=headers)
    def do_OPTIONS(self): self.send(204,b'',headers={'Allow':'GET, POST, PUT, DELETE, OPTIONS'})
    def do_GET(self):
        path=urlparse(self.path).path; user=self.auth()
        if path=='/' or path=='/index.html': return self.send(200,(ROOT/'templates'/'index.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
        if path=='/app.css': return self.send(200,(ROOT/'static'/'app.css').read_text(encoding='utf-8'),'text/css; charset=utf-8')
        if path=='/app.js': return self.send(200,(ROOT/'static'/'app.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8')
        if path=='/api/me': return self.json(200,{'user':dict(id=user['id'],name=user['name'],email=user['email'],role=user['role']),'csrf':user['csrf']} if user else {'user':None})
        if path=='/api/modules':
            if not user:return self.json(401,{'error':'Sign in to continue.'})
            c=db(); rows=c.execute('SELECT * FROM modules WHERE status="published" OR owner=? ORDER BY published_at DESC',(user['id'],)).fetchall(); result=[]
            for m in rows:
                p=package(c,m,user['role']=='creator' and m['owner']==user['id']); p['completed']=bool(c.execute('SELECT 1 FROM attempts WHERE module_id=? AND learner=? AND completed IS NOT NULL',(m['id'],user['id'])).fetchone()); result.append(p)
            c.close(); return self.json(200,result)
        if path.startswith('/api/modules/'):
            parts=path.split('/'); mid=parts[3] if len(parts)>3 else ''; c=db(); m=module_row(c,mid)
            if not m: c.close(); return self.json(404,{'error':'Module not found.'})
            if not user or (m['status']!='published' and m['owner']!=user['id']): c.close(); return self.json(403,{'error':'You do not have access to this module.'})
            if len(parts)==5 and parts[4]=='results' and user['role']=='creator' and m['owner']==user['id']:
                rows=c.execute('SELECT attempts.*,users.name,users.email FROM attempts JOIN users ON users.id=attempts.learner WHERE attempts.module_id=? ORDER BY started DESC',(mid,)).fetchall(); c.close(); return self.json(200,[dict(name=r['name'],email=r['email'],completed=bool(r['completed']),score=r['score'],started=r['started'],completed_at=r['completed']) for r in rows])
            result=package(c,m,user['role']=='creator' and m['owner']==user['id']); c.close(); return self.json(200,result)
        if path.startswith('/media/'):
            name=Path(path).name
            if not user: return self.send(401,'Sign in required.','text/plain')
            c=db(); row=c.execute('SELECT * FROM modules WHERE id=?',(name,)).fetchone()
            if not row or (row['owner']!=user['id'] and row['status']!='published'): c.close(); return self.send(403,'Forbidden','text/plain')
            f=FILES/row['video']; c.close()
            if not f.exists(): return self.send(404,'Missing media','text/plain')
            size=f.stat().st_size; start,end=0,size-1; rng=self.headers.get('Range')
            if rng:
                mm=re.match(r'bytes=(\d*)-(\d*)',rng)
                if mm:
                    start=int(mm.group(1) or 0); end=min(int(mm.group(2) or end),end)
                    if start>end:return self.send(416,b'')
            self.send_response(206 if rng else 200); self.send_header('Content-Type',{'.mp4':'video/mp4','.mov':'video/quicktime','.webm':'video/webm'}.get(f.suffix.lower(),'application/octet-stream')); self.send_header('Accept-Ranges','bytes'); self.send_header('Content-Length',str(end-start+1))
            if rng:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with f.open('rb') as stream:
                stream.seek(start); remaining=end-start+1
                while remaining:
                    chunk=stream.read(min(256*1024,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
            return
        self.json(404,{'error':'Not found'})
    def do_POST(self):
        path=urlparse(self.path).path; raw=self.body(); user=self.auth()
        if path=='/api/login':
            try: data=json.loads(raw)
            except: return self.json(400,{'error':'Enter your login details.'})
            c=db(); row=c.execute('SELECT * FROM users WHERE email=? AND password=?',(data.get('email','').lower(),data.get('password',''))).fetchone()
            if not row: c.close(); return self.json(401,{'error':'Email or password is incorrect.'})
            token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24); c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token,row['id'],csrf,int(time.time())+86400*14)); c.commit(); c.close(); return self.json(200,{'user':dict(id=row['id'],name=row['name'],email=row['email'],role=row['role']),'csrf':csrf},headers={'Set-Cookie':f'trainly={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=1209600'})
        if path=='/api/logout':
            if user:
                c=db(); c.execute('DELETE FROM sessions WHERE token=?',(user['token'],)); c.commit(); c.close()
            return self.json(200,{'ok':True},headers={'Set-Cookie':'trainly=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'})
        if not user:return self.json(401,{'error':'Sign in to continue.'})
        if self.headers.get('X-CSRF-Token')!=user['csrf']: return self.json(403,{'error':'Session expired. Refresh and try again.'})
        c=db()
        if path=='/api/modules':
            if user['role']!='creator': c.close(); return self.json(403,{'error':'Creator access is required.'})
            try: data=json.loads(raw)
            except: c.close(); return self.json(400,{'error':'Check the module details.'})
            mid=uuid.uuid4().hex[:12]; title=(data.get('title') or '').strip()
            if not title:c.close(); return self.json(400,{'error':'Add a module title first.'})
            c.execute('INSERT INTO modules(id,owner,title,description) VALUES(?,?,?,?)',(mid,user['id'],title,data.get('description',''))); c.execute('INSERT INTO lessons VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,mid,0,'Introduction','Add a short overview for learners.',0,0)); c.commit(); m=module_row(c,mid); result=package(c,m,True); c.close(); return self.json(201,result)
        if path.startswith('/api/modules/'):
            parts=path.split('/'); mid=parts[3]; m=module_row(c,mid)
            if not m: c.close(); return self.json(404,{'error':'Module not found.'})
            if user['role']!='creator' or m['owner']!=user['id']: c.close(); return self.json(403,{'error':'Creator access is required.'})
            if len(parts)==5 and parts[4]=='upload':
                content=self.headers.get('Content-Type',''); boundary=re.search(r'boundary=(?:"([^"]+)"|([^;]+))',content)
                if not boundary:c.close(); return self.json(400,{'error':'Choose an MP4, MOV, or WebM video.'})
                marker=(boundary.group(1) or boundary.group(2)).encode(); filedata=None; filename=''
                for part in raw.split(b'--'+marker):
                    if b'filename=' not in part: continue
                    header,sep,blob=part.partition(b'\r\n\r\n')
                    match=re.search(rb'filename="([^"]+)"',header)
                    if match:
                        filename=Path(match.group(1).decode('utf8','ignore')).name; filedata=blob.rsplit(b'\r\n',1)[0]; break
                ext=Path(filename).suffix.lower()
                if filedata is None or ext not in ('.mp4','.mov','.webm'):c.close();return self.json(400,{'error':'Choose an MP4, MOV, or WebM video.'})
                if len(filedata)>1024*1024*1024:c.close();return self.json(413,{'error':'This video is larger than the 1 GB limit.'})
                asset=f'{mid}-{uuid.uuid4().hex[:8]}{ext}'; (FILES/asset).write_bytes(filedata); c.execute('UPDATE modules SET video=?,duration=0 WHERE id=?',(asset,mid)); c.commit(); c.close(); return self.json(200,{'ok':True,'filename':filename,'message':'Video saved. Add the lesson and quiz content below; automatic transcription will be available after an AI provider is configured.'})
            c.close();return self.json(404,{'error':'Not found'})
        if path.startswith('/api/attempts'):
            data=json.loads(raw or b'{}'); mid=data.get('module_id'); m=module_row(c,mid)
            if not m or m['status']!='published':c.close();return self.json(404,{'error':'Published module not found.'})
            aid=uuid.uuid4().hex; c.execute('INSERT INTO attempts(id,module_id,learner,started) VALUES(?,?,?,?)',(aid,mid,user['id'],int(time.time())));c.commit();c.close();return self.json(201,{'id':aid})
        if path.startswith('/api/attempts/'):
            aid=path.split('/')[3]; data=json.loads(raw or b'{}'); qid=data.get('question_id'); choice=data.get('choice'); attempt=c.execute('SELECT * FROM attempts WHERE id=? AND learner=?',(aid,user['id'])).fetchone(); q=c.execute('SELECT * FROM questions WHERE id=? AND module_id=?',(qid,attempt['module_id'] if attempt else '')).fetchone()
            if not attempt or not q:c.close();return self.json(404,{'error':'Question not found.'})
            correct=int(choice)==q['answer']; c.execute('INSERT INTO answers(attempt_id,question_id,choice,correct) VALUES(?,?,?,?)',(aid,qid,choice,int(correct))); c.commit(); answered=c.execute('SELECT COUNT(DISTINCT question_id) FROM answers WHERE attempt_id=?',(aid,)).fetchone()[0]; total=c.execute('SELECT COUNT(*) FROM questions WHERE module_id=?',(attempt['module_id'],)).fetchone()[0]
            completed=int(time.time()) if answered>=total else None; score=round(c.execute('SELECT AVG(correct)*100 FROM (SELECT MAX(correct) correct FROM answers WHERE attempt_id=? GROUP BY question_id)',(aid,)).fetchone()[0] or 0)
            c.execute('UPDATE attempts SET score=?,completed=COALESCE(?,completed) WHERE id=?',(score,completed,aid));c.commit(); explanation=q['explanation'];c.close();return self.json(200,{'correct':correct,'explanation':explanation,'score':score,'completed':bool(completed)})
        self.json(404,{'error':'Not found'})

    def do_PUT(self):
        path=urlparse(self.path).path; user=self.auth()
        if not user:return self.json(401,{'error':'Sign in to continue.'})
        if self.headers.get('X-CSRF-Token')!=user['csrf']:return self.json(403,{'error':'Session expired. Refresh and try again.'})
        try:data=json.loads(self.body())
        except:return self.json(400,{'error':'Check the saved details.'})
        parts=path.strip('/').split('/'); c=db()
        if len(parts)<3 or parts[0]!='api' or parts[1]!='modules':c.close();return self.json(404,{'error':'Not found'})
        mid=parts[2];m=module_row(c,mid)
        if not m:c.close();return self.json(404,{'error':'Module not found.'})
        if user['role']!='creator' or m['owner']!=user['id']:c.close();return self.json(403,{'error':'Creator access is required.'})
        if len(parts)==3:
            title=(data.get('title') or '').strip()
            if not title:c.close();return self.json(400,{'error':'Add a module title first.'})
            c.execute('UPDATE modules SET title=?,description=? WHERE id=?',(title,data.get('description',''),mid))
        elif len(parts)==4 and parts[3] in ('lessons','questions'):
            table=parts[3];items=data.get('items',[])
            if table=='lessons':
                for x in items:
                    title=(x.get('title') or '').strip(); start=float(x.get('start',0));end=float(x.get('end',0))
                    if not title or start<0 or end<start or (m['duration'] and end>m['duration']):c.close();return self.json(400,{'error':'Check each lesson title and time range.'})
                for i,x in enumerate(items):
                    lid=x.get('id') or uuid.uuid4().hex
                    c.execute('INSERT INTO lessons VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,title=excluded.title,summary=excluded.summary,start=excluded.start,end=excluded.end',(lid,mid,i,(x.get('title') or '').strip(),x.get('summary',''),float(x.get('start',0)),float(x.get('end',0))))
                ids=[x.get('id') for x in items if x.get('id')]; c.execute('DELETE FROM lessons WHERE module_id=? AND id NOT IN ('+(','.join('?'*len(ids)) if ids else "''")+')',[mid]+ids)
            else:
                for i,x in enumerate(items):
                    opts=x.get('options',[])
                    if not (x.get('prompt') or '').strip() or len(opts)<2 or int(x.get('answer',-1)) not in range(len(opts)):c.close();return self.json(400,{'error':'Each question needs a prompt, options, and one correct answer.'})
                    qid=x.get('id') or uuid.uuid4().hex
                    c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,prompt=excluded.prompt,options=excluded.options,answer=excluded.answer,explanation=excluded.explanation,at=excluded.at',(qid,mid,i,x['prompt'].strip(),json.dumps(opts),int(x['answer']),x.get('explanation',''),float(x.get('at',m['duration']))))
                ids=[x.get('id') for x in items if x.get('id')]; c.execute('DELETE FROM questions WHERE module_id=? AND id NOT IN ('+(','.join('?'*len(ids)) if ids else "''")+')',[mid]+ids)
        else:c.close();return self.json(404,{'error':'Not found'})
        c.commit();m=module_row(c,mid);result=package(c,m,True);c.close();return self.json(200,result)

    def do_PATCH(self):
        path=urlparse(self.path).path;user=self.auth()
        if not user:return self.json(401,{'error':'Sign in to continue.'})
        if self.headers.get('X-CSRF-Token')!=user['csrf']:return self.json(403,{'error':'Session expired. Refresh and try again.'})
        parts=path.strip('/').split('/');c=db()
        if len(parts)!=4 or parts[:2]!=['api','modules'] or parts[3]!='publish':c.close();return self.json(404,{'error':'Not found'})
        m=module_row(c,parts[2])
        if not m or user['role']!='creator' or m['owner']!=user['id']:c.close();return self.json(403,{'error':'Creator access is required.'})
        lessons=c.execute('SELECT * FROM lessons WHERE module_id=? ORDER BY start',(m['id'],)).fetchall();qs=c.execute('SELECT * FROM questions WHERE module_id=?',(m['id'],)).fetchall()
        if not m['title'].strip() or not lessons or not qs:c.close();return self.json(400,{'error':'Add a title, at least one lesson, and at least one quiz question before publishing.'})
        for i,x in enumerate(lessons):
            if x['end']<=x['start'] or (i and x['start']<lessons[i-1]['end']):c.close();return self.json(400,{'error':'Lesson times must be valid and cannot overlap.'})
        c.execute("UPDATE modules SET status='published',published_at=? WHERE id=?",(int(time.time()),m['id']));c.commit();c.close();return self.json(200,{'ok':True})

if __name__=='__main__':
    port=int(os.environ.get('PORT','8000')); print(f'Trainly is ready at http://127.0.0.1:{port}'); ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
