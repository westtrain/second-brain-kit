# 검색 평가와 선택적 QMD

기본 검색, QMD 키워드 검색, QMD 의미 검색을 같은 질문·근거로 비교한다. MCP 없이도 실행할 수 있다.
자동 평가 후보 생성이나 실제 자료 수집은 수행하지 않는다. 공개 예제는 모두 가상 기록이다.

## 추가 설치 없이 평가하기

```bash
python3 scripts/evaluate_search.py --root examples/search-eval/work --scope work \
  --dataset examples/search-eval/cases.json --split development
python3 scripts/evaluate_search.py --root examples/search-eval/work --scope work \
  --dataset examples/search-eval/cases.json --split test
```

개인용 예제는 root를 examples/search-eval/personal, scope를 personal로 바꾼다.
development는 개선용, test는 마지막 검증용이다. 한 번에 하나의 split만 선택한다.
공개 가상 평가셋은 기능 예제이며 비공개 벤치마크가 아니다. 일반적인 한국어 품질의 증거로 사용하지 않는다.

| 지표 | 의미 |
|---|---|
| hit_rate_at_k | 정답 문서가 하나 이상 상위 k개 안에 있는 양성 질문 비율 |
| recall_at_k | 질문별 정답 문서 중 상위 k개에서 찾은 비율의 평균 |
| mrr_at_k | 첫 정답 순위의 역수 평균. 없으면 0 |
| evidence_coverage_at_k | 정답 근거 구절까지 반환된 발췌에 포함된 비율의 질문별 평균 |
| no_answer_accuracy | 정답 문서가 없는 질문에 결과를 반환하지 않은 비율 |
| boundary_violations | forbidden_paths 또는 다른 scope의 결과가 반환된 건수 |

해당 종류의 질문이 없으면 지표는 null이다. 조회 실패를 빈 결과로 바꾸지 않고 평가를 중단한다.
boundary_violations가 있으면 종료 코드 1이다. 낮은 검색 점수 자체는 실패 종료가 아니라 개선할 측정값이다.
이 평가는 **검색과 발췌**를 측정한다. 답변 정확성·최신 상태 판단·OS 권한을 증명하지 않는다.
현재 상태가 다른 정본/세션/과거 기록 사례도 포함하지만, 의미 판단은 snapshot 기반 답변 검증으로 별도 확인해야 한다.

## 내 평가셋 만들기

[평가 후보 템플릿](../templates/search-evaluation.md)을 사용해 사용자 요청 범위에서 후보를 만든다.
사진 예시처럼 id, query, category, split, relevant_paths, evidence를 두고 scope와 review_status를 추가했다.
모델이 만든 후보는 candidate로 보관하고 질문·정답·정확한 근거를 검토한 뒤 reviewed로 바꾼다.
실제 질문을 섞고, 문서와 표현이 같은 쉬운 문제에만 맞추지 않는다. test의 정답을 보며 튜닝하면 별도 검증용 질문을 새로 확보한다.

```bash
python3 scripts/evaluate_search.py --root ~/brains/my-second-brain/work --scope work \
  --dataset ~/brains/my-second-brain/evaluation-local/work-cases.json --split development --validate-only
```

개인/업무 평가셋은 각 보관 범위를 따른다. 실제 질문·근거·경로·평가 결과에도 정보가 들어간다.
공개 킷에는 가상 예제만 둔다. evidence가 원문에 없거나 범위 밖 경로·중복 ID·미검토 후보가 있으면 평가를 거부한다.

## QMD는 선택 사항

[QMD](https://github.com/tobi/qmd)는 로컬 키워드·벡터·재정렬 검색을 제공한다. 설치와 모델 사용은 사용자가 선택한다.
킷은 QMD를 자동 설치하거나 인덱스를 만들지 않는다. 어댑터는 지정한 인덱스·collection만 조회하고 원본을 다시 읽는다.
`qmd-keyword`는 BM25 검색, `qmd-hybrid`는 QMD의 의미 검색·질의 확장·재정렬을 사용한다.
후자는 모델 다운로드·디스크·메모리·실행 시간이 추가로 필요하다. 기본 Python 도구에는 영향을 주지 않는다.

아래는 별도 설치한 QMD 2.8.3 CLI 기준이다. 실제 파일을 인덱싱하기 전 회사 정책과 범위를 확인한다.

```bash
# 개인과 업무는 서로 다른 named index를 사용한다. 이름만 다르고 같은 DB를 공유하지 않게 구성한다.
qmd --index second-brain-work collection add ~/brains/my-second-brain/work --name work
qmd --index second-brain-work update
# 의미 검색이 필요할 때만 모델과 임베딩 생성
qmd --index second-brain-work embed

python3 scripts/brain_access.py --root ~/brains/my-second-brain/work --scope work \
  --qmd-index second-brain-work --qmd-collection work --backend qmd-keyword '문서 검토'
```

인덱스 안에는 본문·벡터·경로·검색 캐시가 들어간다. 개인용·업무용 DB/설정을 분리하고 공개 저장소·일반 백업에 섞지 않는다.
인덱싱 대상의 Markdown 패턴과 ignore를 검토해 실제로 필요한 문서만 포함한다. 갱신 hook에 git pull 같은 명령을 자동 등록하지 않는다.
QMD 업데이트 명령·모델 다운로드는 MCP에서 제공하지 않는다. 운영자가 선택한 환경에서 별도로 수행한다.

QMD 검색 평가에는 기존 명령에 다음 옵션을 추가한다.

```bash
python3 scripts/evaluate_search.py --root examples/search-eval/work --scope work \
  --dataset examples/search-eval/cases.json --split development \
  --qmd-index synthetic-work --qmd-collection work --backend qmd-keyword
```

이 예제는 synthetic-work/work collection을 가상 work 폴더로 **별도 생성한 뒤** 실행한다.
literal과 같은 root·scope·split·k로 비교한다. 답변이 없는 질문도 결과가 나올 수 있으므로 높은 재현율만으로 도입을 결정하지 않는다.

MCP에 연결하려면 mcp_config.py 명령에 `--qmd-index second-brain-work --qmd-collection work`를 추가한다.
이 설정도 한 scope만 연결한다. 검색 범위 필터는 OS 권한을 대신하지 않는다.

## 오래된 인덱스와 결과 검증

수정/삭제 후 QMD의 update, 의미 검색에는 필요한 embed 갱신을 수행한다. 인덱스는 정본이 아니며 Git에 포함하지 않는다.
QMD가 반환한 본문·발췌는 신뢰하지 않는다. 허용 경로를 확인한 뒤 선택한 브레인의 원본에서 본문·해시를 새로 읽는다.
범위 밖 경로와 해석할 수 없는 QMD URI는 거부하고, 제외한 archive/inbox와 삭제된 문서는 결과에서 제거한다.
반대로 아직 색인되지 않은 문서는 찾지 못할 수 있다. 최신 pending 조회는 반드시 project_snapshot을 사용한다.
