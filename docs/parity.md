# 운영 구조와 공개본의 대응

v0.2.0은 개인·업무 브레인의 역할, 공통 도구, 검토·전달, 예약 운영을 같은 구조로 제공한다.
실제 기록·소속 매핑·개인 사실·출처·기기 설정·기존 Git 이력은 공개본에 포함하지 않는다.

| 운영 구성 | 공개본 |
|---|---|
| 독립된 개인/업무 정본 | init_brain.py --pair로 두 개의 독립 Git 저장소 생성 |
| sessions → projects, 등록부, snapshot/영수증 | 기존 공통 엔진과 동일한 처리 흐름 |
| MEMORY/INDEX/읽기 전용 audit | 공통 엔진, Gemini 진입점도 지침/링크 검사에 포함 |
| 개인 경력·배움·블로그 | career/companies, learnings, blog |
| 업무 미해결 문제·실제 장애 | findings, incidents와 빈 운영 목록 |
| 경험 후보·본문 검토·승인 전달 | exports/candidates, exports/reviews, exact hash release |
| 회사별 경력 소속 | 빈 company-registry와 companies/bind-company 도구 |
| 통합·블로그·catch-up | 같은 호스트 검증 흐름, 경로와 planner를 기기 설정으로 일반화 |
| launchd 예약 | 저장소별 plist 생성 및 명시적 활성화 |
| 네 AI | 같은 엔진 + AGENTS/CLAUDE/GEMINI 진입점과 공급자별 CLI adapter |

실제 파일 구조는 scope별로 다르며 공통 infrastructure와 정책은 함께 설치된다.
업무 자동화는 원격 없는 업무 정본에서만 작동한다. 개인 GitHub push·개인 전달·공개 게시를 자동화하지 않는다.
예약은 생성 시 등록하지 않고 사용자가 선택한 뒤 활성화한다. Linux는 동일 run.py를 cron/systemd에서 실행한다.

## 공개 전 검증 구분

도구 단위/통합 테스트는 가상 기록으로 저장·통합·경험 전달·두 저장소 분리·예약 상태·AI 출력 처리를 확인한다.
CLI 도움말과 공식 지침을 확인한 것, 실제 모델 응답을 받은 것, 사용자의 실제 자료를 처리한 것은 서로 다르다.
이 배포 검증에서는 실제 회사·개인 기록을 다른 모델이나 공개 저장소로 전달하지 않는다.

## 공개 킷의 지식 재사용 확장

자료 수집·지식 문서·문맥 선택·주장별 출처 검증은 knowledge.py/knowledge_workflow.py로 제공한다.
실제 운영 브레인에 자동 설치하지 않으며 적용 전 별도 변경 검토를 거친다. 기존 블로그 자동화와 독립적이다.
[지식 흐름](../system/knowledge-workflow.md)과 [가상 체험](knowledge-walkthrough.md)을 참고한다.
