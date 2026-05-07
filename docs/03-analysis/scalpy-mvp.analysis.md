# Scalpy MVP Gap Analysis

> **Feature**: scalpy-mvp
> **Date**: 2026-05-07
> **Phase**: Check (PDCA)
> **Design**: [scalpy-mvp.design.md](../02-design/features/scalpy-mvp.design.md)
> **Plan**: [scalpy-mvp.plan.md](../01-plan/features/scalpy-mvp.plan.md)

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 수동 스캘핑의 속도/판단 한계 극복 + 다양한 전략을 체계적으로 비교 테스트 |
| **WHO** | 개인 투자자 (본인), 스캘핑 초보 |
| **RISK** | 실거래 시 예기치 못한 손실 발생 가능. 모의투자 우선 검증 필수 |
| **SUCCESS** | 모의투자 환경에서 5개 전략이 독립적으로 동작하고, 2~3종목 동시 운용 가능 |
| **SCOPE** | MVP: 국내 주식 전용, 로컬 실행, 알림 제외 |

---

## 1. Overall Match Rate

```
Overall = (Structural × 0.2) + (Functional × 0.4) + (Contract × 0.4)
        = (94.4 × 0.2) + (80 × 0.4) + (85 × 0.4)
        = 18.88 + 32.0 + 34.0
        = 84.9%
```

| Category | Score | Status |
|----------|:-----:|:------:|
| Structural Match | 94.4% | OK |
| Functional Depth | 80.0% | Warning |
| API Contract | 85.0% | Warning |
| **Overall** | **84.9%** | **Warning** |

---

## 2. Structural Match (94.4%)

Design §11.1 파일 목록 대비 구현 파일 존재 여부.

| 결과 | 개수 |
|------|:----:|
| PASS | 34/36 |
| FAIL | 2/36 |

### Missing Files

| # | File | Severity | Notes |
|---|------|----------|-------|
| 1 | `src/scalpy/broker/kis.py` | Critical | KIS 실거래 브로커 구현체 미작성 |
| 2 | `tests/conftest.py` | Minor | 공유 테스트 fixture |

---

## 3. Functional Depth (80.0%)

### Fully Matched (100%)

- Core 모델 (Signal, Order, Position, TradeRecord): 모든 필드 일치
- Enums (Side, OrderType, OrderStatus, MarketPhase): 모든 값 일치
- Error Hierarchy: 8개 예외 클래스 전체 일치
- DB Schema: 3 테이블, 모든 컬럼/인덱스 일치
- BaseStrategy ABC: 인터페이스 완전 일치
- BaseBroker ABC: 인터페이스 완전 일치
- 5개 전략 구현: 실제 알고리즘 로직 포함

### Partial Match

| Module | Score | Gap |
|--------|:-----:|-----|
| `broker/kis.py` | 0% | 파일 자체 미존재 |
| `data/stream.py` | 40% | 콜백 구조만 존재, 실제 WebSocket 연결 없음 |
| Dashboard | 60% | Main 페이지만 구현, Strategy/History/Settings 3페이지 미구현 |
| `main.py` | 85% | MockBroker 하드코딩, KIS 선택 로직 없음 |

---

## 4. API Contract (85.0%)

### 완전 일치

- BaseStrategy ABC (§4.1): 3 메서드 모두 일치
- BaseBroker ABC (§4.2): 7 메서드 모두 일치
- TradingEngine 의존성 와이어링: 정상

### 시그니처 차이 (Design 개선 필요)

| Method | Design | Implementation | Impact |
|--------|--------|----------------|--------|
| `RiskManager.check_stop_loss` | `(position, config: RiskConfig)` | `(position)` — self 속성 사용 | Minor (개선) |
| `RiskManager.check_take_profit` | `(position, config: RiskConfig)` | `(position)` — self 속성 사용 | Minor (개선) |
| `RiskManager.get_max_position_size` | `(symbol, balance)` | `(symbol, balance, price)` | Minor (Design 누락 수정) |

---

## 5. Plan Success Criteria 평가

### 5.1 Definition of Done (Plan §4.1)

