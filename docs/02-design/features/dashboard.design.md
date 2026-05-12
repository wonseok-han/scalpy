# Dashboard Design

> Architecture: Option C — Pragmatic Balance

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 로그 기반 모니터링은 실시간성 부족, 긴급 제어 불가 |
| **WHO** | 개인 투자자 (프로젝트 소유자) — 외출 중에도 모니터링 필요 |
| **RISK** | 대시보드 API가 트레이딩 엔진 성능에 영향을 줄 수 있음 |
| **SUCCESS** | 브라우저에서 실시간 포지션 확인 + 긴급 정지 가능 + 텔레그램 알림 수신 |
| **SCOPE** | EventBus + FastAPI(SSE) + 프론트엔드 + 텔레그램 봇 |

## 1. Overview

단일 프로세스 내에서 TradingEngine과 FastAPI 대시보드를 공존시킨다.
EventBus가 엔진 이벤트를 대시보드/텔레그램에 전파하고, FastAPI는 별도 스레드에서 uvicorn으로 실행한다.

```
┌─────────────────────────────────────────────────┐
│  asyncio event loop (main thread)               │
│                                                 │
│  TradingEngine ──emit──> EventBus               │
│  MarketDataStream          │                    │
│  ScreeningLoop             ├──> DashboardState  │
│                            ├──> TelegramNotifier│
│                            └──> SignalLogger    │
│                                                 │
├─────────────────────────────────────────────────┤
│  uvicorn thread                                 │
│  FastAPI app ──read──> DashboardState           │
│              ──SSE───> Browser                  │
│              ──action─> Engine control          │
└─────────────────────────────────────────────────┘
```

## 2. Module Structure

### 2.1 신규 모듈

```
src/scalpy/
├── events/
│   ├── __init__.py          # EventBus export
│   └── bus.py               # EventBus — publish/subscribe
├── dashboard/               # 기존 Streamlit 코드 제거, FastAPI로 교체
│   ├── __init__.py
│   ├── server.py            # FastAPI app + uvicorn 스레드 실행
│   ├── routes.py            # REST API 엔드포인트
│   ├── sse.py               # SSE 스트리밍 엔드포인트
│   └── state.py             # DashboardState — 엔진 상태 스냅샷
├── notification/
│   ├── __init__.py
│   └── telegram.py          # TelegramNotifier
└── static/
    └── index.html           # 프론트엔드 (단일 HTML + htmx)
```

### 2.2 수정 모듈

| 파일 | 변경 |
|------|------|
| `src/scalpy/main.py` | EventBus 초기화, 대시보드 서버 시작, 텔레그램 초기화 |
| `src/scalpy/trading/engine.py` | 이벤트 emit (체결, 신호, 포지션 변경, 손절/익절) |
| `config/settings.toml` | `[default.dashboard]`, `[default.telegram]` 섹션 추가 |

## 3. EventBus Design

```python
class EventBus:
    """간단한 비동기 이벤트 버스. fire-and-forget 방식."""

    def subscribe(self, event_type: str, handler: Callable) -> None: ...
    def unsubscribe(self, event_type: str, handler: Callable) -> None: ...
    async def emit(self, event_type: str, data: dict) -> None: ...
```

### 이벤트 타입

| Event | Data | 발생 시점 |
|-------|------|-----------|
| `order.filled` | symbol, side, price, qty, strategy | 주문 체결 |
| `signal.generated` | symbol, side, strategy, price, confidence | 전략 신호 발생 |
| `position.opened` | symbol, qty, avg_price, strategy | 포지션 신규 |
| `position.closed` | symbol, qty, pnl, reason | 포지션 청산 (손절/익절 포함) |
| `engine.started` | — | 엔진 시작 |
| `engine.stopped` | — | 엔진 정지 |
| `screening.completed` | symbols, count | 스크리닝 완료 |
| `tick.received` | symbol, price, volume | 틱 수신 (state 업데이트용) |

### 성능 보장

