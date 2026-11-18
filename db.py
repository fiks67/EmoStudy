import pymysql
import pymysql.cursors
from contextlib import contextmanager
from dbutils.pooled_db import PooledDB

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'emotion_learning',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': True
}

# Connection pool — reuses connections instead of open/close per request
_pool = PooledDB(
    creator=pymysql,
    maxconnections=20,  # max concurrent connections
    mincached=0,        # min idle connections kept ready
    maxcached=10,       # max idle connections in pool
    blocking=True,      # wait if pool is full (no error thrown)
    ping=1,             # verify connection before use
    **DB_CONFIG
)

def get_connection():
    return _pool.connection()

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()    # returns to pool, not actually closed

def apply_indexes():
    """Create composite indexes and run safe schema migrations on every startup."""
    indexes = [
        ("idx_emotion_session_student_time", "emotion_logs",
         "(session_id, student_id, detected_at)"),
        ("idx_answer_session_student_time",  "answer_logs",
         "(session_id, student_id, answered_at)"),
        ("idx_session_class_ended",          "sessions",
         "(class_id, ended_at)"),
    ]
    with get_db() as conn:
        with conn.cursor() as cur:
            for idx_name, table, cols in indexes:
                cur.execute(f"""
                    SELECT COUNT(*) AS n FROM information_schema.statistics
                    WHERE table_schema = DATABASE()
                      AND table_name   = '{table}'
                      AND index_name   = '{idx_name}'
                """)
                if (cur.fetchone() or {}).get('n', 0) == 0:
                    cur.execute(f"CREATE INDEX {idx_name} ON {table} {cols}")

            # Create push_subscriptions table if not exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_id    INT NOT NULL,
                    endpoint   TEXT NOT NULL,
                    p256dh     VARCHAR(255) NOT NULL,
                    auth       VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT NOW(),
                    UNIQUE KEY uq_user_endpoint (user_id, p256dh(64))
                )
            """)

            # Add multilingual + essay columns to questions if not present
            cur.execute("""
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'questions'
            """)
            existing_cols = {r['COLUMN_NAME'] for r in cur.fetchall()}

            # essay support: question_type column
            if 'question_type' not in existing_cols:
                cur.execute("""
                    ALTER TABLE questions
                    ADD COLUMN question_type ENUM('multiple_choice','essay')
                    NOT NULL DEFAULT 'multiple_choice'
                """)

            # essay support: allow long essay text in answer_logs.selected_answer
            cur.execute("""
                SELECT DATA_TYPE FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'answer_logs' AND COLUMN_NAME = 'selected_answer'
            """)
            al_type = (cur.fetchone() or {}).get('DATA_TYPE', '')
            if al_type.lower() != 'text':
                cur.execute("ALTER TABLE answer_logs MODIFY COLUMN selected_answer TEXT")
            lang_cols = [
                ('question_text_en', 'TEXT'),
                ('question_text_my', 'TEXT'),
                ('option_a_en', 'VARCHAR(500)'),
                ('option_b_en', 'VARCHAR(500)'),
                ('option_c_en', 'VARCHAR(500)'),
                ('option_d_en', 'VARCHAR(500)'),
                ('option_a_my', 'VARCHAR(500)'),
                ('option_b_my', 'VARCHAR(500)'),
                ('option_c_my', 'VARCHAR(500)'),
                ('option_d_my', 'VARCHAR(500)'),
                ('topic_en', 'VARCHAR(255)'),
                ('topic_my', 'VARCHAR(255)'),
                ('essay_answer', 'TEXT'),
            ]
            for col, col_def in lang_cols:
                if col not in existing_cols:
                    cur.execute(f"ALTER TABLE questions ADD COLUMN {col} {col_def}")

            # Add very_hard to ENUM if not present yet
            cur.execute("""
                SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'questions' AND COLUMN_NAME = 'difficulty'
            """)
            col_type = (cur.fetchone() or {}).get('COLUMN_TYPE', '')
            if 'very_hard' not in col_type:
                cur.execute("""
                    ALTER TABLE questions
                    MODIFY COLUMN difficulty
                    ENUM('very_easy','easy','medium','hard','very_hard') NOT NULL
                """)
                cur.execute("""
                    ALTER TABLE group_difficulty
                    MODIFY COLUMN difficulty
                    ENUM('very_easy','easy','medium','hard','very_hard') DEFAULT 'medium'
                """)

# ============================================================
# USERS
# ============================================================
def get_user_by_username(username):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cur.fetchone()

def create_user(name, username, password, role):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (name, username, password, role) VALUES (%s,%s,%s,%s)",
                        (name, username, password, role))
            return cur.lastrowid

def get_user_by_id(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()

def update_user(user_id, name, username, password=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            if password:
                cur.execute("UPDATE users SET name=%s, username=%s, password=%s WHERE id=%s",
                            (name, username, password, user_id))
            else:
                cur.execute("UPDATE users SET name=%s, username=%s WHERE id=%s",
                            (name, username, user_id))

# ============================================================
# CLASSES
# ============================================================
def get_class_by_id(class_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, u.name as teacher_name
                FROM classes c JOIN users u ON c.teacher_id = u.id
                WHERE c.id = %s
            """, (class_id,))
            return cur.fetchone()

