#!/usr/bin/env python3
"""Codex에 전달할 로컬 원본과 등록된 콘텐츠를 표시한다."""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sources = [path for path in (root / "원본").glob("*") if not path.name.startswith(".")]
sources.extend(path for path in root.iterdir()
               if path.suffix.lower() in {".exe", ".apk", ".xapk", ".apks"} and path.is_file())

print('이 폴더를 Codex에서 열고 “분석해줘”라고 요청하세요.')
if sources:
    print("프로젝트에 놓인 원본")
    for path in sorted(sources):
        print("  " + str(path.relative_to(root)))
else:
    print("게임 실행파일 경로를 알려주거나 실행파일·설치 폴더·APK를 원본/에 놓으세요.")

registered = sorted(path.parent.relative_to(root / "콘텐츠")
                    for path in (root / "콘텐츠").glob("*/*/설정.json"))
if registered:
    print("등록 콘텐츠")
    for path in registered:
        print("  " + str(path))
print("신규 설계와 모델 검증은 python3 도구/밸런스.py --help 에서 확인하세요.")
