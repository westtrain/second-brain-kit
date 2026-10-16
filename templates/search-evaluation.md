# 검색 평가 후보 만들기

사용자가 평가 후보 생성을 요청한 문서만 대상으로 다음 JSON 배열을 제안한다.
문서 저장만 요청한 경우 평가 기록을 자동 추가하지 않는다. 실제 질문도 함께 후보로 수집하되 사용자 요청 범위만 반영한다.

- 문서 표현 그대로인 질문과 실제 사용자가 할 법한 다른 표현을 섞는다.
- 답을 추측하지 않는다. relevant_paths에는 실제 근거 문서, evidence에는 본문의 정확한 구절을 넣는다.
- 답이 없는 질문은 relevant_paths=[]와 evidence={}로 표시한다.
- 과거 상태와 현재 상태가 다른 사례, 미통합 세션, 개인/업무 경계 사례를 포함한다.
- 검토 전 review_status는 candidate다. 사람이 근거·소유 범위를 확인한 사례만 reviewed로 바꾼다.
- development는 검색 개선용이다. test의 정답을 보며 검색을 조정하지 않고 마지막 검증에 사용한다.
- 실제 질문·정답·경로도 개인/회사 자료다. 해당 브레인에 따로 보관하며 공개 킷에 복사하지 않는다.

```json
[
  {
    "id": "example-001",
    "query": "가상 문서의 검토는 일 년에 몇 번인가요?",
    "category": "paraphrase",
    "scope": "work",
    "split": "development",
    "review_status": "candidate",
    "relevant_paths": ["notes/example-policy.md"],
    "evidence": {"notes/example-policy.md": "검토 주기: 연 2회"},
    "forbidden_paths": []
  }
]
```
