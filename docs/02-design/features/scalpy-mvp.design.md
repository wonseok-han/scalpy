# Scalpy MVP Design Document

> **Summary**: 한국투자증권 Open API 기반 국내 주식 자동 스캘핑 트레이딩 봇
>
> **Project**: Scalpy
> **Version**: 0.1.0
> **Author**: wonseok-han
> **Date**: 2026-05-07
> **Status**: Draft
> **Planning Doc**: [scalpy-mvp.plan.md](../../01-plan/features/scalpy-mvp.plan.md)

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

## 1. Overview

### 1.1 Design Goals

- 전략 모듈을 플러그인 방식으로 교체/비교 가능하게 설계
- asyncio 기반 비동기 처리로 WebSocket 수신과 주문 실행을 동시 처리
- 모의투자/실거래 전환이 설정 한 줄로 가능하도록 추상화
- 손절/익절 안전장치가 항상 활성화된 상태로 동작

### 1.2 Design Principles

- **Strategy Pattern**: 전략을 추상 클래스로 정의하고 레지스트리로 관리
- **Dependency Inversion**: broker/data 계층은 추상 인터페이스 기반으로 목 교체 가능
- **Fail-Safe Default**: 모의투자 모드 기본, 손절 로직 없으면 주문 거부

---

## 2. Architecture

### 2.0 Architecture Comparison

**Selected**: Option C (Pragmatic Balance) — 개인 MVP에 적합한 수준의 모듈 분리. 전략 플러그인은 확장 가능하면서 과도한 추상화 없음.

### 2.1 Component Diagram

```
┌──────────────────────────────────────────────────────────┐
│                     Streamlit Dashboard                   │
│              (실시간 시세, 포지션, 수익률)                  │
└──────────────────┬───────────────────────────────────────┘
                   │ reads
┌──────────────────▼───────────────────────────────────────┐
│                   Trading Engine (asyncio)                │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌────────────┐  │
│  │ Position │  │   Risk   │  │ Order  │  │  Strategy  │  │
│  │ Manager  │  │ Manager  │  │ Queue  │  │  Registry  │  │
│  └────┬─────┘  └────┬─────┘  └───┬────┘  └─────┬──────┘  │
│       │              │            │              │         │
└───────┼──────────────┼────────────┼──────────────┼────────┘
        │              │            │              │
┌───────▼──────────────▼────────────▼──────┐  ┌───▼───────┐
│            Broker (pykis)                │  │ Strategies│
│  ┌──────────┐  ┌───────────┐             │  │ ┌───────┐ │
│  │  Auth    │  │  WebSocket │             │  │ │MA Cross│ │
│  │  Token   │  │  Stream    │             │  │ │Bollinger│ │
│  └──────────┘  └───────────┘             │  │ │RSI     │ │
└──────────────────┬───────────────────────┘  │ │Orderbook│ │
                   │                          │ │VWAP    │ │
┌──────────────────▼──────────────────────┐   │ └───────┘ │
│          PostgreSQL (Docker)             │   └──────────┘
│  trades / positions / strategy_results   │
└──────────────────────────────────────────┘
```

### 2.2 Data Flow

```
Market Data (WebSocket) → Data Stream → Strategy Engine → Signal Generation
    → Risk Check (손절/익절 확인) → Order Queue → Broker API → Execution
    → Position Update → DB Storage → Dashboard Render
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| Trading Engine | Broker, Strategy, Data | 매매 루프 오케스트레이션 |
| Strategy | Core (models) | 시세 데이터로 매매 신호 생성 |
| Broker | Core (models), pykis | 한투 API 통신 |
| Data | Core (models), SQLAlchemy | DB 저장/조회 |
| Dashboard | Data, Trading Engine | 실시간 상태 표시 |
| Risk Manager | Core (models), Position | 손절/익절 판단 |

---

## 3. Data Model

### 3.1 Entity Definition

```python
@dataclass
class Signal:
    symbol: str
    side: Side           # BUY / SELL
    strategy: str        # 전략 이름
    price: Decimal
    quantity: int
    confidence: float    # 0.0 ~ 1.0
    timestamp: datetime

@dataclass
class Order:
    id: str
    symbol: str
    side: Side
    order_type: OrderType  # MARKET / LIMIT
    price: Decimal
    quantity: int
    status: OrderStatus    # PENDING / FILLED / CANCELLED / REJECTED
    strategy: str
    created_at: datetime
    filled_at: datetime | None

@dataclass
class Position:
    symbol: str
    side: Side
    quantity: int
    avg_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    strategy: str
    opened_at: datetime

@dataclass
class TradeRecord:
    id: str
    symbol: str
    side: Side
    price: Decimal
    quantity: int
    strategy: str
    pnl: Decimal
    executed_at: datetime
