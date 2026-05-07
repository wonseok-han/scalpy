# Scalpy MVP Planning Document

> **Summary**: 한국투자증권 Open API 기반 국내 주식 자동 스캘핑 트레이딩 봇
>
> **Project**: Scalpy
> **Version**: 0.1.0
> **Author**: wonseok-han
> **Date**: 2026-05-06
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 스캘핑 트레이딩은 빠른 판단과 실행이 필요하지만 수동으로는 속도/일관성 한계가 있고, 다양한 전략을 체계적으로 비교 테스트할 방법이 없음 |
| **Solution** | pykis SDK 기반 자동 스캘핑 봇을 Python으로 구현하고, 전략을 모듈식으로 설계하여 교체/비교 가능하게 구성 |
| **Function/UX Effect** | CLI + Streamlit 대시보드로 실시간 시세 조회, 자동 주문, 포지션 모니터링, 수익률 추적을 한 화면에서 확인 |
| **Core Value** | 스캘핑 전략을 안전하게(모의투자) 탐색하고 검증할 수 있는 개인용 자동매매 플랫폼 |

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

### 1.1 Purpose

한국투자증권 Open API를 활용하여 국내 주식 시장에서 자동 스캘핑 트레이딩을 수행하는 봇을 개발한다. 스캘핑 지식이 부족한 상태에서 다양한 전략을 모듈식으로 구현하고, 모의투자 환경에서 안전하게 전략을 검증할 수 있는 플랫폼을 구축한다.

### 1.2 Background

- 스캘핑은 초단타 매매로, 수동 실행 시 속도와 감정 통제에 한계가 있음
- 한국투자증권은 Open API를 제공하며, pykis 등 Python SDK가 활발히 유지보수됨
- 개인 로컬 환경에서만 운용 예정 (배포 시 약관 이슈 우려)

### 1.3 Related Documents

- 한국투자증권 Open API 문서: https://apiportal.koreainvestment.com
- pykis GitHub: https://github.com/Soju06/python-kis

---

## 2. Scope

### 2.1 In Scope

- [x] 실시간 시세 조회 (WebSocket 기반 호가/체결 수신)
- [x] 자동 주문 실행 (전략 조건 기반 매수/매도)
- [x] 손절/익절 자동 청산
- [x] 포지션 모니터링 (보유 종목, 평균단가, 수익률)
- [x] 수익률 대시보드 (Streamlit 기반)
- [x] 전략 모듈 시스템 (5개 전략 동시 구현)
  - 이동평균선 크로스
  - 볼린저밴드 돌파
  - RSI 과매수/과매도
  - 호가창 기반 (매수/매도 잔량 비율)
  - VWAP 기반
- [x] 체결 이력 / 수익률 / 전략 성과 저장 (PostgreSQL)
- [x] 모의투자 환경 지원

### 2.2 Out of Scope

