from flask import Flask, render_template, request, jsonify, redirect, url_for, session, Response, stream_with_context, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from befunge_engine import BefungeInterpreter
import time
import os
import csv
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = "SUPER_SECRET_CONTEST_KEY_CHANGE_THIS_IN_PROD"
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///contest.db'
# Use the Cloud Database URL if available, otherwise fall back to local SQLite for testing
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1) # Fix for some cloud providers

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///contest.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static_files' 
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- MODELS ---
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password_hash = db.Column(db.String(128))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password_hash = db.Column(db.String(128)) 
    score = db.Column(db.Integer, default=0)
    total_time = db.Column(db.Float, default=0.0)
    warnings = db.Column(db.Integer, default=0) 

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    points = db.Column(db.Integer)
    sample_input = db.Column(db.String(100))
    sample_output = db.Column(db.String(100))
    is_visible = db.Column(db.Boolean, default=False)

class TestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    input_data = db.Column(db.String(200))
    expected_output = db.Column(db.String(200))

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    status = db.Column(db.String(20))
    details = db.Column(db.String(100))
    solve_time = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Broadcast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.Text)
    sent_at = db.Column(db.Float, default=0.0)

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_running = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.Float, default=0.0)
    duration_seconds = db.Column(db.Integer, default=3600)
    q_update_ts = db.Column(db.Float, default=0.0)
    is_frozen = db.Column(db.Boolean, default=False)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200))
    display_name = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=False)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)

def get_config():
    conf = Config.query.first()
    if not conf:
        conf = Config(is_running=False, start_time=0, duration_seconds=3600, is_frozen=False)
        db.session.add(conf)
        db.session.commit()
    return conf