def get_class_by_code(class_code):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, u.name as teacher_name
                FROM classes c JOIN users u ON c.teacher_id = u.id
                WHERE c.class_code = %s AND c.active = 1
            """, (class_code,))
            return cur.fetchone()

def get_classes_by_teacher(teacher_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, COUNT(e.student_id) as student_count,
                       (SELECT COUNT(*) FROM sessions s
                        WHERE s.class_id = c.id AND s.ended_at IS NULL) as has_active_session,
                       (SELECT s.session_name FROM sessions s
                        WHERE s.class_id = c.id AND s.ended_at IS NULL LIMIT 1) as active_session_name
                FROM classes c
                LEFT JOIN enrollments e ON c.id = e.class_id
                WHERE c.teacher_id = %s
                GROUP BY c.id
                ORDER BY c.created_at DESC
            """, (teacher_id,))
            return cur.fetchall()

def create_class(teacher_id, class_name, class_code):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO classes (teacher_id, class_name, class_code) VALUES (%s,%s,%s)",
                        (teacher_id, class_name, class_code))
            return cur.lastrowid

def delete_class_by_teacher(class_id, teacher_id):
    """Hapus kelas milik guru beserta data terkait (sessions, logs, enrollments)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM classes WHERE id = %s AND teacher_id = %s", (class_id, teacher_id))
            cls = cur.fetchone()
            if not cls:
                return False

            cur.execute("SELECT id FROM sessions WHERE class_id = %s", (class_id,))
            session_rows = cur.fetchall()
            session_ids = [s['id'] for s in session_rows]

            if session_ids:
                placeholders = ",".join(["%s"] * len(session_ids))
                cur.execute(f"DELETE FROM answer_logs WHERE session_id IN ({placeholders})", tuple(session_ids))
                cur.execute(f"DELETE FROM emotion_logs WHERE session_id IN ({placeholders})", tuple(session_ids))
                cur.execute(f"DELETE FROM group_difficulty WHERE session_id IN ({placeholders})", tuple(session_ids))
                cur.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", tuple(session_ids))

            cur.execute("DELETE FROM enrollments WHERE class_id = %s", (class_id,))
            cur.execute("DELETE FROM classes WHERE id = %s AND teacher_id = %s", (class_id, teacher_id))
            return True

# ============================================================
# ENROLLMENTS
# ============================================================
def enroll_student(class_id, student_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT IGNORE INTO enrollments (class_id, student_id) VALUES (%s,%s)
            """, (class_id, student_id))

def get_students_in_class(class_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.name, u.username, e.joined_at
                FROM enrollments e JOIN users u ON e.student_id = u.id
                WHERE e.class_id = %s ORDER BY u.name
            """, (class_id,))
            return cur.fetchall()

def get_unenrolled_students(class_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.name, u.username
                FROM users u
                WHERE u.role = 'student'
                  AND u.created_at IS NOT NULL
                  AND u.id NOT IN (
                    SELECT e.student_id FROM enrollments e WHERE e.class_id = %s
                  )
                ORDER BY u.name
            """, (class_id,))
            return cur.fetchall()

