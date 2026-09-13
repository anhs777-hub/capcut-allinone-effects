# -*- coding: utf-8 -*-
"""캡컷 프로젝트에 인트로 영상을 끼워 넣는다.

  python add_intro.py "완성.zip" "인트로.mp4" [옵션]

위치 지정
  --at 5            5번째 씬 앞          (숫자만 = 씬 번호)
  --at -1           마지막 씬 앞
  --at start / end  맨 앞 / 맨 뒤
  --at 55.1         55.10초 근처의 씬 경계
  --at 0:00:55:10   55초 10프레임 근처의 씬 경계
  --exact           씬 경계로 붙이지 말고 그 시각에서 씬을 갈라 정확히 넣기

옵션
  --list            씬 목록만 보고 끝내기
  --fill crop       인트로를 화면에 꽉 채우기 (위아래 검은 띠 제거)
  --mute            인트로 소리 끄기
  --logo-on-intro   인트로 위에도 로고 띄우기
  --bgm keep        배경음악을 인트로 구간에서 끊지 않기
"""

import argparse
import copy
import hashlib
import json
import os
import sys
import uuid
import zipfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _capcut import (US, Project, fmt_time, fmt_dur, new_id, dup_material,   # noqa: E402
                     out_path_with_suffix, parse_position, probe_mp4,
                     setup_console, split_segment, die)

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")


# ── 씬 목록 ────────────────────────────────────────────────────

def print_scenes(pj, limit=None):
    segs = pj.scenes()
    print("  번호   시작 시각      길이")
    rows = list(enumerate(segs, 1))
    if limit and len(rows) > limit:
        head, tail = rows[:limit - 3], rows[-3:]
    else:
        head, tail = rows, []
    for i, s in head:
        tr = s["target_timerange"]
        print(f"  {i:4d}   {fmt_time(tr['start'])}   {tr['duration'] / US:8.1f}초")
    if tail:
        print(f"   ...   ({len(rows) - len(head) - len(tail)}개 생략)")
        for i, s in tail:
            tr = s["target_timerange"]
            print(f"  {i:4d}   {fmt_time(tr['start'])}   {tr['duration'] / US:8.1f}초")


# ── 위치 결정 ──────────────────────────────────────────────────

def boundaries(segs):
    b = [int(s["target_timerange"]["start"]) for s in segs]
    last = segs[-1]["target_timerange"]
    b.append(int(last["start"]) + int(last["duration"]))
    return b


def scene_at(segs, t):
    """t 를 품고 있는 씬 index (경계면 None)."""
    for i, s in enumerate(segs):
        tr = s["target_timerange"]
        st, du = int(tr["start"]), int(tr["duration"])
        if st < t < st + du:
            return i
    return None


def resolve(pj, spec, exact):
    """PosSpec -> (넣을 시각, 씬 index, 가를 씬 index 또는 None, 안내문 리스트)"""
    segs = pj.scenes()
    bnd = boundaries(segs)
    notes = []

    if spec.kind == "start":
        return bnd[0], 0, None, notes
    if spec.kind == "end":
        return bnd[-1], len(segs), None, notes
    if spec.kind == "scene":
        k = spec.value
        if k == 0:
            die("씬 번호는 1부터입니다. (맨 앞은 엔터 또는 start)")
        idx = (k - 1) if k > 0 else (len(segs) + k)
        if not 0 <= idx <= len(segs):
            die(f"씬 번호 범위를 벗어났습니다 (1 ~ {len(segs)}, 또는 -1 ~ -{len(segs)})")
        return int(segs[idx]["target_timerange"]["start"]), idx, None, notes

    # 시각 지정
    t = max(0, min(int(spec.value), bnd[-1]))
    inside = scene_at(segs, t)
    if exact and inside is not None:
        notes.append(f"요청한 시각 {fmt_time(t)} 에 정확히 넣습니다 (--exact)")
        return t, inside + 1, inside, notes

    near = min(bnd, key=lambda b: abs(b - t))
    idx = bnd.index(near)
    if near != t:
        diff = (near - t) / US
        notes.append(f"요청한 시각 {fmt_time(t)} → 가장 가까운 씬 경계로 붙였습니다 "
                     f"({diff:+.2f}초)")
        if abs(diff) >= 1.0:
            notes.append(f"※ {abs(diff):.1f}초 차이가 납니다. 씬 중간을 자르지 않고 "
                         f"경계에만 넣기 때문입니다. 정확히 넣으려면 --exact 를 쓰세요.")
    return near, idx, None, notes


