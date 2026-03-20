import os
import json
import secrets
from datetime import datetime
from functools import wraps

from flask import Flask, redirect, url_for, session, request, render_template, jsonify, g
from authlib.integrations.flask_client import OAuth

from database import init_db, get_db
from grader import grade_submission, run_code, get_ai_feedback, generate_problem_with_ai

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

TEACHER_EMAILS = []

def get_teacher_emails():
    return [e.strip() for e in os.environ.get('TEACHER_EMAILS', '').split(',') if e.strip()]

# 개발 환경에서 HTTP 허용
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

# ── Google OAuth (앱 config로 동적 읽기) ──────────────────────────
app.config['GOOGLE_CLIENT_ID']     = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()

oauth = OAuth(app)
google = oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


# ── 데코레이터 ──────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            session['next'] = request.url
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('index'))
        if session['user']['email'] not in TEACHER_EMAILS:
            return render_template('error.html', message='교사 권한이 필요합니다.'), 403
        return f(*args, **kwargs)
    return decorated


@app.before_request
def before_request():
    g.db = get_db()


@app.teardown_appcontext
def teardown_db(error):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# ── 인증 라우트 ────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('home'))
    return render_template('index.html')


@app.route('/home')
@login_required
def home():
    user = session['user']
    is_teacher = user["email"] in get_teacher_emails()
    db = get_db()
    recent = db.execute('''
        SELECT s.*, p.title as problem_title
        FROM submissions s JOIN problems p ON s.problem_id = p.id
        WHERE s.user_id = ? ORDER BY s.submitted_at DESC LIMIT 10
    ''', [user['id']]).fetchall()
    return render_template('home.html', user=user, is_teacher=is_teacher,
                           recent_submissions=[dict(r) for r in recent])


@app.route('/auth/login')
def auth_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return render_template('error.html',
                               message='.env 파일에 GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 설정해주세요.')
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def auth_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo') or {}

    # userinfo 엔드포인트에서 직접 가져오기 (fallback)
    if not user_info.get('email'):
        resp = google.get('https://www.googleapis.com/oauth2/v3/userinfo',
                          token=token)
        user_info = resp.json()

    google_id = user_info.get('sub', user_info.get('id', ''))
    email     = user_info.get('email', '')
    name      = user_info.get('name', '')
    picture   = user_info.get('picture', '')

    db = get_db()
    db.execute(
        'INSERT OR REPLACE INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)',
        [google_id, email, name, picture],
    )
    db.commit()

    session['user'] = {'id': google_id, 'email': email, 'name': name, 'picture': picture}
    next_url = session.pop('next', url_for('home'))
    return redirect(next_url)


@app.route('/auth/logout')
def auth_logout():
    session.clear()
    return redirect(url_for('index'))


# ── 학생 라우트 ────────────────────────────────────────────────────

@app.route('/problem/<int:problem_id>')
@login_required
def problem(problem_id):
    db = get_db()
    prob = db.execute('SELECT * FROM problems WHERE id = ? AND active = 1', [problem_id]).fetchone()
    if not prob:
        return render_template('error.html', message='문제를 찾을 수 없거나 비활성화된 문제입니다.'), 404

    user = session['user']
    submission = db.execute(
        'SELECT * FROM submissions WHERE problem_id = ? AND user_id = ? ORDER BY submitted_at DESC LIMIT 1',
        [problem_id, user['id']],
    ).fetchone()

    return render_template(
        'problem.html',
        problem=dict(prob),
        user=user,
        is_teacher=user["email"] in get_teacher_emails(),
        submission=dict(submission) if submission else None,
    )


@app.route('/api/run', methods=['POST'])
@login_required
def api_run():
    data = request.json
    code  = data.get('code', '')
    stdin = data.get('stdin', '')
    if not code.strip():
        return jsonify({'error': '코드를 입력해주세요.'}), 400
    return jsonify(run_code(code, stdin))


