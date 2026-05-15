# Scalpy Quant

한국투자증권 Open API 기반 단기 퀀트 자동매매 봇.

일목균형/모멘텀/평균회귀/팩터 전략으로 단기 퀀트 매매를 대시보드에서 실시간 제어하고, 모의투자 환경에서 안전하게 검증할 수 있는 개인용 자동매매 플랫폼.

## 주요 기능

- **4개 퀀트 전략**: 일목균형(분봉), 모멘텀(틱), 평균회귀(분봉), 팩터(틱)
- **전체 시장 퀀트 스크리닝**: KRX 종목 대상 모멘텀/거래량/변동성/RSI 팩터 스코어링 → 자동 선별
- **장세 판단 & 전략 추천**: 시장 평균 등락률 + 상승/하락 비율 기반 강세/횡보/약세 판단, 장세에 맞는 전략 추천
- **일목균형 구름 필터**: ichimoku 전략 활성 시 구름 아래 종목 스크리닝 제외 + 구름 위 종목 가산점
- **Trailing Stop**: 고점 추적 매도 (고점 대비 N% 하락 시 매도, 수익을 극대화)
- **수익 보호**: trailing 활성화 전 본전 방어 (peak gain 도달 후 수익률 하락 시 매도)
- **균등 분배 포지션 사이징**: 총 자산 ÷ max_open_positions 자동 계산
- **실시간 WebSocket 시세**: KIS Open API 체결가/호가 실시간 수신 + 자동 재연결
- **자동 매매**: 전략 신호 → 쿨다운 → 리스크 검증 → 주문 실행 파이프라인
- **리스크 관리**: 손절/trailing stop/수익보호/횡보 청산, 최대 포지션 제한, 분할 매도
- **장 마감 자동 청산**: 설정 시 장 마감 전 전체 보유 종목 분할 매도
- **FastAPI + SSE 대시보드**: 실시간 포지션/손익/스크리닝/전략 신호/장세 표시
- **주기적 재스크리닝**: 설정 주기마다 종목 교체 + WS 구독 갱신
- **백테스트**: 퀀트 전략 과거 데이터 검증
- **야간 운영**: 일간 자동 재초기화 (미체결 정리, 포지션 동기화, 재스크리닝)
- **거래 DB 분리**: 모의투자/실거래 거래내역 분리 저장 (PostgreSQL)
- **텔레그램 알림**: 체결/손절/익절/엔진 상태 알림 (선택)
- **모의투자 우선**: 기본 모의투자 모드, 실거래 전환은 설정 파일에서만 가능

## 아키텍처

```
MarketData (WebSocket) → Strategy Engine → Signal → Cooldown → Risk Check → Order → KIS API
                              ↑                                                        ↓
                         EventBus ←──────────── Position Manager ←────────────── Execution
                           ↓   ↓
            Dashboard (FastAPI/SSE)  TelegramNotifier
               ↕ Browser
```

| 레이어 | 역할 | 위치 |
|--------|------|------|
| Core | 도메인 모델, 열거형, 예외 | `src/scalpy/core/` |
| Strategy | 퀀트 전략 모듈, 레지스트리 | `src/scalpy/strategy/` |
| Trading | 엔진, 포지션, 리스크, 주문 | `src/scalpy/trading/` |
| Broker | 증권사 API 추상화 (Mock/KIS) | `src/scalpy/broker/` |
| Data | WebSocket 스트림, OHLCV 저장소 | `src/scalpy/data/` |
| Events | 비동기 EventBus | `src/scalpy/events/` |
| Dashboard | FastAPI 서버, SSE, REST API | `src/scalpy/dashboard/` |
| Notification | 텔레그램 봇 알림 | `src/scalpy/notification/` |
| Screening | 퀀트 팩터 기반 종목 선별 | `src/scalpy/screening/` |
| Static | 대시보드 프론트엔드 | `src/scalpy/static/` |

## 설치

### Docker (권장)

```bash
git clone https://github.com/wonseok-han/scalpy.git
cd scalpy

cp config/.secrets.toml.sample config/.secrets.toml
# config/.secrets.toml에 KIS API 키 입력

docker compose up -d
```

PostgreSQL + scalpy가 함께 시작됩니다. 크래시 시 자동 재시작.

대시보드: http://localhost:8080

### 로컬 설치

```bash
conda create -n scalpy python=3.12
conda activate scalpy
pip install -e ".[dev]"

# PostgreSQL 먼저 실행
docker compose up -d postgres

python -m scalpy.main
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

`config/settings.toml`에서 종목, 전략, 리스크 등을 설정:

```toml
[default]
mock = true  # 모의투자 모드 (실거래: false)