def remove_student_from_class(class_id, student_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM enrollments
                WHERE class_id = %s AND student_id = %s
            """, (class_id, student_id))
            return cur.rowcount > 0

# ============================================================
# SESSIONS
# ============================================================
def create_session(class_id, session_name):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sessions (class_id, session_name) VALUES (%s,%s)",
                        (class_id, session_name))
            session_id = cur.lastrowid
            # Round 1: all start at medium. After round 1 done, auto-adjust sets emotion-based difficulty.
            for cat in ['Happy', 'Engaged', 'Confused', 'Frustrated']:
                cur.execute("INSERT IGNORE INTO group_difficulty (session_id, emotion_category, difficulty) VALUES (%s,%s,'medium')",
                            (session_id, cat))
            return session_id

def get_active_session(class_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM sessions WHERE class_id = %s AND ended_at IS NULL
                ORDER BY started_at DESC LIMIT 1
            """, (class_id,))
            return cur.fetchone()

def end_session(session_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET ended_at = NOW() WHERE id = %s", (session_id,))

def end_all_active_sessions_by_teacher(teacher_id):
    """End semua sesi aktif milik guru saat logout."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sessions s
                JOIN classes c ON s.class_id = c.id
                SET s.ended_at = NOW()
                WHERE c.teacher_id = %s AND s.ended_at IS NULL
            """, (teacher_id,))

def delete_session_by_class(session_id, class_id):
    """Hapus satu sesi jika benar milik class terkait."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sessions WHERE id = %s AND class_id = %s", (session_id, class_id))
            s = cur.fetchone()
            if not s:
                return False

            cur.execute("DELETE FROM answer_logs WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM emotion_logs WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM group_difficulty WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM sessions WHERE id = %s AND class_id = %s", (session_id, class_id))
            return True

# ============================================================
# QUESTIONS
# ============================================================
def get_questions_by_difficulty(difficulty):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM questions WHERE difficulty = %s LIMIT 10", (difficulty,))
            rows = cur.fetchall()
            result = []
            for r in rows:
                def fb(col, base, _r=r):
                    return _r.get(col) or _r.get(base) or ''
                result.append({
                    'id': r['id'],
                    'difficulty': r['difficulty'],
                    'question_type': r.get('question_type') or 'multiple_choice',
                    'correct_letter': r.get('correct_answer') or '',
                    'essay_answer': r.get('essay_answer') or '',
                    'video_url': r.get('video_url') or None,
                    'video_type': r.get('video_type') or None,
                    'texts': {
                        'id': r['question_text'] or '',
                        'en': fb('question_text_en', 'question_text'),
                        'my': fb('question_text_my', 'question_text'),
                    },
                    'topics': {
                        'id': r['topic'] or '',
                        'en': fb('topic_en', 'topic'),
                        'my': fb('topic_my', 'topic'),
                    },
                    'opts': {
                        'id': [r['option_a'], r['option_b'], r['option_c'], r['option_d']],
                        'en': [fb('option_a_en','option_a'), fb('option_b_en','option_b'),
                               fb('option_c_en','option_c'), fb('option_d_en','option_d')],
                        'my': [fb('option_a_my','option_a'), fb('option_b_my','option_b'),
                               fb('option_c_my','option_c'), fb('option_d_my','option_d')],
                    },
                })
            return result

# ============================================================
# GROUP DIFFICULTY
# ============================================================
def get_group_difficulty(session_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT emotion_category, difficulty FROM group_difficulty WHERE session_id = %s", (session_id,))
            rows = cur.fetchall()
            return {r['emotion_category']: r['difficulty'] for r in rows}

def update_group_difficulty(session_id, category, difficulty):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO group_difficulty (session_id, emotion_category, difficulty)
                VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE difficulty=%s, updated_at=NOW()
            """, (session_id, category, difficulty, difficulty))

