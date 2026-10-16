# 기여

버그 보고와 PR을 환영합니다. 테스트는 Python 표준 라이브러리와 Git으로 실행할 수 있습니다.
변경용 브랜치를 만들고 관련 테스트, brain.py check, memory_tools.py index --check를 통과시켜 주세요.
새 문서를 추가했다면 linked worktree에서 INDEX를 재생성하세요.
실제 기록·기기 경로·계정 설정·자격증명 대신 최소 가상 재현 사례를 사용하세요.
초기 공개 이력에는 도구·공통 지침·빈 등록부·가상 테스트만 포함합니다.
기여한 코드는 이 프로젝트의 MIT 라이선스로 배포됩니다.

검색 평가는 examples/search-eval의 가상 자료만 기본 사용합니다. 실제 질문·정답·경로·연결 설정·검색 DB는 공개 PR에 포함하지 마세요.
MCP 변경은 별도 Python 환경에 requirements-mcp.txt를 설치하고 test_mcp_server.py를 실행합니다.
기본 테스트 환경에서는 SDK가 없는 MCP 전송 테스트만 skip되며, CI의 별도 MCP job에서는 실제 SDK 클라이언트로 실행합니다.
