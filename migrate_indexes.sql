-- Run this once on existing databases to add performance indexes.
-- Safe to re-run: uses IF NOT EXISTS / checks for duplicates.

USE emotion_learning;

-- Composite index for get_student_latest_emotion
-- Query: WHERE session_id=? AND student_id=? ORDER BY detected_at DESC LIMIT 1
CREATE INDEX IF NOT EXISTS idx_emotion_session_student_time
    ON emotion_logs (session_id, student_id, detected_at);

-- Composite index for get_session_leaderboard
-- Query: WHERE session_id=? GROUP BY student_id, MAX(answered_at)
CREATE INDEX IF NOT EXISTS idx_answer_session_student_time
    ON answer_logs (session_id, student_id, answered_at);

-- Composite index for active-session subquery in get_classes_by_teacher
-- Query: WHERE class_id=? AND ended_at IS NULL
CREATE INDEX IF NOT EXISTS idx_session_class_ended
    ON sessions (class_id, ended_at);