- `emit()`은 fire-and-forget: `asyncio.create_task()`로 핸들러 실행
- 핸들러 예외는 로깅만 하고 전파하지 않음
- 엔진 코드에서 `await bus.emit()` 부분은 핸들러 완료를 기다리지 않음

## 4. API Design

### 4.1 REST Endpoints

| Method | Path | 설명 | Response |
|--------|------|------|----------|
| GET | `/api/status` | 엔진 상태 + 계좌 요약 | `{running, connected, balance, total_pnl}` |
| GET | `/api/positions` | 보유 포지션 목록 | `[{symbol, qty, avg_price, current_price, pnl, pnl_pct}]` |
| GET | `/api/screening` | 스크리닝 현황 | `{symbols, next_scan_at, config}` |
| GET | `/api/signals` | 최근 신호 로그 (최대 100건) | `[{time, symbol, side, strategy, price}]` |
| POST | `/api/actions/liquidate` | 전체 청산 | `{success, results: [{symbol, status}]}` |
| POST | `/api/actions/stop` | 엔진 정지 | `{success}` |
| POST | `/api/actions/start` | 엔진 재시작 | `{success}` |
| POST | `/api/actions/rescan` | 즉시 재스크리닝 | `{success, symbols}` |
| GET | `/api/events` | SSE 스트림 | `text/event-stream` |

### 4.2 SSE Events

```
event: tick
data: {"symbol": "005930", "price": 71500, "volume": 1234}

event: position
data: {"symbol": "005930", "qty": 100, "pnl": 500, "pnl_pct": 0.7}

event: signal
data: {"symbol": "005930", "side": "buy", "strategy": "ma_cross", "price": 71500}

event: order
data: {"symbol": "005930", "side": "buy", "price": 71500, "qty": 100, "status": "filled"}

event: screening
data: {"symbols": ["005930", "000660"], "count": 5}

event: engine
data: {"running": true}
```

## 5. DashboardState

```python
class DashboardState:
    """엔진 상태의 읽기 전용 스냅샷. EventBus 핸들러로 자동 업데이트."""

    positions: dict[str, PositionSnapshot]   # symbol → 현재 포지션
    signals: deque[SignalRecord]             # 최근 100건
    screening: ScreeningSnapshot             # 현재 스크리닝 상태
    engine_running: bool
    last_tick_at: datetime | None
    balance: Decimal
    daily_pnl: Decimal
```

- EventBus 핸들러로 자동 갱신
- FastAPI 라우트에서 읽기만 함 (thread-safe: GIL + 단순 dict 교체)
- SSE 핸들러도 이 state를 구독

## 6. TelegramNotifier

```python
class TelegramNotifier:
    """텔레그램 봇 알림. EventBus 구독자."""

    def __init__(self, token: str, chat_id: str) -> None: ...
    async def on_order_filled(self, data: dict) -> None: ...
    async def on_position_closed(self, data: dict) -> None: ...
    async def on_engine_state(self, data: dict) -> None: ...
```

- `httpx.AsyncClient`로 비동기 전송
- 실패 시 로그만 남기고 재시도 없음 (fire-and-forget)
- `telegram.enabled = false`이면 초기화 자체 건너뜀

### 메시지 형식

```
📈 매수 체결
종목: 삼성전자 (005930)
가격: 71,500원 × 100주
전략: ma_cross

🔻 손절 청산
종목: 카카오 (035720)
손익: -15,000원 (-2.1%)
```

## 7. Frontend (index.html)

단일 HTML 파일. htmx + SSE로 서버 푸시 수신.

### 레이아웃

