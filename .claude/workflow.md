## Development Workflow

### Git 브랜치 워크플로 (필수 준수)

```
main (배포) ← develop (통합) ← feat/xxx (작업)
```

1. **작업 브랜치 생성**: 항상 `develop` 기준으로 생성 (`git checkout -b feat/xxx develop`)
2. **PR 생성**: 항상 `--base develop` 으로 생성. **절대 main 대상 PR을 임의로 만들지 않는다.**
3. **develop 머지**: squash merge
4. **main 머지**: 사용자가 "main에 머지해", "배포하자" 등 **명시적으로 요청할 때만** develop → main PR 생성

> **금지사항:**
> - main 직접 커밋 금지
> - 사용자 요청 없이 main 대상 PR 생성 금지
> - 사용자 요청 없이 main에 머지/push 금지

---

## 구현 완료 후 검증 (필수)

> **중요:** 구현 후 빌드/테스트 검증 없이 바로 커밋하지 말 것.

---

## Release Workflow

```
/changelog → changelogs/vX.Y.Z.md 생성 + develop 커밋/push
/pr        → develop → main Release PR 생성
PR 머지    → GitHub Actions 자동 태그 + 릴리즈 발행
```

---

## Key Commands

### 개발 커맨드 (Claude 슬래시)

| 명령 | 설명 |
|---|---|
| `/commit` | staged 변경사항 커밋 (승인 없이 즉시 실행) |
| `/pr` | GitHub PR 생성 (base 브랜치 자동 감지) |
| `/changelog` | 릴리즈용 changelog 생성 (`changelogs/vX.Y.Z.md`) |
