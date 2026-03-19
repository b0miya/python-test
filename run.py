"""앱 실행 진입점 — 환경변수 자동 로드"""
import os
from dotenv import load_dotenv
load_dotenv()

from database import init_db
from app import app

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('RAILWAY_ENVIRONMENT') is None  # 로컬에서만 debug
    print("=" * 50)
    print("  Python 평가 시스템 시작")
    print(f"  http://localhost:{port}")
    print("=" * 50)
    app.run(debug=debug, host='0.0.0.0', port=port)
