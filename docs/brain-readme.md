# 나의 로컬 세컨브레인

AGENTS.md와 공통 지침을 읽은 AI에서 목표·결정·프로젝트 결과를 저장하고 이어서 사용합니다.
이 저장소에는 기본 원격이 없습니다. 개인 원격은 별도 private 저장소로 명시적으로 선택하세요.

- [기억 진입점](../MEMORY.md) · [전체 색인](../INDEX.md)
- [프로젝트 등록부](../system/project-registry.json)
- [운영 흐름](../system/workflows.md) · [Git 절차](../system/git-workflow.md)
- [문서 규칙](../system/conventions.md) · [정보 경계](../system/privacy.md)
- [스킬](../skills/second-brain-sync/SKILL.md)

```bash
python3 scripts/brain.py check
python3 scripts/session_sync.py catalog
python3 scripts/memory_tools.py audit --json
```

다른 폴더에서 저장할 때는 이 브레인 안에서 `python3 scripts/install_sync_skill.py`로 스킬을 설치합니다.
기존 설치 config는 보존되므로 personal이 원하는 정본 경로인지 직접 확인하세요.
프로젝트 쓰기는 정본의 sync_workflow.py를 사용합니다. 일반 변경도 작업별 linked worktree에서 검사합니다.
프로젝트는 비어 있습니다. “새 프로젝트를 등록하고 오늘 작업을 요약으로 저장해줘”로 시작하세요.
기록 통합은 별도 요청입니다. 모순·과거 기록·미확인 날짜를 자동 확정하지 않습니다.

선택 기능으로 [MCP 연결](../docs/mcp.md), [검색 평가·QMD](../docs/search-evaluation.md)를 제공합니다.
MCP는 서버 하나에 이 브레인 하나만 연결하며 기본 조회 전용입니다. 실제 기록·검색 인덱스·연결 설정을 공개하지 않습니다.

이 도구의 배포·업데이트 안내: https://github.com/westtrain/second-brain-kit

## 지식으로 재사용하기

자료 수집·주장별 근거·지식 갱신과 질문/퀴즈/보고서는 [지식 흐름](../system/knowledge-workflow.md)과
[가상 체험](../docs/knowledge-walkthrough.md)을 따른다. 생성한 기억은 공개 킷과 별도로 유지한다.
