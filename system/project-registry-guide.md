# 프로젝트 소속

project-registry.json은 상위 프로젝트 ID·목적·별칭·소속 session_groups의 기준이다.
같은 저장소·기술·폴더라는 이유로 관계를 추정하지 않는다. 새 등록은 sync_workflow.py register를 사용한다.
분명한 기존 하위 작업 연결만 bind로 추가하며 다른 프로젝트의 관계를 가져오지 않는다.
catalog의 expected_registry와 snapshot의 expected를 읽은 후 변경한다.
