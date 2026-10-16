# 주간 통합과 블로그 자동화

기존 운영과 같은 흐름이다. 통합(토요일 09시), 블로그 후보(일요일 10시), 로그인/매시간 catch-up을 분리한다.
작업 저장소별 잠금을 공유하며 실제 작업은 등록 프로젝트를 순서대로 처리한다.
자동화는 별도 work 브레인에서만 허용하고 원격이 있거나 정본이 dirty이면 중단한다.
개인 원격 push·게시·review·release를 자동으로 수행하지 않는다.

## 선택한 AI로 계획 생성

생성한 업무 브레인의 automation/config.example.json을 automation/config.json으로 복사한다.
provider와 executable을 codex, claude, gemini 또는 grok으로 지정하고 해당 CLI에 사용자가 로그인한다.
실제 config는 Git에서 제외한다. API 키·토큰은 이 파일에 넣지 않는다.

```bash
python3 automation/run.py check
python3 automation/run.py integration
python3 automation/run.py blog
python3 automation/run.py catch-up
python3 automation/schedule_state.py status
```

check는 도구·저장 위치를 확인하며 인증 성공이나 의미 판단을 보장하지 않는다.
계획은 전용 작업 디렉터리에서 생성하고 각 CLI의 읽기 전용/계획 모드와 도구 제한을 사용한다.
Gemini는 plan 모드, Grok은 read-only sandbox와 도구 비활성화, Claude는 도구 비활성화와 plan 모드,
Codex는 read-only sandbox를 쓴다. 제공한 근거와 schema로 JSON만 생성하도록 요청한다.
Gemini의 --skip-trust는 호스트가 새로 만든 계획 디렉터리에만 적용하며 원본 기억 저장소의 신뢰 설정은 바꾸지 않는다.
CLI의 지침 발견·sandbox 기능은 각 공급자의 동작이며 호스트의 데이터 검증과 별개다.

호스트는 pending ID 전체 분류·원문 snapshot 버전·날짜·기존 출처 링크 보존을 검사하고,
sync_workflow.py로 linked worktree·문서 검사·커밋·local main 반영을 수행한다.
커밋·변경 경로·통합 영수증을 확인한 뒤 결과를 기록한다. 모델 출력의 명령은 실행하지 않는다.
블로그는 최근 8일 실제 새 통합 영수증이 생긴 근거에서 새 한국어·영어 후보 한 쌍만 만든다.
개인 전달·게시는 특정 검토본에 대한 별도 승인 단계다.

## 결과와 재시도

| outcome | 의미 | 처리 |
|---|---|---|
| success | 실제 반영과 검증 완료 | 다음 주기 |
| noop | pending 없는 정상 무작업 | 다음 주기 |
| partial | 검증된 일부 반영 + 보류 | 다음 주기 또는 수동 검토 |
| deferred | 충돌·과거 기록·근거 부족으로 보류 | 다음 주기 또는 수동 검토 |
| failed | 모델·버전·검사·Git 실패 | 다음 catch-up에서 재시도 |

partial/deferred에는 completed_at을 쓰지 않는다. 프로세스 종료 코드 0만으로 성공을 기록하지 않는다.
result.json과 SHA256을 검증하며 과거 marker는 교체 시 history에 보존한다.
상태·로그·모델 근거는 ~/.local/state/second-brain/<저장소별-id>/ 아래에 보관한다.
이는 업무 범위의 로컬 런타임 자료이며 개인 브레인/공개 저장소로 복사하지 않는다. 보관 위치도 조직 기준을 따라야 한다.

## 선택적인 예약 설치

초기 생성·다운로드는 예약을 등록하지 않는다. macOS에서 업무 브레인 안에서 명시적으로 설치한다.

```bash
# 먼저 생성할 plist만 확인 (등록 안 함)
python3 automation/install_schedule.py --output-dir /원하는/검토폴더
# 실제 등록을 원하는 경우에만
python3 automation/install_schedule.py --output-dir ~/Library/LaunchAgents --activate
```

plist 이름과 로그 위치는 저장소별로 다르다. 기존 내용이 다르면 덮어쓰지 않는다.
Linux는 같은 run.py 명령을 사용자가 선택한 cron/systemd 타이머에서 실행한다.
통합 → 블로그 순서의 catch-up은 첫 실패에서 중단한다. 출처 충돌을 자동 확정하지 않는다.

## 기억 점검은 별도 단계

주간 통합: sessions → 프로젝트 정본.
기억 점검: memory_tools.py audit → 중복·충돌·낡은 내용·연결 누락 검토 보고.
이번 도구는 점검 결과로 기록을 자동 삭제·archive하지 않는다.
