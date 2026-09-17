# -*- coding: utf-8 -*-
"""캡컷 자동 효과 v2 — 핵심 로직 (GUI 없이도 단독 사용 가능).

캡컷 프로젝트 zip을 받아 아래를 적용한 "[완성] *.zip"을 만든다. 원본은 건드리지 않는다.
  1) 모든 씬: 느린 랜덤 드리프트(줌인/줌아웃/팬) 키프레임
  2) "휙" 스냅 컷: 3~4분에 1번꼴(설정 가능)로 랜덤 씬에 빠른 화면 점프 키프레임 삽입
  3) 씬 사이 랜덤 전환 (effects.json 카탈로그에서 선택된 것만)
  4) 전체 구간 필터/화면효과 (카탈로그에서 선택된 것만)
  5) (옵션) 채널 로고 오버레이 (위치/크기 지정)
  6) (옵션) 자막 스타일 일괄 변경 (글자색/배경색/테두리)
  7) (옵션) 챕터 제목 오버레이 (타임스탬프 목록대로 좌측 상단에 표시)
"""

import copy
import json
import os
import random
import re
import struct
import time
import uuid
import zipfile

US = 1_000_000
FRAME = 33333
FILL_PHOTO = 1.05
FILL_VIDEO = 1.10
ZOOM_HI = 1.48
SNAP_RANGES = {"rare": (180, 240), "often": (60, 120)}
TRANSITION_DURATIONS = [466666, 500000, 666666, 800000, 1000000]


def new_id():
    return str(uuid.uuid4()).upper()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── 이미지 / 타임라인 유틸 ──────────────────────────────────────

