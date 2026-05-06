다음 단계를 순서대로 실행하여 GitHub PR을 생성하라.

## 0. 환경 주의사항

- **scm_breeze 충돌**: `git` 명령은 `/usr/bin/git` 절대경로 사용
- **gh CLI 필수**: `gh auth status`로 인증 상태 확인. 미인증이면 사용자에게 안내 후 중단

## 1. 현재 상태 확인

```bash
/usr/bin/git branch --show-current
/usr/bin/git status
```

- staged/unstaged 변경이 있으면 사용자에게 경고하고 계속 진행할지 확인
- `main` 브랜치에서는 PR 생성 불가 — 안내 후 중단

## 2. base 브랜치 결정

| 현재 브랜치 | base | PR 유형 |
|-------------|------|---------|
| `develop` | `main` | Release PR |
| 그 외 (`feat/*`, `fix/*`, `refactor/*` 등) | `develop` | Feature PR |

## 3. 변경 내역 분석

```bash
/usr/bin/git fetch origin {base}
/usr/bin/git log origin/{base}..HEAD --oneline
/usr/bin/git diff --stat origin/{base}..HEAD
```

- 새 커밋이 없으면: "base 대비 변경사항이 없습니다" 알리고 **중단**

## 4. PR 제목/본문 작성

### Feature PR (→ develop)

제목 규칙:
- 브랜치 이름에서 prefix 추출: `feat/add-profile` → `feat: add profile`
- 커밋이 1개면 해당 커밋 메시지를 제목으로 사용
- 70자 이내

본문 형식:
```markdown
## Summary
- 변경 사항 1~3줄 요약 (커밋 분석 기반)

## Changes
- 주요 변경 파일/기능 나열

## Test
- [ ] 테스트 항목 (변경 내용에 맞게)
```

### Release PR (develop → main)

제목: `Release v{version}` (changelogs/ 디렉토리에서 최신 버전 파일명 추출)

본문 형식:
```markdown
## Release v{version}

changelogs/v{version}.md 내용을 그대로 포함
```

- changelogs/ 에 해당 버전 파일이 없으면 사용자에게 `/changelog` 로 먼저 생성하라고 안내 후 **중단**

## 5. 사용자 확인

PR 생성 전 아래 내용을 보여주고 확인을 받는다:
- base ← head 브랜치
- PR 제목
- PR 본문 미리보기

## 6. PR 생성

```bash
gh pr create --base {base} --head {head} --title "{title}" --body-file /tmp/pr-body.md
```

- Write 툴로 `/tmp/pr-body.md` 생성 후 `--body-file` 사용
- 생성 후 PR URL을 사용자에게 출력

## 7. 주의사항

- PR 본문에 비밀 정보가 포함되지 않도록 주의
- 이미 같은 base/head 조합의 열린 PR이 있으면 알리고 중단
- push되지 않은 커밋이 있으면 `--push` 옵션 없이 push 먼저 할지 확인
- Draft PR을 원하면 사용자 요청 시에만 `--draft` 추가
