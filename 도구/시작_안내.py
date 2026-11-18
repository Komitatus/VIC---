#!/usr/bin/env python3
"""직접 실행하는 Codex 프로젝트 안내. 등록 콘텐츠의 실제 폴더를 읽는다."""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
registered = sorted(str(path.parent.relative_to(root / "콘텐츠")) for path in (root / "콘텐츠").glob("*/*/설정.json"))
message = """[Codex 콘텐츠 밸런스] 이 폴더를 Codex에서 열고 일반 문장으로 요청하세요.
등록: 내게임의 성장던전을 새 콘텐츠로 등록해줘.
설계: 성장던전 보상·성장 밸런스를 설계해줘. 무과금 p50 14~21일, 28일 도달률 90% 이상.
검증: 성장던전 모델을 검증하고 이 집계 로그 CSV와 대조해줘.
직접 스킬 지정: $new-content / $content-balance / $validate-balance
Python만으로 실행: python3 도구/밸런스.py --help
등록 콘텐츠: """ + (", ".join(registered) if registered else "없음 — 콘텐츠 등록부터 요청하세요")
print(message)
wuwa_documents = root / "문서" / "명조" / "index.html"
if wuwa_documents.is_file():
    print("명조 기획서·분석서·제안서: " + str(wuwa_documents))
print("예시게임 / 성장던전은 계산기 검증용 가상 예제이며 명조가 아닙니다.")
