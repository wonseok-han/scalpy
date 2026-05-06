다음 단계를 순서대로 실행하여 릴리즈용 changelog 파일을 생성하라.

## 0. 환경 주의사항

- **scm_breeze 충돌**: `git` 명령은 `/usr/bin/git` 절대경로 사용

## 1. 현재 상태 확인

```bash
/usr/bin/git branch --show-current
/usr/bin/git fetch origin main
/usr/bin/git fetch origin develop
```

- develop 브랜치가 아니면 사용자에게 알리고 develop으로 전환할지 확인
- main 대비 develop에 새 커밋이 있는지 확인:

```bash
/usr/bin/git log origin/main..origin/develop --oneline
```

- 새 커밋이 없으면: "main 대비 변경사항이 없습니다" 알리고 **중단**

## 2. 이전 태그 이후 변경 내역 분석

```bash
LATEST_TAG=$(/usr/bin/git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
/usr/bin/git log "$LATEST_TAG"..origin/develop --oneline
/usr/bin/git diff --shortstat "$LATEST_TAG"..origin/develop
```

커밋 목록을 분석하여 카테고리별로 분류한다:
- **Added**: `feat` 접두사 커밋
- **Changed**: `refactor`, `perf`, `style`, `docs`, `chore`, `ci` 접두사 커밋
- **Fixed**: `fix` 접두사 커밋

## 3. 버전 결정

시맨틱 버전 규칙:
- `feat` 커밋이 있으면 **minor** bump (0.2.0 → 0.3.0)
- `feat`이 없으면 **patch** bump (0.2.0 → 0.2.1)

결정된 버전을 사용자에게 보여주고, 변경을 원하면 수정할 수 있도록 한다.

## 4. changelog 파일 작성

`changelogs/` 디렉토리에 `v{version}.md` 파일을 생성한다.
디렉토리가 없으면 자동으로 생성한다.

```
changelogs/
├── v0.1.0.md
├── v0.2.0.md
└── v0.3.0.md   ← 새로 생성
```

파일 형식:
```markdown
## v{version} - YYYY-MM-DD

한 줄 요약. N files changed, +N / -N lines.

### Added

- **기능명** — PR #N
  - 세부 변경 1
  - 세부 변경 2

### Changed

- **변경 항목** — PR #N
  - 세부 변경

### Fixed

- 수정 내용

### Statistics

| Item | Count |
|------|-------|
| Files changed | N |
| Lines added | +N |
| Lines deleted | -N |
| Merged PRs | #N ~ #N (N) |
```

규칙:
- 커밋 메시지를 그대로 나열하지 말고, **의미 단위로 그룹핑**하여 사람이 읽기 좋게 작성
- PR 번호가 있으면 포함
- 빈 카테고리(해당 커밋이 없는)는 생략
- Statistics의 파일/라인 수치는 `git diff --shortstat`에서 가져옴

## 5. 사용자 확인

changelog 초안을 사용자에게 보여주고 확인을 받는다.
수정 요청이 있으면 반영한 뒤 다시 확인을 받는다.

## 6. develop에 커밋 + push

승인된 changelog 파일을 develop에 커밋하고 push한다.

```bash
/usr/bin/git add changelogs/v{version}.md
```

커밋 메시지: `docs: add changelog for v{version}`
커밋은 `/commit` 커맨드의 방식을 따른다 (임시 파일 방식, Co-Authored-By 포함).

```bash
/usr/bin/git push origin develop
```

## 7. 다음 단계 안내

완료 후 사용자에게 안내한다:

```
changelog 생성 완료: changelogs/v{version}.md

다음 단계:
  /pr    develop → main Release PR 생성
         PR 머지 시 GitHub Actions가 자동으로 태그 생성 + 릴리즈 발행
```

## 8. 주의사항

- 이미 같은 버전의 changelog 파일이 존재하면 사용자에게 알리고 덮어쓸지 확인
- `changelogs/v{version}.md`가 릴리즈 노트의 **Source of Record** — GitHub Release는 이 파일에서 자동 생성됨
- push는 develop에만 한다
