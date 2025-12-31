from flask import Flask, render_template, request, jsonify, redirect, url_for, session, Response, stream_with_context
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash
from befunge_engine import BefungeInterpreter
import time
import os
import csv
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = "SUPER_SECRET_CONTEST_KEY_CHANGE_THIS_IN_PROD"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///contest.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    warnings = db.Column(db.Integer, default=0) # NEW: Proctoring Warning Counter

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    points = db.Column(db.Integer)
    sample_input = db.Column(db.String(100))
    sample_output = db.Column(db.String(100))

class TestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    input_data = db.Column(db.String(200))
    expected_output = db.Column(db.String(200))

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    status = db.Column(db.String(20))     # 'passed' or 'failed'
    details = db.Column(db.String(100))   # e.g., "Passed 3/4", "TLE"
    solve_time = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_running = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.Float, default=0.0)
    duration_seconds = db.Column(db.Integer, default=3600)

def get_config():
    conf = Config.query.first()
    if not conf:
        conf = Config(is_running=False, start_time=0, duration_seconds=3600)
        db.session.add(conf)
        db.session.commit()
    return conf

# --- AUTH ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')

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
                session.clear() # Security Wipe
                session['admin_id'] = user.id
                session['username'] = user.username
                return redirect('/admin')
        else:
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                session.clear() # Security Wipe
                session['user_id'] = user.id
                session['username'] = user.username
                return redirect('/contest')
        
        return render_template('login.html', error="Invalid Credentials", role=target_role)

    return render_template('login.html', role=role)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# --- CONTEST UI ---

@app.route('/contest')
def contest_ui():
    if 'user_id' not in session:
        return redirect('/login?role=participant')
    
    user = User.query.get(session['user_id'])
    return render_template('index.html', user=user)

# --- API ROUTES ---

@app.route('/api/status')
def get_status():
    conf = get_config()
    now = time.time()
    end_time = conf.start_time + conf.duration_seconds
    remaining = max(0, end_time - now) if conf.is_running else 0
    if conf.is_running and remaining == 0:
        conf.is_running = False
        db.session.commit()
    return jsonify({'running': conf.is_running, 'remaining': int(remaining)})

@app.route('/api/questions')
def get_questions():
    if 'user_id' not in session: return jsonify([])
    conf = get_config()
    if not conf.is_running: return jsonify([])
    
    questions = Question.query.all()
    return jsonify([{'id': q.id, 'title': q.title, 'points': q.points, 'desc': q.description, 's_in': q.sample_input} for q in questions])

@app.route('/api/leaderboard')
def get_leaderboard():
    users = User.query.order_by(User.score.desc(), User.total_time.asc()).limit(20).all()
    return jsonify([{
        'username': u.username, 
        'score': u.score, 
        'time': round(u.total_time, 2),
        'warnings': u.warnings # NEW: Send warning count
    } for u in users])

@app.route('/api/report_violation', methods=['POST'])
def report_violation():
    if 'user_id' not in session: return jsonify({})
    
    user = User.query.get(session['user_id'])
    if user:
        user.warnings += 1
        db.session.commit()
        print(f"VIOLATION: User {user.username} switched tabs! Total: {user.warnings}")
        
    return jsonify({'status': 'logged', 'warnings': user.warnings})

@app.route('/api/my_submissions')
def my_submissions():
    if 'user_id' not in session: return jsonify([])
    
    subs = db.session.query(Submission, Question.title)\
        .join(Question, Submission.question_id == Question.id)\
        .filter(Submission.user_id == session['user_id'])\
        .order_by(Submission.timestamp.desc()).all()
        
    return jsonify([{
        'title': title,
        'status': s.status,
        'details': s.details,
        'time': s.timestamp.strftime("%H:%M:%S")
    } for s, title in subs])

