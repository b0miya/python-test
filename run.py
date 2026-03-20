"""앱 실행 진입점 — 환경변수 자동 로드"""
import os
from dotenv import load_dotenv
# override=False: 이미 설정된 환경변수(Railway Variables)를 .env로 덮어쓰지 않음
load_dotenv(override=False)

from database import init_db
from app import app

init_db()
port = int(os.environ.get('PORT', 5000))
debug = os.environ.get('RAILWAY_ENVIRONMENT') is None

# 환경변수 확인 로그
gid = os.environ.get('GOOGLE_CLIENT_ID', '')
print(f"[ENV] GOOGLE_CLIENT_ID 길이: {len(gid)}, 앞10자: {gid[:10]!r}")
print(f"[ENV] RAILWAY_ENVIRONMENT: {os.environ.get('RAILWAY_ENVIRONMENT', '(없음)')}")

if __name__ == '__main__':
    print("=" * 50)
    print(f"  Python 평가 시스템 시작 — port {port}")
    print("=" * 50)
    app.run(debug=debug, host='0.0.0.0', port=port)