# --- ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/practice')
def practice():
    return render_template('practice.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    role = request.args.get('role', 'participant')
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        target_role = request.form['role']
        if target_role == 'admin':
            user = Admin.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                session.clear() 
                session['admin_id'] = user.id
                session['username'] = user.username
                return redirect('/admin')
        else:
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                session.clear() 
                session['user_id'] = user.id
                session['username'] = user.username
                return redirect('/contest')
        return render_template('login.html', error="Invalid Credentials", role=target_role)
    return render_template('login.html', role=role)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.warnings = (user.warnings or 0) + 1
            db.session.commit()
    session.clear()
    return redirect('/')

@app.route('/contest')
def contest_ui():
    if 'user_id' not in session: return redirect('/login?role=participant')
    user = User.query.get(session['user_id'])
    active_doc = Document.query.filter_by(is_active=True).first()
    doc_name = active_doc.display_name if active_doc else "DOCUMENTS"
    return render_template('index.html', user=user, doc_name=doc_name)

# --- API ---

@app.route('/api/status')
def get_status():
    conf = get_config()
    now = time.time()
    end_time = conf.start_time + conf.duration_seconds
    remaining = max(0, end_time - now) if conf.is_running else 0
    if conf.is_running and remaining == 0:
        conf.is_running = False
        db.session.commit()
    
    active_doc = Document.query.filter_by(is_active=True).first()
    doc_id = active_doc.id if active_doc else 0
    
    return jsonify({
        'running': conf.is_running, 
        'remaining': int(remaining),
        'q_ts': conf.q_update_ts,
        'doc_id': doc_id,
        'doc_name': active_doc.display_name if active_doc else "DOCUMENTS"
    })

@app.route('/api/questions')
def get_questions():
    if 'user_id' not in session: return jsonify([])
    conf = get_config()
    if not conf.is_running: return jsonify([])
    
    questions = Question.query.filter_by(is_visible=True).all()
    solved_ids = [s.question_id for s in Submission.query.filter_by(user_id=session['user_id'], status='passed').all()]

    return jsonify([{
        'id': q.id, 
        'title': q.title, 
        'points': q.points, 
        'desc': q.description, 
        's_in': q.sample_input,
        's_out': q.sample_output,
        'solved': q.id in solved_ids 
    } for q in questions])

@app.route('/api/leaderboard')
def get_leaderboard():
    conf = get_config()
    if conf.is_frozen and 'admin_id' not in session: return jsonify({'frozen': True})
    users = User.query.order_by(User.score.desc(), User.total_time.asc()).limit(20).all()
    return jsonify([{'username': u.username, 'score': u.score, 'time': u.total_time, 'warnings': (u.warnings or 0)} for u in users])

@app.route('/api/report_violation', methods=['POST'])
def report_violation():
    if 'user_id' not in session: return jsonify({})
    data = request.json or {}
    user = User.query.get(session['user_id'])
    if user:
        user.warnings = (user.warnings or 0) + 1
        db.session.commit()
    return jsonify({'status': 'logged'})

@app.route('/api/broadcasts')
def get_broadcasts():
    if 'user_id' not in session: return jsonify([])
    msgs = Broadcast.query.filter(Broadcast.sent_at > 0).all()
    return jsonify([{'id': m.id, 'message': m.message, 'sent_at': m.sent_at} for m in msgs])

@app.route('/api/my_submissions')
def my_submissions():
    if 'user_id' not in session: return jsonify([])
    subs = db.session.query(Submission, Question.title).join(Question, Submission.question_id == Question.id).filter(Submission.user_id == session['user_id']).order_by(Submission.timestamp.desc()).all()
    return jsonify([{'title': title, 'status': s.status, 'details': s.details, 'time': s.timestamp.strftime("%H:%M:%S")} for s, title in subs])

@app.route('/api/submit', methods=['POST'])
def submit_code():
    if 'user_id' not in session: return jsonify({'status': 'error', 'message': 'Not logged in'})
    conf = get_config()
    if not conf.is_running: return jsonify({'status': 'error', 'message': 'Contest inactive'})
    if time.time() > (conf.start_time + conf.duration_seconds): return jsonify({'status': 'error', 'message': 'Time up'})
    
    data = request.json
    user_id, q_id, code = session['user_id'], data.get('question_id'), data.get('code')
    cases = TestCase.query.filter_by(question_id=q_id).all()
    passed_count = 0
    fail_reason = "Wrong Answer"
    
    for i, case in enumerate(cases):
        vm = BefungeInterpreter()
        output = vm.run(code, case.input_data, tick_limit=50000)
        if "Time Limit Exceeded" in output:
            fail_reason = "TLE (Time Limit)"
            break
        if output.strip() == case.expected_output.strip(): passed_count += 1
        else:
            fail_reason = f"Failed Case #{i+1}"
            break
            
    is_perfect = (passed_count == len(cases)) and (len(cases) > 0)
    status_str = 'passed' if is_perfect else 'failed'
    detail_str = "✅ AC (All Passed)" if is_perfect else (f"⚠️ TLE" if fail_reason.startswith("TLE") else f"❌ {fail_reason} ({passed_count}/{len(cases)})")
    
    user = User.query.get(user_id)
    time_taken = time.time() - conf.start_time
    
    db.session.add(Submission(user_id=user_id, question_id=q_id, status=status_str, details=detail_str, solve_time=time_taken))
    
    if is_perfect and not (Submission.query.filter_by(user_id=user_id, question_id=q_id, status='passed').count() > 1):
        user.score += Question.query.get(q_id).points
        user.total_time += time_taken
        
    db.session.commit()
    return jsonify({'status': status_str, 'new_score': user.score, 'details': detail_str})

@app.route('/api/run', methods=['POST'])
def run_code():
    data, vm = request.json, BefungeInterpreter()
    return jsonify({'output': vm.run(data.get('code'), data.get('input', ""))})

# --- ADMIN ROUTES ---

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'admin_id' not in session: return redirect('/login?role=admin')
    if request.method == 'POST':
        new_q = Question(title=request.form['title'], description=request.form['desc'], points=request.form['points'], sample_input=request.form['s_in'], sample_output=request.form['s_out'], is_visible=False)
        db.session.add(new_q)
        db.session.commit()
        db.session.add(TestCase(question_id=new_q.id, input_data=request.form['s_in'], expected_output=request.form['s_out']))
        for h_in, h_out in zip(request.form.getlist('hidden_in[]'), request.form.getlist('hidden_out[]')):
            if h_in.strip() or h_out.strip(): db.session.add(TestCase(question_id=new_q.id, input_data=h_in, expected_output=h_out))
        db.session.commit()
    return render_template('admin.html', questions=Question.query.all(), admin_name=session['username'], broadcasts=Broadcast.query.all(), config=get_config(), documents=Document.query.all())

@app.route('/admin/control', methods=['POST'])
def admin_control():
    if 'admin_id' not in session: return redirect('/')
    conf, action, value = get_config(), request.form.get('action'), request.form.get('value')
    if action == 'start': 
        conf.is_running = True
        conf.start_time = time.time()
        conf.duration_seconds = int(value) * 60
    elif action == 'stop': conf.is_running = False
    elif action == 'add_time': conf.duration_seconds += int(value) * 60
    elif action == 'toggle_freeze': conf.is_frozen = not conf.is_frozen
    db.session.commit()
    return redirect('/admin')

@app.route('/admin/delete/<int:q_id>', methods=['POST'])
def delete_question(q_id):
    if 'admin_id' not in session: return redirect('/')
    q = Question.query.get(q_id)
    if q:
        TestCase.query.filter_by(question_id=q_id).delete()
        Submission.query.filter_by(question_id=q_id).delete()
        db.session.delete(q)
        db.session.commit()
        get_config().q_update_ts = time.time()
        db.session.commit()
    return redirect('/admin')

@app.route('/admin/question/toggle/<int:q_id>', methods=['POST'])
def toggle_question(q_id):
    if 'admin_id' not in session: return redirect('/')
    q = Question.query.get(q_id)
    if q:
        q.is_visible = not q.is_visible
        get_config().q_update_ts = time.time()
        db.session.commit()
    return redirect('/admin')

@app.route('/admin/reset', methods=['POST'])
def reset_contest_data():
    if 'admin_id' not in session: return redirect('/')
    db.session.query(Submission).delete()
    db.session.query(User).update({User.score: 0, User.total_time: 0.0, User.warnings: 0})
    get_config().is_running = False
    get_config().is_frozen = False
    db.session.commit()
    return redirect('/admin')

@app.route('/admin/download_leaderboard', methods=['POST'])
def download_leaderboard():
    if 'admin_id' not in session: return redirect('/')
    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        questions = Question.query.order_by(Question.id).all()
        writer.writerow(['Rank', 'Username', 'Score', 'Total Time', 'Warnings'] + [q.title for q in questions])
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for rank, user in enumerate(User.query.order_by(User.score.desc(), User.total_time.asc()).all()):
            row = [rank + 1, user.username, user.score, round(user.total_time, 2), user.warnings]
            for q in questions:
                sub = Submission.query.filter_by(user_id=user.id, question_id=q.id, status='passed').first()
                row.append(f"{round(sub.solve_time, 2)}" if sub else "-")
            writer.writerow(row)
            yield data.getvalue(); data.seek(0); data.truncate(0)
    response = Response(stream_with_context(generate()), mimetype='text/csv')
    response.headers.set('Content-Disposition', 'attachment', filename='befunge_detailed_results.csv')
    return response

@app.route('/admin/broadcast/add', methods=['POST'])
def add_broadcast():
    if 'admin_id' not in session: return redirect('/')
    if request.form['message']: db.session.add(Broadcast(message=request.form['message'], sent_at=0.0)); db.session.commit()
    return redirect('/admin')

@app.route('/admin/broadcast/send/<int:b_id>', methods=['POST'])
def send_broadcast(b_id):
    if 'admin_id' not in session: return redirect('/')
    b = Broadcast.query.get(b_id)
    if b: b.sent_at = time.time(); db.session.commit()
    return redirect('/admin')

@app.route('/admin/broadcast/delete/<int:b_id>', methods=['POST'])
def delete_broadcast(b_id):
    if 'admin_id' not in session: return redirect('/')
    b = Broadcast.query.get(b_id)
    if b: db.session.delete(b); db.session.commit()
    return redirect('/admin')

@app.route('/admin/document/upload', methods=['POST'])
def upload_document():
    if 'admin_id' not in session: return redirect('/')
    if 'doc_file' in request.files and request.form['doc_name']:
        f = request.files['doc_file']
        if f.filename != '':
            filename = secure_filename(f.filename)
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            new_doc = Document(filename=filename, display_name=request.form['doc_name'], is_active=False)
            db.session.add(new_doc)
            db.session.commit()
    return redirect('/admin')

@app.route('/admin/document/toggle/<int:doc_id>', methods=['POST'])
def toggle_document(doc_id):
    if 'admin_id' not in session: return redirect('/')
    Document.query.update({Document.is_active: False})
    doc = Document.query.get(doc_id)
    if doc: doc.is_active = True
    db.session.commit()
    return redirect('/admin')

@app.route('/admin/document/hide/<int:doc_id>', methods=['POST'])
def hide_document(doc_id):
    if 'admin_id' not in session: return redirect('/')
    doc = Document.query.get(doc_id)
    if doc: doc.is_active = False
    db.session.commit()
    return redirect('/admin')

@app.route('/admin/document/delete/<int:doc_id>', methods=['POST'])
def delete_document(doc_id):
    if 'admin_id' not in session: return redirect('/')
    doc = Document.query.get(doc_id)
    if doc:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], doc.filename))
        except: pass
        db.session.delete(doc)
        db.session.commit()
    return redirect('/admin')

@app.route('/get_active_document')
def get_active_document():
    doc = Document.query.filter_by(is_active=True).first()
    if doc: return send_from_directory(app.config['UPLOAD_FOLDER'], doc.filename)
    return "No Document is currently active."

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)