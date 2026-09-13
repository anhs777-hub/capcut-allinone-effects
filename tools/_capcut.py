# -*- coding: utf-8 -*-
"""캡컷 프로젝트 zip 공용 유틸 (add_intro / hold_last / swap_paid_fx 가 함께 씀).

이 파일은 직접 실행하지 않습니다. 건드리지 마세요.
"""

import copy
import json
import os
import struct
import sys
import uuid
import zipfile

US = 1_000_000
DEFAULT_FPS = 30.0


# ── 콘솔 (한글 깨짐 방지) ──────────────────────────────────────

def setup_console():
    """한글/이모지가 깨지지 않게 콘솔 출력 코드페이지를 UTF-8 로.

    bat 에서 chcp 를 쓰면 파일로 넘긴 입력(stdin)이 먹혀버리는 cmd 버그가 있어서
    출력 코드페이지만 파이썬 안에서 직접 바꾼다. 입력 쪽은 건드리지 않는다.
    """
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def die(msg):
    print("\n[오류] " + msg)
    sys.exit(1)


# ── 기본 ────────────────────────────────────────────────────────

def new_id():
    return str(uuid.uuid4()).upper()


def fmt_time(us, fps=None):
    """1234567 -> '0:00:01.23'"""
    if us is None:
        return "-"
    neg = us < 0
    us = abs(int(us))
    h, rem = divmod(us, 3600 * US)
    m, rem = divmod(rem, 60 * US)
    s, rem = divmod(rem, US)
    return f"{'-' if neg else ''}{h}:{m:02d}:{s:02d}.{rem // 10000:02d}"


def fmt_dur(us):
    return f"{us / US:.1f}초"


# ── zip 읽기/쓰기 ──────────────────────────────────────────────

def find_draft_entry(names):
    """zip 안 타임라인 파일 경로 (가장 얕은 것 우선)."""
    for base in ("draft_info.json", "draft_content.json"):
        cands = [n for n in names if n.split("/")[-1] == base]
        if cands:
            return min(cands, key=lambda n: n.count("/"))
    return None