# ── 인트로 머티리얼/세그먼트 만들기 ────────────────────────────

def contain_dims(w, h, cw, ch):
    r = min(cw / w, ch / h)
    return w * r, h * r


def cover_scale(w, h, cw, ch):
    dw, dh = contain_dims(w, h, cw, ch)
    return max(cw / dw, ch / dh)


def build_intro_material(pj, arc_name, w, h, dur, has_audio):
    """기존 영상 머티리얼을 본떠서 인트로용 머티리얼을 만든다."""
    vids = (pj.draft.get("materials") or {}).get("videos") or []
    base = None
    for v in vids:
        if v.get("type") == "video":
            base = v
            break
    if base is None:
        die("프로젝트에 영상 머티리얼이 없어 인트로를 만들 수 없습니다.")
    mat = copy.deepcopy(base)
    mat["id"] = new_id()
    mat["type"] = "video"
    mat["path"] = pj.placeholder_prefix() + "/Resources/" + arc_name
    mat["material_name"] = arc_name
    if "extra_info" in mat:            # 원본 클립에 없는 키는 새로 만들지 않는다
        mat["extra_info"] = arc_name
    mat["width"] = int(w)
    mat["height"] = int(h)
    mat["duration"] = int(dur)
    mat["has_audio"] = bool(has_audio)
    for k in ("local_material_id", "material_id", "md5", "request_id",
              "reverse_path", "intensifies_path", "origin_material_id"):
        if k in mat:
            mat[k] = ""
    if isinstance(mat.get("crop"), dict):
        mat["crop"] = {"lower_left_x": 0.0, "lower_left_y": 1.0,
                       "lower_right_x": 1.0, "lower_right_y": 1.0,
                       "upper_left_x": 0.0, "upper_left_y": 0.0,
                       "upper_right_x": 1.0, "upper_right_y": 0.0}
    mat["crop_scale"] = 1.0
    pj.draft["materials"].setdefault("videos", []).append(mat)
    return mat


def build_intro_segment(pj, template, mat, at_us, dur, scale, mute):
    """본편 세그먼트를 본떠서 인트로 세그먼트를 만든다."""
    seg = copy.deepcopy(template)
    seg["id"] = new_id()
    seg["material_id"] = mat["id"]
    seg["target_timerange"] = {"start": int(at_us), "duration": int(dur)}
    seg["source_timerange"] = {"start": 0, "duration": int(dur)}
    seg["speed"] = 1.0
    seg["common_keyframes"] = []
    seg["keyframe_refs"] = []
    seg["clip"] = {
        "scale": {"x": round(scale, 6), "y": round(scale, 6)},
        "rotation": 0.0,
        "transform": {"x": 0.0, "y": 0.0},
        "flip": {"vertical": False, "horizontal": False},
        "alpha": 1.0,
    }
    seg["uniform_scale"] = {"on": True, "value": 1.0}
    seg["volume"] = 0.0 if mute else 1.0
    seg["last_nonzero_volume"] = 1.0

    idx = pj.material_index()
    trans_ids = {t["id"] for t in (pj.draft.get("materials") or {})
                 .get("transitions", []) or [] if t.get("id")}
    refs = []
    for r in template.get("extra_material_refs") or []:
        if r in trans_ids:
            continue                      # 인트로 앞뒤는 컷
        new_ref = dup_material(pj, r, idx)
        refs.append(new_ref)
        bucket, m = idx.get(new_ref, (None, None))
        if bucket == "speeds" and isinstance(m, dict):
            m["speed"] = 1.0
            m["mode"] = 0
            m["curve_speed"] = None
    seg["extra_material_refs"] = refs
    return seg


