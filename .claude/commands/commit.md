다음 단계를 순서대로 실행하여 git 커밋을 진행하라. **사용자 승인 없이 바로 커밋한다.**

## 0. 환경 주의사항

- **scm_breeze 충돌**: `git` 명령은 `_safe_eval` 오류가 발생하므로 반드시 `/usr/bin/git` 절대경로 사용
- **HEREDOC 미동작**: `-m "$(cat <<'EOF'...)"` 패턴이 이 환경에서 동작하지 않으므로 반드시 임시 파일(`/tmp/commit_msg.txt`) 방식 사용

## 1. 현재 상태 파악

아래 명령을 병렬로 실행한다:
- `/usr/bin/git status` — staged 파일 목록 확인 (절대 `-uall` 플래그 사용 금지)
- `/usr/bin/git diff --cached` — staged된 변경 내용만 확인
- `/usr/bin/git log --oneline -5` — 최근 커밋 메시지 스타일 파악

staged된 파일이 없으면 사용자에게 알리고 종료한다 (`git add` 제안 금지).

## 2. 커밋 메시지 작성

변경 내용을 분석해 커밋 메시지를 작성한다:
- 첫 줄(제목): 50자 이내, 명령문 형태 (예: "Add", "Fix", "Update", "Remove")
- 변경의 **why**를 중심으로, what은 diff에서 볼 수 있으므로 간결하게
- 해당 저장소의 최근 커밋 스타일을 따름
- 비밀 정보가 담긴 파일(.env 등)은 절대 포함하지 않음 (포함돼 있으면 커밋 중단하고 사용자에게 경고)

## 3. 커밋 실행

- 스테이징은 사용자가 직접 하므로, 추가적인 `git add`는 하지 않는다
- 현재 staged된 내용만 커밋한다
- **임시 파일 방식**으로 커밋 메시지 전달:

```
# 1단계: Write 툴로 /tmp/commit_msg.txt 파일 생성
#   - 이미 존재하면 먼저 /bin/rm -f /tmp/commit_msg.txt 로 제거 후 재생성
#   - 파일 내용에 커밋 메시지 + Co-Authored-By 포함

# 2단계: 파일로 커밋
/usr/bin/git commit -F /tmp/commit_msg.txt
```

커밋 메시지 파일 형식:
```
<제목 한 줄>

<본문 (옵션)>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

- 커밋 후 `/usr/bin/git status`로 성공 여부 확인
- pre-commit hook 실패 시: 문제를 수정한 뒤 **새 커밋**으로 재시도 (amend 금지)

## 4. 주의사항

- push는 하지 않는다 (사용자가 명시적으로 요청할 때만)
- 승인 단계는 생략 — 커밋 메시지를 출력한 뒤 곧바로 실행
- 파괴적 옵션(`--amend`, `--no-verify`, force push 등)은 사용자가 명시적으로 요청하지 않는 한 사용하지 않는다