```

### 3.2 Enums

```python
class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"

class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

class MarketPhase(str, Enum):
    PRE_MARKET = "pre_market"
    OPEN = "open"
    CLOSE = "close"
    AFTER_HOURS = "after_hours"
```

### 3.3 Database Schema

```sql
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    price NUMERIC(15, 2) NOT NULL,
    quantity INTEGER NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    pnl NUMERIC(15, 2),
    executed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    quantity INTEGER NOT NULL,
    avg_price NUMERIC(15, 2) NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    realized_pnl NUMERIC(15, 2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE strategy_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    total_trades INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    total_pnl NUMERIC(15, 2) DEFAULT 0,
    max_drawdown NUMERIC(15, 2) DEFAULT 0,
    win_rate NUMERIC(5, 2) DEFAULT 0,
    date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_strategy ON trades(strategy);
CREATE INDEX idx_trades_executed_at ON trades(executed_at);
CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_strategy_results_date ON strategy_results(date);
```

---

## 4. Internal API (모듈 간 인터페이스)

### 4.1 Strategy Interface

```python
class BaseStrategy(ABC):
    name: str
    description: str

    @abstractmethod
    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        """체결 데이터 수신 시 호출. 매매 신호 반환 또는 None."""

    @abstractmethod
    async def on_orderbook(self, symbol: str, asks: list, bids: list) -> Signal | None:
        """호가 데이터 수신 시 호출."""

    def configure(self, params: dict) -> None:
        """설정 파일에서 전략별 파라미터 주입."""
```

### 4.2 Broker Interface

```python
class BaseBroker(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_balance(self) -> Decimal: ...

    @abstractmethod
    async def subscribe_market_data(self, symbols: list[str], callback) -> None: ...
```

### 4.3 Risk Manager Interface

```python
class RiskManager:
    def check_stop_loss(self, position: Position, config: RiskConfig) -> bool: ...
    def check_take_profit(self, position: Position, config: RiskConfig) -> bool: ...
    def validate_order(self, order: Order, balance: Decimal) -> bool: ...
    def get_max_position_size(self, symbol: str, balance: Decimal) -> int: ...
```

---

## 5. UI/UX Design (Streamlit Dashboard)

### 5.1 Screen Layout

```
┌─────────────────────────────────────────────────────────┐
│  Scalpy Dashboard          [모의투자] [실행중] [09:15:32]│
├──────────────────────┬──────────────────────────────────┤
│ 실시간 시세            │ 포지션 현황                      │
│ ┌──────────────────┐  │ ┌──────────────────────────────┐│
│ │ 삼성전자  72,500  │  │ │종목   수량  평단  수익률     ││
│ │ SK하이닉스 185,000│  │ │삼전   10   72,000  +0.7%  ││
│ │ 카카오    52,300  │  │ │SK     5    184,000 +0.5%  ││
│ └──────────────────┘  │ └──────────────────────────────┘│
├──────────────────────┼──────────────────────────────────┤
│ 전략 신호 로그         │ 수익률 차트                      │
│ [MA] 삼전 BUY 72,400  │ ┌──────────────────────────────┐│
│ [RSI] SK SELL 185,500 │ │ 📈 일별 수익률 그래프         ││
│ [BB] 카카오 HOLD      │ └──────────────────────────────┘│
├──────────────────────┴──────────────────────────────────┤
│ 전략별 성과                                              │
│ MA Cross: 12승 8패 (60%) | RSI: 8승 4패 (67%) | ...     │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Dashboard Pages

| Page | Route | Description |
|------|-------|-------------|
| Main | `/` | 실시간 시세 + 포지션 + 신호 로그 |
| Strategy | `/strategy` | 전략별 성과 비교, 파라미터 조정 |
| History | `/history` | 체결 이력 테이블, 필터링 |
| Settings | `/settings` | 종목/전략/손절 비율 설정 |

---

## 6. Error Handling

### 6.1 Error Hierarchy

```python
class ScalpyError(Exception): ...
class BrokerError(ScalpyError): ...
class AuthenticationError(BrokerError): ...
class OrderError(BrokerError): ...
class InsufficientBalanceError(OrderError): ...
class StrategyError(ScalpyError): ...
class DataError(ScalpyError): ...
class ConnectionError(DataError): ...
```

### 6.2 Error Handling Policy

| Error Type | Action | Logging |
|------------|--------|---------|
| AuthenticationError | 토큰 자동 갱신 후 재시도 (최대 3회) | WARNING |
| ConnectionError | 5초 간격 재연결 (최대 10회), 실패 시 포지션 안전 점검 | ERROR |
| OrderError | 주문 거부 로깅, 전략에 실패 알림 | ERROR |
| InsufficientBalanceError | 주문 스킵, 잔고 부족 알림 | WARNING |
| StrategyError | 해당 전략만 비활성화, 나머지 계속 동작 | ERROR |

---

## 7. Security Considerations

- [x] API 키/시크릿은 `.secrets.toml`에 저장 (gitignore 포함)
- [x] 모의투자 모드 기본값 (`KIS_MOCK=true`)
- [x] 실거래 전환 시 설정 파일에서만 가능 (CLI 인자로 전환 불가)
- [x] DB 연결 문자열 환경변수 분리
- [x] 주문 금액 상한선 설정 가능

---

## 8. Test Plan

### 8.1 Test Scope

| Type | Target | Tool | Phase |
|------|--------|------|-------|
| Unit | 전략 신호 생성 로직 | pytest | Do |
| Unit | 리스크 관리 (손절/익절 판단) | pytest | Do |
| Unit | 포지션 계산 (평균단가, 수익률) | pytest | Do |
| Integration | Broker mock → 주문 실행 흐름 | pytest | Do |
| Integration | DB 저장/조회 | pytest + testcontainers | Do |

### 8.2 Unit Test Scenarios

| # | Module | Test Description | Expected Result |
|---|--------|-----------------|-----------------|
| 1 | strategy/ma_cross | 골든크로스 발생 시 BUY 신호 | Signal(side=BUY) |
| 2 | strategy/ma_cross | 데드크로스 발생 시 SELL 신호 | Signal(side=SELL) |
| 3 | strategy/rsi | RSI < 30 시 BUY 신호 | Signal(side=BUY) |
| 4 | strategy/rsi | RSI > 70 시 SELL 신호 | Signal(side=SELL) |
| 5 | strategy/bollinger | 하단밴드 돌파 시 BUY 신호 | Signal(side=BUY) |
| 6 | trading/risk | 손절 비율 도달 시 청산 판단 | check_stop_loss = True |
| 7 | trading/risk | 익절 비율 도달 시 청산 판단 | check_take_profit = True |
| 8 | trading/risk | 잔고 부족 시 주문 거부 | validate_order = False |
| 9 | trading/position | 매수 후 평균단가 계산 | avg_price 정확히 계산 |
| 10 | trading/position | 수익률 계산 | unrealized_pnl 정확 |

### 8.3 Seed Data Requirements

| Entity | Minimum Count | Key Fields |
|--------|:------------:|------------|
| trades | 50 | 다양한 전략, 양수/음수 PnL |
| positions | 3 | 서로 다른 종목 |
| strategy_results | 5일치 × 5전략 | 승/패 다양 |

---

## 9. Clean Architecture

### 9.1 Layer Structure

| Layer | Responsibility | Location |
|-------|---------------|----------|
| **Core** | 도메인 모델, 열거형, 예외, 비즈니스 규칙 | `src/scalpy/core/` |
| **Strategy** | 전략 모듈, 추상 인터페이스, 레지스트리 | `src/scalpy/strategy/` |
| **Trading** | 매매 엔진, 포지션, 리스크, 주문 관리 | `src/scalpy/trading/` |
| **Broker** | 증권사 API 추상화 + pykis 구현체 | `src/scalpy/broker/` |
| **Data** | WebSocket 스트림, DB 리포지토리 | `src/scalpy/data/` |
| **Dashboard** | Streamlit UI | `src/scalpy/dashboard/` |

### 9.2 Dependency Rules

```
Dashboard → Trading Engine → Strategy (via Registry)
                           → Broker (via ABC)
                           → Data (via Repository)
                           → Core (models, enums)

Rule: Core는 외부 의존 없음 (순수 Python dataclass + enum)
      Strategy는 Core만 의존
      Broker는 Core만 의존
      Trading은 Core, Strategy, Broker, Data 의존
      Dashboard는 읽기 전용 (Trading 상태 조회만)
```

---

## 10. Coding Convention

### 10.1 Naming Conventions

| Target | Rule | Example |
|--------|------|---------|
| Modules | snake_case | `ma_cross.py`, `risk.py` |
| Classes | PascalCase | `MACrossStrategy`, `RiskManager` |
| Functions | snake_case | `check_stop_loss()`, `place_order()` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT`, `DEFAULT_STOP_LOSS` |
| Type aliases | PascalCase | `PriceData`, `OrderCallback` |

### 10.2 Import Order

```python
# 1. stdlib
import asyncio
from datetime import datetime
from decimal import Decimal

# 2. third-party
import sqlalchemy as sa
from pykis import KoreaInvestment

# 3. local
from scalpy.core.models import Signal, Order
from scalpy.strategy.base import BaseStrategy
```

### 10.3 Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `KIS_APP_KEY` | 한투 앱키 | (필수) |
| `KIS_APP_SECRET` | 한투 시크릿 | (필수) |
| `KIS_ACCOUNT_NO` | 계좌번호 | (필수) |
| `KIS_MOCK` | 모의투자 여부 | `true` |
| `DATABASE_URL` | PostgreSQL URL | `postgresql://scalpy:scalpy@localhost:5432/scalpy` |
| `STOP_LOSS_RATIO` | 손절 비율 | `0.02` (2%) |
| `TAKE_PROFIT_RATIO` | 익절 비율 | `0.03` (3%) |
| `MAX_POSITION_SIZE` | 종목당 최대 수량 | `100` |

---

## 11. Implementation Guide

### 11.1 File Structure

```
src/scalpy/
├── __init__.py
├── main.py                     # 엔트리포인트 (CLI)
├── config.py                   # 설정 로딩 (dynaconf)
├── core/
│   ├── __init__.py
│   ├── models.py               # Signal, Order, Position, TradeRecord
│   ├── enums.py                # Side, OrderType, OrderStatus, MarketPhase
│   └── exceptions.py           # ScalpyError 계층
├── broker/
│   ├── __init__.py
│   ├── base.py                 # BaseBroker ABC
│   ├── kis.py                  # KIS 구현체 (pykis)
│   └── mock.py                 # MockBroker (테스트/모의)
├── strategy/
│   ├── __init__.py
│   ├── base.py                 # BaseStrategy ABC
│   ├── registry.py             # StrategyRegistry (자동 발견)
│   ├── ma_cross.py             # 이동평균선 크로스
│   ├── bollinger.py            # 볼린저밴드 돌파
│   ├── rsi.py                  # RSI 과매수/과매도
│   ├── orderbook.py            # 호가창 기반
│   └── vwap.py                 # VWAP 기반
├── trading/
│   ├── __init__.py
│   ├── engine.py               # TradingEngine (asyncio 메인 루프)
│   ├── position.py             # PositionManager
│   ├── risk.py                 # RiskManager (손절/익절)
│   └── order.py                # OrderManager (큐 + 실행)
├── data/
│   ├── __init__.py
│   ├── stream.py               # MarketDataStream (WebSocket)
│   ├── repository.py           # TradeRepository (SQLAlchemy)
│   └── schema.py               # DB 테이블 정의
└── dashboard/
    ├── __init__.py
    ├── app.py                  # Streamlit 메인
    └── components/
        ├── __init__.py
        ├── price_ticker.py     # 실시간 시세
        ├── position_table.py   # 포지션 테이블
        ├── signal_log.py       # 전략 신호 로그
        └── performance.py      # 수익률 차트
```

### 11.2 Implementation Order

1. [ ] **M1: Core** — 모델, 열거형, 예외 정의
2. [ ] **M2: Config** — pyproject.toml, 설정 로딩, docker-compose
3. [ ] **M3: Data** — DB 스키마, 리포지토리, WebSocket 스트림
4. [ ] **M4: Broker** — 추상 클래스, MockBroker, KIS 구현체
5. [ ] **M5: Strategy** — 추상 클래스, 레지스트리, 5개 전략 구현
6. [ ] **M6: Trading** — 엔진, 포지션, 리스크, 주문 관리
7. [ ] **M7: Dashboard** — Streamlit 메인, 컴포넌트
8. [ ] **M8: Integration** — main.py, 통합 테스트, 모의투자 검증

### 11.3 Session Guide

#### Module Map

| Module | Scope Key | Description | Estimated Files |
|--------|-----------|-------------|:---------------:|
| Core + Config | `module-1` | 도메인 모델, 설정, 프로젝트 기반 | 8 |
| Data + Broker | `module-2` | DB/WebSocket + 증권사 API 연동 | 7 |
| Strategy | `module-3` | 전략 추상 클래스 + 5개 전략 구현 | 8 |
| Trading Engine | `module-4` | 매매 엔진, 포지션, 리스크, 주문 | 5 |
| Dashboard | `module-5` | Streamlit UI 컴포넌트 | 6 |
| Integration | `module-6` | main.py, 통합 테스트, 검증 | 3 |

#### Recommended Session Plan

| Session | Scope | Description | Estimated Turns |
|---------|-------|-------------|:---------------:|
| Session 1 | `--scope module-1` | Core + Config + pyproject.toml + docker-compose | 30-40 |
| Session 2 | `--scope module-2` | Data 계층 + Broker 추상화/구현 | 40-50 |
| Session 3 | `--scope module-3` | Strategy 시스템 + 5개 전략 | 40-50 |
| Session 4 | `--scope module-4` | Trading Engine + Risk + Position | 40-50 |
| Session 5 | `--scope module-5` | Streamlit Dashboard | 30-40 |
| Session 6 | `--scope module-6` | Integration + 모의투자 검증 | 30-40 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-07 | Initial draft | wonseok-han |
