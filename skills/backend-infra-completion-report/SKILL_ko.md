---
name: backend-infra-completion-report
description: 백엔드, 인프라, 배포, 마이그레이션, 아키텍처, 보안, 호환성, 운영 작업에 대한 self-contained HTML 완료 보고서를 생성한다.
uuid: a43a68f9-fda2-4960-a49a-0a97ebf96a8a
language: ko
review_version: "1.0.0"
generated_at: "2026-05-25"
report_family: completion-report-html
recommended_output: out/report.html
recommended_mode: custom-skill-profile
primary_use_case: backend-infrastructure-completion-report
status: recommended
related_skills:
  - skill-creator
  - theme-factory
  - web-artifacts-builder: optional-only
dependencies:
  - python>=3.10
  - jinja2>=3.1
  - pyyaml>=6.0
  - markdown-it-py>=3.0
  - beautifulsoup4>=4.12
---

# 백엔드 / 인프라 완료 보고서 Skill

## 결론

공통 `completion-report-html` Skill 안에 **backend-infra 프로파일**을 두는 방식 사용.

보고서는 감사 가능한 문서형 HTML 산출물이어야 한다. 출력: `out/report.html` (self-contained).

## 추천 출력 구조

섹션:

1. 요약
2. 범위와 전제
3. 대상 환경
4. 완료 체크리스트
5. 아키텍처 개요
6. 인프라 토폴로지
7. 구현 단계
8. 설정 변경 사항
9. 검증 근거
10. 보안 검토
11. 호환성 및 deprecated 메모
12. 운영 영향도
13. 롤백 계획
14. 남은 작업
15. 부록: 명령어, 로그, 설정 조각, 원본 근거

## HTML 레이아웃

```text
Header: 제목, 날짜, 상태, 완료율, 위험도
Left nav: 섹션 앵커
Main: 요약 카드, 단계 타임라인, 아키텍처 다이어그램, 검증 표, 위험/호환성 블록, 부록
```

## 아키텍처 다이어그램 전략

1. Inline SVG (선호)
2. Mermaid → 빌드 시 SVG
3. ASCII (단순 토폴로지만)

외부 CDN 자산 금지.

## 승인 기준

- `out/report.html`이 브라우저에서 직접 열린다
- 모든 핵심 단계에 상태와 근거가 있다
- 아키텍처가 네트워크 없이 표시된다
- 보안 및 호환성 섹션이 존재한다
- deprecated/legacy 항목이 명확히 표시된다
- 위험한 변경에는 롤백 지침이 있다
- 명령어/로그/설정 근거가 부록에 포함된다