def register_meta(pj, arc_name, w, h, dur):
    """draft_meta_info.json 에 인트로 파일을 등록 (캡컷 파일 인식용).

    file_Path 형식이 다른 항목과 어긋나면 캡컷이 "미디어 분실"로 띄운다.
    내보낸 zip 안에서는 "##_draftpath_placeholder_...##/Resources/파일명" 형식이라
    실제로 파일이 등록된 항목들의 형식을 그대로 따라간다.
    (경로가 빈 더미 항목이 목록 맨 앞에 있는 경우가 있어 그런 건 걸러낸다)
    """
    if not isinstance(pj.meta, dict):
        return False
    groups = pj.meta.setdefault("draft_materials", [])
    g0 = next((g for g in groups if g.get("type") == 0), None)
    if g0 is None:
        g0 = {"type": 0, "value": []}
        groups.append(g0)
    vals = g0.setdefault("value", [])

    real = [v for v in vals if isinstance(v.get("file_Path"), str)
            and "/Resources/" in v["file_Path"]]
    if real:
        common = Counter(v["file_Path"].split("/Resources/")[0] for v in real)
        prefix = common.most_common(1)[0][0] + "/Resources/"
    else:
        prefix = pj.placeholder_prefix() + "/Resources/"

    sample = (next((v for v in real if v.get("metetype") == "video"), None)
              or (real[0] if real else None))
    entry = copy.deepcopy(sample) if sample else {}
    entry.update({
        "id": str(uuid.uuid4()),
        "extra_info": arc_name,
        "file_Path": prefix + arc_name,
        "width": int(w), "height": int(h),
        "duration": int(dur),
        "metetype": "video",
        "type": 0,
        "md5": "",
        "roughcut_time_range": {"duration": -1, "start": -1},
        "sub_time_range": {"duration": -1, "start": -1},
    })
    vals.append(entry)
    return True


# ── 만든 zip 자기검사 ─────────────────────────────────────────

def verify_output(out, arc_path, mat_id, src_md5):
    """만든 zip 을 다시 열어 인트로가 제대로 붙었는지 확인한다.

    캡컷에서 "미디어 분실" 로 뜨는 원인은 대부분 여기서 걸러진다.
    """
    checks = []

    def ok(cond, label, detail=""):
        checks.append((bool(cond), label, detail))

    tail = arc_path.split("/Resources/")[-1]
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        entry = next((n for n in names if os.path.basename(n)
                      in ("draft_info.json", "draft_content.json")), None)
        meta_name = next((n for n in names
                          if os.path.basename(n) == "draft_meta_info.json"), None)
        draft = json.loads(z.read(entry).decode("utf-8")) if entry else {}

        # 1. 영상 파일이 온전히 들어갔나
        if arc_path in names:
            blob = z.read(arc_path)
            ok(hashlib.md5(blob).hexdigest() == src_md5,
               "인트로 영상이 zip 안에 온전히 들어감", f"{len(blob):,} bytes")
        else:
            ok(False, "인트로 영상이 zip 안에 들어감", "파일이 없음")

        # 2. 머티리얼이 그 파일을 정확히 가리키나
        vids = (draft.get("materials") or {}).get("videos") or []
        mat = next((v for v in vids if v.get("id") == mat_id), None)
        ok(mat is not None and (mat.get("path") or "").endswith("/Resources/" + tail),
           "머티리얼 경로가 그 파일을 가리킴", tail)

        # 3. 경로 접두사가 다른 클립과 같은가 (다르면 캡컷이 못 찾는다)
        others = [v["path"] for v in vids if v.get("id") != mat_id and v.get("path")]
        if mat and others:
            ok((mat.get("path") or "").split("/Resources/")[0]
               == others[0].split("/Resources/")[0],
               "경로 형식이 다른 클립과 동일")

        # 4. draft_meta_info 등록
        if meta_name:
            meta = json.loads(z.read(meta_name).decode("utf-8"))
            vals = [v for g in meta.get("draft_materials") or []
                    for v in (g.get("value") or [])]
            mine = [v for v in vals if (v.get("file_Path") or "").endswith("/" + tail)]
            ok(mine, "draft_meta_info 에 등록됨")
            rest = [v["file_Path"] for v in vals
                    if v.get("file_Path") and not v["file_Path"].endswith("/" + tail)]
            if mine and rest:
                ok(mine[0]["file_Path"].split("/Resources/")[0]
                   == rest[0].split("/Resources/")[0],
                   "등록 경로 형식이 다른 파일과 동일")

        # 5. 세그먼트 연결 · 겹침
        ids = {m.get("id") for arr in (draft.get("materials") or {}).values()
               if isinstance(arr, list) for m in arr if isinstance(m, dict)}
        orphan = overlap = intro_seg = 0
        for t in draft.get("tracks") or []:
            end = None
            for s in sorted(t.get("segments") or [],
                            key=lambda x: int(x["target_timerange"]["start"])):
                mid = s.get("material_id")
                if mid and mid not in ids:
                    orphan += 1
                if mid == mat_id:
                    intro_seg += 1
                st = int(s["target_timerange"]["start"])
                if end is not None and st < end:
                    overlap += 1
                end = st + int(s["target_timerange"]["duration"])
        ok(intro_seg == 1, "타임라인에 인트로 클립 1개", f"{intro_seg}개")
        ok(orphan == 0, "끊긴 참조 없음", f"{orphan}건" if orphan else "")
        ok(overlap == 0, "겹치는 클립 없음", f"{overlap}건" if overlap else "")

    print("\n  [자기검사]")
    for good, label, detail in checks:
        print(f"    {'✔' if good else '✘'} {label}" + (f"  ({detail})" if detail else ""))
    return all(c[0] for c in checks)


