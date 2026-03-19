import sqlite3
import os
from flask import g

DATABASE = os.path.join(os.path.dirname(__file__), 'classroom.db')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            google_id TEXT PRIMARY KEY,
            email     TEXT UNIQUE NOT NULL,
            name      TEXT,
            picture   TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS problems (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT NOT NULL,
            description   TEXT NOT NULL,
            template_code TEXT DEFAULT '',
            test_cases    TEXT DEFAULT '[]',
            constraints   TEXT DEFAULT '',
            time_limit    INTEGER DEFAULT 5,
            active        INTEGER DEFAULT 1,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_id   INTEGER REFERENCES problems(id),
            user_id      TEXT,
            user_email   TEXT,
            user_name    TEXT,
            code         TEXT,
            score        REAL,
            passed_cases INTEGER,
            total_cases  INTEGER,
            result_detail TEXT,
            ai_feedback  TEXT,
            submitted_at TEXT
        );
    ''')
    conn.commit()
    # 기존 DB에 ai_feedback 컬럼이 없으면 추가 (마이그레이션)
    try:
        conn.execute('ALTER TABLE submissions ADD COLUMN ai_feedback TEXT')
        conn.commit()
    except Exception:
        pass  # 이미 존재하는 경우 무시
    conn.close()
    print(f'[DB] 초기화 완료: {DATABASE}')
