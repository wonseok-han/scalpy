# Auto Screening Design

> Architecture: **Option C — Pragmatic Balance**

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 수동 종목 설정은 스캘핑 기회를 놓치게 하고, 완전 자동화를 가로막는 병목 |
| **WHO** | 개인 투자자 (프로젝트 소유자) — 서버 구동 후 방치형 자동매매 희망 |
| **RISK** | KIS API 호출 제한 (초당 20건), WebSocket 구독 20종목 제한, 스크리닝 품질이 수익에 직결 |
| **SUCCESS** | 수동 종목 설정 없이 자동 종목 선별 → 전략 신호 → 매매 파이프라인 완성 |
| **SCOPE** | Screener 모듈 신규 + TradingEngine/main.py 연동. 전략/브로커 모듈은 변경 없음 |

---

## 1. Overview

`screening/screener.py` 단일 모듈에 스크리닝 로직을 집중하고, 기존 모듈(kis.py, stream.py, main.py)에 최소한의 변경을 가하는 구조.

```
KIS REST API ──→ Screener.scan() ──→ 상위 5종목
                    │                      │
                    │ (거래량 조회)          │ (결과)
                    │ (변동성 필터)          ↓
                    │               main.py: update_symbols()
                    │                  │           │
                    │                  ↓           ↓
                    │            Stream.update()  Engine에 반영
                    │
                    └──→ 30분~1시간 주기 반복 (asyncio.create_task)
```

## 2. Module Structure

### 2.1 신규 파일

| 파일 | 역할 |
|------|------|
| `src/scalpy/screening/__init__.py` | 패키지 초기화 |
| `src/scalpy/screening/screener.py` | 스크리닝 핵심 로직 (조회 + 필터 + 점수화 + 선별) |

### 2.2 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/scalpy/broker/kis.py` | `get_top_volume_stocks()` 메서드 추가 |
| `src/scalpy/broker/base.py` | `get_top_volume_stocks()` 추상 메서드 추가 |
| `src/scalpy/broker/mock.py` | `get_top_volume_stocks()` mock 구현 |
| `src/scalpy/data/stream.py` | `update_subscriptions()` 메서드 추가 |
| `src/scalpy/trading/engine.py` | `update_symbols()` 메서드 추가 |
| `src/scalpy/main.py` | Screener 초기화 + 주기적 실행 루프 |
| `config/settings.toml` | `[default.screening]` 섹션 추가 |

## 3. Detailed Design

### 3.1 Screener (`src/scalpy/screening/screener.py`)

```python
class StockScreener:
    def __init__(
        self,
        broker: BaseBroker,
        max_stocks: int = 5,
        min_volatility: float = 0.02,
        min_volume: int = 100_000,
    ) -> None: ...

    async def scan(self, held_symbols: list[str] | None = None) -> list[str]:
        """스크리닝 실행. held_symbols는 교체 대상에서 제외."""

    def _filter_by_volatility(self, stocks: list[dict]) -> list[dict]:
        """변동성 임계값 이상 필터."""

    def _score_and_rank(self, stocks: list[dict]) -> list[str]:
        """거래량×변동성 복합 점수로 정렬, 상위 N개 반환."""
```

**스크리닝 알고리즘:**
1. `broker.get_top_volume_stocks()` → 거래량 상위 30종목 + 시세 정보
2. 변동성 필터: `(고가 - 저가) / 시가 >= min_volatility` (기본 2%)
3. 거래량 필터: `거래량 >= min_volume` (기본 10만주)
4. 복합 점수: `score = normalized_volume × 0.6 + normalized_volatility × 0.4`
5. 상위 `max_stocks`개 선별
6. `held_symbols`가 있으면 해당 종목은 결과에 무조건 포함 (슬롯 차지)

### 3.2 Broker 확장

#### `BaseBroker` (추상 메서드 추가)

```python
@abstractmethod
async def get_top_volume_stocks(self, count: int = 30) -> list[dict]:
    """거래량 상위 종목 조회. 반환: [{"symbol": str, "volume": int, "high": Decimal, "low": Decimal, "open": Decimal, "price": Decimal, "name": str}, ...]"""
```

#### `KISBroker.get_top_volume_stocks()`

- KIS REST API: **거래량순위 조회** (`/uapi/domestic-stock/v1/ranking/volume`)
- tr_id: `FHPST01710000` (모의/실거래 동일)
- 응답에서 `symbol`, `volume`, `high`, `low`, `open`, `price`, `name` 추출
- API 호출 간 `asyncio.sleep(0.1)` 으로 rate limit 준수

#### `MockBroker.get_top_volume_stocks()`

- 테스트용 고정 데이터 반환 (삼성전자, SK하이닉스 등 5종목)

### 3.3 MarketDataStream 확장

```python
async def update_subscriptions(self, new_symbols: list[str]) -> None:
    """기존 구독 해지 + 신규 구독. WebSocket 연결 유지."""
```

- 현재 구독 중인 종목 목록 유지 (`self._subscribed: set[str]`)
- 제거 대상: `current - new` → 구독 해지 메시지 전송 (tr_type="2")
- 추가 대상: `new - current` → 구독 메시지 전송 (tr_type="1")
- 각 메시지 간 `asyncio.sleep(0.05)` 으로 안정성 확보