class Project:
    """캡컷 프로젝트 zip 하나."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        if not os.path.exists(self.path):
            die("파일이 없습니다: " + self.path)
        if not zipfile.is_zipfile(self.path):
            die("zip 파일이 아닙니다: " + os.path.basename(self.path)
                + "\n     캡컷에서 '프로젝트 내보내기' 한 zip을 넣어주세요.")
        with zipfile.ZipFile(self.path) as z:
            self.names = z.namelist()
            self.entry = find_draft_entry(self.names)
            if not self.entry:
                die("타임라인 파일(draft_info/draft_content.json)을 못 찾았어요.\n"
                    "     캡컷 프로젝트 zip이 맞는지 확인해 주세요.")
            self.draft = json.loads(z.read(self.entry))
            self.root = self.entry.rsplit("/", 1)[0] + "/" if "/" in self.entry else ""
            self.meta_entry = None
            self.meta = None
            cand = self.root + "draft_meta_info.json"
            if cand in self.names:
                try:
                    self.meta = json.loads(z.read(cand))
                    self.meta_entry = cand
                except Exception:
                    self.meta = None

    # -- 조회 -------------------------------------------------

    @property
    def fps(self):
        try:
            return float(self.draft.get("fps") or DEFAULT_FPS) or DEFAULT_FPS
        except Exception:
            return DEFAULT_FPS

    def video_tracks(self):
        return [t for t in self.draft.get("tracks", [])
                if t.get("type") == "video" and t.get("segments")]

    def main_track(self):
        vts = self.video_tracks()
        if not vts:
            die("영상 트랙을 찾지 못했어요.")
        # 세그먼트가 가장 많은 트랙 = 본편 (로고 오버레이는 1개짜리)
        return max(vts, key=lambda t: len(t["segments"]))

    def scenes(self):
        return self.main_track()["segments"]

    def timeline_end(self):
        end = 0
        for t in self.draft.get("tracks", []):
            for s in t.get("segments", []):
                tr = s.get("target_timerange") or {}
                end = max(end, tr.get("start", 0) + tr.get("duration", 0))
        return end

    def material_index(self):
        """id -> (버킷이름, 머티리얼) 색인."""
        idx = {}
        for bucket, items in (self.draft.get("materials") or {}).items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("id"):
                        idx[it["id"]] = (bucket, it)
        return idx

    def placeholder_prefix(self):
        for v in (self.draft.get("materials") or {}).get("videos", []) or []:
            p = v.get("path", "")
            if p.startswith("##_draftpath_placeholder_"):
                return p.split("/Resources/")[0]
        did = self.draft.get("id", "root")
        return "##_draftpath_placeholder_" + did + "_##"

    # -- 저장 -------------------------------------------------

    def save(self, out_path, add_files=None, drop=()):
        """원본 zip을 그대로 복사하면서 타임라인/메타만 갈아끼운다."""
        add_files = add_files or {}
        drop = set(drop)
        with zipfile.ZipFile(self.path) as zin, \
                zipfile.ZipFile(out_path, "w") as zout:
            for item in zin.infolist():
                name = item.filename
                if name in drop or name in add_files:
                    continue
                if name == self.entry:
                    zout.writestr(name, json.dumps(self.draft, ensure_ascii=False,
                                                   separators=(",", ":")),
                                  zipfile.ZIP_DEFLATED)
                elif self.meta_entry and name == self.meta_entry:
                    zout.writestr(name, json.dumps(self.meta, ensure_ascii=False,
                                                   separators=(",", ":")),
                                  zipfile.ZIP_DEFLATED)
                else:
                    zi = zipfile.ZipInfo(name, date_time=item.date_time)
                    zi.compress_type = item.compress_type
                    zi.external_attr = item.external_attr
                    zout.writestr(zi, zin.read(name))
            for name, data in add_files.items():
                zout.writestr(name, data, zipfile.ZIP_DEFLATED)
        return out_path


# ── 출력 파일 이름 ─────────────────────────────────────────────

def out_path_with_suffix(src, suffix):
    """'[완성] a.zip' + '_인트로' -> '[완성] a_인트로.zip' (중복이면 (2))"""
    d = os.path.dirname(os.path.abspath(src))
    stem, ext = os.path.splitext(os.path.basename(src))
    out = os.path.join(d, stem + suffix + ext)
    n = 2
    while os.path.exists(out):
        out = os.path.join(d, stem + suffix + f" ({n})" + ext)
        n += 1
    return out


# ── 시간/위치 입력 파싱 ────────────────────────────────────────

class PosSpec:
    """넣을 위치. kind: 'start' | 'end' | 'scene' | 'time'"""

    def __init__(self, kind, value=None, raw=""):
        self.kind = kind
        self.value = value
        self.raw = raw


def parse_position(text, fps=DEFAULT_FPS):
    """사용자가 친 위치 문자열 -> PosSpec.

    엔터/start      맨 앞
    end             맨 뒤
    5               5번째 씬 앞      (숫자만 = 씬 번호)
    -1              마지막 씬 앞
    55.1  55.1s     55.10초
    55s             55초
    0:55  3:20      분:초
    0:55.1          분:초.소수
    1:23:45         시:분:초
    0:00:55:10      시:분:초:프레임
    """
    s = (text or "").strip().lower()
    if s in ("", "start", "처음", "앞", "맨앞"):
        return PosSpec("start", raw=text)
    if s in ("end", "끝", "맨뒤", "뒤"):
        return PosSpec("end", raw=text)

    # 숫자만 = 씬 번호
    try:
        if s.lstrip("-").isdigit():
            return PosSpec("scene", int(s), raw=text)
    except Exception:
        pass

    had_s = s.endswith("s")
    if had_s:
        s = s[:-1].strip()

    parts = s.split(":")
    try:
        if len(parts) == 4:                       # 시:분:초:프레임
            h, m, sec, fr = parts
            total = (int(h) * 3600 + int(m) * 60 + int(sec)) * US
            total += int(round(float(fr) / fps * US))
            return PosSpec("time", total, raw=text)
        if len(parts) == 3:                       # 시:분:초(.소수)
            h, m, sec = parts
            return PosSpec("time", int(round(
                ((int(h) * 3600 + int(m) * 60) + float(sec)) * US)), raw=text)
        if len(parts) == 2:                       # 분:초(.소수)
            m, sec = parts
            return PosSpec("time", int(round(
                (int(m) * 60 + float(sec)) * US)), raw=text)
        if "." in s or had_s:                     # 55.1 / 55s
            return PosSpec("time", int(round(float(s) * US)), raw=text)
    except ValueError:
        pass
    return None


# ── 키프레임 (선형 보간 / 자르기) ──────────────────────────────

def _kf_time(kf):
    return int(kf.get("time_offset", 0) or 0)


def _kf_value(kf):
    vals = kf.get("values") or [0.0]
    return float(vals[0])


def kf_value_at(kf_list, t):
    """curveType=Line 기준 t 시점 값 (범위 밖은 양 끝 값으로 고정)."""
    if not kf_list:
        return None
    pts = sorted(kf_list, key=_kf_time)
    if t <= _kf_time(pts[0]):
        return _kf_value(pts[0])
    if t >= _kf_time(pts[-1]):
        return _kf_value(pts[-1])
    for a, b in zip(pts, pts[1:]):
        ta, tb = _kf_time(a), _kf_time(b)
        if ta <= t <= tb:
            if tb == ta:
                return _kf_value(b)
            r = (t - ta) / (tb - ta)
            return _kf_value(a) + (_kf_value(b) - _kf_value(a)) * r
    return _kf_value(pts[-1])


def _clone_kf(sample, time_offset, value):
    kf = copy.deepcopy(sample)
    kf["id"] = new_id()
    kf["time_offset"] = int(round(time_offset))
    kf["values"] = [round(float(value), 6)]
    return kf


def split_keyframes(common_keyframes, cut):
    """세그먼트 로컬 시각 cut 에서 키프레임 묶음을 앞/뒤로 가른다.

    자른 지점의 값을 보간해서 앞의 마지막 = 뒤의 첫 값으로 이어 붙인다.
    반환: (앞 common_keyframes, 뒤 common_keyframes, {property_type: 자른지점값})
    """
    front, back, at_cut = [], [], {}
    for group in common_keyframes or []:
        kfs = sorted(group.get("keyframe_list") or [], key=_kf_time)
        if not kfs:
            continue
        prop = group.get("property_type")
        v_cut = kf_value_at(kfs, cut)
        at_cut[prop] = v_cut
        sample = kfs[0]

        f_list = [k for k in kfs if _kf_time(k) < cut]
        f_list.append(_clone_kf(sample, cut, v_cut))

        b_list = [_clone_kf(sample, 0, v_cut)]
        for k in kfs:
            if _kf_time(k) > cut:
                nk = copy.deepcopy(k)
                nk["id"] = new_id()
                nk["time_offset"] = _kf_time(k) - cut
                b_list.append(nk)

        fg = copy.deepcopy(group)
        fg["id"] = new_id()
        fg["keyframe_list"] = [copy.deepcopy(k) for k in f_list]
        for k in fg["keyframe_list"]:
            k["id"] = new_id()
        front.append(fg)

        bg = copy.deepcopy(group)
        bg["id"] = new_id()
        bg["keyframe_list"] = b_list
        back.append(bg)
    return front, back, at_cut


# ── 세그먼트 자르기 ────────────────────────────────────────────

def dup_material(project, mat_id, index=None):
    """머티리얼을 복제해 새 id를 돌려준다 (없으면 원래 id 그대로)."""
    idx = index if index is not None else project.material_index()
    hit = idx.get(mat_id)
    if not hit:
        return mat_id
    bucket, mat = hit
    clone = copy.deepcopy(mat)
    clone["id"] = new_id()
    project.draft["materials"].setdefault(bucket, []).append(clone)
    idx[clone["id"]] = (bucket, clone)
    return clone["id"]


def split_segment(project, seg, at_us, index=None):
    """target 기준 절대시각 at_us 에서 세그먼트를 둘로 가른다.

    - 소스 구간을 speed 배율 반영해 정확히 나눠 끊김 없이 잇는다
    - 키프레임은 자른 지점 값으로 보간해서 앞/뒤를 연결
    - 전환(transition)은 뒤 조각으로 옮긴다 (앞 조각 -> 삽입물은 컷)
    - 부속 머티리얼(speed/canvas/...)은 뒤 조각용으로 복제
    반환: (앞, 뒤)
    """
    idx = index if index is not None else project.material_index()
    tr = seg["target_timerange"]
    start, dur = int(tr["start"]), int(tr["duration"])
    cut = int(at_us) - start
    if cut <= 0 or cut >= dur:
        raise ValueError("자를 수 없는 위치")

    speed = float(seg.get("speed") or 1.0) or 1.0
    front = copy.deepcopy(seg)
    back = copy.deepcopy(seg)
    front["id"] = new_id()
    back["id"] = new_id()

    front["target_timerange"] = {"start": start, "duration": cut}
    back["target_timerange"] = {"start": start + cut, "duration": dur - cut}

    src = seg.get("source_timerange")
    if src:
        s0 = int(src.get("start", 0))
        sdur = int(src.get("duration", 0))
        scut = int(round(cut * speed))
        scut = max(0, min(scut, sdur))
        front["source_timerange"] = {"start": s0, "duration": scut}
        back["source_timerange"] = {"start": s0 + scut, "duration": sdur - scut}

    f_kf, b_kf, at_cut = split_keyframes(seg.get("common_keyframes"), cut)
    front["common_keyframes"] = f_kf
    back["common_keyframes"] = b_kf

    # 앞 조각의 정지값은 자른 지점 값으로 (화면이 튀지 않게)
    if at_cut and isinstance(front.get("clip"), dict):
        clip = front["clip"]
        if "KFTypePositionX" in at_cut or "KFTypePositionY" in at_cut:
            t = dict(clip.get("transform") or {"x": 0.0, "y": 0.0})
            if at_cut.get("KFTypePositionX") is not None:
                t["x"] = round(at_cut["KFTypePositionX"], 6)
            if at_cut.get("KFTypePositionY") is not None:
                t["y"] = round(at_cut["KFTypePositionY"], 6)
            clip["transform"] = t
        if at_cut.get("KFTypeScaleX") is not None:
            v = round(at_cut["KFTypeScaleX"], 6)
            clip["scale"] = {"x": v, "y": v}

    # 전환은 뒤 조각으로, 부속 머티리얼은 뒤 조각용으로 복제
    trans_ids = {t["id"] for t in (project.draft.get("materials") or {})
                 .get("transitions", []) or [] if t.get("id")}
    refs = list(seg.get("extra_material_refs") or [])
    front["extra_material_refs"] = [r for r in refs if r not in trans_ids]
    back["extra_material_refs"] = [
        (r if r in trans_ids else dup_material(project, r, idx)) for r in refs]

    # 텍스트/오디오 등 본체 머티리얼도 뒤 조각용으로 복제 (공유 회피)
    if seg.get("material_id"):
        back["material_id"] = dup_material(project, seg["material_id"], idx)

    return front, back


# ── mp4 헤더 읽기 (외부 프로그램 없이) ─────────────────────────

def _iter_boxes(f, end):
    while f.tell() < end:
        head = f.read(8)
        if len(head) < 8:
            return
        size, typ = struct.unpack(">I4s", head)
        start = f.tell()
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            start = f.tell()
            body = size - 16
        elif size == 0:
            body = end - start
        else:
            body = size - 8
        if body < 0:
            return
        yield typ.decode("latin-1"), start, body
        f.seek(start + body)


def probe_mp4(path):
    """mp4/mov 헤더에서 (길이us, 가로, 세로, 소리있음) 을 읽는다."""
    size = os.path.getsize(path)
    dur_us, w, h, has_audio = None, None, None, False
    with open(path, "rb") as f:
        for typ, start, body in _iter_boxes(f, size):
            if typ != "moov":
                continue
            f.seek(start)
            for t2, s2, b2 in _iter_boxes(f, start + body):
                if t2 == "mvhd":
                    f.seek(s2)
                    ver = f.read(1)[0]
                    f.read(3)
                    if ver == 1:
                        f.read(16)
                        ts = struct.unpack(">I", f.read(4))[0]
                        du = struct.unpack(">Q", f.read(8))[0]
                    else:
                        f.read(8)
                        ts = struct.unpack(">I", f.read(4))[0]
                        du = struct.unpack(">I", f.read(4))[0]
                    if ts:
                        dur_us = int(round(du / ts * US))
                elif t2 == "trak":
                    f.seek(s2)
                    tw = th = None
                    handler = None
                    for t3, s3, b3 in _iter_boxes(f, s2 + b2):
                        if t3 == "tkhd":
                            f.seek(s3)
                            ver = f.read(1)[0]
                            f.read(3)
                            f.read(16 if ver == 1 else 8)
                            f.read(4)          # track id
                            f.read(4)          # reserved
                            f.read(8 if ver == 1 else 4)   # duration
                            f.read(8 + 2 + 2 + 2 + 2 + 36)  # 예약/레이어/매트릭스
                            tw = struct.unpack(">I", f.read(4))[0] / 65536.0
                            th = struct.unpack(">I", f.read(4))[0] / 65536.0
                        elif t3 == "mdia":
                            f.seek(s3)
                            for t4, s4, b4 in _iter_boxes(f, s3 + b3):
                                if t4 == "hdlr":
                                    f.seek(s4 + 8)
                                    handler = f.read(4).decode("latin-1")
                    if handler == "soun":
                        has_audio = True
                    if handler == "vide" and tw and th and not (w and h):
                        w, h = int(round(tw)), int(round(th))
    return dur_us, w, h, has_audio


# ── 효과 카탈로그 (app\effects.json) ───────────────────────────

def load_catalog():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "app", "effects.json"),
                 os.path.join(here, "effects.json"),
                 os.path.join(here, "..", "effects.json")):
        cand = os.path.normpath(cand)
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    return json.load(f), cand
            except Exception:
                pass
    return None, None
