---
name: wiki-skill-import
description: 고정된 읽기 전용 gateway 서버 또는 MCP 읽기 도구를 통해 UUID 기준 Wiki.js 콘텐츠를 읽는다. Wiki.js 직접 API 접근, curl, scraping 없이 영어/한국어 Markdown을 함께 조회한다.
---

# Wiki Skill Import

UUID를 기준으로 Wiki.js 콘텐츠를 읽는다. 모든 agent는 고정 gateway 서버를
통해서만 접근해야 한다. Wiki.js GraphQL API에 직접 연결하지 않는다.

이 skill은 두 가지 읽기 인터페이스를 지원한다.

- **MCP 읽기 인터페이스**: 클라이언트가 MCP를 지원하면 gateway MCP 서버를 사용한다.
- **REST 읽기 인터페이스**: MCP를 사용할 수 없을 때 gateway HTTP endpoint를 사용한다.

두 인터페이스 모두 이 skill에서는 읽기 전용이다.

## 고정 서버

```text
GATEWAY_URL=https://md-gw.zerotymer.net
GATEWAY_MCP_URL=https://md-gw.zerotymer.net/api/v2/mcp
GATEWAY_TOKEN=<token>   # 읽기는 선택
```

Agent가 사용하는 gateway는 읽기 전용이다. 이 skill은 콘텐츠 읽기만 설명한다.

## 접근 규칙

- 구조화된 콘텐츠 읽기는 고정 gateway 서버만 사용한다.
- 클라이언트가 MCP를 지원하면 MCP 읽기 도구를 우선 사용한다.
- MCP를 사용할 수 없으면 REST 읽기 endpoint를 사용한다.
- 현재 읽기는 토큰이 필요 없다. 그래도 토큰이 있으면 `Authorization: Bearer <GATEWAY_TOKEN>`을
  보낸다. 이후 버전에서 필수가 될 수 있다.
- 스크립트에서 REST endpoint를 호출할 때는 `User-Agent`를 명시한다 (아래 참고).
- Wiki.js GraphQL에 직접 접근하지 않는다.
- `curl`은 사용하지 않는다.
- Wiki.js HTML을 기본 데이터 소스로 가져오지 않는다.
- 렌더링된 HTML을 scraping, parsing하거나 HTML에서 Markdown을 추출하지 않는다.
- 이 skill에서 Wiki.js 콘텐츠를 변경하지 않는다.

`https://md.zerotymer.net/`은 Wiki.js 웹 UI다. Gateway 접근이 실패했을 때
사용자가 페이지 존재 여부를 사람이 직접 확인하는 보조 참고 용도로만 유도한다.
자동 import용 데이터 소스로 사용하지 않는다.

## MCP 읽기

MCP를 사용할 수 있으면 다음 서버에 연결한다.

```text
https://md-gw.zerotymer.net/api/v2/mcp
```

`get_page_by_uuid`에 대응하는 읽기 도구를 사용한다.

입력:

```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "type": "skill"
}
```

`type` 필드는 선택 사항이다. 호출자가 `skill`, `guide`, `agent` 같은 경로
prefix를 제공한 경우에만 포함한다. 제공되지 않았으면 생략한다.

MCP 읽기 도구는 shell 예시를 피하고 agent를 구조화된 tool contract 안에
머물게 하므로 우선 인터페이스로 사용한다.

## REST 읽기

MCP를 사용할 수 없으면 gateway REST 읽기 endpoint로 영어와 한국어 콘텐츠를
함께 조회한다.

```text
GET https://md-gw.zerotymer.net/api/v2/documents/<uuid>[?type=<type>]
Authorization: Bearer <GATEWAY_TOKEN>   # 선택
```

`type` 파라미터는 MCP 입력과 같은 규칙을 따른다. 호출자가 경로 prefix를
제공한 경우에만 전달한다.

### User-Agent

