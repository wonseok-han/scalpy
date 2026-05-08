.PHONY: help run dashboard backtest-screen backtest-fetch backtest-run backtest-daily backtest-info test lint typecheck

help: ## 도움말
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Live Trading ──

run: ## 라이브 트레이딩 + 대시보드 시작
	python -m scalpy.main

dashboard: ## 대시보드만 시작 (http://localhost:8080)
	python -m scalpy.main

# ── Backtest ──

backtest-daily: ## 오늘 데이터 수집 + 백테스트 (TOP=10)
	scalpy-backtest daily --top $(or $(TOP),10)

backtest-screen: ## 거래량 상위 종목 스크리닝 + 수집 (COUNT=50 DAYS=1)
	scalpy-backtest fetch --screen --screen-count $(or $(COUNT),50) --days $(or $(DAYS),1)

backtest-fetch: ## 분봉 데이터 수집 (SYMBOLS=005930,000660 DAYS=1)
	scalpy-backtest fetch --symbols $(or $(SYMBOLS),005930,000660) --days $(or $(DAYS),1)

backtest-run: ## 백테스트 실행 (SYMBOLS=005930,000660)
	scalpy-backtest run --symbols $(or $(SYMBOLS),005930,000660) --balance $(or $(BALANCE),500000)

backtest-info: ## 저장된 분봉 데이터 현황
	scalpy-backtest info

# ── Dev ──

test: ## 테스트 실행
	python -m pytest tests/ -v

lint: ## 린트
	python -m ruff check src/ tests/

typecheck: ## 타입체크
	python -m mypy src/scalpy/