| # | 기준 | 상태 | 근거 |
|---|------|:----:|------|
| 1 | 5개 전략이 독립적으로 매수/매도 신호 생성 | ⚠️ Partial | 5개 전략 로직 구현 완료 + 테스트 통과. 단 실제 데이터 소스(WebSocket) 미연결 |
| 2 | 2~3종목 동시 시세 수신 및 주문 실행 | ⚠️ Partial | settings.toml에 2종목 설정, engine이 종목별 처리. 실제 수신 불가 |
| 3 | 손절/익절 설정 시 자동 청산 | ✅ Met | `RiskManager` + `TradingEngine._check_risk/_force_close` + 테스트 |
| 4 | 체결 이력 PostgreSQL 저장 | ✅ Met | `TradeRepository.save_trade()` + `schema.py` + docker-compose |
| 5 | Streamlit 대시보드 실시간 포지션/수익률 | ⚠️ Partial | 4개 컴포넌트 구현. TradingEngine↔Dashboard 데이터 연결 없음 |
| 6 | 전략 추가 시 모듈만 추가하면 동작 | ✅ Met | StrategyRegistry 패턴 + `build_registry()` |

### 5.2 Quality Criteria (Plan §4.2)

| # | 기준 | 상태 | 근거 |
|---|------|:----:|------|
| 1 | 타입 힌트 100% (mypy strict) | ⚠️ Partial | 34 파일 중 1 파일(`data/schema.py`)에서 7 에러 |
| 2 | 핵심 로직 유닛 테스트 | ✅ Met | 31 tests, all passed |
| 3 | 린트 에러 0 (ruff) | ❌ Not Met | 8 에러 (import 정렬, StrEnum, 미사용 import) |
| 4 | 빌드/실행 성공 | ✅ Met | 통합 테스트 통과 |

---

## 6. Runtime Verification Results

| Check | Result | Details |
|-------|:------:|---------|
| pytest | ✅ 31 passed | 0 failures, 0.12s |
| mypy strict | ⚠️ 7 errors | `data/schema.py` Numeric 타입 파라미터 누락 |
| ruff | ⚠️ 8 errors | import 정렬, str+Enum→StrEnum, 미사용 import |

---

## 7. Gap List (Severity Order)

### Critical (구현 필수)

| # | Gap | Design Ref | File |
|---|-----|-----------|------|
| G-01 | KIS Broker 구현체 미존재 | §11.1, Plan FR-01/02 | `broker/kis.py` |
| G-02 | MarketDataStream에 실제 WebSocket 연결 없음 | §2.2 | `data/stream.py` |

### Important (품질 향상)

| # | Gap | Design Ref | File |
|---|-----|-----------|------|
| G-03 | main.py에 KIS/Mock 브로커 선택 로직 없음 | Plan FR-15 | `main.py` |
| G-04 | Dashboard Strategy 페이지 미구현 | §5.2 | — |
| G-05 | Dashboard History 페이지 미구현 | §5.2 | — |
| G-06 | Dashboard Settings 페이지 미구현 | §5.2 | — |
| G-07 | TradingEngine→Dashboard 데이터 브릿지 없음 | §2.1 | — |
| G-08 | Integration 테스트 미작성 (Broker flow, DB) | §8.1 | `tests/` |
| G-09 | 에러 핸들링 정책 미적용 (토큰 갱신, 재연결) | §6.2 | — |
| G-10 | mypy strict 에러 7건 | Plan §4.2 | `data/schema.py` |
| G-11 | ruff 린트 에러 8건 | Plan §4.2 | 다수 파일 |

### Minor

| # | Gap | Design Ref | File |
|---|-----|-----------|------|
| G-12 | RiskManager 시그니처 Design과 차이 (개선) | §4.3 | Design 문서 업데이트 필요 |
| G-13 | conftest.py 미존재 | Plan §7.3 | `tests/` |

---

## 8. Recommended Actions

1. **G-10, G-11 즉시 수정 가능** — mypy/ruff 에러는 코드 변경으로 즉시 해결
2. **G-01, G-02는 API 키 필요** — 한투 API 키 발급 후 구현 가능
3. **G-04~G-06** — Dashboard 추가 페이지는 별도 세션에서 구현 권장
4. **G-12** — Design 문서 업데이트 (구현이 더 나은 설계)