- 해외 주식 대응
- 알림 기능 (텔레그램, 슬랙 등)
- 서버 배포 / 클라우드 운용
- 4종목 이상 동시 운용
- 백테스팅 엔진 (향후 확장 고려)
- 웹 기반 관리 UI (Streamlit 대시보드로 대체)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 한국투자증권 API 인증 (앱키/시크릿 기반 토큰 발급) | High | Pending |
| FR-02 | 실시간 호가/체결 데이터 WebSocket 수신 | High | Pending |
| FR-03 | 전략 모듈 인터페이스 정의 (공통 추상 클래스) | High | Pending |
| FR-04 | 이동평균선 크로스 전략 구현 | High | Pending |
| FR-05 | 볼린저밴드 돌파 전략 구현 | High | Pending |
| FR-06 | RSI 과매수/과매도 전략 구현 | High | Pending |
| FR-07 | 호가창 기반 전략 구현 | Medium | Pending |
| FR-08 | VWAP 기반 전략 구현 | Medium | Pending |
| FR-09 | 매수/매도 주문 실행 | High | Pending |
| FR-10 | 손절/익절 자동 청산 (비율 설정 가능) | High | Pending |
| FR-11 | 포지션 관리 (보유 종목, 평균단가, 실시간 수익률) | High | Pending |
| FR-12 | 체결 이력 DB 저장 (PostgreSQL) | High | Pending |
| FR-13 | 전략별 성과 기록 및 비교 | Medium | Pending |
| FR-14 | Streamlit 대시보드 (실시간 시세, 포지션, 수익률) | Medium | Pending |
| FR-15 | 모의투자/실거래 환경 전환 (설정 기반) | High | Pending |
| FR-16 | 동시 2~3종목 운용 | Medium | Pending |
| FR-17 | 설정 파일 기반 파라미터 관리 (종목, 전략, 손절/익절 비율 등) | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | WebSocket 시세 수신 → 주문 실행 지연 < 500ms | 타임스탬프 로깅 |
| Reliability | 네트워크 끊김 시 자동 재연결 + 포지션 안전 처리 | 수동 테스트 |
| Safety | 모의투자 모드 기본값, 실거래 전환 시 명시적 확인 | 설정 파일 검증 |
| Maintainability | 전략 모듈 추가 시 기존 코드 수정 없이 플러그인 방식 | 새 전략 추가 테스트 |
| Logging | 모든 주문/체결/에러를 구조화된 로그로 기록 | 로그 파일 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 모의투자 환경에서 5개 전략이 독립적으로 매수/매도 신호를 생성
- [ ] 2~3종목 동시 시세 수신 및 주문 실행 가능
- [ ] 손절/익절 설정 시 자동 청산 동작 확인
- [ ] 체결 이력이 PostgreSQL에 정상 저장
- [ ] Streamlit 대시보드에서 실시간 포지션/수익률 확인 가능
- [ ] 전략 추가 시 기존 코드 수정 없이 모듈만 추가하면 동작

### 4.2 Quality Criteria

- [ ] 타입 힌트 100% 적용 (mypy strict)
- [ ] 핵심 로직 유닛 테스트 (pytest)
- [ ] 린트 에러 0 (ruff)
- [ ] 빌드/실행 성공

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 모의투자에서 검증 안 된 로직이 실거래에 적용 | High | Medium | 실거래 전환 시 이중 확인 + 설정 파일에 `DRY_RUN=true` 기본값 |
| API 토큰 만료로 주문 실패 | High | High | 토큰 자동 갱신 로직 + 만료 전 선제 갱신 |
| WebSocket 연결 끊김 시 미체결 주문 방치 | High | Medium | 재연결 로직 + 포지션 안전 점검 (전량 청산 옵션) |
| 동시 종목 운용 시 주문 충돌/레이스 컨디션 | Medium | Medium | 종목별 독립 실행 루프 + 주문 큐 관리 |
| pykis SDK 버그/미지원 기능 | Medium | Low | 필요 시 REST API 직접 호출로 폴백 |
| PostgreSQL 로컬 설정 복잡도 | Low | Medium | Docker Compose로 PostgreSQL 원클릭 실행 |

---

## 6. Impact Analysis

> 신규 프로젝트이므로 기존 코드 영향 없음.

### 6.1 Changed Resources

| Resource | Type | Change Description |
|----------|------|--------------------|
| 전체 프로젝트 | New Project | 신규 생성 |

### 6.2 Current Consumers

해당 없음 (신규 프로젝트)

### 6.3 Verification

- [x] 신규 프로젝트로 기존 소비자 없음

---

## 7. Architecture Considerations

### 7.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites, portfolios | ☐ |
| **Dynamic** | Feature-based modules | Web apps, SaaS MVPs | ☒ |
| **Enterprise** | Strict layer separation, DI | High-traffic, complex systems | ☐ |

### 7.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| Language | Python / Node.js / Go | Python 3.12+ | 금융 분석 라이브러리 생태계, pykis SDK 지원 |
| API SDK | pykis / mojito2 / 직접 구현 | pykis | 타입 힌트, 활발한 유지보수, 커뮤니티 |
| Database | SQLite / PostgreSQL / CSV | PostgreSQL | 체결 이력 대량 저장, 쿼리 유연성, 확장성 |
| Dashboard | Streamlit / Dash / Gradio | Streamlit | 빠른 프로토타이핑, Python 네이티브 |
| Task Runner | asyncio / threading / multiprocessing | asyncio | WebSocket + 주문 실행의 비동기 처리에 최적 |
| Config | YAML / TOML / .env | TOML (pyproject.toml 통합) | Python 표준, 구조화된 설정 |
| ORM | SQLAlchemy / raw SQL | SQLAlchemy | 타입 안전, 마이그레이션 지원 |
| Testing | pytest / unittest | pytest | 표준, 풍부한 플러그인 |
| Linting | ruff / flake8+black | ruff | 올인원, 빠름 |
| Package Manager | uv / pip / poetry | uv | 빠른 설치, 록파일 지원, 최신 표준 |

