# 색인과 기억 점검

MEMORY.md는 짧은 수동 진입점이며 INDEX.md는 metadata·프로젝트 등록부·통합 영수증으로 전체 재생성한다.
색인은 현재 checkout만 포함한다. 다른 worktree·미커밋 정본 자료를 임의 합치지 않는다.
정확한 pending은 session_sync.py snapshot으로 다시 확인한다.

```bash
python3 scripts/memory_tools.py index --check
python3 scripts/memory_tools.py audit --as-of 2026-10-16
python3 scripts/memory_tools.py audit --json
```

위 명령은 읽기 전용이다. audit는 오래된 as_of·미통합·출처·고아·충돌 키워드·장기 draft/blocker/finding을 검토 후보로 보고한다.
기본 기준은 오래된 내용 30일, 미통합 14일이며 --stale-days, --pending-days로 변경할 수 있다.
키워드와 날짜만으로 의미 충돌·현재 유효성을 확정하지 않는다. 자동 삭제·archive·회사 자료 전달은 하지 않는다.

작업별 linked worktree에서 문서 변경 후 다음을 실행한다.

```bash
python3 scripts/memory_tools.py index
python3 scripts/brain.py check
```

INDEX에는 수동 내용을 섞지 않는다. 생성 헤더 없는 파일과 symlink는 교체하지 않는다.
sync_workflow는 허용된 mutation 경로를 검증한 뒤 INDEX를 같은 커밋에서 갱신한다.
주간 통합과 읽기 전용 기억 점검은 별도 단계이며 이 키트는 예약 작업을 자동 등록하지 않는다.