Gateway는 Cloudflare 뒤에 있으며, 일부 기본 클라이언트 User-Agent를 403으로
거부한다. 특히 Python의 `Python-urllib/3.x`가 해당된다. 대부분의 HTTP
클라이언트는 문제없다. Python(`urllib`, 스크립트, 도구)에서는 User-Agent를
명시한다.

```python
req = urllib.request.Request(url, headers={"User-Agent": "my-tool/1.0"})
```

## 응답 형태

MCP와 REST 읽기는 같은 논리 구조를 반환한다.

```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "type": "skill",
  "pages": {
    "en": {
      "id": 10,
      "path": "skill/550e8400-...",
      "locale": "en",
      "title": "My Skill",
      "description": "...",
      "content": "---\nname: my-skill\n---\n# My Skill\n...",
      "tags": ["skill"],
      "contentHash": "sha256..."
    },
    "ko": {
      "id": 11,
      "path": "skill/550e8400-...",
      "locale": "ko",
      "title": "내 스킬",
      "description": "...",
      "content": "---\nname: my-skill\n---\n# 내 스킬\n...",
      "tags": ["skill"],
      "contentHash": "sha256..."
    }
  }
}
```

locale이 없으면 해당 값은 `null`이다. 두 locale이 모두 없으면
`PAGE_NOT_FOUND`로 보고한다.

## 모드

동적 참조 모드:

1. 요청 시점에 gateway로 최신 콘텐츠를 읽는다.
2. MCP를 우선 사용하고, MCP를 사용할 수 없을 때만 REST를 사용한다.
3. 반환된 Markdown을 현재 작업의 임시 context로만 사용한다.
4. 프로젝트 파일을 쓰지 않는다.

가져오기 모드:

1. 요청 시점에 gateway로 최신 콘텐츠를 읽는다.
2. MCP를 우선 사용하고, MCP를 사용할 수 없을 때만 REST를 사용한다.
3. 사용자가 import, install, refresh, save, apply를 명시적으로 요청한 경우에만
   로컬 파일을 쓴다.
4. 영어와 한국어 파일을 항상 쌍으로 유지한다.

## 가져오기 레이아웃

skill을 프로젝트에 가져올 때는 다음 위치에 쓴다.

```text
skills/<skill-name>/
  SKILL.md
  SKILL_ko.md
```

이 저장소 안에서 Wiki.js 문서 수정본을 내보낼 때는 `md/`를 수정하지 않는다.
다음 위치에 언어별 사본을 쓴다.

```text
.output/<uuid>/
  en.md
  ko.md
  meta.json
```

## 콘텐츠 규칙

- `pages.en.content`를 영어 Markdown 원본으로 사용한다.
- `pages.ko.content`를 한국어 Markdown 원본으로 사용한다.
- 두 locale은 의미상 동일하게 유지한다.
- 언어별 필드가 아닌 frontmatter는 서로 맞춘다.
- skill 파일의 최종 `SKILL.md`는 반드시 `name`과 `description`이 있는 skill
  frontmatter로 시작해야 한다. Wiki.js page frontmatter가 그 앞에 오면 제거한다.

## 오류 처리

| 상황 | 처리 |
| --- | --- |
| MCP 사용 불가 | REST 읽기 endpoint 사용 (토큰 불필요) |
| gateway 연결 실패 | 고정 gateway URL과 UUID를 보고하고 중단 |
| 본문이 plain text/HTML이고 `X-Served-By` 헤더 없는 403 | Cloudflare의 User-Agent 차단; User-Agent를 명시하고 재시도 |
| 그 외 401 / 403 | 인증 또는 권한 실패로 보고하고 중단 |
| 두 locale 모두 없음 | `PAGE_NOT_FOUND`를 보고하고, best-effort 요청이 없으면 중단 |
| 한 locale만 없음 | 사용자가 partial import를 허용한 경우에만 가능한 locale 사용 |
| `content` 비어 있음 | 경고하고 빈 파일은 쓰지 않음 |
| skill `name` 없음 | `title`에서 slug를 만들고 경고한 뒤, import mode에서만 계속 |