# ============================================================
# EMOTION LOGS
# ============================================================
def save_emotion_log(session_id, student_id, emotion_raw, category, confidence):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO emotion_logs (session_id, student_id, emotion_raw, emotion_category, confidence)
                VALUES (%s,%s,%s,%s,%s)
            """, (session_id, student_id, emotion_raw, category, confidence))

def get_student_latest_emotion(session_id, student_id):
    """Return the most recent emotion_category for one student in a session, or None."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT emotion_category FROM emotion_logs
                WHERE session_id = %s AND student_id = %s
                ORDER BY detected_at DESC LIMIT 1
            """, (session_id, student_id))
            row = cur.fetchone()
            return row['emotion_category'] if row else None

def get_latest_emotions(session_id):
    """Ambil emosi terbaru per siswa dalam sesi ini"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT el.student_id, u.name as student_name,
                       el.emotion_raw, el.emotion_category, el.confidence, el.detected_at
                FROM emotion_logs el
                JOIN users u ON el.student_id = u.id
                WHERE el.session_id = %s
                AND el.detected_at = (
                    SELECT MAX(el2.detected_at) FROM emotion_logs el2
                    WHERE el2.session_id = %s AND el2.student_id = el.student_id
                )
            """, (session_id, session_id))
            return cur.fetchall()

# ============================================================
# ANSWER LOGS
# ============================================================
def save_answer(session_id, student_id, question_id, selected, is_correct):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO answer_logs (session_id, student_id, question_id, selected_answer, is_correct)
                VALUES (%s,%s,%s,%s,%s)
            """, (session_id, student_id, question_id, selected, is_correct))

def count_students_finished_session(session_id):
    """Hitung berapa siswa yang sudah menjawab minimal 1 soal pada sesi."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT student_id) AS n
                FROM answer_logs
                WHERE session_id = %s
            """, (session_id,))
            row = cur.fetchone()
            return (row or {}).get('n', 0) or 0

def count_students_in_session_class(session_id):
    """Hitung total siswa terdaftar pada kelas dari sesi."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT e.student_id) AS n
                FROM sessions s
                JOIN enrollments e ON e.class_id = s.class_id
                WHERE s.id = %s
            """, (session_id,))
            row = cur.fetchone()
            return (row or {}).get('n', 0) or 0

def get_student_stats(session_id):
    """Hitung total jawaban & akurasi per siswa"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT al.student_id, u.name as student_name,
                       COUNT(*) as total,
                       COALESCE(SUM(al.is_correct),0) as correct,
                       ROUND(COALESCE(SUM(al.is_correct),0)/NULLIF(COUNT(al.is_correct),0)*100) as accuracy
                FROM answer_logs al JOIN users u ON al.student_id = u.id
                WHERE al.session_id = %s
                GROUP BY al.student_id, u.name
            """, (session_id,))
            return {r['student_id']: r for r in cur.fetchall()}

def get_session_leaderboard(session_id):
    """Ranking siswa: accuracy DESC, tiebreaker finished_at ASC (selesai duluan rank lebih tinggi)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT al.student_id, u.name as student_name,
                       COUNT(*) as total,
                       COALESCE(SUM(al.is_correct),0) as correct,
                       ROUND(COALESCE(SUM(al.is_correct),0)/NULLIF(COUNT(al.is_correct),0)*100) as accuracy,
                       MAX(al.answered_at) as finished_at
                FROM answer_logs al JOIN users u ON al.student_id = u.id
                WHERE al.session_id = %s
                GROUP BY al.student_id, u.name
                ORDER BY accuracy DESC, finished_at ASC
            """, (session_id,))
            rows = cur.fetchall()
            result = []
            for r in rows:
                result.append({
                    'student_id':   int(r['student_id']),
                    'student_name': r['student_name'],
                    'total':        int(r['total'] or 0),
                    'correct':      int(r['correct'] or 0),
                    'accuracy':     int(r['accuracy'] or 0),
                })
            return result

