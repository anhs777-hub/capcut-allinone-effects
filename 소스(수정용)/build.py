# -*- coding: utf-8 -*-
"""캡컷자동올인원 빌드 스크립트.

app.py + capcut_core.py 를 PyInstaller 로 단일 exe 로 묶고,
실제로 쓰는 폴더(..\\캡컷 올인원 효과 프로그램\\app\\)의 exe 를 교체한다.

원본과 동일한 빌드 옵션:
  --onefile --windowed --name 캡컷자동올인원   (Python 3.13)

주의: effects.json / settings.json 은 exe 바깥(app 폴더)에 두는 데이터라
      exe 안에 넣지 않는다. 배포 폴더의 기존 파일은 건드리지 않는다.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "캡컷자동올인원"

# 새 exe 를 넣을 곳. 실제로 쓰는 폴더를 먼저 찾는다.
_PARENT = os.path.dirname(HERE)
_CANDIDATES = [
    os.path.join(_PARENT, "app"),                              # 이 폴더가 프로그램 폴더 안에 있을 때
    os.path.join(_PARENT, "캡컷 올인원 효과 프로그램", "app"),   # 바탕화면에 나란히 있을 때
    os.path.join(_PARENT, "다람바람_캡컷자동올인원_배포", "app"),
]
DIST_DIR = next((p for p in _CANDIDATES if os.path.isdir(p)), _CANDIDATES[0])


def main():
    if sys.version_info[:2] != (3, 13):
        print(f"[경고] 원본은 Python 3.13 으로 빌드되었습니다. 지금은 "
              f"{sys.version_info.major}.{sys.version_info.minor} 입니다.")

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[안내] PyInstaller 가 없어서 설치합니다...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", APP_NAME,
        os.path.join(HERE, "app.py"),
    ]
    print("[빌드]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)

    built = os.path.join(HERE, "dist", APP_NAME + ".exe")
    if not os.path.exists(built):
        raise SystemExit("[실패] 빌드 결과물을 찾지 못했습니다: " + built)
    print("[완료] " + built + f"  ({os.path.getsize(built):,} bytes)")

    if os.path.isdir(DIST_DIR):
        target = os.path.join(DIST_DIR, APP_NAME + ".exe")
        shutil.copy2(built, target)
        print("[배포] " + target + " 교체 완료")
    else:
        print("[안내] 배포 폴더가 없어 복사는 건너뜁니다: " + DIST_DIR)


if __name__ == "__main__":
    main()