# ── 트랙 밀기 / 끊기 ───────────────────────────────────────────

def is_logo_track(pj, track):
    return track.get("type") == "video" and track is not pj.main_track()


def extend_over(pj, seg, gap, mat_index):
    """세그먼트를 인트로 구간만큼 늘려서 끊기지 않게 한다."""
    tr = seg["target_timerange"]
    tr["duration"] = int(tr["duration"]) + gap
    src = seg.get("source_timerange")
    if src:
        speed = float(seg.get("speed") or 1.0) or 1.0
        want = int(src.get("duration", 0)) + int(round(gap * speed))
        hit = mat_index.get(seg.get("material_id"))
        limit = None
        if hit and isinstance(hit[1], dict) and hit[1].get("duration"):
            limit = int(hit[1]["duration"]) - int(src.get("start", 0))
        if limit is not None and want > limit:
            if hit[1].get("type") == "photo":
                hit[1]["duration"] = int(hit[1]["duration"]) + gap   # 사진은 늘려도 됨
                src["duration"] = want
                return True
            src["duration"] = max(0, limit)
            return False
        src["duration"] = want
    return True


def shift_and_split(pj, at_us, gap, keep_logo, keep_bgm):
    """at_us 이후를 gap 만큼 밀고, 걸친 세그먼트는 앞뒤로 가른다."""
    main = pj.main_track()
    mat_index = pj.material_index()
    report = {"split": 0, "shift": 0, "extend": 0, "short": []}

    for track in pj.draft.get("tracks", []):
        ttype = track.get("type")
        keep = (ttype == "audio" and keep_bgm) or (is_logo_track(pj, track) and keep_logo)
        out = []
        for seg in list(track.get("segments") or []):
            tr = seg.get("target_timerange") or {}
            st, du = int(tr.get("start", 0)), int(tr.get("duration", 0))
            if st >= at_us:
                tr["start"] = st + gap
                report["shift"] += 1
                out.append(seg)
            elif st + du <= at_us:
                out.append(seg)
            else:                                    # 인트로 지점에 걸친 세그먼트
                if keep:
                    ok = extend_over(pj, seg, gap, mat_index)
                    report["extend"] += 1
                    if not ok:
                        report["short"].append(ttype)
                    out.append(seg)
                else:
                    front, back = split_segment(pj, seg, at_us, mat_index)
                    back["target_timerange"]["start"] += gap
                    report["split"] += 1
                    out.extend([front, back])
        track["segments"] = sorted(out, key=lambda s: int(
            (s.get("target_timerange") or {}).get("start", 0)))
    return report, main


