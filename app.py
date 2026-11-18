from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory, Response
from flask_socketio import SocketIO, emit, join_room
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from emotion_detector import detect_emotion_from_base64
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import db
from datetime import datetime
import random, string, os, uuid, csv, io, json
from pywebpush import webpush, WebPushException

# Load VAPID keys
_VAPID_KEYS_PATH = os.path.join(os.path.dirname(__file__), 'vapid_keys.json')
with open(_VAPID_KEYS_PATH) as _f:
    _VAPID = json.load(_f)
VAPID_PUBLIC_KEY  = _VAPID['public_key']
VAPID_PRIVATE_KEY = _VAPID['private_key']
VAPID_CLAIMS      = {'sub': 'mailto:admin@emotionapp.local'}

app = Flask(__name__)
app.secret_key = 'emotion-app-secret-2025'
app.config['WTF_CSRF_TIME_LIMIT'] = 3600   # token valid 1 hour
socketio = SocketIO(app, cors_allowed_origins="*")
csrf    = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[])

@app.errorhandler(CSRFError)
def handle_csrf_error(_e):
    return render_template('login.html', error='Session expired or invalid request. Please try again.'), 400

db.apply_indexes()

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'questions')
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB max

# ============================================================
# HELPERS
# ============================================================
def map_emotion(raw):
    """
    Mapping tegas 6 kelas dataset -> 4 kategori aplikasi.
    """
    m = {
        'happy': 'Happy',
        'angry': 'Frustrated',
        'fear': 'Confused',
        'surprise': 'Frustrated',
        'sad': 'Confused',
        'neutral': 'Engaged'
    }
    return m.get(raw, 'Engaged')

def map_emotion_from_scores(emotions):
    """
    Mapping skor 6 kelas -> 4 kategori.
    Perbandingan adil: pakai max(sad,fear) dan max(angry,surprise)
    sehingga setiap kategori diwakili oleh 1 skor terkuat (bukan jumlah).
    """
    if not emotions:
        return 'Engaged', {
            'Happy': 0.0, 'Engaged': 0.0, 'Confused': 0.0, 'Frustrated': 0.0
        }
    neutral_score  = float(emotions.get('neutral', 0.0))
    sad_score      = float(emotions.get('sad', 0.0))
    fear_score     = float(emotions.get('fear', 0.0))
    angry_score    = float(emotions.get('angry', 0.0))
    surprise_score = float(emotions.get('surprise', 0.0))
    happy_score    = float(emotions.get('happy', 0.0))

    confused_score   = sad_score + fear_score
    frustrated_score = angry_score + surprise_score

    MIN_SCORE = 0.18

    scaled = {
        'Happy':      happy_score,
        'Engaged':    neutral_score,
        'Confused':   confused_score   if confused_score   >= MIN_SCORE else 0.0,
        'Frustrated': frustrated_score if frustrated_score >= MIN_SCORE else 0.0,
    }

    top_cat = max(scaled, key=scaled.get)

    raw_group_scores = {
        'Happy':      happy_score,
        'Engaged':    neutral_score,
        'Confused':   confused_score,
        'Frustrated': frustrated_score,
    }
    return top_cat, raw_group_scores

