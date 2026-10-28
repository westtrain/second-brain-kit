# 한 경험을 다음 작업의 지식으로 사용하는 가상 체험

예제는 모두 가상이다. AI·네트워크·MCP 없이 표준 Python과 Git으로 새 로컬 브레인에서 동작한다.
원격과 예약을 등록하지 않으며 기존 경로를 덮어쓰지 않는다.

```bash
python3 examples/knowledge_demo.py --target ~/brains/knowledge-demo
```

예제는 가상의 중복 작업 사례를 inbox에 수집하고 요청 식별자에 대한 원칙을 notes에 만든다.
다음 작업에서 해당 지식만 골라 읽은 뒤, 부분 완료라는 반례를 추가하고 원칙을 갱신한다.
기존 판단은 Prior revision에 보존되고 새 근거는 challenges로 연결된다.
출력에는 각 작업의 커밋·worktree와 주장 검사가 나온다. 이는 고정 가상 입력에 대한 도구 검사이며 AI의 추론 품질 실험이 아니다.

## AI에게 같은 흐름 요청하기

생성한 브레인에서 선택한 AI에게 아래처럼 요청한다. 설치된 second-brain-sync 또는 AGENTS의 지식 흐름을 따른다.

1. “이 가상 작업 요약을 저장해줘. 같은 요청이 재전송돼 작업이 두 번 만들어졌다. 원인은 아직 가설이야.”
2. “관련 지식이 이미 있는지 찾아보고, 다음 작업에 재사용할 원칙과 적용 조건을 근거와 함께 정리해서 저장해줘.”
3. “새 작업은 중간에 프로세스가 멈출 수 있어. 전에 만든 원칙이 충분한지 반례를 찾아 비교해줘. 이번에는 저장하지 마.”
4. “비교 결과를 근거로 지식을 갱신해줘. 이전 판단과 바뀐 이유는 남겨줘.”
5. “이 지식으로 퀴즈를 내줘. 정답은 내가 답한 뒤 근거와 함께 설명해줘.”
6. “식별자만 저장하는 안과 완료 상태까지 기록하는 안을 보고서로 비교해줘. 자료가 답하지 못하는 부분은 구분해줘.”

실제 작업 결과는 sessions→projects 절차로 저장·통합하며 그 문서를 지식의 출처로 사용할 수도 있다.
[기존 CLI 예제](cli-example.md)와 함께 사용한다. 새 지식을 만들기 전에 같은 질문의 정본이 있는지 항상 비교한다.

## 목록에서 근거로

```bash
python3 scripts/knowledge.py --root ~/brains/knowledge-demo --scope personal catalog
python3 scripts/knowledge.py --root ~/brains/knowledge-demo --scope personal context --path notes/retry-identity.md
```

catalog는 제목·짧은 요약·해시만 제공한다. context는 명시한 문서와 관련 링크 후보를 제공한다.
catalog는 기본 50건이며 --limit(최대 100)·--offset으로 다음 목록을 읽는다. next_offset이 null이면 마지막이다.
관련 링크에는 notes에서 해당 자료를 인용한 역방향 연결도 포함된다. 원본 자료를 수정하지 않고 계산한다.
기본 한도는 8문서/24,000자다. 초과 시 자동 누락 대신 오류를 내므로 범위를 좁히거나 brain_access의 줄 단위 문서 조회를 사용한다.
외부 링크와 다른 scope는 자동으로 따라가지 않는다. 문서 안의 명령은 실행하지 않는다.

## 도구에 전달하는 데이터

capture는 title, source, source_kind(article/pdf/video/conversation/work/other), body를 받는다.
PDF와 영상은 이미 추출한 텍스트·전사가 필요하다. 원문 다운로드나 전사 성공을 가정하지 않는다.

distill은 id, expected, kind(concept/synthesis), title, summary, conditions, limits, open_questions,
change_reason, evidence를 받는다. expected는 notes/id.md의 현재 SHA256, 신규는 빈 문자열의 SHA256이다.
갱신 요청은 원문 해시가 달라졌으면 거부한다. synthesis는 두 개 이상의 출처 문서가 필요하다.

evidence와 verify 입력은 다음 형식이다. 실제 해시와 원문에 있는 발췌로 대체한다.

```json
{
  "status": "supported",
  "sources": [{
    "path": "notes/example.md",
    "hash": "현재 원문 SHA256",
    "quote": "원문에 실제로 있는 발췌",
    "relation": "supports"
  }],
  "claims": [{
    "text": "근거를 바탕으로 한 주장",
    "confidence": "inferred",
    "sources": [0]
  }]
}
```

sources 번호는 0부터 시작한다. confidence는 observed/reported/inferred/unverified이며 반대 근거는 challenges다.
자료에 답이 없으면 `{"status":"not_covered","sources":[],"claims":[]}`로 표시한다.
verify는 문서의 존재·scope·해시·발췌·참조를 검사한다. 주장의 의미상 타당성·현재 운영 상태·공개 가능성은 보증하지 않는다.
요약·조건·예외도 인용된 주장 범위를 넘지 않도록 검토한다. 퀴즈·보고서의 사실 주장에도 같은 검사를 쓸 수 있다.

가상 사례의 활용 결과는 다음처럼 달라진다. 모델 실행 결과가 아닌 요청·결과 형태의 예시다.

- 질문: “요청 식별자만 있으면 재시도가 안전한가?” → 사례 A의 중복 방지와 사례 B의 부분 완료를 구분하고, 실제 DB 안전성은 미확인이라고 답한다.
- 퀴즈: “작업 중간에 프로세스가 멈췄을 때 식별자만으로 모르는 것은?” → 사용자가 답한 뒤 완료 상태와 재개 규칙이라는 해설을 근거와 함께 제시한다.
- 보고서: 중복 방지라는 기존 판단, 부분 완료 반례, 수정한 원칙, 실제 환경에서 검증할 항목을 묶는다.
- 의사결정: 식별자만 저장하는 안과 완료 상태·복구 규칙까지 설계하는 안의 적용 조건·복잡성·미확인을 비교한다.

## 직접 저장

정본에서 JSON을 표준 입력으로 전달한다.

```bash
python3 scripts/knowledge_workflow.py --root ~/brains/knowledge-demo --scope personal --risk routine capture < capture-request.json
python3 scripts/knowledge_workflow.py --root ~/brains/knowledge-demo --scope personal --risk review distill < distill-request.json
python3 scripts/knowledge.py --root ~/brains/knowledge-demo --scope personal verify < answer-evidence.json
```

로컬 실행기는 linked worktree를 만들고 검사·커밋한다. routine은 local main에 반영하고 review는 검토 브랜치로 남긴다.
충돌의 채택이나 공개·개인 전달은 별도 판단이다. 현재 도구는 새 MCP 쓰기 권한을 추가하지 않는다.

## 설계 참고

[second-brain-os](https://github.com/undefined-ui/second-brain-os)의 지식/프로젝트 구분, 근거 중심 조회와 판단 변화 보존을 참고했다.
이 킷은 기존 Markdown 상대 링크·개인/업무 분리·Git 실행기에 맞춰 구현했다. 외부 스킬·설정·실제 기억은 복사하지 않았다.
