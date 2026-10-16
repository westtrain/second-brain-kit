---
status: confirmed
updated: 2026-01-15
source: synthetic evaluation fixture
---
# 중복 요청 처리

예약 생성의 멱등성 키를 검사해 재시도로 인한 중복 생성을 방지한다.
같은 키의 요청에는 최초 처리 결과를 반환한다.