# ── 메인 ───────────────────────────────────────────────────────

def sort_inputs(files):
    """드래그 순서와 무관하게 zip / 영상 을 가른다."""
    zips = [f for f in files if f.lower().endswith(".zip")]
    vids = [f for f in files if f.lower().endswith(VIDEO_EXT)]
    if not zips:
        die("캡컷 프로젝트 zip 을 같이 넣어주세요.")
    if not vids:
        die("인트로 영상(mp4)을 같이 넣어주세요.\n"
            "     Ctrl 누르고 zip + mp4 를 같이 클릭해서 함께 끌어놓으세요.")
    return zips[0], vids[0]


def ask_position(pj):
    print()
    print_scenes(pj, limit=25)
    print()
    print("  엔터=맨 앞 · end=맨 뒤 · 숫자=씬 번호 · -1=마지막 씬 앞")
    print("  시간은 55.1 / 55.1s / 0:55.1 / 0:00:55:10 (초:프레임)")
    try:
        raw = input("  Position: ")
    except EOFError:
        raw = ""
    spec = parse_position(raw, pj.fps)
    while spec is None:
        print("  못 알아들었어요. 예: 5 / -1 / end / 55.1 / 0:00:55:10")
        try:
            raw = input("  Position: ")
        except EOFError:
            raw = ""
        spec = parse_position(raw, pj.fps)
    exact = False
    if spec.kind == "time":
        try:
            exact = (input("  Exact? (씬을 갈라 정확히 그 시각에 넣기) y/N: ")
                     .strip().lower().startswith("y"))
        except EOFError:
            exact = False
    return spec, exact