@app.route('/api/submit', methods=['POST'])
@login_required
def api_submit():
    data       = request.json
    problem_id = data.get('problem_id')
    code       = data.get('code', '')

    if not code.strip():
        return jsonify({'error': '코드를 입력해주세요.'}), 400

    db = get_db()
    prob = db.execute('SELECT * FROM problems WHERE id = ? AND active = 1', [problem_id]).fetchone()
    if not prob:
        return jsonify({'error': '문제를 찾을 수 없습니다.'}), 404

    test_cases = json.loads(prob['test_cases'])
    result = grade_submission(code, test_cases)

    user = session['user']
    cursor = db.execute(
        '''INSERT INTO submissions
           (problem_id, user_id, user_email, user_name, code, score,
            passed_cases, total_cases, result_detail, submitted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        [
            problem_id, user['id'], user['email'], user['name'],
            code, result['score'], result['passed'], result['total'],
            json.dumps(result['results'], ensure_ascii=False),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ],
    )
    db.commit()
    result['submission_id'] = cursor.lastrowid
    return jsonify(result)


@app.route('/api/feedback/<int:sub_id>', methods=['POST'])
@login_required
def api_feedback(sub_id):
    """AI 피드백 생성 (제출 후 프론트에서 별도 호출)"""
    db = get_db()
    row = db.execute(
        '''SELECT s.*, p.title as prob_title, p.description as prob_desc
           FROM submissions s JOIN problems p ON s.problem_id = p.id
           WHERE s.id = ?''',
        [sub_id],
    ).fetchone()
    if not row:
        return jsonify({'error': '제출 내역을 찾을 수 없습니다.'}), 404

    sub = dict(row)
    # 본인 제출 또는 교사만 허용
    user = session['user']
    if sub['user_id'] != user['id'] and user["email"] not in get_teacher_emails():
        return jsonify({'error': '권한이 없습니다.'}), 403

    # 이미 생성된 피드백이 있으면 그대로 반환
    if sub.get('ai_feedback'):
        return jsonify(json.loads(sub['ai_feedback']))

    test_results = json.loads(sub.get('result_detail') or '[]')
    feedback = get_ai_feedback(
        code=sub['code'],
        problem_title=sub['prob_title'],
        problem_description=sub['prob_desc'],
        test_results=test_results,
        score=sub['score'],
    )

    if not feedback:
        return jsonify({'error': 'ANTHROPIC_API_KEY를 .env에 설정해주세요.'}), 500

    db.execute('UPDATE submissions SET ai_feedback = ? WHERE id = ?',
               [json.dumps(feedback, ensure_ascii=False), sub_id])
    db.commit()
    return jsonify(feedback)


@app.route('/api/generate_problem', methods=['POST'])
@teacher_required
def api_generate_problem():
    """AI로 Python 문제 자동 생성"""
    data       = request.json
    topic      = data.get('topic', '')
    difficulty = data.get('difficulty', '보통')
    concept    = data.get('concept', '')

    if not topic.strip():
        return jsonify({'error': '주제를 입력해주세요.'}), 400

    result = generate_problem_with_ai(topic, difficulty, concept)
    if result:
        return jsonify(result)
    return jsonify({'error': 'ANTHROPIC_API_KEY를 .env에 설정하거나 나중에 다시 시도해주세요.'}), 500


# ── 교사 대시보드 ──────────────────────────────────────────────────

@app.route('/dashboard')
@teacher_required
def dashboard():
    db = get_db()
    problems = db.execute('SELECT * FROM problems ORDER BY created_at DESC').fetchall()
    stats = db.execute(
        'SELECT problem_id, COUNT(*) as count, AVG(score) as avg_score FROM submissions GROUP BY problem_id'
    ).fetchall()
    stats_map = {s['problem_id']: dict(s) for s in stats}
    return render_template(
        'dashboard.html',
        user=session['user'],
        is_teacher=True,
        problems=[dict(p) for p in problems],
        stats_map=stats_map,
    )


@app.route('/dashboard/problem/new', methods=['GET', 'POST'])
@teacher_required
def new_problem():
    if request.method == 'POST':
        data = request.json
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO problems
               (title, description, template_code, test_cases, constraints, time_limit, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            [
                data['title'],
                data['description'],
                data.get('template_code', ''),
                json.dumps(data.get('test_cases', []), ensure_ascii=False),
                data.get('constraints', ''),
                data.get('time_limit', 5),
                1 if data.get('active', True) else 0,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ],
        )
        db.commit()
        return jsonify({'id': cursor.lastrowid, 'message': '문제가 생성되었습니다.'})
    return render_template('edit_problem.html', user=session['user'], is_teacher=True, problem=None)


@app.route('/dashboard/problem/<int:problem_id>', methods=['GET', 'PUT', 'DELETE'])
@teacher_required
def edit_problem(problem_id):
    db = get_db()
    if request.method == 'GET':
        prob = db.execute('SELECT * FROM problems WHERE id = ?', [problem_id]).fetchone()
        if not prob:
            return render_template('error.html', message='문제를 찾을 수 없습니다.'), 404
        return render_template('edit_problem.html', user=session['user'], is_teacher=True, problem=dict(prob))

    elif request.method == 'PUT':
        data = request.json
        db.execute(
            '''UPDATE problems SET title=?, description=?, template_code=?,
               test_cases=?, constraints=?, time_limit=?, active=? WHERE id=?''',
            [
                data['title'], data['description'], data.get('template_code', ''),
                json.dumps(data.get('test_cases', []), ensure_ascii=False),
                data.get('constraints', ''), data.get('time_limit', 5),
                1 if data.get('active', True) else 0, problem_id,
            ],
        )
        db.commit()
        return jsonify({'message': '수정되었습니다.'})

    elif request.method == 'DELETE':
        db.execute('DELETE FROM problems WHERE id = ?', [problem_id])
        db.commit()
        return jsonify({'message': '삭제되었습니다.'})


@app.route('/dashboard/submissions')
@teacher_required
def submissions():
    db = get_db()
    problem_id = request.args.get('problem_id')
    if problem_id:
        subs = db.execute(
            '''SELECT s.*, p.title as problem_title
               FROM submissions s JOIN problems p ON s.problem_id = p.id
               WHERE s.problem_id = ? ORDER BY s.submitted_at DESC''',
            [problem_id],
        ).fetchall()
    else:
        subs = db.execute(
            '''SELECT s.*, p.title as problem_title
               FROM submissions s JOIN problems p ON s.problem_id = p.id
               ORDER BY s.submitted_at DESC LIMIT 200''',
        ).fetchall()
    problems = db.execute('SELECT id, title FROM problems ORDER BY title').fetchall()
    return render_template(
        'submissions.html',
        user=session['user'],
        is_teacher=True,
        submissions=[dict(s) for s in subs],
        problems=[dict(p) for p in problems],
        selected_problem=problem_id,
    )


@app.route('/dashboard/submission/<int:sub_id>')
@teacher_required
def submission_detail(sub_id):
    db = get_db()
    sub = db.execute(
        '''SELECT s.*, p.title as problem_title, p.test_cases
           FROM submissions s JOIN problems p ON s.problem_id = p.id
           WHERE s.id = ?''',
        [sub_id],
    ).fetchone()
    if not sub:
        return render_template('error.html', message='제출 내역을 찾을 수 없습니다.'), 404
    sub = dict(sub)
    sub['result_detail'] = json.loads(sub['result_detail'] or '[]')
    sub['ai_feedback_data'] = json.loads(sub['ai_feedback']) if sub.get('ai_feedback') else None
    return render_template('submission_detail.html', user=session['user'], is_teacher=True, sub=sub)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