def generate_class_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ============================================================
# AUTH ROUTES
# ============================================================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('teacher_dashboard') if session['role'] == 'teacher' else url_for('student_page'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role     = request.form.get('role', '').strip()

    user = db.get_user_by_username(username)
    if not user or user['role'] != role:
        return render_template('login.html', error='Wrong username, password, or role.')

    if user['role'] == 'teacher':
        stored = user['password']
        if stored.startswith('pbkdf2:') or stored.startswith('scrypt:'):
            if not check_password_hash(stored, password):
                return render_template('login.html', error='Wrong username, password, or role.')
        else:
            if stored != password:
                return render_template('login.html', error='Wrong username, password, or role.')
            db.update_user(user['id'], user['name'], user['username'], generate_password_hash(password))
    else:
        if user['password'] != password:
            return render_template('login.html', error='Wrong username, password, or role.')

    session['user_id']   = user['id']
    session['user_name'] = user['name']
    session['username']  = user['username']
    session['role']      = user['role']
    return redirect(url_for('teacher_dashboard') if role == 'teacher' else url_for('select_class'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name     = request.form.get('name','').strip()
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        role     = request.form.get('role','student')
        if role == 'teacher':
            return render_template('register.html', error='Teacher registration is not allowed. Contact a registered teacher.')
        if db.get_user_by_username(username):
            return render_template('register.html', error='Username is already taken.')
        db.create_user(name, username, password, role)
        return render_template('login.html', success='Account created successfully, please sign in.')
    return render_template('register.html')

@app.route('/teacher/add-teacher', methods=['POST'])
def teacher_add_teacher():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
    name     = request.form.get('name','').strip()
    username = request.form.get('username','').strip()
    password = request.form.get('password','').strip()
    if not name or not username or not password:
        return redirect(url_for('teacher_dashboard', error='All fields are required.'))
    if db.get_user_by_username(username):
        return redirect(url_for('teacher_dashboard', error='Username is already taken.'))
    db.create_user(name, username, generate_password_hash(password), 'teacher')
    return redirect(url_for('teacher_dashboard', success='Teacher account added successfully.'))

@app.route('/student/edit-profile', methods=['POST'])
def student_edit_profile():
    if session.get('role') != 'student':
        return redirect(url_for('index'))
    name       = request.form.get('name', '').strip()
    username   = request.form.get('username', '').strip()
    current_pw = request.form.get('current_password', '').strip()
    new_pw     = request.form.get('new_password', '').strip()
    confirm_pw = request.form.get('confirm_password', '').strip()
    if not name or not username or not current_pw:
        return redirect(url_for('student_page'))
    user = db.get_user_by_id(session['user_id'])
    if not user or user['password'] != current_pw:
        return redirect(url_for('student_page') + '?profile_error=Current+password+is+incorrect.')
    existing = db.get_user_by_username(username)
    if existing and existing['id'] != session['user_id']:
        return redirect(url_for('student_page') + '?profile_error=Username+is+already+taken.')
    if new_pw:
        if new_pw != confirm_pw:
            return redirect(url_for('student_page') + '?profile_error=New+password+confirmation+does+not+match.')
        db.update_user(session['user_id'], name, username, new_pw)
    else:
        db.update_user(session['user_id'], name, username)
    session['user_name'] = name
    session['username']  = username
    return redirect(url_for('student_page') + '?profile_success=1')

@app.route('/teacher/edit-profile', methods=['POST'])
def teacher_edit_profile():
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    name       = request.form.get('name', '').strip()
    username   = request.form.get('username', '').strip()
    current_pw = request.form.get('current_password', '').strip()
    new_pw     = request.form.get('new_password', '').strip()
    confirm_pw = request.form.get('confirm_password', '').strip()
    if not name or not username or not current_pw:
        return redirect(url_for('teacher_dashboard', error='Name, username, and current password are required.'))
    user = db.get_user_by_id(session['user_id'])
    if not user:
        return redirect(url_for('teacher_dashboard', error='Current password is incorrect.'))
    stored = user['password']
    if stored.startswith('pbkdf2:') or stored.startswith('scrypt:'):
        pw_ok = check_password_hash(stored, current_pw)
    else:
        pw_ok = stored == current_pw
    if not pw_ok:
        return redirect(url_for('teacher_dashboard', error='Current password is incorrect.'))
    existing = db.get_user_by_username(username)
    if existing and existing['id'] != session['user_id']:
        return redirect(url_for('teacher_dashboard', error='Username is already taken.'))
    if new_pw:
        if new_pw != confirm_pw:
            return redirect(url_for('teacher_dashboard', error='New password confirmation does not match.'))
        db.update_user(session['user_id'], name, username, generate_password_hash(new_pw))
    else:
        db.update_user(session['user_id'], name, username)
    session['user_name'] = name
    session['username']  = username
    return redirect(url_for('teacher_dashboard', success='Profile updated successfully!'))

@app.route('/logout')
def logout():
    if session.get('role') == 'teacher':
        db.end_all_active_sessions_by_teacher(session['user_id'])
    session.clear()
    return redirect(url_for('index'))

# ============================================================
# TEACHER ROUTES
# ============================================================
@app.route('/teacher')
def teacher_dashboard():
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('index'))
    classes = db.get_classes_by_teacher(session['user_id'])
    error   = request.args.get('error')
    success = request.args.get('success')
    return render_template('teacher_dashboard.html',
                           name=session['user_name'],
                           session_username=session['username'],
                           classes=classes,
                           error=error, success=success)

@app.route('/teacher/create-class', methods=['POST'])
def create_class():
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    class_name = request.form.get('class_name','').strip()
    if not class_name:
        classes = db.get_classes_by_teacher(session['user_id'])
        return render_template('teacher_dashboard.html',
                               name=session['user_name'],
                               session_username=session['username'],
                               classes=classes,
                               error='Class name cannot be empty.')
    class_code = generate_class_code()
    db.create_class(session['user_id'], class_name, class_code)
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete-class/<int:class_id>', methods=['POST'])
def delete_class(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    db.delete_class_by_teacher(class_id, session['user_id'])
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/class/<int:class_id>')
def class_room(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    classes = db.get_classes_by_teacher(session['user_id'])
    cls = next((c for c in classes if c['id'] == class_id), None)
    class_name = cls['class_name'] if cls else f'Class {class_id}'
    active_session = db.get_active_session(class_id)
    students = db.get_students_in_class(class_id)
    return render_template('classroom.html', name=session['user_name'],
                           class_id=class_id, class_name=class_name,
                           active_session=active_session, students=students)

@app.route('/teacher/start-session', methods=['POST'])
@csrf.exempt
def start_session():
    data = request.get_json(force=True, silent=True) or {}
    class_id = data.get('class_id') or request.form.get('class_id')
    if not class_id:
        return jsonify({'success': False, 'message': 'class_id required'}), 400
    class_id = int(class_id)
    session_name = f"Session {datetime.now().strftime('%d/%m %H:%M')}"
    sid = db.create_session(class_id, session_name)
    socketio.emit('session_started', {'session_id': sid}, room=f"class_{class_id}")
    return jsonify({'success': True, 'session_id': sid, 'session_name': session_name})

@app.route('/teacher/end-session', methods=['POST'])
@csrf.exempt
def end_session():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': 'session_id required'}), 400
    db.end_session(session_id)
    return jsonify({'success': True})

# ============================================================
# REPORTS
# ============================================================
@app.route('/teacher/reports/<int:class_id>')
def reports(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    all_sessions = db.get_all_sessions_report(class_id)
    students = db.get_students_in_class(class_id)
    latest_emotions = db.get_latest_emotions_by_class(class_id)
    active_session_ids = [s['id'] for s in all_sessions if not s.get('ended_at')]
    return render_template('reports.html', name=session['user_name'],
                           class_id=class_id, all_sessions=all_sessions,
                           students=students, latest_emotions=latest_emotions,
                           active_session_ids=active_session_ids)

@app.route('/teacher/adjust-soal/<int:class_id>')
def adjust_soal_page(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    active_session = db.get_active_session(class_id)
    latest_emotions = db.get_latest_emotions_by_class(class_id)
    return render_template('adjust_soal.html',
                           name=session['user_name'],
                           class_id=class_id,
                           active_session=active_session,
                           latest_emotions=latest_emotions)

def _build_emotion_groups_payload(class_id):
    active_session = db.get_active_session(class_id)
    if not active_session:
        return {
            'active_session': None,
            'groups': {'Happy': [], 'Engaged': [], 'Confused': [], 'Frustrated': []},
            'summary': {'Happy': {'count': 0, 'percentage': 0, 'difficulty': 'medium'},
                        'Engaged': {'count': 0, 'percentage': 0, 'difficulty': 'medium'},
                        'Confused': {'count': 0, 'percentage': 0, 'difficulty': 'medium'},
                        'Frustrated': {'count': 0, 'percentage': 0, 'difficulty': 'medium'}},
            'total': 0
        }

    emotions = db.get_latest_emotions(active_session['id'])
    stats = db.get_student_stats(active_session['id'])
    group_diff = db.get_group_difficulty(active_session['id'])

    groups = {'Happy': [], 'Engaged': [], 'Confused': [], 'Frustrated': []}
    for e in emotions:
        cat = e.get('emotion_category') or 'Engaged'
        if cat not in groups:
            groups[cat] = []
        st = stats.get(e['student_id'], {'total': 0, 'correct': 0, 'accuracy': 0})
        groups[cat].append({
            'name': e.get('student_name', '-'),
            'student_id': e.get('student_id'),
            'emotion_raw': e.get('emotion_raw', '-'),
            'confidence': float(e.get('confidence', 0) or 0),
            'total': st.get('total', 0),
            'accuracy': float(st.get('accuracy', 0) or 0)
        })

    total = len(emotions)
    summary = {}
    for cat in ['Happy', 'Engaged', 'Confused', 'Frustrated']:
        count = len(groups.get(cat, []))
        summary[cat] = {
            'count': count,
            'percentage': round(count / total * 100) if total > 0 else 0,
            'difficulty': group_diff.get(cat, 'medium')
        }

    return {
        'active_session': active_session,
        'groups': groups,
        'summary': summary,
        'total': total
    }

@app.route('/teacher/emotion-groups/<int:class_id>')
def emotion_groups_page(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))

    payload = _build_emotion_groups_payload(class_id)
    return render_template(
        'emotion_groups.html',
        name=session['user_name'],
        class_id=class_id,
        active_session=payload['active_session'],
        groups=payload['groups'],
        summary=payload['summary'],
        total=payload['total']
    )

@app.route('/api/emotion-groups/<int:class_id>')
def emotion_groups_api(class_id):
    if session.get('role') != 'teacher':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    payload = _build_emotion_groups_payload(class_id)
    active = payload.get('active_session')
    return jsonify({
        'success': True,
        'class_id': class_id,
        'active_session': {
            'id': active.get('id'),
            'session_name': active.get('session_name')
        } if active else None,
        'groups': payload.get('groups', {}),
        'summary': payload.get('summary', {}),
        'total': payload.get('total', 0),
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/teacher/class/<int:class_id>/students')
def manage_students_page(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))

    classes = db.get_classes_by_teacher(session['user_id'])
    target_class = next((c for c in classes if c['id'] == class_id), None)
    if not target_class:
        return redirect(url_for('teacher_dashboard'))

    students = db.get_students_in_class(class_id)
    available_students = db.get_unenrolled_students(class_id)
    students_creds = db.get_students_credentials(class_id)
    return render_template(
        'manage_students.html',
        name=session['user_name'],
        class_id=class_id,
        class_name=target_class['class_name'],
        students=students,
        available_students=available_students,
        students_creds=students_creds
    )

@app.route('/teacher/class/<int:class_id>/students/add', methods=['POST'])
def add_student_to_class(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))

    student_id = int(request.form.get('student_id', 0))
    if student_id:
        db.enroll_student(class_id, student_id)
    return redirect(url_for('manage_students_page', class_id=class_id))

@app.route('/teacher/class/<int:class_id>/students/remove/<int:student_id>', methods=['POST'])
def remove_student_from_class_route(class_id, student_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))

    classes = db.get_classes_by_teacher(session['user_id'])
    target_class = next((c for c in classes if c['id'] == class_id), None)
    if not target_class:
        return redirect(url_for('teacher_dashboard'))

    enrolled_ids = {s['id'] for s in db.get_students_in_class(class_id)}
    if student_id in enrolled_ids:
        db.remove_student_from_class(class_id, student_id)

    return redirect(url_for('manage_students_page', class_id=class_id))

@app.route('/teacher/questions')
def manage_questions_page():
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    difficulty = request.args.get('difficulty', '').strip() or None
    questions = db.list_questions(difficulty)
    return render_template('questions_manage.html',
                           name=session['user_name'],
                           questions=questions,
                           selected_difficulty=difficulty)

@app.route('/teacher/questions/create', methods=['POST'])
def create_question_route():
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    difficulty = request.form.get('difficulty', '').strip()
    question_text = request.form.get('question_text', '').strip()
    option_a = request.form.get('option_a', '').strip()
    option_b = request.form.get('option_b', '').strip()
    option_c = request.form.get('option_c', '').strip()
    option_d = request.form.get('option_d', '').strip()
    correct_answer = request.form.get('correct_answer', '').strip().upper()
    topic = request.form.get('topic', '').strip()

    if difficulty not in ['very_easy', 'easy', 'medium', 'hard', 'very_hard']:
        return redirect(url_for('manage_questions_page'))
    if not question_text:
        return redirect(url_for('manage_questions_page'))
    question_type = request.form.get('question_type', 'multiple_choice').strip()
    essay_answer = None
    if question_type != 'essay':
        if not all([option_a, option_b, option_c, option_d]) or correct_answer not in ['A','B','C','D']:
            return redirect(url_for('manage_questions_page'))
    else:
        option_a = option_b = option_c = option_d = correct_answer = ''
        essay_answer = request.form.get('essay_answer', '').strip() or None

    video_url = None
    video_type = None
    video_source = request.form.get('video_source', '').strip()

    if video_source == 'youtube':
        yt_url = request.form.get('youtube_url', '').strip()
        if yt_url:
            video_url = yt_url
            video_type = 'youtube'
    elif video_source == 'upload':
        file = request.files.get('video_file')
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext in ALLOWED_VIDEO_EXTENSIONS:
                filename = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                video_url = f"uploads/questions/{filename}"
                video_type = 'upload'
            elif ext in ALLOWED_IMAGE_EXTENSIONS:
                filename = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                video_url = f"uploads/questions/{filename}"
                video_type = 'image'

    db.create_question(
        difficulty, question_text, option_a, option_b, option_c, option_d, correct_answer, topic,
        video_url, video_type, question_type,
        question_text_en=request.form.get('question_text_en','').strip() or None,
        question_text_my=request.form.get('question_text_my','').strip() or None,
        option_a_en=request.form.get('option_a_en','').strip() or None,
        option_b_en=request.form.get('option_b_en','').strip() or None,
        option_c_en=request.form.get('option_c_en','').strip() or None,
        option_d_en=request.form.get('option_d_en','').strip() or None,
        option_a_my=request.form.get('option_a_my','').strip() or None,
        option_b_my=request.form.get('option_b_my','').strip() or None,
        option_c_my=request.form.get('option_c_my','').strip() or None,
        option_d_my=request.form.get('option_d_my','').strip() or None,
        topic_en=request.form.get('topic_en','').strip() or None,
        topic_my=request.form.get('topic_my','').strip() or None,
        essay_answer=essay_answer,
    )
    return redirect(url_for('manage_questions_page', difficulty=difficulty))

@app.route('/teacher/questions/edit/<int:question_id>', methods=['GET', 'POST'])
def edit_question_route(question_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    question = db.get_question(question_id)
    if not question:
        return redirect(url_for('manage_questions_page'))

    if request.method == 'GET':
        q = dict(question)
        if q.get('video_url') and q.get('video_type') not in ('youtube',):
            q['video_url_display'] = '/' + q['video_url'] if not q['video_url'].startswith('/') else q['video_url']
        return jsonify(q)

    difficulty    = request.form.get('difficulty', '').strip()
    question_text = request.form.get('question_text', '').strip()
    option_a      = request.form.get('option_a', '').strip()
    option_b      = request.form.get('option_b', '').strip()
    option_c      = request.form.get('option_c', '').strip()
    option_d      = request.form.get('option_d', '').strip()
    correct_answer= request.form.get('correct_answer', '').strip().upper()
    topic         = request.form.get('topic', '').strip()

    question_type = request.form.get('question_type', 'multiple_choice').strip()
    if not difficulty or not question_text:
        return redirect(url_for('manage_questions_page'))
    essay_answer = None
    if question_type != 'essay':
        if not all([option_a, option_b, option_c, option_d]) or correct_answer not in ['A','B','C','D']:
            return redirect(url_for('manage_questions_page'))
    else:
        option_a = option_b = option_c = option_d = correct_answer = ''
        essay_answer = request.form.get('essay_answer', '').strip() or None

    video_url  = question.get('video_url')
    video_type = question.get('video_type')
    video_source = request.form.get('video_source', '').strip()

    if video_source == 'youtube':
        yt_url = request.form.get('youtube_url', '').strip()
        if yt_url:
            video_url, video_type = yt_url, 'youtube'
    elif video_source == 'upload':
        file = request.files.get('video_file')
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext in ALLOWED_VIDEO_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS:
                if question.get('video_type') == 'upload' and question.get('video_url'):
                    old = os.path.join(os.path.dirname(__file__), 'static', question['video_url'])
                    if os.path.exists(old): os.remove(old)
                filename = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                video_url  = f"uploads/questions/{filename}"
                video_type = 'upload' if ext in ALLOWED_VIDEO_EXTENSIONS else 'image'
    elif video_source == 'none':
        if question.get('video_type') == 'upload' and question.get('video_url'):
            old = os.path.join(os.path.dirname(__file__), 'static', question['video_url'])
            if os.path.exists(old): os.remove(old)
        video_url, video_type = None, None

    db.update_question(
        question_id, difficulty, question_text, option_a, option_b,
        option_c, option_d, correct_answer, topic, video_url, video_type, question_type,
        question_text_en=request.form.get('question_text_en','').strip() or None,
        question_text_my=request.form.get('question_text_my','').strip() or None,
        option_a_en=request.form.get('option_a_en','').strip() or None,
        option_b_en=request.form.get('option_b_en','').strip() or None,
        option_c_en=request.form.get('option_c_en','').strip() or None,
        option_d_en=request.form.get('option_d_en','').strip() or None,
        option_a_my=request.form.get('option_a_my','').strip() or None,
        option_b_my=request.form.get('option_b_my','').strip() or None,
        option_c_my=request.form.get('option_c_my','').strip() or None,
        option_d_my=request.form.get('option_d_my','').strip() or None,
        topic_en=request.form.get('topic_en','').strip() or None,
        topic_my=request.form.get('topic_my','').strip() or None,
        essay_answer=essay_answer,
    )
    return redirect(url_for('manage_questions_page', difficulty=difficulty))

@app.route('/teacher/questions/delete/<int:question_id>', methods=['POST'])
def delete_question_route(question_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    question = db.get_question(question_id)
    if question and question.get('video_type') == 'upload' and question.get('video_url'):
        file_path = os.path.join(os.path.dirname(__file__), 'static', question['video_url'])
        if os.path.exists(file_path):
            os.remove(file_path)
    db.delete_question(question_id)
    return redirect(url_for('manage_questions_page'))

@app.route('/teacher/reports/session/<int:session_id>')
def session_report(session_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    report = db.get_session_report(session_id)
    return render_template('session_report.html', report=report)

@app.route('/api/session-report/<int:session_id>')
def session_report_api(session_id):
    if session.get('role') != 'teacher':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    report = db.get_session_report(session_id)
    if not report or not report.get('session'):
        return jsonify({'success': False, 'message': 'Session report not found'}), 404

    students = []
    for s in report.get('students', []):
        students.append({
            'id': s.get('id'),
            'name': s.get('name'),
            'total_answers': s.get('total_answers') or 0,
            'correct_answers': s.get('correct_answers') or 0,
            'accuracy': float(s.get('accuracy') or 0),
            'final_emotion': s.get('final_emotion') or 'None'
        })

    timeline = [
        {'emotion_category': r.get('emotion_category', ''),
         'time_slot': r.get('time_slot', ''),
         'count': int(r.get('count', 0))}
        for r in report.get('timeline', [])
    ]

    return jsonify({
        'success': True,
        'session_id': session_id,
        'emotion_summary': report.get('emotion_summary', {}),
        'students': students,
        'timeline': timeline,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/teacher/reports/delete-session/<int:session_id>', methods=['POST'])
@csrf.exempt
def delete_session_report(session_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    class_id = int(request.form.get('class_id', 0))
    db.delete_session_by_class(session_id, class_id)
    return redirect(url_for('reports', class_id=class_id))

@app.route('/teacher/reports/<int:class_id>/export-csv')
def export_class_csv(class_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    cls          = db.get_class_by_id(class_id) or {}
    all_sessions = db.get_all_sessions_report(class_id)
    export_date  = datetime.now().strftime('%Y-%m-%d')

    out = io.StringIO()
    out.write('﻿')  # UTF-8 BOM for Excel
    w = csv.writer(out)

    # Header block
    w.writerow(['CLASS SESSION REPORT'])
    w.writerow(['Class', cls.get('class_name', f'Class {class_id}')])
    w.writerow(['Teacher', cls.get('teacher_name', '')])
    w.writerow(['Export Date', export_date])
    w.writerow(['Total Sessions', len(all_sessions)])
    w.writerow([])

    # Column headers
    w.writerow(['#', 'Session Name', 'Date', 'End Time', 'Status',
                'Students', 'Total Answers', 'Avg Accuracy (%)'])

    total_ans = 0
    acc_sum   = 0
    acc_count = 0
    for i, s in enumerate(all_sessions, 1):
        started = s['started_at'].strftime('%Y-%m-%d %H:%M') if s.get('started_at') else ''
        ended   = s['ended_at'].strftime('%Y-%m-%d %H:%M') if s.get('ended_at') else ''
        status  = 'Ended' if s.get('ended_at') else 'Active'
        acc     = float(s.get('avg_accuracy') or 0)
        ta      = int(s.get('total_answers') or 0)
        total_ans += ta
        if acc:
            acc_sum += acc; acc_count += 1
        w.writerow([i, s.get('session_name', ''), started, ended, status,
                    s.get('active_students', 0), ta, acc])

    # Summary row
    w.writerow([])
    w.writerow(['', 'TOTALS / AVERAGE', '', '', '',
                '', total_ans,
                round(acc_sum / acc_count, 1) if acc_count else 0])

    safe_name = ''.join(c for c in cls.get('class_name', str(class_id)) if c.isalnum() or c in ' _-').strip().replace(' ', '_')
    filename  = f"sessions_{safe_name}_{export_date}.csv"
    return Response(out.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@app.route('/teacher/reports/session/<int:session_id>/export-csv')
def export_session_csv(session_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('index'))
    report = db.get_session_report(session_id)
    sess   = report.get('session') or {}
    students = report.get('students', [])
    emotion_summary = report.get('emotion_summary', {})

    started = sess['started_at'].strftime('%Y-%m-%d %H:%M') if sess.get('started_at') else ''
    ended   = sess['ended_at'].strftime('%Y-%m-%d %H:%M') if sess.get('ended_at') else 'Active'
    export_date = datetime.now().strftime('%Y-%m-%d')

    out = io.StringIO()
    out.write('﻿')  # UTF-8 BOM for Excel
    w = csv.writer(out)

    # Header block
    w.writerow(['SESSION REPORT'])
    w.writerow(['Session Name', sess.get('session_name', '')])
    w.writerow(['Class', sess.get('class_name', '')])
    w.writerow(['Teacher', sess.get('teacher_name', '')])
    w.writerow(['Start Time', started])
    w.writerow(['End Time', ended])
    w.writerow(['Export Date', export_date])
    w.writerow([])

    # Emotion summary
    w.writerow(['EMOTION SUMMARY'])
    w.writerow(['Emotion', 'Students'])
    for emotion in ['Happy', 'Engaged', 'Confused', 'Frustrated']:
        w.writerow([emotion, emotion_summary.get(emotion, 0)])
    w.writerow([])

    # Student results
    w.writerow(['STUDENT RESULTS'])
    w.writerow(['#', 'Student Name', 'Questions Answered', 'Correct', 'Accuracy (%)', 'Final Emotion'])
    total_ans = total_correct = 0
    for i, s in enumerate(students, 1):
        ans     = int(s.get('total_answers') or 0)
        correct = int(s.get('correct_answers') or 0)
        acc     = float(s.get('accuracy') or 0)
        total_ans += ans; total_correct += correct
        w.writerow([i, s.get('name', ''), ans, correct, acc,
                    s.get('final_emotion', '') or '—'])

    # Totals row
    w.writerow([])
    w.writerow(['', 'TOTAL / AVERAGE', total_ans, total_correct,
                round(total_correct / total_ans * 100, 1) if total_ans else 0, ''])

    safe_sname = ''.join(c for c in sess.get('session_name', str(session_id)) if c.isalnum() or c in ' _-').strip().replace(' ', '_')
    date_part  = sess['started_at'].strftime('%Y-%m-%d') if sess.get('started_at') else export_date
    filename   = f"session_{safe_sname}_{date_part}.csv"
    return Response(out.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})

# ============================================================
# STUDENT ROUTES
# ============================================================
@app.route('/student/history')
def student_history():
    if session.get('role') != 'student':
        return redirect(url_for('index'))
    history = db.get_student_session_history(session['user_id'])
    return render_template('student_history.html',
                           name=session['user_name'],
                           history=history)

@app.route('/student/select-class')
def select_class():
    if session.get('role') != 'student':
        return redirect(url_for('index'))
    return render_template('select_class.html', name=session['user_name'])

@app.route('/student/join-class', methods=['POST'])
def join_class():
    if session.get('role') != 'student':
        return redirect(url_for('index'))
    class_code = request.form.get('class_code','').strip().upper()
    cls = db.get_class_by_code(class_code)
    if not cls:
        return render_template('select_class.html', name=session['user_name'], error='Class code not found.')
    db.enroll_student(cls['id'], session['user_id'])
    session['class_id']   = cls['id']
    session['class_code'] = cls['class_code']
    session['class_name'] = cls['class_name']
    return redirect(url_for('student_page'))

@app.route('/student')
def student_page():
    if session.get('role') != 'student':
        return redirect(url_for('index'))
    class_id = session.get('class_id')
    if not class_id:
        return redirect(url_for('select_class'))
    active_session = db.get_active_session(class_id)
    if not active_session:
        return render_template('waiting.html', name=session['user_name'],
                               class_name=session.get('class_name'),
                               class_id=class_id)
    difficulty_map = db.get_group_difficulty(active_session['id'])
    latest_emotion = db.get_student_latest_emotion(active_session['id'], session['user_id'])
    student_emotion = latest_emotion if latest_emotion in ('Happy', 'Engaged', 'Confused', 'Frustrated') else 'Engaged'
    initial_diff = difficulty_map.get(student_emotion, 'medium')
    questions = db.get_questions_by_difficulty(initial_diff)
    return render_template('student.html', name=session['user_name'],
                           session_username=session['username'],
                           session_id=active_session['id'],
                           class_name=session.get('class_name'),
                           questions=questions, difficulty=initial_diff,
                           student_id=session['user_id'])

# ============================================================
# API ENDPOINTS
# ============================================================
@app.route('/api/detect-emotion', methods=['POST'])
@csrf.exempt
def detect_emotion():
    data         = request.get_json()
    image_data   = data.get('image')
    student_id   = data.get('student_id')
    session_id   = data.get('session_id')
    if not all([image_data, student_id, session_id]):
        return jsonify({'error': 'Missing data'}), 400

    result = detect_emotion_from_base64(image_data)
    if result:
        raw_emotion = result.get('dominant')
        emotions = result.get('emotions', {}) or {}

        category_from_raw = map_emotion(raw_emotion)
        category_from_scores, group_scores = map_emotion_from_scores(emotions)
        category = category_from_scores

        if category_from_raw == 'Happy' and group_scores.get('Happy', 0.0) >= 0.40:
            category = 'Happy'

        try:
            db.save_emotion_log(session_id, student_id, raw_emotion,
                                category, result['confidence'])
        except Exception:
            return jsonify({'success': False, 'message': 'session_invalid'})
        socketio.emit('emotion_update', {
            'session_id': session_id, 'student_id': student_id,
            'category': category, 'emotion': raw_emotion
        }, room=f"session_{session_id}")
        return jsonify({
            'success': True,
            'emotion': raw_emotion,
            'category': category,
            'raw_emotion': raw_emotion,
            'group_scores': group_scores
        })
    return jsonify({'success': False, 'message': 'No face detected'})

@app.route('/api/submit-answer', methods=['POST'])
@csrf.exempt
def submit_answer():
    data       = request.get_json()
    session_id = data['session_id']
    student_id = data['student_id']
    db.save_answer(session_id, student_id,
                   data['question_id'], data['selected'], data['is_correct'])
    stats = db.get_student_stats(session_id)
    stat  = stats.get(student_id, {})
    socketio.emit('student_progress', {
        'student_id':   student_id,
        'student_name': stat.get('student_name', ''),
        'total':        int(stat.get('total', 0) or 0),
        'correct':      int(stat.get('correct', 0) or 0),
        'accuracy':     float(stat.get('accuracy', 0) or 0)
    }, room=f"session_{session_id}")


    leaderboard = db.get_session_leaderboard(session_id)
    socketio.emit('leaderboard_update', {'rankings': leaderboard}, room=f"session_{session_id}")

    return jsonify({'success': True})

@app.route('/api/session-leaderboard/<int:session_id>')
def session_leaderboard_api(session_id):
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify({'rankings': db.get_session_leaderboard(session_id)})

@app.route('/api/student-finished', methods=['POST'])
@csrf.exempt
def student_finished():
    data       = request.get_json()
    session_id = data.get('session_id')
    student_id = data.get('student_id')
    if not session_id or not student_id:
        return jsonify({'success': False, 'message': 'session_id and student_id required'}), 400

    # Track per-round completion in memory (resets each time teacher starts a new round)
    done_set = _round_done.setdefault(session_id, set())
    done_set.add(student_id)

    # Gunakan jumlah siswa terdaftar di kelas sebagai acuan utama
    total = db.count_students_in_session_class(session_id)
    if total == 0:
        # Fallback ke connected jika kelas belum ada data
        total = sum(
            1 for info in _socket_sessions.values()
            if info.get('role') == 'student' and info.get('session_id') == session_id
        )
    if total > 0 and len(done_set) >= total:
        adj_summary = _run_auto_adjust(session_id)
        socketio.emit('all_students_done', {
            'finished': len(done_set),
            'total':    int(total),
            'adj_summary': adj_summary
        }, room=f"session_{session_id}")
        teacher_id = db.get_teacher_id_by_session(session_id)
        if teacher_id:
            _send_push_to_teacher(
                teacher_id,
                title='Semua Siswa Selesai',
                body=f'Semua {int(total)} siswa telah menyelesaikan ronde ini.',
                url=f'/teacher'
            )

    return jsonify({'success': True, 'finished_count': len(done_set), 'total_students': int(total)})

@app.route('/api/emotion-summary/<int:session_id>')
def emotion_summary(session_id):
    emotions  = db.get_latest_emotions(session_id)
    stats     = db.get_student_stats(session_id)
    group_diff = db.get_group_difficulty(session_id)

    groups = {}
    for e in emotions:
        cat = e['emotion_category'] or 'Engaged'
        if cat not in groups:
            groups[cat] = []
        st = stats.get(e['student_id'], {'total':0,'correct':0,'accuracy':0})
        groups[cat].append({'name': e['student_name'], 'student_id': e['student_id'],
                            'total': st.get('total',0), 'correct': st.get('correct',0) or 0,
                            'accuracy': st.get('accuracy',0) or 0})

    total = len(emotions)
    summary = {}
    from db import get_questions_by_difficulty
    group_questions = {}
    for cat in ['Happy','Engaged','Confused','Frustrated']:
        count = len(groups.get(cat,[]))
        diff = group_diff.get(cat,'medium')
        summary[cat] = {'count': count, 'percentage': round(count/total*100) if total>0 else 0, 'difficulty': diff}
        group_questions[cat] = get_questions_by_difficulty(diff)

    return jsonify({'groups': groups, 'summary': summary,
                    'total': total, 'group_questions': group_questions})

@app.route('/api/change-group-difficulty', methods=['POST'])
@csrf.exempt
def change_group_difficulty():
    data = request.get_json()
    db.update_group_difficulty(data['session_id'], data['category'], data['difficulty'])
    socketio.emit('difficulty_changed', {'category': data['category'],
                  'difficulty': data['difficulty']}, room=f"session_{data['session_id']}")
    return jsonify({'success': True})

@app.route('/api/get-questions/<difficulty>')
def get_questions_api(difficulty):
    return jsonify({'questions': db.get_questions_by_difficulty(difficulty)})

_DIFF_LEVELS = ['very_easy', 'easy', 'medium', 'hard', 'very_hard']

def _step_difficulty(current, delta):
    idx = _DIFF_LEVELS.index(current) if current in _DIFF_LEVELS else 2
    return _DIFF_LEVELS[max(0, min(4, idx + delta))]

_EMOTION_DELTA = {
    'Happy':      +2,
    'Engaged':    +1,
    'Confused':   -1,
    'Frustrated': -2,
}

def _run_auto_adjust(session_id):
    """
    5-level adaptive flow per round berdasarkan emosi terdeteksi:
      Happy      +2  →  medium → hard → very_hard (2 round)
      Engaged    +1  →  medium → hard → very_hard (3 round)
      Confused   -1  →  medium → easy → very_easy (3 round)
      Frustrated -2  →  medium → easy → very_easy (2 round)
    Grup kosong tidak diubah. Fallback tanpa deteksi: semua +1.
    """
    latest   = db.get_latest_emotions(session_id)
    curr_map = db.get_group_difficulty(session_id)

    counts = {'Happy': 0, 'Engaged': 0, 'Confused': 0, 'Frustrated': 0}
    for r in (latest or []):
        cat = r.get('emotion_category') or 'Engaged'
        if cat in counts:
            counts[cat] += 1

    no_data = sum(counts.values()) == 0
    updates = []

    for cat in ['Happy', 'Engaged', 'Confused', 'Frustrated']:
        cur = curr_map.get(cat, 'medium')
        if no_data:
            delta = +1
        elif counts[cat] == 0:
            updates.append({'category': cat, 'difficulty': cur, 'prev': cur})
            continue
        else:
            delta = _EMOTION_DELTA[cat]

        new_diff = _step_difficulty(cur, delta)
        db.update_group_difficulty(session_id, cat, new_diff)
        updates.append({'category': cat, 'difficulty': new_diff, 'prev': cur})

    return updates

def _send_push_to_teacher(teacher_id, title, body, url='/teacher'):
    subs = db.get_push_subscriptions_by_user(teacher_id)
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub['endpoint'],
                    'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}
                },
                data=json.dumps({'title': title, 'body': body, 'url': url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException:
            pass

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js',
                               mimetype='application/javascript')

@app.route('/api/vapid-public-key')
def vapid_public_key():
    return jsonify({'public_key': VAPID_PUBLIC_KEY})

@app.route('/api/push-subscribe', methods=['POST'])
@csrf.exempt
def push_subscribe():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    db.save_push_subscription(
        session['user_id'],
        data['endpoint'],
        data['keys']['p256dh'],
        data['keys']['auth']
    )
    return jsonify({'success': True})

@app.route('/api/start-round', methods=['POST'])
@csrf.exempt
def start_round():
    """Teacher triggers next round: broadcast current difficulty settings to all students."""
    data = request.get_json()
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': 'session_id required'}), 400
    # Reset round tracker so the next round's completions are counted fresh
    _round_done[session_id] = set()
    group_diff = db.get_group_difficulty(session_id)
    updates = [{'category': cat, 'difficulty': diff} for cat, diff in group_diff.items()]
    socketio.emit('difficulty_changed', {
        'session_id': session_id,
        'updates': updates
    }, room=f"session_{session_id}")
    return jsonify({'success': True, 'updates': updates})

@app.route('/api/auto-adjust-difficulty', methods=['POST'])
@csrf.exempt
def auto_adjust_difficulty():
    data = request.get_json()
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': 'session_id required'}), 400
    updates = _run_auto_adjust(session_id)
    if not updates:
        return jsonify({'success': False, 'message': 'No emotion data for this session yet'}), 400
    socketio.emit('difficulty_changed', {
        'session_id': session_id,
        'updates': updates
    }, room=f"session_{session_id}")
    return jsonify({'success': True, 'updates': updates})

# ============================================================
# SOCKETIO
# ============================================================
_socket_sessions = {}   
_round_done      = {}   

@socketio.on('join_session')
def handle_join(data):
    sid        = request.sid
    session_id = data.get('session_id')
    role       = data.get('role', 'student')
    name       = data.get('name', '')
    room       = f"session_{session_id}"
    join_room(room)
    _socket_sessions[sid] = {'session_id': session_id, 'name': name, 'role': role}
    emit('user_joined', {'name': name, 'role': role}, room=room)

@socketio.on('student_frame')
def handle_student_frame(data):
    session_id = data.get('session_id')
    if session_id:
        emit('student_frame', data, room=f"session_{session_id}", include_self=False)

@socketio.on('disconnect')
def handle_disconnect():
    info = _socket_sessions.pop(request.sid, None)
    if info and info.get('role') == 'student':
        socketio.emit('student_left', {'name': info['name']},
                      room=f"session_{info['session_id']}")

@socketio.on('join_class')
def handle_join_class(data):
    join_room(f"class_{data.get('class_id')}")

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