def main():
    setup_console()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("files", nargs="+", help="프로젝트 zip 과 인트로 영상 (순서 무관)")
    ap.add_argument("--at", default=None, help="넣을 위치 (씬 번호 / 시각 / start / end)")
    ap.add_argument("--exact", action="store_true", help="씬을 갈라 정확한 시각에 넣기")
    ap.add_argument("--list", action="store_true", help="씬 목록만 보기")
    ap.add_argument("--fill", choices=("fit", "crop"), default="fit",
                    help="crop = 화면에 꽉 채워 검은 띠 제거")
    ap.add_argument("--mute", action="store_true", help="인트로 소리 끄기")
    ap.add_argument("--logo-on-intro", action="store_true", help="인트로 위에도 로고")
    ap.add_argument("--bgm", choices=("split", "keep"), default="split",
                    help="keep = 배경음악을 인트로에서 끊지 않음")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    if a.list and len(a.files) == 1:
        pj = Project(a.files[0])
        print(f"파일: {os.path.basename(pj.path)}   씬 {len(pj.scenes())}개   "
              f"길이 {fmt_time(pj.timeline_end())}\n")
        print_scenes(pj)
        return

    zip_path, mp4_path = sort_inputs(a.files)
    pj = Project(zip_path)
    segs = pj.scenes()
    print(f"프로젝트: {os.path.basename(pj.path)}   씬 {len(segs)}개   "
          f"길이 {fmt_time(pj.timeline_end())}")

    if a.list:
        print()
        print_scenes(pj)
        return

    dur, w, h, has_audio = probe_mp4(mp4_path)
    if not dur:
        die("인트로 영상의 길이를 읽지 못했습니다: " + os.path.basename(mp4_path))
    w = w or 1920
    h = h or 1080
    print(f"인트로:   {os.path.basename(mp4_path)}   {w}x{h}   {dur / US:.2f}초"
          f"   소리 {'있음' if has_audio else '없음'}")

    cc = pj.draft.get("canvas_config") or {}
    cw = int(cc.get("width") or 1920)
    ch = int(cc.get("height") or 1080)
    scale = 1.0
    if a.fill == "crop":
        scale = round(cover_scale(w, h, cw, ch), 6)
        print(f"          --fill crop → 배율 {scale} 로 꽉 채웁니다")
    elif abs(w / h - cw / ch) > 0.01:
        dw, dh = contain_dims(w, h, cw, ch)
        bar = max(0, (ch - dh) / 2)
        if bar >= 2:
            print(f"          ※ 비율이 달라 위아래 {bar:.0f}px 검은 띠가 생깁니다. "
                  f"없애려면 --fill crop")

    # 위치 결정
    if a.at is None:
        spec, exact = ask_position(pj)
    else:
        spec = parse_position(a.at, pj.fps)
        if spec is None:
            die("위치를 못 알아들었습니다: " + a.at)
        exact = a.exact
    at_us, idx, split_idx, notes = resolve(pj, spec, exact)

    where = "맨 뒤" if idx >= len(segs) else f"{idx + 1}번째 씬 앞"
    print(f"\n넣는 위치: {where}  ({fmt_time(at_us)} 지점)")
    for n in notes:
        print("  " + n)

    if split_idx is not None:
        s = segs[split_idx]
        st, du = int(s["target_timerange"]["start"]), int(s["target_timerange"]["duration"])
        head, tail = at_us - st, st + du - at_us
        print(f"  {split_idx + 1}번째 씬을 {fmt_time(at_us)} 지점에서 갈랐습니다 "
              f"(앞 {head / US:.2f}초 + 뒤 {tail / US:.2f}초,")
        print("   줌 모션도 잘린 지점 값으로 이어집니다)")
        if min(head, tail) < 1.5 * US:
            near = st if head < tail else st + du
            side = "앞" if head < tail else "뒤"
            print(f"  ※ {side} 조각이 {min(head, tail) / US:.2f}초밖에 안 남습니다. "
                  f"거의 안 보이는 자투리가 생깁니다.")
            print(f"     깔끔하게 하려면 씬 경계인 {fmt_time(near)} 에 넣으세요 "
                  f"(--exact 빼고 --at {fmt_time(near)} 또는 씬 번호로).")

    # 밀기 + 가르기
    rep, main = shift_and_split(pj, at_us, dur,
                                keep_logo=a.logo_on_intro, keep_bgm=(a.bgm == "keep"))

    # 인트로 넣기
    arc_dir = pj.root + "Resources/"
    base = os.path.basename(mp4_path)
    arc_name, n = base, 2
    while arc_dir + arc_name in pj.names:
        stem, ext = os.path.splitext(base)
        arc_name = f"{stem}_{n}{ext}"
        n += 1

    template = max(main["segments"], key=lambda s: int(s["target_timerange"]["duration"]))
    mat = build_intro_material(pj, arc_name, w, h, dur, has_audio)
    seg = build_intro_segment(pj, template, mat, at_us, dur, scale, a.mute)
    main["segments"].append(seg)
    main["segments"].sort(key=lambda s: int(s["target_timerange"]["start"]))
    register_meta(pj, arc_name, w, h, dur)
    pj.draft["duration"] = pj.timeline_end()

    print(f"\n  뒤로 민 세그먼트 {rep['shift']}개 · 앞뒤로 가른 것 {rep['split']}개"
          + (f" · 인트로 위로 이어간 것 {rep['extend']}개" if rep["extend"] else ""))
    if rep["short"]:
        print("  [경고] 소재 길이가 모자라 인트로 구간을 다 못 덮은 트랙이 있습니다: "
              + ", ".join(sorted(set(rep["short"]))))
    print(f"  전체 길이 {fmt_time(pj.timeline_end())} (+{dur / US:.2f}초)")

    with open(mp4_path, "rb") as f:
        blob = f.read()
    out = a.out or out_path_with_suffix(pj.path, "_인트로")
    pj.save(out, add_files={arc_dir + arc_name: blob})
    print(f"\n[완료] {os.path.basename(out)}")
    print(f"       {out}")

    good = verify_output(out, arc_dir + arc_name, mat["id"],
                         hashlib.md5(blob).hexdigest())
    if good:
        print("\n       이 파일을 캡컷으로 불러오세요.")
        print("       ※ 같은 이름 프로젝트가 캡컷에 열려 있으면 먼저 닫아주세요.")
        print("         (열어둔 채로 불러오면 인트로가 '미디어 분실'로 뜹니다)")
    else:
        print("\n       [주의] ✘ 항목이 있습니다. 그대로 알려주세요.")


if __name__ == "__main__":
    main()
