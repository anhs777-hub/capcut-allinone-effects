# -*- coding: utf-8 -*-
"""마지막 씬을 늘려서 음성이 끝난 뒤에도 화면이 잠깐 더 머물게 한다.

  python hold_last.py "완성.zip" [--hold 1.0]

캡컷에서 마지막 씬(아웃트로/CTA)이 음성보다 먼저 끊기는 경우를 고친다.
음성·자막 중 가장 늦게 끝나는 시각을 찾아, 그보다 --hold 초 만큼
화면이 더 유지되도록 마지막 씬과 로고를 늘린다.

  --hold 1.0   음성이 끝난 뒤 몇 초 더 유지할지 (기본 1.0초)
  --check      바꾸지 않고 현재 상태만 보기
  --out        저장할 파일명 직접 지정
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _capcut import (US, Project, die, fmt_time,          # noqa: E402
                     out_path_with_suffix, setup_console)

STILL_LIMIT = 3600 * US      # 캡컷은 사진 소재 길이를 10800초로 잡는다


# ── 트랙 끝 시각 ──────────────────────────────────────────────

def track_end(track):
    end = 0
    for s in track.get("segments") or []:
        tr = s.get("target_timerange") or {}
        end = max(end, int(tr.get("start", 0)) + int(tr.get("duration", 0)))
    return end


def last_segment(track):
    segs = track.get("segments") or []
    if not segs:
        return None
    return max(segs, key=lambda s: int(s["target_timerange"]["start"]))


def content_end(pj):
    """음성·자막이 끝나는 시각 (둘 중 늦은 쪽)."""
    ends = {}
    for t in pj.draft.get("tracks") or []:
        typ = t.get("type")
        if typ in ("audio", "text") and t.get("segments"):
            ends[typ] = max(ends.get(typ, 0), track_end(t))
    return ends


# ── 세그먼트 늘리기 ───────────────────────────────────────────

def set_speed(pj, seg, speed, idx):
    """세그먼트에 걸린 speed 머티리얼까지 같이 바꾼다."""
    seg["speed"] = round(float(speed), 6)
    for r in seg.get("extra_material_refs") or []:
        bucket, m = idx.get(r, (None, None))
        if bucket == "speeds" and isinstance(m, dict):
            m["speed"] = round(float(speed), 6)
            m["mode"] = 0
            m["curve_speed"] = None


def extend_segment(pj, seg, extra, idx):
    """세그먼트를 extra 만큼 늘린다. 어떻게 늘렸는지 설명을 돌려준다.

    키프레임(줌/이동)은 세그먼트 로컬 시각이라 건드리지 않는다.
    마지막 키프레임 이후로는 그 값이 그대로 유지돼서,
    늘어난 구간은 화면이 멈춘 것처럼 보인다. (원하는 동작)
    """
    tr = seg["target_timerange"]
    new_dur = int(tr["duration"]) + int(extra)
    src = seg.get("source_timerange")
    bucket, mat = idx.get(seg.get("material_id"), (None, None))
    mat_dur = int((mat or {}).get("duration") or 0)

    if not src:                                   # 소스 구간이 없는 소재
        tr["duration"] = new_dur
        return "그대로 늘림"

    s0 = int(src.get("start", 0))
    sdur = int(src.get("duration", 0))
    speed = float(seg.get("speed") or 1.0) or 1.0

    is_still = mat_dur >= STILL_LIMIT or (mat or {}).get("type") == "photo"
    if is_still:
        tr["duration"] = new_dur
        src["duration"] = int(round(new_dur * speed))
        return "사진이라 그대로 늘림"

    need = int(round(new_dur * speed))            # 같은 속도로 필요한 소스 길이
    spare = mat_dur - s0
    if need <= spare:
        tr["duration"] = new_dur
        src["duration"] = need
        return f"남은 소재를 {(need - sdur) / US:.2f}초 더 사용"

    # 소재가 모자라면 속도를 낮춰 같은 소스를 더 길게 편다
    new_speed = sdur / new_dur
    tr["duration"] = new_dur
    set_speed(pj, seg, new_speed, idx)
    return f"소재가 모자라 속도 {speed:.3f}x → {new_speed:.3f}x 로 늦춤"


# ── 본체 ─────────────────────────────────────────────────────

def main():
    setup_console()
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("zip")
    ap.add_argument("--hold", type=float, default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()

    pj = Project(a.zip)
    main_tr = pj.main_track()
    idx = pj.material_index()

    ends = content_end(pj)
    if not ends:
        die("음성·자막 트랙을 찾지 못했어요. 늘릴 기준이 없습니다.")
    voice_end = max(ends.values())
    which = max(ends, key=lambda k: ends[k])
    label = {"audio": "음성", "text": "자막"}[which]

    main_end = track_end(main_tr)
    tl_end = pj.timeline_end()

    print(f"프로젝트: {os.path.basename(a.zip)}   전체 길이 {fmt_time(tl_end)}")
    print("\n  트랙별 끝나는 시각")
    for t in pj.draft.get("tracks") or []:
        if not t.get("segments"):
            continue
        nm = {"video": "화면", "audio": "음성", "text": "자막",
              "effect": "화면효과", "filter": "필터", "sticker": "스티커"}
        typ = nm.get(t.get("type"), t.get("type"))
        if t.get("type") == "video" and t is not main_tr:
            typ = "로고/워터마크"
        elif t.get("type") == "video":
            typ = "화면 (메인)"
        print(f"    {typ:<14} {fmt_time(track_end(t))}")

    gap = voice_end - main_end
    print(f"\n  {label}이 끝나는 시각   {fmt_time(voice_end)}")
    print(f"  화면이 끝나는 시각   {fmt_time(main_end)}", end="")
    if gap > 0:
        print(f"   ← {gap / US:.2f}초 먼저 끊깁니다")
    else:
        print(f"   (이미 {-gap / US:.2f}초 더 유지됨)")

    hold = a.hold
    if hold is None and not a.check:
        try:
            raw = input("\n  음성이 끝난 뒤 몇 초 더 유지할까요? (엔터=1.0초): ")
        except EOFError:
            raw = ""
        # BOM·공백·"1.5초" 같은 군더더기를 걷어내고 숫자만 읽는다
        raw = raw.replace("﻿", "").strip()
        if not raw:
            hold = 1.0
        else:
            m = re.search(r"[-+]?\d*[.,]?\d+", raw)
            if not m:
                die(f"숫자로 적어주세요: {raw!r}")
            hold = float(m.group().replace(",", "."))
    if hold is None:
        hold = 1.0

    target = voice_end + int(round(hold * US))
    extra = target - main_end

    if a.check:
        print(f"\n  {hold:.1f}초 여운을 주려면 마지막 씬을 "
              f"{extra / US:+.2f}초 늘려야 합니다.")
        return

    if extra <= 0:
        print(f"\n  이미 {label} 끝나고 {-gap / US:.2f}초 이상 유지되고 있어서 "
              f"바꿀 게 없습니다.")
        return

    # 마지막 씬 늘리기
    seg = last_segment(main_tr)
    st = int(seg["target_timerange"]["start"])
    before = int(seg["target_timerange"]["duration"])
    how = extend_segment(pj, seg, extra, idx)
    print(f"\n  마지막 씬 {fmt_time(st)} ~ {fmt_time(main_end)}")
    print(f"    {before / US:.2f}초 → {(before + extra) / US:.2f}초  "
          f"(+{extra / US:.2f}초)")
    print(f"    {how}")
    print("    줌/이동은 원래 끝값에서 멈춘 채로 유지됩니다.")
    if "속도" in how:
        slow = (before + extra) / before - 1
        if slow > 0.2:
            print(f"    ※ 이 씬이 {slow * 100:.0f}% 느려집니다. "
                  f"움직임이 많은 씬이면 눈에 띌 수 있어요.")
            print("      신경 쓰이면 여운을 줄여서 다시 돌려보세요.")

    # 끝까지 깔려 있던 로고·워터마크도 같이 늘린다
    for t in pj.video_tracks():
        if t is main_tr:
            continue
        e = track_end(t)
        if e < main_end - US:            # 끝까지 안 가던 트랙은 그대로 둔다
            continue
        s2 = last_segment(t)
        how2 = extend_segment(pj, s2, target - e, idx)
        print(f"\n  로고/워터마크도 {fmt_time(e)} → {fmt_time(target)} 로 늘림")
        print(f"    {how2}")

    pj.draft["duration"] = pj.timeline_end()

    out = a.out or out_path_with_suffix(pj.path, "_여운")
    pj.save(out)
    print(f"\n[완료] {os.path.basename(out)}")
    print(f"       {out}")

    # 자기검사
    chk = Project(out)
    m2 = chk.main_track()
    new_main_end = track_end(m2)
    ok_end = new_main_end >= voice_end + int(round(hold * US)) - 2
    overlap = 0
    for t in chk.draft.get("tracks") or []:
        end = None
        for s in sorted(t.get("segments") or [],
                        key=lambda x: int(x["target_timerange"]["start"])):
            s0 = int(s["target_timerange"]["start"])
            if end is not None and s0 < end:
                overlap += 1
            end = s0 + int(s["target_timerange"]["duration"])
    print("\n  [자기검사]")
    print(f"    {'✔' if ok_end else '✘'} 화면이 {label} 끝나고 "
          f"{(new_main_end - voice_end) / US:.2f}초 더 유지됨")
    print(f"    {'✔' if overlap == 0 else '✘'} 겹치는 클립 없음"
          + (f"  ({overlap}건)" if overlap else ""))
    print(f"    ✔ 전체 길이 {fmt_time(chk.timeline_end())}")
    print("\n       이 파일을 캡컷으로 불러오세요.")
    print("       ※ 같은 이름 프로젝트가 캡컷에 열려 있으면 먼저 닫아주세요.")


if __name__ == "__main__":
    main()