# ============================================================
# REPORTS
# ============================================================
def get_session_report(session_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            # Info sesi
            cur.execute("""
                SELECT s.*, c.class_name, c.class_code, u.name as teacher_name
                FROM sessions s JOIN classes c ON s.class_id = c.id
                JOIN users u ON c.teacher_id = u.id WHERE s.id = %s
            """, (session_id,))
            session_info = cur.fetchone()

            # Emotion summary (REAL-TIME SNAPSHOT):
            # hitung 1 siswa = 1 emosi terbaru pada sesi ini.
            cur.execute("""
                SELECT latest.emotion_category, COUNT(*) as count
                FROM (
                    SELECT el.student_id, el.emotion_category
                    FROM emotion_logs el
                    WHERE el.session_id = %s
                      AND el.detected_at = (
                          SELECT MAX(el2.detected_at)
                          FROM emotion_logs el2
                          WHERE el2.session_id = %s
                            AND el2.student_id = el.student_id
                      )
                ) latest
                GROUP BY latest.emotion_category
            """, (session_id, session_id))
            emotion_summary = {r['emotion_category']: r['count'] for r in cur.fetchall()}

            # Per student detail
            cur.execute("""
                SELECT u.id, u.name,
                       COUNT(DISTINCT al.id) as total_answers,
                       COALESCE(SUM(al.is_correct),0) as correct_answers,
                       ROUND(COALESCE(SUM(al.is_correct),0)/NULLIF(COUNT(al.is_correct),0)*100,1) as accuracy,
                       (SELECT el2.emotion_category FROM emotion_logs el2
                        WHERE el2.student_id = u.id AND el2.session_id = %s
                        ORDER BY el2.detected_at DESC LIMIT 1) as final_emotion
                FROM users u
                JOIN enrollments e ON e.student_id = u.id
                JOIN sessions s ON s.id = %s
                LEFT JOIN answer_logs al ON al.student_id = u.id AND al.session_id = %s
                WHERE e.class_id = s.class_id
                GROUP BY u.id, u.name ORDER BY accuracy DESC
            """, (session_id, session_id, session_id))
            students = cur.fetchall()

            # Emotion timeline (per 5 menit)
            cur.execute("""
                SELECT emotion_category,
                       DATE_FORMAT(detected_at, '%%H:%%i') as time_slot,
                       COUNT(*) as count
                FROM emotion_logs WHERE session_id = %s
                GROUP BY emotion_category, time_slot ORDER BY time_slot
            """, (session_id,))
            timeline = cur.fetchall()

            return {'session': session_info, 'emotion_summary': emotion_summary,
                    'students': students, 'timeline': timeline}

def get_all_sessions_report(class_id):
    """Ringkasan semua sesi dalam satu kelas"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.id, s.session_name, s.started_at, s.ended_at,
                       COUNT(DISTINCT al.student_id) as active_students,
                       COUNT(al.id) as total_answers,
                       ROUND(COALESCE(SUM(al.is_correct),0)/NULLIF(COUNT(al.is_correct),0)*100,1) as avg_accuracy
                FROM sessions s
                LEFT JOIN answer_logs al ON al.session_id = s.id
                WHERE s.class_id = %s GROUP BY s.id ORDER BY s.started_at DESC
            """, (class_id,))
            return cur.fetchall()

def get_latest_emotions_by_class(class_id):
    """Ambil emosi terbaru setiap siswa untuk kelas tertentu."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id AS student_id,
                       u.name,
                       u.username,
                       el.emotion_raw,
                       el.emotion_category,
                       el.confidence,
                       el.detected_at
                FROM enrollments e
                JOIN users u ON u.id = e.student_id
                LEFT JOIN emotion_logs el ON el.id = (
                    SELECT el2.id
                    FROM emotion_logs el2
                    JOIN sessions s2 ON s2.id = el2.session_id
                    WHERE s2.class_id = e.class_id
                      AND el2.student_id = e.student_id
                    ORDER BY el2.detected_at DESC
                    LIMIT 1
                )
                WHERE e.class_id = %s
                ORDER BY u.name
            """, (class_id,))
            return cur.fetchall()

