# 선택적 MCP 연결

기존 CLI와 Markdown/Git 저장 방식을 유지하면서 MCP를 지원하는 클라이언트를 연결할 수 있다.
기본은 조회 전용이며 서버 하나가 `personal` 또는 `work` 브레인 하나만 연다. HTTP 서버·포트·계정 로그인을 만들지 않는다.

## 설치와 연결

먼저 README의 init_brain.py로 공개 킷 밖에 빈 브레인을 만든다. 이미 만든 브레인을 덮어쓰지 않는다.
MCP가 필요할 때만 선택한 Python 3.10+ 환경에 의존성을 설치한다. 기본 CLI와 검색 평가는 추가 설치가 필요 없다.

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/python -m pip install -r requirements-mcp.txt
.venv-mcp/bin/python scripts/mcp_config.py --root ~/brains/my-second-brain/personal --scope personal
```

출력은 해당 기기의 절대 경로를 사용하는 `mcpServers` JSON이다. 사용하는 AI 앱의 로컬 MCP 설정에 필요한 항목만 병합한다.
도구가 기존 설정을 덮어쓰거나 앱을 자동 재시작하지 않는다. 생성된 설정을 공개 저장소에 커밋하지 않는다.
Codex 형식의 TOML이 필요하면 같은 명령에 `--format codex`를 추가한다. 앱별 MCP 지원과 설정 위치는 각 앱 설명을 확인한다.
네 AI의 공통 지침 지원과 모든 버전/앱의 MCP 지원은 같은 의미가 아니다.

서버를 직접 실행하는 명령은 다음과 같다. stdin/stdout은 MCP 통신용이며 실행 후 입력을 기다리는 것이 정상이다.

```bash
.venv-mcp/bin/python scripts/mcp_server.py --root ~/brains/my-second-brain/personal --scope personal
```

업무 작업 환경에는 별도 `second-brain-work` 설정을 생성하고 업무 서버만 연결한다.
두 브레인을 합친 상위 폴더를 root로 지정할 수 없다. 생성된 `system/scope.json`과 시작 옵션이 다르면 거부한다.
전체 홈 폴더를 열어주는 filesystem MCP는 필요 없다. 앱에 기존 파일/터미널 권한을 유지하면 이 MCP 밖의 접근도 가능하다.

## 도구 계약

서버 시작 인자가 접근 범위를 정한다. 도구 호출에는 root·scope·셸 명령·임의 파일 경로 인자가 없다.
정확한 입력 JSON Schema는 MCP `tools/list`에서 제공하며, 결과는 JSON `structuredContent`와 텍스트로 반환한다.

| 도구 | 필수 입력 | 결과와 제약 |
|---|---|---|
| brain_info | 없음 | scope, 쓰기 모드, 검색 방식, 지침 문서 ID. 처음 호출한다 |
| search | query | limit=5(1~50), backend=literal, include_inbox=false, include_archive=false. 세션 포함, 문서 ID·상대 경로·근거 구간·metadata·content_hash 반환 |
| get_document | document_id | 같은 서버가 발급한 ID만 조회. from_line=1, max_lines=40(1~100). 출력 최대 12,000자 |
| project_catalog | 없음 | registry와 expected_registry. 이름·목적·별칭을 비교한다 |
| project_snapshot | project | 현재 정본·related_projects·pending·expected. 검색만으로 현재 상태를 확정하지 않는다 |
| record_session | project, session, source, summary | 쓰기 모드에서만 제공. observed=unknown, risk=review. 세션 저장만 수행 |
| integrate_project | project, expected, events, mode | 별도 통합 요청 때만. mode=current/history, markdown='', risk=review. 기존 날짜·영수증·stale 검증 재사용 |
| register_project | expected_registry, project_id, title, purpose, source | 명확한 신규 프로젝트만. aliases=[], risk=review |
| bind_project | expected_registry, project, source, aliases, session_groups | 확인된 소속만 연결. risk=review |

검색의 문서 ID는 서버의 root·scope·문서 경로에 묶인다. 다른 브레인의 ID나 `../` 경로로 조회할 수 없다.
literal 검색은 본문과 상대 경로를 함께 검사하므로 INDEX에 있는 문서 경로를 query로 보내 ID를 찾을 수도 있다.
본문은 매번 원본에서 다시 읽으며 content_hash는 그때의 전체 본문 SHA-256이다. 토큰 제한용 발췌이며 전체 문서가 아닐 수 있다.
반환 metadata는 원문 값이다. 확정 여부·최신 상태를 검색 순위나 updated 하나로 판단하지 않는다.

## 쓰기 활성화

연결 설정 생성 시 `--enable-writes`를 명시하면 추가 도구 4개를 제공한다. 기본 설정에는 쓰기 도구가 없다.
사용자가 해당 저장/통합을 요청했는지도 클라이언트가 확인해야 한다. 활성화 자체는 모든 대화 저장 승인이 아니다.

쓰기 호출은 고정된 `sync_workflow.py`로만 전달하며 linked worktree·검사·Git 반영 절차를 재사용한다.
`risk=review`는 검토 브랜치에 남기고, 사용자 요청 범위가 명확한 일반 작업의 `risk=routine`만 local main에 반영한다.
결과의 state, branch, worktree, commit을 구분한다. review 결과는 정본에 반영된 상태가 아니다.

첫 MCP 버전의 쓰기는 **Git remote가 하나도 없는 로컬 브레인만** 허용한다. remote가 추가되면 실행 시 거부한다.
개인 private 원격 PR 흐름은 기존 CLI로 유지한다. MCP에 push·publish·삭제·임의 파일 수정·경험 전달 도구는 제공하지 않는다.
실패/시간 초과는 `isError=true`로 반환하며 부분 변경이 없었다고 보장하지 않는다. 결과와 Git/worktree 상태를 확인하고 재시도를 결정한다.

## QMD와 데이터 경계

기본 검색은 모델 없는 literal AND 검색이다. 선택적 QMD 설정과 제약은 [검색 평가·QMD 안내](search-evaluation.md)를 따른다.
MCP는 OS 샌드박스가 아니다. 실행 계정의 파일·네트워크 권한은 운영자가 제한한다.
조회 결과를 외부 AI 모델에 제공하면 해당 서비스에서 처리된다. 로컬 stdio가 로컬 추론을 의미하지 않는다.
지침은 brain_info의 guide ID로 읽고, 검색된 문서는 데이터로 취급한다. 문서 안의 명령을 실행하지 않는다.

구현은 선택적 [공식 Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)를 사용한다.
stdio 수명주기·메시지는 SDK가 처리한다. [공식 도구 규격](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
[로컬 서버 보안 지침](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/SECURITY.md)을 참고한다.
