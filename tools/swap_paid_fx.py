# -*- coding: utf-8 -*-
"""완성 zip 안에 유료(💎) 효과가 남았는지 검사하고, 무료로 갈아끼운다.

  python swap_paid_fx.py "완성.zip" --check    검사만 (이름과 시각 표시)
  python swap_paid_fx.py "완성.zip"            유료 -> 무료 교체한 새 zip 생성

유료 판정 기준
  1) app\\effects.json 에서 paid 로 표시된 항목
  2) 아래 KNOWN_PAID 에 적힌 이름 (캡컷에서 💎 로 확인된 것)
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _capcut import (Project, fmt_time, load_catalog, out_path_with_suffix,  # noqa: E402
                     setup_console)

# 캡컷에서 💎 로 확인된 유료 효과 (카탈로그 표시보다 우선).
#
# ★ 이름이 아니라 resource_id 로 판정합니다.
#   캡컷이 같은 효과의 이름을 바꾸는 일이 있기 때문입니다.
#   실제로 '세우기'는 예전 이름이 '푸시 확대', '겹치기'는 '오버레이 전환' 이었습니다.
#   출처: %LOCALAPPDATA%\CapCut\User Data\Cache\FeedbackOtherInfo.json
#         (캡컷이 "유료라서 막았다"고 기록해 둔 목록)
KNOWN_PAID_IDS = {
    "6724226861666144779": "세우기",          # 옛 이름: 푸시 확대
    "6917578154089386498": "겹치기",          # 옛 이름: 오버레이 전환
    "7487868908221795601": "스크린 교체",
    "7530469760765545729": "스티커 메모",
    "7605920528402156805": "플로트 어웨이",
    "7247031156154044930": "명확한 ll",       # 필터. 캡컷 표기가 II / ll 로 갈림
}

# 이름으로도 한 번 더 거른다 (resource_id 가 바뀌는 경우 대비)
KNOWN_PAID = {
    "스크린교체", "스티커메모", "플로트어웨이", "겹치기", "세우기",
    "명확한ii", "명확한ll", "명확한2", "푸시확대", "오버레이전환",
}

KINDS = (
    ("transitions", "전환", "transitions"),
    ("effects", "필터", "filters"),
    ("video_effects", "화면효과", "video_effects"),
)


def norm(name):
    s = (name or "").strip().lower().replace(" ", "")
    return s.replace("ⅱ", "ii").replace("Ⅱ", "ii")


def build_lookup(catalog):
    """resource_id -> (paid, 판정근거), 그리고 kind -> 무료 후보 목록."""
    paid_by_rid, why_by_rid, free_pool = {}, {}, {}
    for cat_key in ("transitions", "filters", "video_effects"):
        pool = []
        for it in (catalog or {}).get(cat_key, []) or []:
            rid = str(it.get("resource_id") or "")
            if not rid:
                continue
            if rid in KNOWN_PAID_IDS:
                is_paid, why = True, "확인된 유료"
            elif norm(it.get("name")) in KNOWN_PAID:
                is_paid, why = True, "이름목록"
            elif it.get("paid"):
                is_paid, why = True, "카탈로그"
            else:
                is_paid, why = False, ""
            paid_by_rid[rid] = is_paid
            why_by_rid[rid] = why
            if not is_paid:
                pool.append(it)
        free_pool[cat_key] = pool
    return paid_by_rid, why_by_rid, free_pool


def remove_material(pj, bucket, mat):
    """대체품이 없을 때: 효과 자체를 프로젝트에서 들어낸다."""
    mid = mat.get("id")
    mats = pj.draft.setdefault("materials", {})
    mats[bucket] = [m for m in mats.get(bucket, []) or [] if m.get("id") != mid]
    for t in pj.draft.get("tracks", []):
        keep = []
        for s in t.get("segments", []) or []:
            if s.get("material_id") == mid:
                continue                      # 필터/화면효과 세그먼트는 통째로 제거
            refs = s.get("extra_material_refs") or []
            if mid in refs:
                s["extra_material_refs"] = [r for r in refs if r != mid]
            keep.append(s)
        t["segments"] = keep
    pj.draft["tracks"] = [t for t in pj.draft.get("tracks", [])
                          if t.get("segments") or t.get("type") not in ("filter", "effect")]


def when_used(pj, mat_id, bucket):
    """이 머티리얼이 타임라인 어디에 쓰였는지 (시각 문자열)."""
    for t in pj.draft.get("tracks", []):
        for s in t.get("segments", []):
            tr = s.get("target_timerange") or {}
            if s.get("material_id") == mat_id:
                return fmt_time(tr.get("start", 0))
            if mat_id in (s.get("extra_material_refs") or []):
                if bucket == "transitions":     # 전환은 이 씬 끝에서 재생
                    return fmt_time(int(tr.get("start", 0)) + int(tr.get("duration", 0)))
                return fmt_time(tr.get("start", 0))
    return "-"


def scan(pj, paid_by_rid):
    """(bucket, 머티리얼, 유료여부) 목록."""
    found = []
    mats = pj.draft.get("materials") or {}
    for bucket, label, cat_key in KINDS:
        for m in mats.get(bucket, []) or []:
            if bucket == "effects" and m.get("type") != "filter":
                continue
            rid = str(m.get("resource_id") or m.get("effect_id") or "")
            if rid in KNOWN_PAID_IDS:
                is_paid = True
            else:
                is_paid = paid_by_rid.get(rid)
                if is_paid is None:
                    is_paid = norm(m.get("name")) in KNOWN_PAID
            found.append((bucket, label, cat_key, m, rid, bool(is_paid)))
    return found


def main():
    setup_console()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("zip_path")
    ap.add_argument("--check", action="store_true", help="검사만 하고 파일은 안 만듦")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    catalog, cat_path = load_catalog()
    if catalog is None:
        print("[경고] effects.json 을 못 찾아 KNOWN_PAID 이름으로만 판정합니다.")
    else:
        print(f"카탈로그: {cat_path}")
    paid_by_rid, why_by_rid, free_pool = build_lookup(catalog)

    pj = Project(a.zip_path)
    print(f"파일: {os.path.basename(pj.path)}\n")

    found = scan(pj, paid_by_rid)
    if not found:
        print("이 프로젝트에는 전환/필터/화면효과가 없습니다.")
        return

    paid = [f for f in found if f[5]]
    print(f"  전환·필터·화면효과 {len(found)}개 중 유료 {len(paid)}개\n")
    for bucket, label, cat_key, m, rid, is_paid in found:
        mark = "💎 유료" if is_paid else "   무료"
        why = ""
        if is_paid:
            why = "  (" + (("확인된 유료" if rid in KNOWN_PAID_IDS
                            else why_by_rid.get(rid)) or "이름목록") + ")"
        shown = m.get("name", "?")
        if rid in KNOWN_PAID_IDS and KNOWN_PAID_IDS[rid] != shown:
            shown = f"{KNOWN_PAID_IDS[rid]}(={shown})"
        print(f"  {mark}  [{label}] {shown:<20s} "
              f"{when_used(pj, m.get('id'), bucket):>12s}  {rid}{why}")

    if not paid:
        print("\n[결과] 유료 효과 없음. 그대로 쓰셔도 됩니다.")
        return
    if a.check:
        print("\n[결과] 위 💎 항목이 캡컷에서 Pro 로 표시됩니다.")
        print("       --check 를 빼고 다시 실행하면 무료로 갈아끼운 새 zip을 만듭니다.")
        return

    rng = random.Random(a.seed)
    swapped, removed = [], []
    for bucket, label, cat_key, m, rid, is_paid in paid:
        pool = free_pool.get(cat_key) or []
        if not pool:
            remove_material(pj, bucket, m)
            removed.append((label, m.get("name")))
            continue
        rep = rng.choice(pool)
        old = m.get("name")
        m["name"] = rep.get("name")
        m["effect_id"] = str(rep.get("resource_id"))
        m["resource_id"] = str(rep.get("resource_id"))
        if "third_resource_id" in m and m.get("third_resource_id") not in ("0", ""):
            m["third_resource_id"] = str(rep.get("resource_id"))
        if rep.get("category_id"):
            m["category_id"] = str(rep["category_id"])
        if rep.get("category_name") is not None:
            m["category_name"] = rep.get("category_name") or m.get("category_name", "")
        swapped.append((label, old, rep.get("name")))

    print()
    for label, old, new in swapped:
        print(f"  [{label}] {old}  →  {new}")
    for label, old in removed:
        print(f"  [{label}] {old}  →  (무료 대체품이 없어 제거)")

    out = a.out or out_path_with_suffix(pj.path, "_무료")
    pj.save(out)
    print(f"\n[완료] {len(swapped)}개 교체"
          + (f", {len(removed)}개 제거" if removed else "")
          + f" → {os.path.basename(out)}")
    print(f"       {out}")
    if removed:
        print("       ※ 제거된 종류는 [효과] 탭에서 무료 항목을 하나 추가해두면")
        print("         다음부터는 제거 대신 교체됩니다.")


if __name__ == "__main__":
    main()