@app.route('/api/submit', methods=['POST'])
def submit_code():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'})
        
    conf = get_config()
    if not conf.is_running: return jsonify({'status': 'error', 'message': 'Contest inactive'})
    if time.time() > (conf.start_time + conf.duration_seconds): return jsonify({'status': 'error', 'message': 'Time up'})

    data = request.json
    user_id = session['user_id']
    q_id = data.get('question_id')
    code = data.get('code')

    # Run Tests
    cases = TestCase.query.filter_by(question_id=q_id).all()
    total_cases = len(cases)
    passed_count = 0
    fail_reason = "Wrong Answer"
    
    for i, case in enumerate(cases):
        vm = BefungeInterpreter()
        output = vm.run(code, case.input_data, tick_limit=50000)
        
        if "Time Limit Exceeded" in output:
            fail_reason = "TLE (Time Limit)"
            break
            
        if output.strip() == case.expected_output.strip():
            passed_count += 1
        else:
            fail_reason = f"Failed Case #{i+1}"
            break

    is_perfect = (passed_count == total_cases) and (total_cases > 0)
    status_str = 'passed' if is_perfect else 'failed'
    
    if is_perfect: detail_str = "✅ AC (All Passed)"
    elif fail_reason.startswith("TLE"): detail_str = "⚠️ TLE"
    else: detail_str = f"❌ {fail_reason} ({passed_count}/{total_cases})"

    # Log Submission
    user = User.query.get(user_id)
    q = Question.query.get(q_id)
    time_taken = time.time() - conf.start_time
    
    sub = Submission(
        user_id=user_id, 
        question_id=q_id, 
        status=status_str, 
        details=detail_str,
        solve_time=time_taken
    )
    db.session.add(sub)
    
    already_solved = Submission.query.filter_by(user_id=user_id, question_id=q_id, status='passed').count() > 1
    
    if is_perfect and not already_solved:
        user.score += q.points
        user.total_time += time_taken
    
    db.session.commit()
    
    return jsonify({
        'status': status_str, 
        'new_score': user.score,
        'details': detail_str
    })

@app.route('/api/run', methods=['POST'])
def run_code():
    if 'user_id' not in session and 'admin_id' not in session:
        return jsonify({'output': "Error: Login required."})
    
    data = request.json
    vm = BefungeInterpreter()
    output = vm.run(data.get('code'), data.get('input', ""))
    return jsonify({'output': output})

# --- ADMIN ROUTES ---

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'admin_id' not in session:
        return redirect('/login?role=admin')
        
    if request.method == 'POST':
        title = request.form['title']
        desc = request.form['desc']
        pts = request.form['points']
        s_in = request.form['s_in']
        s_out = request.form['s_out']
        
        new_q = Question(title=title, description=desc, points=pts, sample_input=s_in, sample_output=s_out)
        db.session.add(new_q)
        db.session.commit()
        
        # Add Sample Case
        db.session.add(TestCase(question_id=new_q.id, input_data=s_in, expected_output=s_out))
        
        # Add Hidden Cases
        for h_in, h_out in zip(request.form.getlist('hidden_in[]'), request.form.getlist('hidden_out[]')):
            if h_in.strip() or h_out.strip(): 
                db.session.add(TestCase(question_id=new_q.id, input_data=h_in, expected_output=h_out))
        
        db.session.commit()
    
    all_questions = Question.query.all()
    return render_template('admin.html', questions=all_questions, admin_name=session['username'])

@app.route('/admin/control', methods=['POST'])
def admin_control():
    if 'admin_id' not in session: return redirect('/')
    action = request.form.get('action')
    value = request.form.get('value')
    conf = get_config()
    if action == 'start':
        conf.is_running = True
        conf.start_time = time.time()
        conf.duration_seconds = int(value) * 60
    elif action == 'stop': conf.is_running = False
    elif action == 'add_time': conf.duration_seconds += int(value) * 60
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
    return redirect('/admin')

@app.route('/admin/reset', methods=['POST'])
def reset_contest_data():
    if 'admin_id' not in session: return redirect('/')
    try:
        db.session.query(Submission).delete()
        db.session.query(User).update({User.score: 0, User.total_time: 0.0, User.warnings: 0})
        conf = get_config()
        conf.is_running = False
        db.session.commit()
    except Exception as e:
        db.session.rollback()
    return redirect('/admin')

@app.route('/admin/download_leaderboard', methods=['POST'])
def download_leaderboard():
    if 'admin_id' not in session: return redirect('/')
    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        questions = Question.query.order_by(Question.id).all()
        question_titles = [q.title for q in questions]
        question_ids = [q.id for q in questions]
        
        header_row = ['Rank', 'Username', 'Score', 'Warnings'] + question_titles
        writer.writerow(header_row)
        yield data.getvalue()
        data.seek(0); data.truncate(0)

        users = User.query.order_by(User.score.desc(), User.total_time.asc()).all()
        for rank, user in enumerate(users):
            row = [rank + 1, user.username, user.score, user.warnings]
            for q_id in question_ids:
                sub = Submission.query.filter_by(user_id=user.id, question_id=q_id, status='passed').first()
                row.append(f"{round(sub.solve_time, 2)}" if sub else "-")
            writer.writerow(row)
            yield data.getvalue()
            data.seek(0); data.truncate(0)

    response = Response(stream_with_context(generate()), mimetype='text/csv')
    response.headers.set('Content-Disposition', 'attachment', filename='befunge_results.csv')
    return response

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)