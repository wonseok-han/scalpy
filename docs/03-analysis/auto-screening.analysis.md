# Auto Screening Gap Analysis

> Match Rate: **95%** → Gap 수정 후 **98%**

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 수동 종목 설정은 스캘핑 기회를 놓치게 하고, 완전 자동화를 가로막는 병목 |
| **WHO** | 개인 투자자 (프로젝트 소유자) — 서버 구동 후 방치형 자동매매 희망 |
| **RISK** | KIS API 호출 제한 (초당 20건), WebSocket 구독 20종목 제한 |
| **SUCCESS** | 수동 종목 설정 없이 자동 종목 선별 → 전략 신호 → 매매 파이프라인 완성 |
| **SCOPE** | Screener 모듈 신규 + TradingEngine/main.py 연동 |

## Match Rate

| Category | Score |
|----------|:-----:|
| Structural Match | 100% |
| Functional Depth | 98% |
| API Contract | 100% |
| **Overall** | **98%** |

## Success Criteria

| ID | 기준 | 결과 | 증거 |
|----|------|:----:|------|
| SC-1 | 종목코드 없이 자동 선별 매매 | ✅ | `main.py:119-136` screening 분기 |
| SC-2 | 5종목 이내 선별 | ✅ | `screener.py:39-41` slot 계산 |
| SC-3 | 주기적 재스크리닝 + 동적 교체 | ✅ | `main.py:73-96` + `stream.py:182-215` |
| SC-4 | 포지션 보유 종목 유지 | ✅ | `screener.py:28-41` held 포함 |
| SC-5 | API 호출 제한 준수 | ✅ | `kis.py:192` sleep + 429 재시도 |

## 수정된 Gap

| # | 내용 | 수정 |
|---|------|------|
| 1 | KIS rate limit 재시도 로직 없음 | 429 응답 시 sleep(1) + 최대 3회 재시도 추가 |
| 2 | WebSocket 개별 종목 에러 처리 없음 | 종목별 try/except로 부분 실패 허용 |
| 3 | engine.py 캡슐화 위반 | `_positions._positions` → `_positions.all()` |

## 테스트 결과

- 전체: 44개 통과 (기존 36 + 신규 8)
- 실패: 0개
