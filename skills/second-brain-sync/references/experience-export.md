# 검토한 경험만 개인으로 전달

이 기능은 업무 원본과 개인 본문을 분리한다. 설치 config의 work와 personal이 서로 독립된 저장소여야 한다.
반출 가능한지 조직 기준을 확인하고, 개인 보관과 공개 게시 승인을 구분한다.
도구의 패턴 검사만으로 공개 가능성을 판단하지 않는다.

## 후보와 고정 검토본

업무 쪽 linked worktree에서 experience_export.py catalog를 조회한다.
중복되지 않는 주제를 일반화해 propose한다. sources와 review_notes는 업무 저장소에만 남는다.
본문에는 고객·동료·내부 URL·티켓·비공개 구조·실제 식별자를 넣지 않는다.
예제가 필요하면 새 가상 예제임을 밝힌다. 검증하지 않은 성과나 완료 상태를 만들지 않는다.

```json
{"id":"example-topic","expected":"catalog의 해시 또는 빈 문자열의 SHA256","project":"상위-id","kind":"learning","title":"일반화한 제목","body":"검토할 본문","sources":["projects/example.md"],"review_notes":"근거 수준·제외한 정보·남은 확인"}
```

propose/review/reopen/release는 JSON 표준 입력이다. review는 개인에게 전달할 정확한 Markdown과 review_hash를 고정한다.
본문 링크를 사용자에게 제시하고 특정 검토본의 개인 보관 승인을 받은 뒤에만 release한다.
review 상태 수정은 reopen → propose → 새 review이며 기존 승인을 재사용하지 않는다.
exported 후보와 사용자가 수정한 개인 문서를 자동 덮어쓰지 않는다.

```json
{"id":"example-topic","review_hash":"사용자가 확인한 본문 해시","approved_for":"personal-storage","approval_source":"실제 승인 발언과 날짜"}
```

개인도 별도 linked worktree를 만들고 --personal-checkout으로 지정한다. 원본·프로젝트 등록부·출처·검토 메모는 복사하지 않는다.
블로그는 <topic>-ko와 <topic>-en 쌍을 준비하며 두 언어의 주장·근거·한계를 일치시킨다.
경력은 원래 일한 회사별로 분류한다. companies/bind-company로 명시된 연결을 확인하며 현재 회사로 과거 소속을 추정하지 않는다.
반영 뒤 양쪽 brain check와 각 저장소 Git 절차를 따른다. 게시·외부 업로드는 별도 명시적 요청이 필요하다.