def image_size(path):
    """PNG/JPEG 헤더에서 (width, height)를 읽는다. 실패하면 None."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
        if head[:2] == b"\xff\xd8":
            with open(path, "rb") as f:
                data = f.read()
            i = 2
            sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                   0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in sof:
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return int(w), int(h)
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                (ln,) = struct.unpack(">H", data[i + 2:i + 4])
                i += 2 + ln
    except Exception:
        pass
    return None


# ── 캡컷 프로젝트(zip / draft) 읽기 ────────────────────────────

def find_draft_entry(names):
    """zip 안에서 타임라인 파일 경로를 찾는다 (가장 얕은 것 우선)."""
    for base in ("draft_info.json", "draft_content.json"):
        cands = [n for n in names if n.split("/")[-1] == base]
        if cands:
            return min(cands, key=lambda n: n.count("/"))
    return None


def main_video_track(draft):
    for t in draft.get("tracks", []):
        if t.get("type") == "video" and t.get("segments"):
            return t
    raise RuntimeError("영상 트랙을 찾지 못했어요.")


def timeline_end(draft):
    vt = main_video_track(draft)
    return max(s["target_timerange"]["start"] + s["target_timerange"]["duration"]
               for s in vt["segments"])


def placeholder_prefix(draft):
    for v in draft.get("materials", {}).get("videos", []):
        p = v.get("path", "")
        if p.startswith("##_draftpath_placeholder_"):
            return p.split("/Resources/")[0]
    did = draft.get("id", "root")
    return "##_draftpath_placeholder_" + did + "_##"


# ── 모션(줌/이동) 키프레임 ─────────────────────────────────────

def contain_dims(w, h, cw, ch):
    r = min(cw / w, ch / h)
    return w * r, h * r


def cover_scale(w, h, cw, ch):
    """이미지가 캔버스를 빈틈없이 덮는 데 필요한 최소 배율.

    16:9와 비율이 다른 이미지(정사각형 등)도 검은 여백 없이 꽉 차게 만든다.
    """
    dw, dh = contain_dims(w, h, cw, ch)
    return max(cw / dw, ch / dh)


def max_offsets(w, h, cw, ch, scale, margin=0.94):
    """scale 배율일 때 가장자리가 안 보이는 최대 이동량 (캔버스 절반 단위)."""
    dw, dh = contain_dims(w, h, cw, ch)
    mx = max(0.0, dw * scale / cw - 1.0) * margin
    my = max(0.0, dh * scale / ch - 1.0) * margin
    return mx, my


def make_kf(prop, points):
    return {
        "id": new_id(), "material_id": "", "property_type": prop,
        "keyframe_list": [
            {"id": new_id(), "curveType": "Line", "time_offset": int(t),
             "left_control": {"x": 0.0, "y": 0.0},
             "right_control": {"x": 0.0, "y": 0.0},
             "values": [round(float(v), 6)], "string_value": "", "graphID": ""}
            for t, v in points
        ],
    }


def build_motion(dur_us, mw, mh, cw, ch, rng, snap_local_us=None, fill=FILL_PHOTO):
    """한 씬의 키프레임 궤적을 만든다.

    기본: 씬 전체에 걸친 느린 드리프트.
    휙 컷 씬(snap_local_us 지정)은 씬 길이에 따라 2~3번의 빠른 점프를 넣고,
    점프 사이사이와 마지막 점프 이후에는 기본 드리프트가 계속 이어진다.
    반환: (X점들, Y점들, 스케일점들, 마지막 상태 (x, y, s), 휙 시각 목록)
    """
    end_t = max(dur_us - FRAME, 1)

    base = cover_scale(mw, mh, cw, ch) * fill
    smax = base * ZOOM_HI

    def rpos(s):
        mx, my = max_offsets(mw, mh, cw, ch, s)
        return rng.uniform(-mx, mx), rng.uniform(-my, my)

    lo_t = 1.2 * US
    hi_t = end_t - 1.5 * US
    if snap_local_us is None or hi_t <= lo_t:
        # 휙 컷 없이 씬 전체를 한 번에 드리프트
        pattern = rng.choice(("in", "in", "in", "in", "out", "out", "pan", "pan"))
        if pattern == "in":
            s0, s1 = round(base, 4), round(base * rng.uniform(1.13, 1.39), 4)
        elif pattern == "out":
            s0, s1 = round(base * rng.uniform(1.13, 1.39), 4), round(base, 4)
        else:
            s0 = s1 = round(base * rng.uniform(1.15, 1.33), 4)
        x0, y0 = rpos(s0)
        x1, y1 = rpos(s1)
        X = [(0, x0), (end_t, x1)]
        Y = [(0, y0), (end_t, y1)]
        S = [(0, s0)] if s0 == s1 else [(0, s0), (end_t, s1)]
        return X, Y, S, (x1, y1, s1), []

    # 휙 컷이 들어가는 씬
    n = 2 if dur_us < 8 * US else 3
    win = (hi_t - lo_t) / n
    s0 = round(base * rng.uniform(1.0, 1.25), 4)
    x0, y0 = rpos(s0)
    X, Y, S = [(0, x0)], [(0, y0)], [(0, s0)]
    cx, cy, cs = x0, y0, s0
    prev = 0.0
    DRIFT = 0.02

    def drift_to(t):
        gap = (t - prev) / US
        ns = clamp(cs + rng.uniform(-0.012, 0.012) * gap, base, smax)
        mx, my = max_offsets(mw, mh, cw, ch, min(cs, ns))
        dx = clamp(rng.uniform(-1, 1) * DRIFT * gap, -0.12, 0.12)
        dy = clamp(rng.uniform(-1, 1) * DRIFT * gap * 0.6, -0.08, 0.08)
        return clamp(cx + dx, -mx, mx), clamp(cy + dy, -my, my), ns

    snap_ts = []
    for i in range(n):
        t = rng.uniform(lo_t + (i + 0.1) * win, lo_t + (i + 0.8) * win)
        t = max(t, prev + 0.35 * US)
        if t > hi_t:
            break

        xa, ya, sa = drift_to(t)
        X.append((t, xa))
        Y.append((t, ya))
        S.append((t, sa))
        cx, cy, cs, prev = xa, ya, sa, t

        t2 = min(t + rng.uniform(0.45, 0.70) * US, end_t - 0.8 * US)
        delta = rng.uniform(0.12, 0.22) * base * rng.choice((1, -1))
        sb = clamp(sa + delta, base, smax)
        if abs(sb - sa) < 0.10 * base:
            sb = min(smax, sa + 0.15 * base)
        xb, yb = rpos(sb)
        X.append((t2, xb))
        Y.append((t2, yb))
        S.append((t2, sb))
        cx, cy, cs, prev = xb, yb, sb, t2
        snap_ts.append(t)

    xe, ye, se = drift_to(end_t)
    X.append((end_t, xe))
    Y.append((end_t, ye))
    S.append((end_t, se))
    return X, Y, S, (xe, ye, se), snap_ts


def apply_motion(draft, rng, snap_mode="rare"):
    """모든 씬에 드리프트 키프레임을 넣고, 설정 빈도로 휙 컷을 섞는다."""
    vt = main_video_track(draft)
    segs = vt["segments"]
    mats = {v["id"]: v for v in draft.get("materials", {}).get("videos", [])}
    cw = draft.get("canvas_config", {}).get("width") or 1920
    ch = draft.get("canvas_config", {}).get("height") or 1080
    total = timeline_end(draft)

    # 휙 컷을 넣을 씬 고르기
    snap_by_seg = {}
    if snap_mode == "every":
        for i, s in enumerate(segs):
            d = s["target_timerange"]["duration"]
            if d >= 4 * US:
                snap_by_seg[i] = rng.uniform(1.1 * US, d - 2.1 * US)
    elif snap_mode in SNAP_RANGES:
        lo, hi = SNAP_RANGES[snap_mode]
        t = rng.uniform(20 * US, hi * US)
        while t < total - 10 * US:
            for i, s in enumerate(segs):
                st = s["target_timerange"]["start"]
                d = s["target_timerange"]["duration"]
                if st <= t < st + d and d >= 4 * US and i not in snap_by_seg:
                    snap_by_seg[i] = clamp(t - st, 1.1 * US, d - 2.1 * US)
                    break
            t += rng.uniform(lo, hi) * US

    snap_times = []
    for i, s in enumerate(segs):
        mat = mats.get(s.get("material_id"), {})
        mw = mat.get("width") or cw
        mh = mat.get("height") or ch
        fill = FILL_PHOTO if mat.get("type") == "photo" else FILL_VIDEO
        dur = s["target_timerange"]["duration"]
        X, Y, S, last, snap_local = build_motion(dur, mw, mh, cw, ch, rng,
                                                 snap_by_seg.get(i), fill)
        s["common_keyframes"] = [
            make_kf("KFTypePositionX", X),
            make_kf("KFTypePositionY", Y),
            make_kf("KFTypeScaleX", S),
            make_kf("KFTypeRotation", [(0, 0.0)]),
        ]
        x, y, sc = last
        clip = s.setdefault("clip", {})
        clip["transform"] = {"x": round(x, 6), "y": round(y, 6)}
        # 키프레임이 스케일을 덮어쓰지만 초기값도 맞춰 둔다
        clip["scale"] = {"x": round(sc, 6), "y": round(sc, 6)}
        clip["rotation"] = 0.0
        clip.setdefault("flip", {"vertical": False, "horizontal": False})
        clip.setdefault("alpha", 1.0)
        s["uniform_scale"] = {"on": True, "value": 1.0}
        for lt in snap_local:
            snap_times.append(round((s["target_timerange"]["start"] + lt) / US, 1))
    return len(segs), snap_times


# ── 전환 ────────────────────────────────────────────────────────

def transition_material(entry, dur):
    return {
        "id": new_id(), "type": "transition", "name": entry["name"],
        "effect_id": entry["resource_id"], "resource_id": entry["resource_id"],
        "third_resource_id": "0", "source_platform": 1, "path": "",
        "duration": int(dur), "is_overlap": True, "platform": "all",
        "category_id": "100000", "category_name": "", "request_id": "",
        "is_ai_transition": False, "video_path": "", "task_id": "",
    }


def apply_transitions(draft, pool, rng):
    """기존 전환을 걷어내고 카탈로그 풀에서 랜덤으로 새로 넣는다."""
    m = draft.setdefault("materials", {})
    old = {t["id"] for t in m.get("transitions", [])}
    m["transitions"] = []
    vt = main_video_track(draft)
    segs = vt["segments"]
    for s in segs:
        s["extra_material_refs"] = [r for r in s.get("extra_material_refs", []) if r not in old]
    if not pool:
        return 0
    n = 0
    for i in range(len(segs) - 1):
        entry = rng.choice(pool)
        limit = min(segs[i]["target_timerange"]["duration"],
                    segs[i + 1]["target_timerange"]["duration"]) // 2
        cands = [d for d in TRANSITION_DURATIONS if d <= limit] or [TRANSITION_DURATIONS[0]]
        mat = transition_material(entry, rng.choice(cands))
        m["transitions"].append(mat)
        segs[i]["extra_material_refs"].append(mat["id"])
        n += 1
    return n


# ── 전체 구간 필터 / 화면효과 ──────────────────────────────────

def filter_material(entry):
    return {
        "id": new_id(), "effect_id": entry["resource_id"], "resource_id": entry["resource_id"],
        "third_resource_id": entry["resource_id"], "name": entry["name"], "report_name": "",
        "type": "filter", "sub_type": "none", "path": "", "value": 1.0, "visible": True,
        "item_effect_type": 0, "category_id": entry.get("category_id", ""),
        "category_name": entry.get("category_name", ""), "category_key": "",
        "sub_category_id": "", "sub_category_name": "", "platform": "all",
        "apply_target_type": 0, "source_platform": 1, "version": "", "adjust_params": [],
        "time_range": None, "formula_id": "", "enable_skin_tone_correction": False,
        "algorithm_artifact_path": "", "intensity_key": "", "face_adjust_params": [],
        "exclusion_group": [], "panel_id": "", "bloom_params": None, "request_id": "",
        "color_match_info": {"target_feature_path": "", "source_feature_path": "",
                             "target_image_path": ""},
        "multi_language_current": "", "lumi_hub_path": "", "covering_relation_change": 0,
        "beauty_face_auto_preset_id": "", "beauty_body_auto_preset_id": "",
        "beauty_face_auto_retouch_info": {"face_id": [], "beauty_face_auto_retouch_id": ""},
        "smart_color_mode": 0, "is_from_intelligent_quality": False,
    }


def video_effect_material(entry):
    return {
        "id": new_id(), "effect_id": entry["resource_id"], "resource_id": entry["resource_id"],
        "name": entry["name"], "type": "video_effect", "sub_type": 0, "bind_segment_id": "",
        "transparent_params": "", "path": "", "value": 1.0,
        "category_id": entry.get("category_id", "100000"),
        "category_name": entry.get("category_name", ""), "platform": "all",
        "apply_target_type": 2, "source_platform": 1, "version": "", "item_effect_type": 0,
        "adjust_params": entry.get("adjust_params", []), "time_range": None, "formula_id": "",
        "apply_time_range": None, "render_index": 0, "track_render_index": 0,
        "common_keyframes": [], "request_id": "", "algorithm_artifact_path": "",
        "disable_effect_faces": [], "covering_relation_change": 0, "enable_mask": True,
        "effect_mask": [], "enable_video_mask_stroke": True, "enable_video_mask_shadow": True,
        "aigc_current_artifact_path": "", "aigc_current_artifact_cnt": 0,
        "aigc_current_artifact_freeze_time": -1, "aigc_current_artifact_freeze_progress": 0.0,
        "sdk_extra": "",
    }


def _base_segment(material_id, target_start, target_dur, render_index, track_render_index):
    return {
        "id": new_id(), "source_timerange": None,
        "target_timerange": {"start": int(target_start), "duration": int(target_dur)},
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "", "state": 0, "speed": 1.0, "is_loop": False, "is_tone_modify": False,
        "reverse": False, "intensifies_audio": False, "cartoon": False,
        "volume": 1.0, "last_nonzero_volume": 1.0, "clip": None, "uniform_scale": None,
        "material_id": material_id, "extra_material_refs": [],
        "render_index": int(render_index), "keyframe_refs": [],
        "enable_lut": False, "enable_adjust": False, "enable_hsl": False, "visible": True,
        "group_id": "", "enable_color_curves": True, "enable_hsl_curves": True,
        "track_render_index": int(track_render_index), "hdr_settings": None,
        "enable_color_wheels": True, "track_attribute": 0, "is_placeholder": False,
        "template_id": "", "enable_smart_color_adjust": False, "template_scene": "default",
        "common_keyframes": [], "caption_info": None,
        "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0,
                              "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
        "enable_color_match_adjust": False, "enable_color_correct_adjust": False,
        "enable_adjust_mask": False, "raw_segment_id": "", "lyric_keyframes": None,
        "enable_video_mask": True, "digital_human_template_group_id": "",
        "color_correct_alg_result": "", "source": "segmentsourcenormal",
        "enable_mask_stroke": False, "enable_mask_shadow": False,
    }


def make_track(ttype, segments):
    return {"attribute": 0, "flag": 0, "id": new_id(), "is_default_name": True,
            "name": "", "segments": segments, "type": ttype}


def _next_track_render_index(draft):
    mx = 0
    for t in draft.get("tracks", []):
        for s in t.get("segments", []):
            mx = max(mx, s.get("track_render_index", 0))
    return mx + 1


def apply_global_effects(draft, filters, effects):
    """기존 필터/효과 트랙을 제거하고 선택된 것들로 새로 깐다."""
    m = draft.setdefault("materials", {})
    removed_ids = set()
    for t in draft.get("tracks", []):
        if t.get("type") in ("filter", "effect"):
            removed_ids.update(s.get("material_id") for s in t.get("segments", []))
    draft["tracks"] = [t for t in draft["tracks"] if t.get("type") not in ("filter", "effect")]
    m["effects"] = [e for e in m.get("effects", []) if e.get("id") not in removed_ids]
    m["video_effects"] = [e for e in m.get("video_effects", []) if e.get("id") not in removed_ids]

    total = timeline_end(draft)
    added = []
    for i, entry in enumerate(filters):
        mat = filter_material(entry)
        m.setdefault("effects", []).append(mat)
        tri = _next_track_render_index(draft)
        seg = _base_segment(mat["id"], 0, total, 10000 + i, tri)
        draft["tracks"].append(make_track("filter", [seg]))
        added.append("필터: " + entry["name"])
    for i, entry in enumerate(effects):
        mat = video_effect_material(entry)
        m.setdefault("video_effects", []).append(mat)
        tri = _next_track_render_index(draft)
        seg = _base_segment(mat["id"], 0, total, 11000 + i, tri)
        draft["tracks"].append(make_track("effect", [seg]))
        added.append("효과: " + entry["name"])
    return added


# ── 로고 오버레이 ──────────────────────────────────────────────

def photo_material(mat_id, path, width, height, duration, name):
    return {
        "id": mat_id, "type": "photo", "path": path, "duration": int(duration),
        "width": int(width), "height": int(height), "category_name": "", "category_id": "",
        "check_flag": 63487,
        "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0,
                 "lower_right_y": 1.0, "upper_left_x": 0.0, "upper_left_y": 0.0,
                 "upper_right_x": 1.0, "upper_right_y": 0.0},
        "crop_ratio": "free", "crop_scale": 1.0, "extra_type_option": 0, "formula_id": "",
        "freeze": None, "has_audio": False, "intensifies_audio_path": "",
        "intensifies_path": "", "is_ai_generate_content": False, "is_copyright": False,
        "is_text_edit_overdub": False, "is_unified_beauty_mode": False, "local_id": "",
        "local_material_id": "", "material_id": "", "material_name": name,
        "material_url": "",
        "matting": {"flag": 0, "has_use_quick_brush": False, "has_use_quick_eraser": False,
                    "interactiveTime": [], "path": "", "strokes": []},
        "media_path": "", "object_locked": None, "origin_material_id": "", "request_id": "",
        "reverse_intensifies_path": "", "reverse_path": "", "smart_motion": None, "source": 0,
        "source_platform": 0,
        "stable": {"matrix_path": "", "stable_level": 0,
                   "time_range": {"duration": 0, "start": 0}},
        "team_id": "",
        "video_algorithm": {"algorithms": [], "time_range": None, "path": "",
                            "gameplay_configs": [], "ai_in_painting_config": [],
                            "complement_frame_config": None, "motion_blur_config": None,
                            "deflicker": None, "noise_reduction": None,
                            "quality_enhance": None, "super_resolution": None,
                            "ai_background_configs": [], "smart_complement_frame": None,
                            "aigc_generate": None, "aigc_generate_list": [],
                            "mouth_shape_driver": None, "ai_expression_driven": None,
                            "ai_motion_driven": None, "image_interpretation": None,
                            "story_video_modify_video_config": {
                                "task_id": "", "is_overwrite_last_video": False,
                                "tracker_task_id": ""},
                            "skip_algorithm_index": []},
        "aigc_type": "none", "cartoon_path": "", "audio_fade": None,
        "multi_camera_info": None, "picture_from": "none", "picture_set_category_id": "",
        "picture_set_category_name": "", "has_sound_separated": False, "aigc_history_id": "",
        "aigc_item_id": "", "local_material_from": "", "smart_match_info": None,
        "beauty_face_preset_infos": [], "beauty_body_preset_id": "",
        "beauty_face_auto_preset": {"preset_id": "", "name": "", "rate_map": "", "scene": ""},
        "beauty_face_auto_preset_infos": [], "beauty_body_auto_preset": None,
        "live_photo_timestamp": -1, "live_photo_cover_path": "",
        "content_feature_info": None, "corner_pin": None,
        "video_mask_stroke": {"resource_id": "", "path": "", "type": "", "color": "",
                              "size": 0.0, "alpha": 0.0, "distance": 0.0, "texture": 0.0,
                              "horizontal_shift": 0.0, "vertical_shift": 0.0},
        "video_mask_shadow": {"resource_id": "", "path": "", "color": "", "alpha": 0.0,
                              "blur": 0.0, "distance": 0.0, "angle": 0.0},
    }


def _companion_materials(m):
    """영상 세그먼트가 참조하는 부속 머티리얼 한 벌을 만들어 등록하고 id 목록을 돌려준다."""
    speed = {"id": new_id(), "type": "speed", "name": "", "mode": 0, "speed": 1.0,
             "curve_speed": None}
    ph = {"id": new_id(), "type": "placeholder_info", "meta_type": "none", "res_path": "",
          "res_text": "", "error_path": "", "error_text": ""}
    canvas = {"id": new_id(), "type": "canvas_color", "color": "", "blur": 0.0, "image": "",
              "album_image": "", "image_id": "", "image_name": "", "source_platform": 0,
              "team_id": ""}
    scm = {"id": new_id(), "type": "none", "audio_channel_mapping": 0}
    color = {"id": new_id(), "is_color_clip": False, "is_gradient": False, "solid_color": "",
             "gradient_colors": [], "gradient_percents": [], "gradient_angle": 90.0,
             "width": 0.0, "height": 0.0}
    vocal = {"id": new_id(), "type": "vocal_separation", "choice": 0, "removed_sounds": [],
             "time_range": None, "production_path": "", "final_algorithm": "",
             "enter_from": ""}
    m.setdefault("speeds", []).append(speed)
    m.setdefault("placeholder_infos", []).append(ph)
    m.setdefault("canvases", []).append(canvas)
    m.setdefault("sound_channel_mappings", []).append(scm)
    m.setdefault("material_colors", []).append(color)
    m.setdefault("vocal_separations", []).append(vocal)
    return [speed["id"], ph["id"], canvas["id"], scm["id"], color["id"], vocal["id"]]


def apply_logo(draft, logo_name, width, height, x, y, size):
    """로고 사진을 전체 길이 오버레이 트랙으로 얹는다."""
    m = draft.setdefault("materials", {})
    total = timeline_end(draft)
    path = placeholder_prefix(draft) + "/Resources/" + logo_name
    mat = photo_material(new_id(), path, width, height, total, logo_name)
    m.setdefault("videos", []).append(mat)

    # 본편 영상보다 위 레이어로
    mx = 0
    for t in draft.get("tracks", []):
        if t.get("type") == "video":
            for s in t.get("segments", []):
                mx = max(mx, s.get("render_index", 0))
    tri = _next_track_render_index(draft)
    seg = _base_segment(mat["id"], 0, total, mx + 1, tri)
    seg["source_timerange"] = {"start": 0, "duration": int(total)}
    seg["clip"] = {
        "scale": {"x": round(size, 6), "y": round(size, 6)},
        "rotation": 0.0,
        "transform": {"x": round(x, 6), "y": round(y, 6)},
        "flip": {"vertical": False, "horizontal": False},
        "alpha": 1.0,
    }
    seg["uniform_scale"] = {"on": True, "value": 1.0}
    seg["hdr_settings"] = {"mode": 1, "intensity": 1.0, "nits": 1000}
    seg["enable_lut"] = True
    seg["enable_adjust"] = True
    seg["extra_material_refs"] = _companion_materials(m)
    draft["tracks"].append(make_track("video", [seg]))
    return path


def register_logo_meta(meta, prefix, name, width, height):
    """draft_meta_info.json에 로고 파일을 등록한다 (캡컷 파일 인식용)."""
    groups = meta.setdefault("draft_materials", [])
    g0 = next((g for g in groups if g.get("type") == 0), None)
    if g0 is None:
        g0 = {"type": 0, "value": []}
        groups.append(g0)
    now = int(time.time())
    g0.setdefault("value", []).append({
        "ai_group_type": "", "create_time": now, "duration": 5000000,
        "extra_info": name, "file_Path": prefix + "/Resources/" + name,
        "height": int(height), "id": str(uuid.uuid4()), "import_time": now,
        "import_time_ms": now * 1000000, "item_source": 1, "md5": "",
        "metetype": "photo",
        "roughcut_time_range": {"duration": -1, "start": -1},
        "sub_time_range": {"duration": -1, "start": -1},
        "type": 0, "width": int(width)})


def normalize_layers(draft):
    """트랙 순서/레이어를 캡컷 관례대로 재배열한다.

    영상(본편) → 필터 → 화면효과 → 자막 → 오버레이(로고/스티커) → 오디오.
    효과가 자막보다 아래(track_render_index가 작음)에 깔리므로
    반짝이/필터가 자막을 덮어 뿌옇게 만들지 않는다.
    """
    tracks = draft.get("tracks", [])
    first_video = next((i for i, t in enumerate(tracks)
                        if t.get("type") == "video"), 0)

    def rank(i):
        ty = tracks[i].get("type")
        if ty == "video":
            return 0 if i == first_video else 4
        return {"filter": 1, "effect": 2, "text": 3, "sticker": 4,
                "audio": 5}.get(ty, 6)

    order = sorted(range(len(tracks)), key=lambda i: (rank(i), i))
    draft["tracks"] = [tracks[i] for i in order]
    for tri, t in enumerate(draft["tracks"]):
        for s in t.get("segments", []):
            s["track_render_index"] = tri


# ── 자막 스타일 ────────────────────────────────────────────────

def hex_to_rgb(hexs):
    hexs = hexs.lstrip("#")
    return [round(int(hexs[i:i + 2], 16) / 255, 6) for i in (0, 2, 4)]


def apply_subtitle_style(draft, st):
    """type=subtitle 텍스트 전체에 스타일을 일괄 적용한다."""
    n = 0
    bw = float(st.get("border_width", 0.0))
    fp = (st.get("font_path") or "").replace(chr(92), "/")
    fs = st.get("font_size")
    for t in draft.get("materials", {}).get("texts", []):
        if t.get("type") != "subtitle":
            continue
        if st.get("text_color"):
            t["text_color"] = st["text_color"]
        if fs:
            t["font_size"] = round(float(fs), 2)
        if fp:
            t["font_path"] = fp
            t["font_name"] = st.get("font_name", "")
            t["font_title"] = st.get("font_name", "")
            t["font_id"] = ""
            t["font_resource_id"] = ""
            t["font_source_platform"] = 0
        if st.get("use_background", True):
            t["background_color"] = st.get("background_color", "#000000")
            t["background_alpha"] = float(st.get("background_alpha", 0.8))
            t["background_style"] = 1
            if st.get("bg_size") is not None:
                t["background_width"] = round(float(st["bg_size"]), 4)
                t["background_height"] = round(float(st["bg_size"]), 4)
        else:
            t["background_alpha"] = 0.0
        t["border_width"] = bw
        if st.get("border_color"):
            t["border_color"] = st["border_color"]
        try:
            c = json.loads(t["content"])
            for sty in c.get("styles", []):
                if st.get("text_color"):
                    fill = sty.setdefault("fill", {}).setdefault("content", {})
                    fill.setdefault("solid", {})["color"] = hex_to_rgb(st["text_color"])
                    fill["render_type"] = "solid"
                if fp:
                    fo = sty.setdefault("font", {})
                    fo["path"] = fp
                    fo["id"] = ""
                if fs:
                    sty["size"] = round(float(fs), 2)
                if bw > 0:
                    sty["strokes"] = [{
                        "width": bw, "mode": 0,
                        "content": {"render_type": "solid",
                                    "solid": {"color": hex_to_rgb(
                                        st.get("border_color", "#000000"))}},
                    }]
                else:
                    for s2 in sty.get("strokes", []):
                        s2["width"] = 0
            t["content"] = json.dumps(c, ensure_ascii=False)
        except Exception:
            pass
        n += 1

    # 자막 위치 일괄 지정
    px, py = st.get("pos_x"), st.get("pos_y")
    if px is not None or py is not None:
        sub_ids = {t["id"] for t in draft.get("materials", {}).get("texts", [])
                   if t.get("type") == "subtitle"}
        for tr in draft.get("tracks", []):
            if tr.get("type") != "text":
                continue
            for seg in tr.get("segments", []):
                if seg.get("material_id") in sub_ids and seg.get("clip"):
                    tf = seg["clip"].setdefault("transform", {"x": 0.0, "y": 0.0})
                    if px is not None:
                        tf["x"] = round(float(px), 4)
                    if py is not None:
                        tf["y"] = round(float(py), 4)
    return n


# ── 챕터 제목 ──────────────────────────────────────────────────

CHAPTER_HOLD = 5.0      # 제목을 띄워두는 기본 시간(초)
CHAPTER_SIZE = 7.0      # 기본 글자 크기 (자막 탭의 "글자 크기"와 같은 눈금)
EM_PX = 10.2            # 글자 크기 1 당 대략 몇 px 인지 (폭 어림용)

# "0:00 인트로" / "[00:01:35] 제목" / "1:35 - 제목" 같은 줄
_TS_HEAD = re.compile(
    r"^[\s\[\(\-*•]*(\d{1,3}):([0-5]?\d)(?::([0-5]?\d))?[\s\]\)]*"
    r"[\-–—:.,|·~]*\s*(.+?)\s*$")
# "인트로 0:00" 처럼 시각이 뒤에 오는 줄
_TS_TAIL = re.compile(
    r"^\s*(.+?)\s*[\[\(\-–—:.,|·~]*\s*"
    r"(\d{1,3}):([0-5]?\d)(?::([0-5]?\d))?[\s\]\)]*$")


def parse_chapters(text):
    """유튜브 설명란 형식의 챕터 목록을 [(시작us, 제목), ...] 으로 바꾼다.

    받아들이는 모양 (섞여 있어도 됨):
        0:00 인트로
        1:35 - 첫 번째 이야기
        [0:12:05] 마무리
        인트로 0:00
    시각이 없는 줄은 건너뛴다. 시각 순으로 정렬하고, 같은 시각이 두 번
    나오면 뒤에 온 것을 쓴다.
    """
    out = []
    for raw in (text or "").replace("﻿", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TS_HEAD.match(line)
        if m:
            a, b, c, title = m.group(1), m.group(2), m.group(3), m.group(4)
        else:
            m = _TS_TAIL.match(line)
            if not m:
                continue
            title, a, b, c = m.group(1), m.group(2), m.group(3), m.group(4)
        if c is None:
            h, mi, s = 0, int(a), int(b)
        else:
            h, mi, s = int(a), int(b), int(c)
        title = title.strip(" \t-–—:.,|·")
        if not title:
            continue
        out.append(((h * 3600 + mi * 60 + s) * US, title))

    out.sort(key=lambda it: it[0])
    merged = []
    for t, title in out:
        if merged and merged[-1][0] == t:
            merged[-1] = (t, title)
        else:
            merged.append((t, title))
    return merged


def read_chapter_file(path):
    """챕터 txt 를 읽어 파싱한다 (utf-8 / cp949 둘 다 시도)."""
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(path, encoding=enc) as f:
                return parse_chapters(f.read())
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_chapters(f.read())


def text_width_norm(text, font_size, canvas_w=1920):
    """글자 폭을 화면 가로 절반(=1.0) 단위로 어림잡는다.

    정확한 값이 아니라 "왼쪽 맞춤" 보정용 근사다. 한글은 한 칸, 영문/숫자는
    반 칸으로 세고, 줄이 여러 개면 가장 긴 줄을 쓴다.
    """
    widest = 0.0
    for line in str(text).split("\n"):
        units = sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in line)
        widest = max(widest, units)
    return 2.0 * (widest * font_size * EM_PX) / max(canvas_w, 1)


def _text_template(draft):
    """프로젝트에 이미 있는 텍스트 머티리얼 (캡컷 버전별 필드를 맞추는 밑바탕)."""
    for t in draft.get("materials", {}).get("texts", []):
        if t.get("type") in ("text", "subtitle") and t.get("content"):
            return t
    return None


def text_material(mat_id, text, st, template=None):
    """제목 한 줄짜리 텍스트 머티리얼을 만든다."""
    size = round(float(st.get("font_size") or CHAPTER_SIZE), 2)
    color = st.get("text_color") or "#ffffff"
    fp = (st.get("font_path") or "").replace(chr(92), "/")
    bw = float(st.get("border_width", 0.0))
    style = {
        "fill": {"alpha": 1.0,
                 "content": {"render_type": "solid",
                             "solid": {"alpha": 1.0, "color": hex_to_rgb(color)}}},
        "font": {"id": "", "path": fp},
        "range": [0, len(text)],
        "size": size,
        "useLetterColor": True,
        "strokes": ([{"content": {"render_type": "solid",
                                  "solid": {"alpha": 1.0,
                                            "color": hex_to_rgb(
                                                st.get("border_color", "#000000"))}},
                      "width": bw}] if bw > 0 else []),
    }
    content = json.dumps({"styles": [style], "text": text}, ensure_ascii=False)

    mat = copy.deepcopy(template) if template else {}
    mat.update({
        "id": mat_id, "type": "text", "content": content,
        "add_type": 0, "alignment": 0, "base_content": "", "bold_width": 0.0,
        "border_alpha": 1.0,
        "border_color": st.get("border_color", "#000000") if bw > 0 else "",
        "border_width": bw,
        "check_flag": 7, "combo_info": {"text_templates": []},
        "fixed_height": -1.0, "fixed_width": -1.0,
        "font_category_id": "", "font_category_name": "",
        "font_id": "", "font_name": st.get("font_name", ""),
        "font_path": fp, "font_resource_id": "", "font_size": size,
        "font_source_platform": 0, "font_team_id": "",
        "font_title": st.get("font_name", "") or "none", "font_url": "", "fonts": [],
        "force_apply_line_max_width": False, "global_alpha": 1.0, "group_id": "",
        "has_shadow": False, "initial_scale": 1.0, "inner_padding": -1.0,
        "is_rich_text": False, "italic_degree": 0, "ktv_color": "", "language": "",
        "layer_weight": 1, "letter_spacing": 0.0, "line_feed": 1,
        "line_max_width": 0.82, "line_spacing": 0.02,
        "multi_language_current": "none", "name": "",
        "original_size": [], "preset_category": "", "preset_category_id": "",
        "preset_has_set_alignment": False, "preset_id": "", "preset_index": 0,
        "preset_name": "", "recognize_task_id": "", "recognize_type": 0,
        "relevance_segment": [],
        "shadow_alpha": 0.9, "shadow_angle": -45.0, "shadow_color": "",
        "shadow_distance": 5.0,
        "shadow_point": {"x": 0.6363961030678928, "y": -0.6363961030678928},
        "shadow_smoothing": 1.0, "shape_clip_x": False, "shape_clip_y": False,
        "style_name": "", "sub_type": 0, "subtitle_keywords": None,
        "subtitle_template_original_fontsize": 0.0,
        "text_alpha": 1.0, "text_color": color, "text_curve": None,
        "text_preset_resource_id": "", "text_size": 30, "text_to_audio_ids": [],
        "tts_auto_update": False, "typesetting": 0, "underline": False,
        "underline_offset": 0.22, "underline_width": 0.05,
        "use_effect_default_color": True,
        "words": {"end_time": [], "start_time": [], "text": []},
        "caption_template_info": {
            "category_id": "", "category_name": "", "effect_id": "", "is_new": False,
            "path": "", "request_id": "", "resource_id": "", "resource_name": "",
            "source_platform": 0},
    })
    if st.get("use_background", True):
        mat.update({
            "background_style": 1,
            "background_color": st.get("background_color", "#000000"),
            "background_alpha": round(float(st.get("background_alpha", 0.45)), 3),
            "background_width": 0.14, "background_height": 0.14,
            "background_round_radius": float(st.get("background_round", 0.0)),
            "background_horizontal_offset": 0.0, "background_vertical_offset": 0.0,
        })
    else:
        mat.update({
            "background_style": 0, "background_color": "", "background_alpha": 0.0,
            "background_width": 0.14, "background_height": 0.14,
            "background_round_radius": 0.0,
            "background_horizontal_offset": 0.0, "background_vertical_offset": 0.0,
        })
    return mat


def apply_chapter_titles(draft, chapters, st):
    """챕터 시작 시각마다 제목을 띄우는 텍스트 트랙을 만든다.

    chapters: [(시작us, 제목), ...]   st: 표시 시간/위치/글자 모양 설정
    돌려주는 값: 실제로 넣은 제목 개수
    """
    if not chapters:
        return 0
    m = draft.setdefault("materials", {})
    total = timeline_end(draft)
    hold = max(0.5, float(st.get("hold", CHAPTER_HOLD))) * US
    size = float(st.get("font_size") or CHAPTER_SIZE)
    cw = draft.get("canvas_config", {}).get("width") or 1920
    x = float(st.get("x", -0.72))
    y = float(st.get("y", 0.80))
    template = _text_template(draft)

    # 본편 영상보다 위 레이어로
    mx = 0
    for t in draft.get("tracks", []):
        if t.get("type") == "video":
            for s in t.get("segments", []):
                mx = max(mx, s.get("render_index", 0))

    segs = []
    for i, (start, title) in enumerate(chapters):
        start = int(start)
        if start >= total:
            break
        nxt = int(chapters[i + 1][0]) if i + 1 < len(chapters) else total
        dur = min(hold, nxt - start, total - start)
        if dur < 0.3 * US:
            continue
        mat = text_material(new_id(), title, st, template)
        m.setdefault("texts", []).append(mat)
        anim = {"id": new_id(), "type": "sticker_animation", "animations": [],
                "multi_language_current": "none"}
        m.setdefault("material_animations", []).append(anim)

        cx = x
        if st.get("align_left", True):
            # transform 은 글자 상자의 "가운데"라서, 왼쪽 끝을 맞추려면
            # 제목 길이의 절반만큼 오른쪽으로 밀어준다.
            cx = x + text_width_norm(title, size, cw) / 2.0
        seg = _base_segment(mat["id"], start, dur, mx + 1, 0)
        seg["extra_material_refs"] = [anim["id"]]
        seg["clip"] = {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": round(clamp(cx, -1.5, 1.5), 6), "y": round(y, 6)},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        }
        seg["uniform_scale"] = {"on": True, "value": 1.0}
        segs.append(seg)

    if segs:
        draft["tracks"].append(make_track("text", segs))
    return len(segs)


# ── 효과 카탈로그 수집 / 출력 ──────────────────────────────────

def scan_zip_for_effects(zip_path):
    """다른 캡컷 zip에서 전환/필터/화면효과의 이름과 resource_id를 수집한다."""
    with zipfile.ZipFile(zip_path) as z:
        entry = find_draft_entry(z.namelist())
        if not entry:
            raise RuntimeError("타임라인 파일(draft_info/draft_content.json)을 못 찾았어요.")
        draft = json.loads(z.read(entry))
    m = draft.get("materials", {})
    found = {"transitions": [], "filters": [], "video_effects": []}
    for t in m.get("transitions", []):
        found["transitions"].append({"name": t.get("name", ""),
                                     "resource_id": t.get("resource_id", "")})
    for e in m.get("effects", []):
        if e.get("type") == "filter":
            found["filters"].append({"name": e.get("name", ""),
                                     "resource_id": e.get("resource_id", ""),
                                     "category_name": e.get("category_name", "")})
    for e in m.get("video_effects", []):
        found["video_effects"].append({"name": e.get("name", ""),
                                       "resource_id": e.get("resource_id", ""),
                                       "category_name": e.get("category_name", ""),
                                       "adjust_params": e.get("adjust_params", [])})
    for k in found:
        seen = set()
        uniq = []
        for it in found[k]:
            if it["resource_id"] and it["resource_id"] not in seen:
                seen.add(it["resource_id"])
                uniq.append(it)
        found[k] = uniq
    return found


# ── 메인 처리 ──────────────────────────────────────────────────

def out_path_for(zip_path):
    d = os.path.dirname(zip_path)
    base = os.path.basename(zip_path)
    if base.startswith("[완성] "):
        base = base[len("[완성] "):]
    stem, ext = os.path.splitext(base)
    out = os.path.join(d, "[완성] " + stem + ext)
    n = 2
    while os.path.exists(out):
        out = os.path.join(d, "[완성] " + stem + " (" + str(n) + ")" + ext)
        n += 1
    return out


def process(zip_path, opts, progress=None):
    """zip_path에 옵션을 적용한 새 zip을 만들고 (출력경로, 통계)를 돌려준다.

    opts = {
      "snap_mode": "none" | "rare"(3~4분) | "often"(1~2분) | "every",
      "transitions": [카탈로그 항목...],          # 비우면 전환 없음
      "filters": [...], "video_effects": [...],  # 전체 구간 적용
      "effect_mode": "all" | "random_one",       # 화면효과: 전부 vs 랜덤 1개
      "logo": None | {"path", "x", "y", "size"},
      "subtitle": None | {"text_color", "use_background", "background_color",
                          "background_alpha", "border_color", "border_width"},
      "chapters": None | {"items": [(시작us, 제목), ...], "hold": 초,
                          "x", "y", "font_size", "text_color", ...},
      "seed": None | int,
    }
    """
    rng = random.Random(opts.get("seed"))
    stats = {}
    with zipfile.ZipFile(zip_path) as zin:
        names = zin.namelist()
        entry = find_draft_entry(names)
        if not entry:
            raise RuntimeError("타임라인 파일(draft_info/draft_content.json)을 못 찾았어요.\n"
                               "캡컷 프로젝트 zip 파일이 맞는지 확인해 주세요.")
        draft = json.loads(zin.read(entry))
        root = entry.rsplit("/", 1)[0] + "/" if "/" in entry else ""

        stats["scenes"], stats["snap_times"] = apply_motion(
            draft, rng, opts.get("snap_mode", "rare"))
        stats["transitions"] = apply_transitions(draft, opts.get("transitions") or [], rng)
        effects_sel = opts.get("video_effects") or []
        if opts.get("effect_mode", "all") == "random_one" and len(effects_sel) > 1:
            effects_sel = [rng.choice(effects_sel)]
        stats["global_fx"] = apply_global_effects(
            draft, opts.get("filters") or [], effects_sel)
        if opts.get("subtitle"):
            stats["subtitles"] = apply_subtitle_style(draft, opts["subtitle"])
        if opts.get("chapters"):
            cs = opts["chapters"]
            stats["chapters"] = apply_chapter_titles(
                draft, cs.get("items") or [], cs)

        logo_bytes = None
        logo_arc = None
        meta_entry = None
        meta_obj = None
        if opts.get("logo"):
            lg = opts["logo"]
            with open(lg["path"], "rb") as f:
                logo_bytes = f.read()
            wh = image_size(lg["path"]) or (500, 500)
            ext = os.path.splitext(lg["path"])[1].lower() or ".png"
            logo_name = "channel_logo" + ext
            logo_arc = root + "Resources/" + logo_name
            apply_logo(draft, logo_name, wh[0], wh[1],
                       lg.get("x", 0.8), lg.get("y", 0.8), lg.get("size", 0.15))
            stats["logo"] = logo_arc

            cand = root + "draft_meta_info.json"
            if cand in names:
                try:
                    meta_obj = json.loads(zin.read(cand))
                    register_logo_meta(meta_obj, placeholder_prefix(draft),
                                       logo_name, wh[0], wh[1])
                    meta_entry = cand
                except Exception:
                    meta_obj = None

        # 트랙 순서/레이어 정리
        normalize_layers(draft)

        out = out_path_for(zip_path)
        infos = zin.infolist()
        total_items = len(infos) + (1 if logo_arc else 0)
        with zipfile.ZipFile(out, "w") as zout:
            for i, item in enumerate(infos):
                if progress:
                    progress(i, total_items)
                if item.filename == entry:
                    zout.writestr(item.filename,
                                  json.dumps(draft, ensure_ascii=False,
                                             separators=(",", ":")),
                                  zipfile.ZIP_DEFLATED)
                elif meta_entry and item.filename == meta_entry:
                    zout.writestr(item.filename,
                                  json.dumps(meta_obj, ensure_ascii=False,
                                             separators=(",", ":")),
                                  zipfile.ZIP_DEFLATED)
                elif logo_arc and item.filename == logo_arc:
                    continue
                else:
                    zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
                    zi.compress_type = item.compress_type
                    zi.external_attr = item.external_attr
                    zout.writestr(zi, zin.read(item.filename))
            if logo_arc:
                zout.writestr(logo_arc, logo_bytes, zipfile.ZIP_DEFLATED)
            if progress:
                progress(total_items, total_items)
    return out, stats
