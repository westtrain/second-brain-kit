# 네 AI의 공통 기억

정본은 모델의 내부 메모리가 아니라 선택한 개인/업무 Markdown 저장소다.
모든 AI는 AGENTS.md → MEMORY.md → INDEX.md → 관련 프로젝트 → 최신 pending 순으로 조회하고 같은 sync_workflow.py를 사용한다.

| AI 환경 | 공통 지침 진입 | 스킬 설치 provider |
|---|---|---|
| Claude Code | CLAUDE.md → AGENTS.md | claude |
| Codex | AGENTS.md | codex |
| Gemini CLI | GEMINI.md에서 AGENTS.md import | gemini |
| Grok Build | AGENTS.md 직접 탐색 | grok |

Gemini의 context 파일과 import 동작은 [공식 Gemini CLI 문서](https://geminicli.com/docs/cli/gemini-md/)에 따른다.
Grok의 AGENTS 및 스킬 경로는 [공식 Grok Build 문서](https://docs.x.ai/build/features/skills-plugins-marketplaces)에 따른다.
GROK.md라는 자동 인식 파일을 가정하지 않는다. 실제 사용 환경에서 발견 상태를 확인한다.

생성한 브레인에서 다음과 같이 선택한 AI의 스킬을 설치한다. --target으로 별도 위치를 지정할 수도 있다.

```bash
python3 scripts/install_sync_skill.py --provider gemini
python3 scripts/install_sync_skill.py --provider grok
```

기존 config는 보존한다. 두 브레인을 만들었다면 --config로 부모의 config.json을 전달하여 새 설치에 개인/업무 경로를 함께 지정한다.
계정·API 키·기기 설정을 공개 저장소로 보내지 않는다. 네 AI의 모델 계정 로그인은 각각 사용자가 수행한다.

로컬 도구가 없는 웹/앱에서는 파일이 자동 동기화된다고 가정하지 않는다. 필요한 Markdown만 허용 범위에서 수동으로 제공하고,
반환한 계획은 로컬 도구가 있는 환경에서 검토·반영한다. 회사 자료 업로드는 해당 조직과 사용자의 허용 범위를 먼저 확인한다.

예약 자동화도 같은 계획 schema와 호스트 검증기를 쓴다. CLI별 출력 형식과 읽기/도구 제한은 adapter가 처리한다.
실제 모델의 의미 판단은 별도이며, 모의 테스트·CLI 도움말 확인·실제 모델 응답 확인을 구분해서 보고한다.
