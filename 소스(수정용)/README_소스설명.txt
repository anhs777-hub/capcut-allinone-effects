==========================================
  캡컷자동올인원 — 소스 코드 (복원본)
  made by 바람님 (with Claude Code)
==========================================

[이 폴더는 무엇인가요?]
  컴퓨터 포맷으로 사라진 소스 코드를,
  배포 폴더에 남아있던 exe 안에서 복원한 것입니다.

  원본 exe(app\캡컷자동올인원.exe) 안의 파이썬 바이트코드와
  여기 소스를 컴파일한 결과가 100% 일치하는 것을 확인했습니다.
  (명령어·상수·줄번호·컬럼 위치까지 전부 동일 / 차이 0건)
  즉 주석과 빈 줄을 뺀 모든 코드가 원본 그대로입니다.


------------------------------------------
[1] 파일 구성
------------------------------------------
  app.py            GUI (tkinter). 5개 탭 · 미리보기 · 설정 저장.
  capcut_core.py    엔진. 캡컷 draft(zip)를 읽어 모션 키프레임/전환/
                    필터/화면효과/로고/자막 스타일/챕터 제목을 적용.
  effects.json      기본 효과 카탈로그 (배포 폴더 것의 사본).
                    실제로 쓰이는 파일은 배포 폴더의 app\effects.json 입니다.
  build.py          PyInstaller 빌드 스크립트.
  빌드하기.bat       build.py 실행용 (더블클릭).
  캡컷자동올인원.spec  PyInstaller가 만든 스펙 파일.


------------------------------------------
[2] 그냥 실행해 보려면
------------------------------------------
  python app.py

  * Python 3.13 권장 (원본이 3.13으로 빌드됨).
  * 추가 설치할 패키지 없음. 표준 라이브러리(tkinter)만 씁니다.
  * 이때는 settings.json / effects.json 을 이 폴더에서 읽고 씁니다.


------------------------------------------
[3] exe로 다시 만들려면
------------------------------------------
  "빌드하기.bat" 더블클릭  (또는  py -3.13 build.py)

  하는 일:
    1) PyInstaller 없으면 자동 설치
    2) --onefile --windowed 로 캡컷자동올인원.exe 생성 (dist\ 폴더)
    3) ..\다람바람_캡컷자동올인원_배포\app\캡컷자동올인원.exe 를 교체

  ★ 3번에서 배포용 exe를 덮어씁니다. 기존 exe를 남겨두고 싶으면
    먼저 백업하거나, build.py 아래쪽 복사 부분을 지우세요.
  ★ effects.json / settings.json 은 exe에 넣지 않습니다.
    (app 폴더에 있는 파일을 그대로 읽어야 사용자가 고칠 수 있으니까요)


------------------------------------------
[4] 코드 지도 (어디를 고치면 뭐가 바뀌나)
------------------------------------------
■ app.py
  DEFAULT_SETTINGS   처음 실행 시 기본값 (로고 위치/자막 색 등)
  SNAP_MODES         [기본] 탭의 "휙 컷 빈도" 선택지
  LOGO_PRESETS       [로고] 탭 위치 프리셋
  App._build_basic/_build_fx/_build_logo/_build_sub
                     각 탭 UI
  App._build_chapter [챕터] 탭 UI (붙여넣기 칸 · txt 읽기 · 미리보기 · 목록)
  App.reload_chapters  붙여넣기 칸 내용 → 목록/미리보기 갱신 (파싱은 여기 한 곳)
  CHAPTER_PRESETS    챕터 제목 위치 프리셋
  App.collect_opts   GUI 값 → core.process 에 넘길 opts 만들기
  App.persist        settings.json / effects.json 저장
  App.done           완료 팝업 문구 (휙 컷 시각 표시)

■ capcut_core.py
  US / FRAME         시간 단위 (1초 = 1,000,000)
  FILL_PHOTO/VIDEO   사진 105% / 영상 110% 확대 (검은 여백 방지)
  ZOOM_HI            줌 최대 배율 (1.48)
  SNAP_RANGES        휙 컷 간격 (rare=180~240초, often=60~120초)
  TRANSITION_DURATIONS  전환 길이 후보
  build_motion       한 씬의 드리프트 + 휙 컷 키프레임 궤적 생성
  apply_motion       모든 씬에 키프레임 적용 + 휙 컷 씬 선정
  apply_transitions  씬 사이 전환 랜덤 삽입
  apply_global_effects  전체 구간 필터/화면효과 트랙 생성
  apply_logo         로고 오버레이 트랙 생성
  apply_subtitle_style  자막 색/배경/테두리/폰트/위치 일괄 변경
  parse_chapters     "0:00 인트로" 같은 줄 → [(시작us, 제목)]
  read_text_file     텍스트 파일 읽기 (utf-8 / cp949)
  read_chapter_file  챕터 txt 읽어서 바로 파싱
  text_material      텍스트 머티리얼 새로 만들기 (제목 한 줄)
  text_width_norm    제목 폭 어림 (왼쪽 끝 맞추기 보정용)
  apply_chapter_titles  챕터 시작마다 제목 세그먼트를 얹은 text 트랙 생성
  normalize_layers   트랙 레이어 순서 정리
                     (효과가 자막 아래로 가서 자막이 안 뿌예짐)
  process            전체 파이프라인 + "[완성] *.zip" 쓰기

==========================================
