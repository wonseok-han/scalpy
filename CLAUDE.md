# Scalpy

> 한국투자증권 Open API 기반 자동 스캘핑 트레이딩 봇.

---

## Core Principles

### 1. SoR (Single Source of Truth) 우선순위

1. **Codebase** — 실제 동작하는 코드
2. **CLAUDE.md** — 이 문서 (프로젝트 규칙/컨벤션)

### 2. No Guessing

모르는 것 → 문서 확인 → 없으면 사용자에게 질문 → 절대 추측 금지.

### 3. 자동매매 안전 원칙

- 실거래 전 반드시 모의투자 환경에서 검증
- 주문 관련 코드 변경 시 사용자 확인 필수
- 손절/이익실현 로직은 항상 존재해야 함 (안전장치 없는 주문 금지)

---

## Current Status

**v0.0.0 — 프로젝트 초기 설정 단계.**

---

## Details (분리된 설정 파일)

@.claude/workflow.md