[default.trading]
auto_start = false          # 대시보드에서 수동 시작
symbols = ["005930", "000660"]
stop_loss_ratio = 0.02      # 2% 손절
trailing_activate_ratio = 0.01  # 1% 수익 시 trailing 활성화
trailing_stop_ratio = 0.02  # 고점 대비 2% 하락 시 매도
max_position_size = 100     # 종목당 최대 수량
max_open_positions = 3      # 동시 보유 최대 포지션 수

[default.strategies]
quant_enabled = ["ichimoku"]  # 퀀트 전략 (ichimoku, momentum, mean_reversion, factor)

[default.dashboard]
enabled = true
port = 8080
```

## 테스트

```bash
pytest

# 개별 테스트
python scripts/test_connection.py   # API 연결 확인
python scripts/test_order.py        # 모의투자 매수 테스트
python scripts/test_websocket.py    # WebSocket 시세 수신 테스트
```

## 전략

| 전략 | 한국어명 | 데이터 | 적합 장세 | 매수 조건 | 매도 조건 | 쿨다운 |
|------|---------|:------:|---------|----------|----------|:------:|
| ichimoku | 일목균형 | 분봉 | 상승 추세장 | 구름 위 + TK 골든크로스 | 구름 이탈/기준선 이탈/TK 데드크로스 | 5분 |
| momentum | 모멘텀 돌파 | 틱 | 강한 상승장 | 거래량 급증 + 고점 돌파 | 모멘텀 둔화 | 30분 |
| mean_reversion | 평균회귀 | 분봉 | 횡보·조정장 | 볼린저 하단밴드 이탈 후 복귀 | 상단밴드 도달 | 10분 |
| factor | 복합 팩터 | 틱 | 종목별 차별화 | 모멘텀+거래량+호가 팩터 합산 ≥ 0.65 | 팩터 점수 역전 | 3분 |

- 대시보드에서 전략 칩을 클릭하면 실시간으로 활성/비활성 전환
- 장세 판단에 따라 추천 전략이 표시됨 (전략 칩에 ★ 추천 라벨)
- 전략 칩 호버 시 적합한 장세 및 전략 설명 툴팁 표시
- `BaseStrategy`를 상속하여 새 전략 추가 가능
- 전략 매도는 손실 구간에서만 동작, 수익 구간은 trailing stop이 관리

## 리스크 관리

| 보호 장치 | 설명 |
|-----------|------|
| 손절 | 설정 비율 도달 시 자동 청산 (전략별 개별 설정 가능) |
| Trailing Stop | 고점 추적 매도 (수익 시 활성화, 고점 대비 N% 하락 시 매도) |
| 수익 보호 | trailing 활성화 전 본전 방어 (peak gain 이후 수익률 하락 시 매도) |
| 횡보 청산 | N시간 보유 후 ±0.5% 이내이면 자동 청산 |
| 장 마감 청산 | 설정 시 장 마감 전 전체 보유 종목 분할 매도 |
| 재매수 쿨다운 | 같은 종목 청산 후 설정 시간 동안 재매수 차단 |
| 신호 쿨다운 | 같은 종목 같은 방향 중복 신호 차단 |
| 중복 매수 차단 | 이미 보유한 종목에 추가 매수 불가 |
| 최대 포지션 제한 | 동시 보유 포지션 수 제한 (기본 3개) |
| 종목당 투입 비율 | 잔고 대비 종목당 최대 투입 비율 제한 |
| 장 마감 매수 차단 | 15:15 이후 신규 매수 불가 |
| API 속도 제한 | 0.3초 간격 API 호출 + 잔고 10초 캐싱 |

## 기술 스택

- **Python 3.12+** / asyncio
- **pykis 0.7** — 한국투자증권 API SDK
- **FastAPI** + **uvicorn** — 대시보드 서버
- **SSE (Server-Sent Events)** — 실시간 데이터 푸시
- **websockets** — 실시간 시세 수신 + 자동 재연결
- **structlog** — 구조화된 로깅
- **dynaconf** — 설정 관리 (환경변수 오버라이드: `SCALPY_` 접두사)
- **Docker Compose** — PostgreSQL + scalpy 원클릭 배포

## 안전 원칙

- 모의투자 모드가 기본값 (`mock = true`)
- 실거래 전환은 `config/settings.toml`에서만 가능 (CLI 인자 전환 불가)
- KIS API URL 미설정 시 서버 시작 불가
- 손절 + trailing stop + 횡보 청산 + 포지션 제한이 항상 활성
- API 키는 `.secrets.toml`에 저장 (gitignore 포함)
