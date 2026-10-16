# 가상 프로젝트로 CLI 사용하기

아래 예제는 가상 데이터다. 생성한 로컬 브레인 정본에서 실행한다. 실제 개인 사실을 포함하지 않는다.
먼저 등록부 해시를 읽어 신규 프로젝트를 등록한다.

```bash
python3 - <<'PY'
import json, subprocess, sys
catalog = json.loads(subprocess.check_output([sys.executable, 'scripts/session_sync.py', 'catalog']))
request = {'expected_registry': catalog['expected_registry'], 'entry': {
    'id': 'example-app', 'title': 'Example App (가상)',
    'purpose': 'CLI 사용법을 연습하는 가상 프로젝트', 'source': '사용자가 실행한 가상 예제',
    'aliases': [], 'session_groups': []}}
subprocess.run([sys.executable, 'scripts/sync_workflow.py', 'register', '--risk', 'routine'],
               input=json.dumps(request), text=True, check=True)
PY
```

가상 작업 결과를 기록한다. 실제 기록에서는 실제 관찰일을 사용한다.

```bash
printf '가상 예제: 요구사항 문서를 정리했다. 구현·테스트·배포는 아직 하지 않았다.\n' | \
  python3 scripts/sync_workflow.py record --risk routine \
  --project example-app --session example-session \
  --source '사용자가 실행한 가상 예제' --observed unknown
python3 scripts/session_sync.py snapshot --project example-app
```

unknown 날짜는 추정하지 않으므로 정본이 없는 이 예제는 통합 대기다.
실제 날짜와 근거가 있는 프로젝트는 스킬 절차대로 snapshot의 expected와 선택한 이벤트 ID로 integrate한다.
각 명령이 출력한 branch·worktree·commit과 INDEX를 확인한다. 이 예제는 원격 없는 로컬 사용을 전제로 한다.