### 3.4 TradingEngine 확장

```python
async def update_symbols(self, symbols: list[str]) -> None:
    """활성 종목 업데이트. 포지션 보유 종목은 자동 포함."""
```

- 현재 포지션 보유 종목 확인 → `held_symbols`
- `self._active_symbols = set(symbols) | set(held_symbols)`

### 3.5 main.py 통합

```python
async def _screening_loop(screener, engine, stream, interval_minutes):
    """주기적 스크리닝 루프."""
    while True:
        held = [s for s in engine.positions.all_symbols() if engine.positions.get(s)]
        new_symbols = await screener.scan(held_symbols=held)
        await stream.update_subscriptions(new_symbols)
        await engine.update_symbols(new_symbols)
        await asyncio.sleep(interval_minutes * 60)
```

- `settings.toml`에 `screening.enabled = true`이면 스크리닝 모드
- `screening.enabled = false`이면 기존 `symbols` 리스트 사용 (하위 호환)

### 3.6 settings.toml 추가

```toml
[default.screening]
enabled = true
max_stocks = 5
min_volatility = 0.02
min_volume = 100000
interval_minutes = 30
```

## 4. API Contract

### KIS REST API — 거래량순위

- **Endpoint**: `GET /uapi/domestic-stock/v1/ranking/volume`
- **tr_id**: `FHPST01710000`
- **Headers**: `authorization`, `appkey`, `appsecret`, `tr_id`, `custtype`
- **Query Params**: `FID_COND_MRKT_DIV_CODE=J`, `FID_INPUT_ISCD=0000`, `FID_DIV_CLS_CODE=0`, `FID_BLNG_CLS_CODE=0`, `FID_TRGT_CLS_CODE=111111111`, `FID_TRGT_EXLS_CLS_CODE=0000000000`, `FID_INPUT_PRICE_1=0`, `FID_INPUT_PRICE_2=0`, `FID_VOL_CNT=0`, `FID_INPUT_DATE_1=""`
- **Response**: `output[]` 배열, 각 항목에 `mksc_shrn_iscd`(종목코드), `data_rank`(순위), `acml_vol`(누적거래량), `stck_hgpr`(고가), `stck_lwpr`(저가), `stck_oprc`(시가), `stck_prpr`(현재가), `hts_kor_isnm`(종목명)

## 5. Error Handling

| 시나리오 | 처리 |
|----------|------|
| API 호출 실패 | 기존 종목 유지, 경고 로그, 다음 주기에 재시도 |
| 스크리닝 결과 0종목 | 기존 종목 유지, 경고 로그 |
| WebSocket 구독 교체 실패 | 부분 성공 허용, 실패 종목 로그 |
| rate limit 초과 | `asyncio.sleep(1)` 후 재시도 (최대 3회) |

## 6. Data Flow

```
[30분 주기 Timer]
    ↓
Screener.scan(held_symbols)
    ↓
KISBroker.get_top_volume_stocks(30)  ← KIS REST API
    ↓
_filter_by_volatility() → _score_and_rank()
    ↓
상위 5종목 + held_symbols
    ↓
MarketDataStream.update_subscriptions()
    ↓ (구독 해지 tr_type=2 → 신규 구독 tr_type=1)
TradingEngine.update_symbols()
    ↓
전략 엔진이 새 종목으로 신호 생성 시작
```

## 7. Test Plan

| ID | 테스트 | 유형 |
|----|--------|------|
| T-1 | Screener가 거래량 상위 5종목을 올바르게 선별 | Unit |
| T-2 | 변동성 필터가 임계값 미만 종목을 제외 | Unit |
| T-3 | held_symbols가 결과에 무조건 포함되는지 | Unit |
| T-4 | max_stocks 제한 준수 | Unit |
| T-5 | MockBroker로 전체 스크리닝→구독→매매 흐름 | Integration |
| T-6 | update_subscriptions에서 구독 해지/추가 정상 동작 | Unit |
| T-7 | 스크리닝 실패 시 기존 종목 유지 (fallback) | Unit |
| T-8 | screening.enabled=false일 때 기존 방식 동작 | Integration |

## 8. Implementation Guide

### 8.1 Implementation Order

1. `BaseBroker`에 `get_top_volume_stocks()` 추상 메서드 추가
2. `MockBroker`에 mock 구현
3. `KISBroker`에 실제 API 호출 구현
4. `screening/screener.py` 구현
5. `MarketDataStream.update_subscriptions()` 구현
6. `TradingEngine.update_symbols()` 구현
7. `main.py` 통합 (스크리닝 루프)
8. `settings.toml` 스크리닝 설정 추가
9. 단위/통합 테스트 작성

### 8.2 Dependencies

- 추가 패키지 없음 (기존 pykis + requests 활용)

### 8.3 Session Guide

| Module | 범위 | 예상 작업 |
|--------|------|-----------|
| module-1 | Broker 확장 + Screener 핵심 | steps 1-4 |
| module-2 | Stream/Engine 연동 + main.py 통합 | steps 5-8 |
| module-3 | 테스트 작성 | step 9 |