### 7.3 Clean Architecture Approach

```
Selected Level: Dynamic

Folder Structure Preview:
scalpy/
├── pyproject.toml              # 프로젝트 설정, 의존성
├── config/
│   ├── settings.toml           # 기본 설정 (종목, 전략, 손절/익절)
│   └── .secrets.toml           # API 키 (gitignore)
├── src/
│   └── scalpy/
│       ├── __init__.py
│       ├── main.py             # 엔트리포인트
│       ├── core/               # 핵심 도메인
│       │   ├── models.py       # 도메인 모델 (Order, Position, Signal)
│       │   ├── enums.py        # 열거형 (OrderType, Side, StrategyType)
│       │   └── exceptions.py   # 커스텀 예외
│       ├── broker/             # 증권사 API 연동
│       │   ├── base.py         # 브로커 추상 클래스
│       │   ├── kis.py          # 한국투자증권 (pykis) 구현체
│       │   └── mock.py         # 테스트용 목 브로커
│       ├── strategy/           # 전략 모듈
│       │   ├── base.py         # 전략 추상 클래스 (Strategy ABC)
│       │   ├── registry.py     # 전략 레지스트리 (플러그인 로딩)
│       │   ├── ma_cross.py     # 이동평균선 크로스
│       │   ├── bollinger.py    # 볼린저밴드 돌파
│       │   ├── rsi.py          # RSI 과매수/과매도
│       │   ├── orderbook.py    # 호가창 기반
│       │   └── vwap.py         # VWAP 기반
│       ├── trading/            # 매매 엔진
│       │   ├── engine.py       # 메인 트레이딩 엔진 (asyncio)
│       │   ├── position.py     # 포지션 관리자
│       │   ├── risk.py         # 리스크 관리 (손절/익절)
│       │   └── order.py        # 주문 큐 + 실행
│       ├── data/               # 데이터 계층
│       │   ├── stream.py       # WebSocket 실시간 데이터
│       │   ├── repository.py   # DB 접근 (SQLAlchemy)
│       │   └── schema.py       # DB 테이블 정의
│       ├── dashboard/          # Streamlit UI
│       │   ├── app.py          # 대시보드 메인
│       │   └── components/     # UI 컴포넌트
│       └── config.py           # 설정 로딩 (dynaconf)
├── tests/
│   ├── conftest.py
│   ├── test_strategy/
│   ├── test_trading/
│   └── test_broker/
├── docker-compose.yml          # PostgreSQL
└── docs/
```

---

## 8. Convention Prerequisites

### 8.1 Existing Project Conventions

- [x] `CLAUDE.md` has project rules
- [ ] Python linting config (ruff)
- [ ] Type checking config (mypy)
- [ ] Pre-commit hooks

### 8.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **Naming** | Missing | snake_case 전체, 클래스 PascalCase | High |
| **Folder structure** | Missing | 위 7.3 구조 따름 | High |
| **Import order** | Missing | stdlib → third-party → local (ruff isort) | Medium |
| **Error handling** | Missing | 커스텀 예외 계층, 주문 실패 시 로깅+재시도 | High |
| **Logging** | Missing | structlog, JSON 포맷 | Medium |

### 8.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `KIS_APP_KEY` | 한투 API 앱키 | Local | ☐ |
| `KIS_APP_SECRET` | 한투 API 시크릿 | Local | ☐ |
| `KIS_ACCOUNT_NO` | 계좌번호 | Local | ☐ |
| `KIS_MOCK` | 모의투자 여부 (기본: true) | Local | ☐ |
| `DATABASE_URL` | PostgreSQL 연결 문자열 | Local | ☐ |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`scalpy-mvp.design.md`)
2. [ ] 프로젝트 초기 구조 생성 (pyproject.toml, src/ 등)
3. [ ] Docker Compose로 PostgreSQL 환경 구성
4. [ ] 한투 API 키 발급 + 모의투자 계좌 신청

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-06 | Initial draft | wonseok-han |
