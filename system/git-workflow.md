# 작업별 Git 흐름

init_brain.py는 새 로컬 저장소를 최초 생성·커밋한 뒤 보호 훅을 활성화한다. 생성한 저장소에는 원격이 없다.
이후 실제 기록은 작업별 linked worktree·브랜치에서 편집한다. 정본 main에서 직접 편집·커밋하지 않는다.
정본 경로의 scripts/sync_workflow.py가 프로젝트 세션 저장·통합·등록·연결의 공통 실행기다.

## 위험에 따른 반영

사용자가 요청한 일반 저장·충돌 없는 통합·명확한 정정·문서/도구 보수는 검사 후 local main에 반영할 수 있다.
명시적으로 승인한 개인 원격이 있으면 범위를 확인한 뒤 작업 브랜치 push·PR·병합 절차를 따른다.
--risk review는 검토를 위해 브랜치/PR에 남기며 --risk routine은 검사 후 자동 병합한다.
공개 upstream은 실제 기록을 보내는 원격으로 사용하지 않는다. 업무 저장소에는 개인 원격을 대신 연결하지 않는다.

출처 충돌의 채택, 삭제·archive·덮어쓰기·재분류, 소유/보관/전송 경계 변경은 결과와 근거를 먼저 보여준다.
현재 요청이 구체적 대상·내용을 승인했다면 같은 승인을 반복해서 요구하지 않는다.
다른 세션의 변경을 포함하지 않으며 실패·충돌·stale 상태를 강제로 우회하지 않는다.

## 도구

Git 상태·remote·worktree·해당 AGENTS.md를 확인한다. 원격이 있으면 최신 origin/main을 기준으로 작업한다.
프로젝트 외 일반 변경은 별도 linked worktree를 만든 뒤 변경 경로만 stage한다.
brain.py check·staged-check·git diff --check를 확인한다. INDEX는 작업 worktree에서 재생성한다.
GitHub 인증은 scripts/github_scope.py와 설치 스킬의 config.json을 통해 명령 프로세스에만 적용한다.
전역 gh auth switch를 사용하지 않는다. 개인·업무 계정은 기기별 설정에서 명시한다.
훅은 로컬 보조 장치이며 서버 권한이나 암호화가 아니다. 사용자가 승인하지 않은 push·공개를 수행하지 않는다.
