-- ============================================================
-- EMOTION LEARNING APP - DATABASE SCHEMA
-- ============================================================

CREATE DATABASE IF NOT EXISTS emotion_learning CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE emotion_learning;

-- USERS (guru & siswa)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('teacher', 'student') NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CLASSES (dibuat oleh guru)
CREATE TABLE IF NOT EXISTS classes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    teacher_id INT NOT NULL,
    class_name VARCHAR(100) NOT NULL,
    class_code VARCHAR(10) NOT NULL UNIQUE,
    active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ENROLLMENTS (siswa join ke kelas)
CREATE TABLE IF NOT EXISTS enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    class_id INT NOT NULL,
    student_id INT NOT NULL,
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_enrollment (class_id, student_id),
    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

-- SESSIONS (sesi belajar dalam kelas)
CREATE TABLE IF NOT EXISTS sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    class_id INT NOT NULL,
    session_name VARCHAR(100),
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME NULL,
    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
);

-- QUESTIONS (bank soal)
CREATE TABLE IF NOT EXISTS questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    difficulty ENUM('very_easy', 'easy', 'medium', 'hard', 'very_hard') NOT NULL,
    question_text TEXT NOT NULL,
    option_a VARCHAR(255) NOT NULL,
    option_b VARCHAR(255) NOT NULL,
    option_c VARCHAR(255) NOT NULL,
    option_d VARCHAR(255) NOT NULL,
    correct_answer CHAR(1) NOT NULL,
    topic VARCHAR(100),
    video_url VARCHAR(500) DEFAULT NULL,
    video_type ENUM('youtube', 'upload') DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- EMOTION LOGS (log deteksi emosi siswa)
CREATE TABLE IF NOT EXISTS emotion_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    student_id INT NOT NULL,
    emotion_raw VARCHAR(50),
    emotion_category ENUM('Happy', 'Engaged', 'Confused', 'Frustrated'),
    confidence FLOAT,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ANSWER LOGS (log jawaban siswa)
CREATE TABLE IF NOT EXISTS answer_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    student_id INT NOT NULL,
    question_id INT NOT NULL,
    selected_answer CHAR(1),
    is_correct TINYINT(1),
    answered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

-- GROUP DIFFICULTY SETTINGS (pengaturan difficulty per emosi per sesi)
CREATE TABLE IF NOT EXISTS group_difficulty (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    emotion_category ENUM('Happy', 'Engaged', 'Confused', 'Frustrated'),
    difficulty ENUM('very_easy', 'easy', 'medium', 'hard', 'very_hard') DEFAULT 'medium',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_group (session_id, emotion_category),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- ============================================================
-- INDEXES (composite — FK indexes already created by InnoDB)
-- ============================================================

-- Fastest path for get_student_latest_emotion: WHERE session+student ORDER BY detected_at
CREATE INDEX IF NOT EXISTS idx_emotion_session_student_time
    ON emotion_logs (session_id, student_id, detected_at);

-- Fastest path for get_session_leaderboard: WHERE session GROUP BY student, MAX(answered_at)
CREATE INDEX IF NOT EXISTS idx_answer_session_student_time
    ON answer_logs (session_id, student_id, answered_at);

-- Fastest path for active-session subquery: WHERE class_id AND ended_at IS NULL
CREATE INDEX IF NOT EXISTS idx_session_class_ended
    ON sessions (class_id, ended_at);

-- ============================================================
-- SEED DATA
-- ============================================================

-- Default users (password: 'password123' - di production hash dulu)
INSERT IGNORE INTO users (name, username, password, role) VALUES
('Bu Sari', 'guru1', 'password123', 'teacher'),
('Pak Budi', 'guru2', 'password123', 'teacher'),
('Fikri', 'siswa1', 'password123', 'student'),
('Faqih', 'siswa2', 'password123', 'student'),
('Ramdhan', 'siswa3', 'password123', 'student'),
('Iqbal', 'siswa4', 'password123', 'student'),
('Melinda', 'siswa5', 'password123', 'student'),
('Fadhilla', 'siswa6', 'password123', 'student'),
('Krisnata', 'siswa7', 'password123', 'student'),
('Azriel', 'siswa9', 'password123', 'student');

-- Default questions
INSERT IGNORE INTO questions (difficulty, question_text, option_a, option_b, option_c, option_d, correct_answer, topic) VALUES
-- Very Easy
('very_easy', 'What is 2 + 2?', '3', '4', '5', '6', 'B', 'Addition'),
('very_easy', 'What is 5 + 3?', '7', '8', '9', '10', 'B', 'Addition'),
('very_easy', 'What is 3 + 5?', '6', '7', '8', '9', 'C', 'Addition'),
-- Easy
('easy', 'What is 5 + 3?', '6', '7', '8', '9', 'C', 'Addition'),
('easy', 'What is 10 - 4?', '5', '6', '7', '8', 'B', 'Subtraction'),
('easy', 'How many sides does a triangle have?', '2', '3', '4', '5', 'B', 'Shapes'),
-- Medium
('medium', 'What is 7 x 3?', '18', '21', '24', '27', 'B', 'Multiplication'),
('medium', 'What is half of 16?', '6', '7', '8', '9', 'C', 'Division'),
('medium', 'What is 25 + 17?', '32', '42', '52', '62', 'B', 'Addition'),
-- Hard
('hard', 'What is 15 x 4?', '50', '55', '60', '65', 'C', 'Multiplication'),
('hard', 'What is 144 / 12?', '10', '11', '12', '13', 'C', 'Division'),
('hard', 'If a book costs $8 and you buy 6, how much?', '42', '46', '48', '54', 'C', 'Multiplication'),
-- Very Hard
('very_hard', 'What is the square root of 196?', '12', '13', '14', '15', 'C', 'Square Root'),
('very_hard', 'What is 17 x 13?', '201', '211', '221', '231', 'C', 'Multiplication'),
('very_hard', 'If a train travels 240 km in 3 hours, what is its speed in km/h?', '60', '70', '80', '90', 'C', 'Speed'),
('very_hard', 'What is 15% of 320?', '42', '46', '48', '52', 'C', 'Percentage'),
('very_hard', 'What is 2 to the power of 8?', '128', '256', '512', '1024', 'B', 'Exponent'),
('very_hard', 'A rectangle has area 108 cm² and width 9 cm. What is its length?', '10', '11', '12', '13', 'C', 'Geometry');
