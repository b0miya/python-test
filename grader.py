import subprocess
import tempfile
import os
import sys
import json
import re

PYTHON_EXEC = sys.executable  # 현재 앱과 같은 Python 인터프리터 사용


def run_code(code: str, stdin_input: str = '', timeout: int = 5) -> dict:
    """Python 코드를 안전하게 실행하고 결과 반환"""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, encoding='utf-8'
    ) as f:
        f.write(code)
        fname = f.name

    try:
        result = subprocess.run(
            [PYTHON_EXEC, fname],
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
        )
        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode,
            'timed_out': False,
        }
    except subprocess.TimeoutExpired:
        return {
            'stdout': '',
            'stderr': f'⏱ 시간 초과 ({timeout}초를 초과했습니다)',
            'returncode': -1,
            'timed_out': True,
        }
    except Exception as e:
        return {
            'stdout': '',
            'stderr': f'실행 오류: {e}',
            'returncode': -1,
            'timed_out': False,
        }
    finally:
        try:
            os.unlink(fname)
        except OSError:
            pass


def grade_submission(code: str, test_cases: list) -> dict:
    """테스트 케이스를 기준으로 채점"""
    if not test_cases:
        return {'passed': 0, 'total': 0, 'score': 0, 'results': []}

    results = []
    passed = 0

    for i, tc in enumerate(test_cases):
        result = run_code(code, tc.get('input', ''), timeout=5)
        expected = tc.get('expected_output', '').strip()
        actual = result['stdout'].strip()
        is_correct = (actual == expected)

        if is_correct:
            passed += 1

        show = tc.get('show', True)  # False면 숨겨진 테스트 케이스
        results.append({
            'test_case': i + 1,
            'passed': is_correct,
            'expected': expected if show else '(숨겨진 테스트)',
            'actual': actual if show else ('정답' if is_correct else '오답'),
            'error': result['stderr'],
            'timed_out': result['timed_out'],
            'hidden': not show,
        })

    score = round(passed / len(test_cases) * 100, 1)
    return {
        'passed': passed,
        'total': len(test_cases),
        'score': score,
        'results': results,
    }


# ── Anthropic AI 피드백 ─────────────────────────────────────────────

def get_ai_feedback(code: str, problem_title: str, problem_description: str,
                    test_results: list, score: float) -> dict | None:
    """Anthropic Claude로 학생 코드 AI 피드백 생성"""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        visible = [r for r in test_results if not r.get('hidden')]
        results_text = '\n'.join(
            f"  테스트 {r['test_case']}: {'✅ 통과' if r['passed'] else '❌ 실패'}"
            + (f" → 예상: {r['expected']!r}  실제: {r['actual']!r}" if not r['passed'] else '')
            + (f" [오류: {r['error'][:120]}]" if r.get('error') and not r['passed'] else '')
            for r in visible
        )

        prompt = f"""학생이 Python 문제를 풀었습니다. 코드를 분석하고 **한국어**로 피드백을 작성해주세요.

## 문제: {problem_title}
{problem_description[:800]}

## 학생 코드
```python
{code}
```

## 채점 결과: {score}점 ({sum(1 for r in test_results if r.get('passed'))}/{len(test_results)} 통과)
{results_text}

---
다음 형식으로 피드백을 작성해주세요:

### ✅ 잘한 점
- (코드에서 좋은 부분들)

### 🔧 개선할 점
- (오류나 개선이 필요한 부분들)

### 💡 힌트
(점수가 100점 미만인 경우만 — 답을 직접 알려주지 말고 방향만 제시)

### 📚 추가 학습 포인트
(관련 Python 개념)"""

        with client.messages.stream(
            model='claude-opus-4-6',
            max_tokens=1500,
            messages=[{'role': 'user', 'content': prompt}],
        ) as stream:
            text = stream.get_final_message().content[0].text

        return {'feedback': text, 'model': 'claude-opus-4-6'}
    except Exception as e:
        print(f'[AI 피드백 오류] {e}')
        return None


def generate_problem_with_ai(topic: str, difficulty: str, concept: str) -> dict | None:
    """Anthropic Claude로 Python 교육 문제 자동 생성"""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Python 프로그래밍 교육용 문제를 만들어주세요.

주제: {topic}
난이도: {difficulty}
학습 개념: {concept or '자유'}

아래 JSON 형식으로만 출력하세요 (다른 텍스트 없이):
{{
  "title": "문제 제목",
  "description": "문제 설명 (HTML 가능, <pre><code> 태그로 예제 표시 권장)",
  "template_code": "# 여기에 코드를 작성하세요\\n",
  "constraints": "제약 조건 (예: 1 ≤ N ≤ 100)",
  "test_cases": [
    {{"input": "입력1", "expected_output": "출력1", "show": true}},
    {{"input": "입력2", "expected_output": "출력2", "show": true}},
    {{"input": "숨긴입력3", "expected_output": "숨긴출력3", "show": false}},
    {{"input": "숨긴입력4", "expected_output": "숨긴출력4", "show": false}},
    {{"input": "숨긴입력5", "expected_output": "숨긴출력5", "show": false}}
  ]
}}

규칙:
- 테스트 케이스 최소 5개 (앞 2개 공개, 나머지 숨김)
- 입출력은 print() 기준으로 정확히 일치해야 함
- 문제 설명은 학생이 이해하기 쉽게 작성"""

        response = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=3000,
            thinking={'type': 'adaptive'},
            messages=[{'role': 'user', 'content': prompt}],
        )

        text = next((b.text for b in response.content if b.type == 'text'), '')
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        return None
    except Exception as e:
        print(f'[AI 문제생성 오류] {e}')
        return None