```
┌─────────────────────────────────────────────┐
│  Scalpy Dashboard          [정지] [전체청산] │
├──────────────────────┬──────────────────────┤
│  계좌 요약            │  엔진 상태            │
│  잔고: 10,000,000원   │  ● 실행 중            │
│  평가: 10,250,000원   │  마지막 틱: 12:30:45  │
│  당일 손익: +250,000  │  종목: 5개            │
├──────────────────────┴──────────────────────┤
│  보유 포지션                                 │
│  ┌───────┬─────┬────────┬────────┬────────┐ │
│  │ 종목   │ 수량 │ 평균단가 │ 현재가   │ 손익   │ │
│  ├───────┼─────┼────────┼────────┼────────┤ │
│  │ 005930│ 100 │ 71,000 │ 71,500 │ +500   │ │
│  └───────┴─────┴────────┴────────┴────────┘ │
├─────────────────────────────────────────────┤
│  스크리닝 현황                [수동 스크리닝]  │
│  선별 종목: 005930, 000660, 035720 ...       │
│  다음 스크리닝: 13:00 (28분 후)              │
├─────────────────────────────────────────────┤
│  전략 신호 로그                              │
│  12:28:23 BUY  005930 ma_cross  71,500      │
│  12:28:20 SELL 035720 rsi       54,200      │
└─────────────────────────────────────────────┘
```

- CSS: 다크 테마, 모노스페이스
- htmx SSE: `<div hx-ext="sse" sse-connect="/api/events">`
- 제어 버튼: htmx POST → `/api/actions/*`

## 8. Settings

```toml
[default.dashboard]
enabled = true
host = "0.0.0.0"
port = 8080

[default.telegram]
enabled = false
bot_token = ""
chat_id = ""
```

## 9. Integration with main.py

```python
async def run() -> None:
    # ... 기존 코드 ...

    # EventBus 초기화
    bus = EventBus()
    engine.set_event_bus(bus)

    # Dashboard
    dashboard_cfg = settings.get("dashboard", {})
    if dashboard_cfg.get("enabled", False):
        state = DashboardState()
        state.register_handlers(bus)
        start_dashboard_server(state, engine, host, port)  # 별도 스레드

    # Telegram
    telegram_cfg = settings.get("telegram", {})
    if telegram_cfg.get("enabled", False):
        notifier = TelegramNotifier(token, chat_id)
        notifier.register_handlers(bus)
```

## 10. Test Plan

| ID | 테스트 | 유형 |
|----|--------|------|
| T-1 | EventBus publish/subscribe 동작 | Unit |
| T-2 | DashboardState 이벤트 수신 후 상태 갱신 | Unit |
| T-3 | REST API 응답 형식 | Unit |
| T-4 | SSE 스트림 이벤트 수신 | Integration |
| T-5 | 전체 청산 API → engine.force_close 호출 | Integration |
| T-6 | TelegramNotifier 메시지 전송 (mock httpx) | Unit |
| T-7 | 엔진 정지/재시작 API | Integration |

## 11. Implementation Guide

### 11.1 구현 순서

| 순서 | 모듈 | 파일 | 의존성 |
|------|------|------|--------|
| 1 | EventBus | `events/bus.py` | 없음 |
| 2 | DashboardState | `dashboard/state.py` | EventBus |
| 3 | FastAPI 서버 + 라우트 | `dashboard/server.py`, `routes.py`, `sse.py` | DashboardState |
| 4 | 프론트엔드 | `static/index.html` | API 엔드포인트 |
| 5 | TelegramNotifier | `notification/telegram.py` | EventBus |
| 6 | Engine 이벤트 emit 연동 | `trading/engine.py` 수정 | EventBus |
| 7 | main.py 통합 | `main.py` 수정 | 전체 |

### 11.2 의존성 추가

```
pip install fastapi uvicorn httpx
```

`pyproject.toml`에 추가:
```toml
dependencies = [
    ...,
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "httpx>=0.27",
]
```

### 11.3 Session Guide

| Session | 모듈 | 예상 시간 |
|---------|------|-----------|
| module-1 | EventBus + DashboardState | 30분 |
| module-2 | FastAPI 서버 + REST API + SSE | 45분 |
| module-3 | 프론트엔드 (index.html) | 30분 |
| module-4 | TelegramNotifier | 20분 |
| module-5 | Engine 연동 + main.py 통합 | 30분 |
