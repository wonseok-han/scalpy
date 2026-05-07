# Scalpy

한국투자증권 Open API 기반 자동 스캘핑 트레이딩 봇.

5개 전략을 모듈식으로 교체/비교하고, 모의투자 환경에서 안전하게 검증할 수 있는 개인용 자동매매 플랫폼.

## 주요 기능

- **5개 전략 플러그인**: 이동평균선 크로스, 볼린저밴드, RSI, 호가창, VWAP
- **실시간 WebSocket 시세**: 한투 Open API 체결가/호가 실시간 수신
- **자동 매매**: 전략 신호 → 리스크 검증 → 주문 실행 파이프라인
- **손절/익절 자동 청산**: 설정 비율 도달 시 즉시 포지션 정리
- **Streamlit 대시보드**: 실시간 시세, 포지션, 전략 성과, 체결 이력
- **모의투자 우선**: 기본 모의투자 모드, 실거래 전환은 설정 파일에서만 가능

## 아키텍처

```
MarketData (WebSocket) → Strategy Engine → Signal → Risk Check → Order → Broker API
                                                                         ↓
                          Dashboard (Streamlit) ← Position Manager ← Execution
```

| 레이어 | 역할 | 위치 |
|--------|------|------|
| Core | 도메인 모델, 열거형, 예외 | `src/scalpy/core/` |
| Strategy | 전략 모듈, 레지스트리 | `src/scalpy/strategy/` |
| Trading | 엔진, 포지션, 리스크, 주문 | `src/scalpy/trading/` |
| Broker | 증권사 API 추상화 (Mock/KIS) | `src/scalpy/broker/` |
| Data | WebSocket 스트림, DB 리포지토리 | `src/scalpy/data/` |
| Dashboard | Streamlit UI | `src/scalpy/dashboard/` |

## 설치

```bash
# 저장소 클론
git clone https://github.com/wonseok-han/scalpy.git
cd scalpy

# 가상환경 생성 및 의존성 설치
conda create -n scalpy python=3.12
conda activate scalpy
pip install -e ".[dev]"

# PostgreSQL 실행
docker-compose up -d
```

## 설정

### API 키 설정

```bash
cp config/.secrets.toml.sample config/.secrets.toml
```

`config/.secrets.toml`을 편집하여 한국투자증권 API 키를 입력:

```toml
[default]
KIS_APP_KEY = "your-app-key"
KIS_APP_SECRET = "your-app-secret"
KIS_ACCOUNT_NO = "12345678-01"
```

> API 키는 [한국투자증권 Open API 포털](https://apiportal.koreainvestment.com)에서 발급받을 수 있습니다.

### 매매 설정

`config/settings.toml`에서 종목, 전략, 손절/익절 비율 등을 설정:

```toml
[default]
mock = true  # 모의투자 모드 (실거래: false)

[default.trading]
symbols = ["005930", "000660"]
stop_loss_ratio = 0.02      # 2% 손절
take_profit_ratio = 0.03    # 3% 익절
max_position_size = 100

[default.strategies]
enabled = ["ma_cross", "bollinger", "rsi", "orderbook", "vwap"]
```

## 실행

```bash
# 자동매매 봇 실행
scalpy

# 대시보드 실행
streamlit run src/scalpy/dashboard/app.py
```

## 테스트

```bash
# 전체 테스트
pytest

# API 연결 확인
python scripts/test_connection.py

# 모의투자 매수 테스트
python scripts/test_order.py

# WebSocket 시세 수신 테스트
python scripts/test_websocket.py
```

## 전략

| 전략 | 설명 | 매수 조건 | 매도 조건 |
|------|------|----------|----------|
| MA Cross | 이동평균선 크로스 | 골든크로스 (단기 > 장기) | 데드크로스 (단기 < 장기) |
| Bollinger | 볼린저밴드 돌파 | 하단밴드 이탈 | 상단밴드 이탈 |
| RSI | 상대강도지수 | RSI < 30 (과매도) | RSI > 70 (과매수) |
| Orderbook | 호가창 잔량 비율 | 매수잔량/매도잔량 >= 1.5 | 매도잔량/매수잔량 >= 1.5 |
| VWAP | 거래량가중평균가격 | 현재가 < VWAP - 0.5% | 현재가 > VWAP + 0.5% |

전략 추가: `BaseStrategy`를 상속한 클래스를 만들고 `StrategyRegistry`에 등록하면 기존 코드 수정 없이 동작합니다.

## 기술 스택

- **Python 3.12+** / asyncio
- **pykis** — 한국투자증권 API SDK
- **SQLAlchemy 2.0** — ORM (PostgreSQL)
- **Streamlit** — 대시보드
- **structlog** — 구조화된 로깅
- **dynaconf** — 설정 관리
- **websockets** — 실시간 시세 수신

## 안전 원칙

- 모의투자 모드가 기본값 (`mock = true`)
- 실거래 전환은 `config/settings.toml`에서만 가능 (CLI 인자 전환 불가)
- 손절/익절 로직 없이는 주문 실행 불가
- API 키는 `.secrets.toml`에 저장 (gitignore 포함)

## 라이선스

Private — 개인 사용 목적
