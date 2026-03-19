"""앱 실행 진입점 — 환경변수 자동 로드"""
from dotenv import load_dotenv
load_dotenv()

from database import init_db
from app import app

if __name__ == '__main__':
    init_db()
    print("=" * 50)
    print("  Python 평가 시스템 시작")
    print("  http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5000)