def list_questions(difficulty=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            if difficulty:
                cur.execute("""
                    SELECT * FROM questions
                    WHERE difficulty = %s
                    ORDER BY created_at DESC, id DESC
                """, (difficulty,))
            else:
                cur.execute("""
                    SELECT * FROM questions
                    ORDER BY created_at DESC, id DESC
                """)
            return cur.fetchall()

def create_question(difficulty, question_text, option_a, option_b, option_c, option_d, correct_answer, topic,
                    video_url=None, video_type=None, question_type='multiple_choice',
                    question_text_en=None, question_text_my=None,
                    option_a_en=None, option_b_en=None, option_c_en=None, option_d_en=None,
                    option_a_my=None, option_b_my=None, option_c_my=None, option_d_my=None,
                    topic_en=None, topic_my=None, essay_answer=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO questions (
                    difficulty, question_text, option_a, option_b, option_c, option_d,
                    correct_answer, topic, video_url, video_type, question_type,
                    question_text_en, question_text_my,
                    option_a_en, option_b_en, option_c_en, option_d_en,
                    option_a_my, option_b_my, option_c_my, option_d_my,
                    topic_en, topic_my, essay_answer
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (difficulty, question_text, option_a, option_b, option_c, option_d,
                  correct_answer, topic, video_url, video_type, question_type,
                  question_text_en or None, question_text_my or None,
                  option_a_en or None, option_b_en or None, option_c_en or None, option_d_en or None,
                  option_a_my or None, option_b_my or None, option_c_my or None, option_d_my or None,
                  topic_en or None, topic_my or None, essay_answer or None))
            return cur.lastrowid

def get_question(question_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM questions WHERE id = %s", (question_id,))
            return cur.fetchone()

def update_question(question_id, difficulty, question_text, option_a, option_b, option_c, option_d, correct_answer, topic,
                    video_url=None, video_type=None, question_type='multiple_choice',
                    question_text_en=None, question_text_my=None,
                    option_a_en=None, option_b_en=None, option_c_en=None, option_d_en=None,
                    option_a_my=None, option_b_my=None, option_c_my=None, option_d_my=None,
                    topic_en=None, topic_my=None, essay_answer=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE questions SET difficulty=%s, question_text=%s,
                  option_a=%s, option_b=%s, option_c=%s, option_d=%s,
                  correct_answer=%s, topic=%s, video_url=%s, video_type=%s, question_type=%s,
                  question_text_en=%s, question_text_my=%s,
                  option_a_en=%s, option_b_en=%s, option_c_en=%s, option_d_en=%s,
                  option_a_my=%s, option_b_my=%s, option_c_my=%s, option_d_my=%s,
                  topic_en=%s, topic_my=%s, essay_answer=%s
                WHERE id=%s
            """, (difficulty, question_text, option_a, option_b, option_c, option_d,
                  correct_answer, topic, video_url, video_type, question_type,
                  question_text_en or None, question_text_my or None,
                  option_a_en or None, option_b_en or None, option_c_en or None, option_d_en or None,
                  option_a_my or None, option_b_my or None, option_c_my or None, option_d_my or None,
                  topic_en or None, topic_my or None, essay_answer or None,
                  question_id))

def delete_question(question_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM questions WHERE id = %s", (question_id,))
            return cur.rowcount > 0

# ============================================================
# CREDENTIALS (for teacher recovery view)
# ============================================================
def get_students_credentials(class_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.name, u.username, u.password
                FROM enrollments e JOIN users u ON e.student_id = u.id
                WHERE e.class_id = %s ORDER BY u.name
            """, (class_id,))
            return cur.fetchall()

# ============================================================
# PUSH SUBSCRIPTIONS
# ============================================================
def save_push_subscription(user_id, endpoint, p256dh, auth):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
                VALUES (%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE endpoint=VALUES(endpoint), auth=VALUES(auth)
            """, (user_id, endpoint, p256dh, auth))

def get_push_subscriptions_by_user(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id=%s
            """, (user_id,))
            return cur.fetchall()

def get_teacher_id_by_session(session_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.teacher_id FROM sessions s
                JOIN classes c ON s.class_id = c.id
                WHERE s.id = %s
            """, (session_id,))
            row = cur.fetchone()
            return row['teacher_id'] if row else None

# ============================================================
# STUDENT HISTORY
# ============================================================
def get_student_session_history(student_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.id AS session_id, s.session_name, s.started_at, s.ended_at,
                       c.class_name,
                       COUNT(al.id) AS total_answers,
                       COALESCE(SUM(al.is_correct), 0) AS correct_answers,
                       ROUND(COALESCE(SUM(al.is_correct),0) / NULLIF(COUNT(al.is_correct), 0) * 100, 1) AS accuracy
                FROM answer_logs al
                JOIN sessions s ON s.id = al.session_id
                JOIN classes c ON c.id = s.class_id
                WHERE al.student_id = %s
                GROUP BY s.id, s.session_name, s.started_at, s.ended_at, c.class_name
                ORDER BY s.started_at DESC
            """, (student_id,))
            return cur.fetchall()
