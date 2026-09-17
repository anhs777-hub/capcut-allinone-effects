# -*- coding: utf-8 -*-
"""캡컷 자동 효과 v2 — GUI.

탭 구성: [기본] 파일/휙컷 빈도  [효과] 전환·필터·화면효과 선택(유료/무료)
        [로고] 이미지·위치·크기  [자막] 색상·배경·테두리
        [챕터] 타임스탬프 목록대로 챕터 제목 표시
설정은 settings.json, 효과 목록은 effects.json에 저장된다.
"""

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import capcut_core as core

BG = "#1e1f24"
BG2 = "#2c2e35"
FG = "#ececed"
SUB = "#9aa0a6"
ACC = "#d8b25a"

APP_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))
CATALOG_FILE = os.path.join(APP_DIR, "effects.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

SNAP_MODES = [
    ("none", "없음 (드리프트만)"),
    ("rare", "3~4분에 1번 (추천)"),
    ("often", "1~2분에 1번"),
    ("every", "씬마다 (어지러울 수 있음)"),
]
LOGO_PRESETS = {
    "오른쪽 위": (0.80, 0.80),
    "중앙 위": (0.0, 0.80),
    "왼쪽 위": (-0.80, 0.80),
}
# 챕터 제목 위치 (가로, 세로 · -100~100)
CHAPTER_PRESETS = {
    "왼쪽 위": (-72, 80),
    "왼쪽 아래": (-72, -70),
    "오른쪽 위": (10, 80),
}

DEFAULT_SETTINGS = {
    "snap_mode": "rare",
    "free_only": False,
    "effect_mode": "random_one",
    "logo": {"use": False, "path": "", "preset": "오른쪽 위",
             "x": 0.80, "y": 0.80, "size": 15},
    "subtitle": {"use": False, "text_color": "#111111", "use_background": True,
                 "background_color": "#ffffff", "background_alpha": 80,
                 "border_color": "#000000", "border_width": 0,
                 "bg_size": 0, "pos_use": False, "pos_x": 0, "pos_y": -80,
                 "pos_preset": "원본 유지", "font_size": 0,
                 "font_name": "", "font_path": ""},
    "chapter": {"use": False, "txt": "", "preset": "왼쪽 위",
                "x": -72, "y": 80, "align_left": True,
                "hold": 5, "font_size": 7, "text_color": "#ffffff",
                "use_background": True, "background_color": "#000000",
                "background_alpha": 45, "border_color": "#000000",
                "border_width": 0, "font_name": "", "font_path": ""},
}


def system_fonts():
    """윈도우에 설치된 폰트 {표시이름: 파일경로} (레지스트리에서 수집)."""
    fonts = {}
    try:
        import winreg
    except ImportError:
        return fonts
    base = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            k = winreg.OpenKey(hive,
                               r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(k)[1]):
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            if not isinstance(val, str):
                continue
            name = name.split(" (")[0].strip()
            if not name:
                continue
            p = val if os.path.isabs(val) else os.path.join(base, val)
            if p.lower().endswith((".ttf", ".otf", ".ttc")) and os.path.exists(p):
                fonts[name] = p
        winreg.CloseKey(k)

    have = {os.path.normcase(v) for v in fonts.values()}
    user_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                            "Microsoft", "Windows", "Fonts")
    for d in (base, user_dir):
        if not d or not os.path.isdir(d):
            continue
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for fn in files:
            p = os.path.join(d, fn)
            if (p.lower().endswith((".ttf", ".otf", ".ttc"))
                    and os.path.normcase(p) not in have):
                fonts.setdefault(os.path.splitext(fn)[0], p)
    return fonts


def load_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(fallback))


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("캡컷자동올인원 - made by 바람님")
        self.geometry("680x768")
        self.minsize(660, 600)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.catalog = load_json(CATALOG_FILE, {"transitions": [], "filters": [],
                                                "video_effects": []})
        st = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
        for k, v in DEFAULT_SETTINGS.items():
            st.setdefault(k, v)
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    st[k].setdefault(k2, v2)
        self.settings = st

        self.zip_path = None
        self.trees = {}

        self._style()
        self._build()

    # ── 스타일 / 기본 레이아웃 ───────────────────────────────────

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=BG2, foreground=FG, padding=(16, 8))
        s.map("TNotebook.Tab", background=[("selected", ACC)],
              foreground=[("selected", "#1e1f24")])
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Sub.TLabel", foreground=SUB)
        s.configure("Acc.TLabel", foreground=ACC)
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TRadiobutton", background=BG, foreground=FG)
        s.map("TRadiobutton", background=[("active", BG)])
        s.configure("Treeview", background=BG2, fieldbackground=BG2, foreground=FG,
                    rowheight=24, borderwidth=0)
        s.configure("Treeview.Heading", background=BG, foreground=SUB, borderwidth=0)
        s.configure("TButton", background=BG2, foreground=FG, borderwidth=0,
                    padding=(10, 6))
        s.map("TButton", background=[("active", "#3a3d46")])
        s.configure("Run.TButton", background=ACC, foreground="#1e1f24",
                    font=("맑은 고딕", 11, "bold"), padding=(10, 10))
        s.map("Run.TButton", background=[("active", "#e6c56f"), ("disabled", BG2)])
        s.configure("Horizontal.TScale", background=BG)
        s.configure("TCombobox", fieldbackground=BG2, background=BG2, foreground=FG)
        s.configure("Horizontal.TProgressbar", background=ACC, troughcolor=BG2)

    def _build(self):
        head = ttk.Label(self, text="  캡컷자동올인원", font=("맑은 고딕", 15, "bold"),
                         style="Acc.TLabel")
        head.pack(anchor="w", padx=14, pady=(14, 2))
        ttk.Label(self, text="  줌·전환·휙컷·로고·자막·챕터 제목까지 한 번에 · made by 바람님",
                  style="Sub.TLabel").pack(anchor="w", padx=14)

        # 하단 고정 영역: 실행 버튼 / 진행바 / 상태줄
        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        self.run_btn = ttk.Button(bottom, text="✨ 효과 넣기 실행", style="Run.TButton",
                                  command=self.start, state="disabled")
        self.run_btn.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(bottom, text="캡컷 프로젝트 zip을 선택해 주세요.",
                                style="Sub.TLabel", wraplength=620)
        self.status.pack(anchor="w", pady=(6, 0))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=10)
        self.tab_basic = ttk.Frame(nb)
        self.tab_fx = ttk.Frame(nb)
        self.tab_logo = ttk.Frame(nb)
        self.tab_sub = ttk.Frame(nb)
        self.tab_ch = ttk.Frame(nb)
        nb.add(self.tab_basic, text=" 기본 ")
        nb.add(self.tab_fx, text=" 효과 ")
        nb.add(self.tab_logo, text=" 로고 ")
        nb.add(self.tab_sub, text=" 자막 ")
        nb.add(self.tab_ch, text=" 챕터 ")
        self._build_basic()
        self._build_fx()
        self._build_logo()
        self._build_sub()
        self._build_chapter()

    # ── [기본] 탭 ────────────────────────────────────────────────

    def _build_basic(self):
        f = self.tab_basic
        ttk.Button(f, text="📁 캡컷 프로젝트 zip 선택", command=self.select_zip) \
            .pack(anchor="w", padx=16, pady=(16, 4))
        self.file_lbl = ttk.Label(f, text="선택된 파일 없음", style="Sub.TLabel",
                                  wraplength=600)
        self.file_lbl.pack(anchor="w", padx=16)

        ttk.Label(f, text="휙 컷 (빠른 화면 점프) 빈도", font=("맑은 고딕", 10, "bold")) \
            .pack(anchor="w", padx=16, pady=(20, 4))
        ttk.Label(f, text="기본 드리프트(느린 랜덤 이동)는 모든 씬에 항상 들어가고,\n"
                          "휙 컷은 아래 빈도로 랜덤 씬에 추가됩니다. 선택된 씬 안에서는\n"
                          "길이에 따라 2~3번 휙휙 움직이고, 사이사이는 드리프트로 이어집니다.",
                  style="Sub.TLabel").pack(anchor="w", padx=16)
        self.snap_var = tk.StringVar(value=self.settings.get("snap_mode", "rare"))
        for val, label in SNAP_MODES:
            ttk.Radiobutton(f, text=label, value=val, variable=self.snap_var) \
                .pack(anchor="w", padx=28, pady=2)

    def select_zip(self):
        p = filedialog.askopenfilename(title="캡컷 프로젝트 zip 선택",
                                       filetypes=[("zip 파일", "*.zip")])
        if p:
            self.zip_path = p
            self.file_lbl.config(text=p)
            self.run_btn.config(state="normal")
            self.status.config(
                text="준비 완료. [효과]·[로고]·[자막]·[챕터] 탭을 확인한 뒤 실행하세요.")
            twin = os.path.splitext(p)[0] + ".txt"
            if os.path.exists(twin):
                self.load_chapter_txt(twin, quiet=True)

    # ── [효과] 탭 ────────────────────────────────────────────────

    def _build_fx(self):
        f = self.tab_fx
        top = ttk.Frame(f)
        top.pack(fill="x", padx=12, pady=(10, 4))
        self.free_only = tk.BooleanVar(value=self.settings.get("free_only", False))
        ttk.Checkbutton(top, text="무료 효과만 사용", variable=self.free_only) \
            .pack(side="left")
        ttk.Button(top, text="다른 zip에서 효과 가져오기", command=self.import_fx) \
            .pack(side="right")

        mode_row = ttk.Frame(f)
        mode_row.pack(fill="x", padx=12, pady=(0, 2))
        ttk.Label(mode_row, text="화면 효과 적용:").pack(side="left")
        self.fx_mode = tk.StringVar(value=self.settings.get("effect_mode", "random_one"))
        ttk.Radiobutton(mode_row, text="체크한 것 중 랜덤 1개 (추천)",
                        value="random_one", variable=self.fx_mode) \
            .pack(side="left", padx=(8, 0))
        ttk.Radiobutton(mode_row, text="체크한 것 모두",
                        value="all", variable=self.fx_mode).pack(side="left", padx=8)

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, padx=12, pady=4)
        for kind, title in (("transitions", "전환 (씬 사이)"),
                            ("filters", "필터 (전체)"),
                            ("video_effects", "화면 효과 (전체)")):
            self._build_tree(body, kind, title)
        ttk.Label(f, text="행 클릭 = 사용/해제 · [유료↔무료] = 선택한 행의 구분 변경\n"
                          "새 효과 추가: 캡컷에서 그 효과만 적용해 내보낸 zip을 "
                          "\"다른 zip에서 효과 가져오기\"로 읽으면 목록에 등록됩니다.",
                  style="Sub.TLabel").pack(anchor="w", padx=12, pady=(2, 8))

    def _build_tree(self, parent, kind, title):
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True, pady=(4, 2))
        hd = ttk.Frame(box)
        hd.pack(fill="x")
        ttk.Label(hd, text=title, font=("맑은 고딕", 9, "bold")).pack(side="left")
        ttk.Button(hd, text="유료↔무료", width=10,
                   command=lambda k=kind: self.toggle_paid(k)).pack(side="right")
        heights = {"transitions": 4, "filters": 2, "video_effects": 6}
        tree = ttk.Treeview(box, columns=("use", "name", "paid"), show="headings",
                            height=heights.get(kind, 4), selectmode="browse")
        tree.heading("use", text="사용")
        tree.heading("name", text="이름")
        tree.heading("paid", text="구분")
        tree.column("use", width=50, anchor="center")
        tree.column("name", width=380)
        tree.column("paid", width=70, anchor="center")
        tree.pack(fill="both", expand=True)
        tree.bind("<Button-1>", lambda e, k=kind: self.on_tree_click(e, k))
        self.trees[kind] = tree
        self.refresh_tree(kind)

    def refresh_tree(self, kind):
        tree = self.trees[kind]
        tree.delete(*tree.get_children())
        for it in self.catalog.get(kind, []):
            tree.insert("", "end", iid=it["resource_id"],
                        values=("☑" if it.get("enabled") else "☐",
                                it.get("name", "?"),
                                "유료" if it.get("paid") else "무료"))

    def _item(self, kind, rid):
        for it in self.catalog.get(kind, []):
            if it["resource_id"] == rid:
                return it
        return None

    def on_tree_click(self, event, kind):
        tree = self.trees[kind]
        rid = tree.identify_row(event.y)
        if not rid:
            return
        it = self._item(kind, rid)
        if it is None:
            return
        it["enabled"] = not it.get("enabled")
        tree.set(rid, "use", "☑" if it["enabled"] else "☐")

    def toggle_paid(self, kind):
        tree = self.trees[kind]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("알림", "목록에서 행을 먼저 선택해 주세요.")
            return
        it = self._item(kind, sel[0])
        if it:
            it["paid"] = not it.get("paid")
            tree.set(sel[0], "paid", "유료" if it["paid"] else "무료")

    def import_fx(self):
        p = filedialog.askopenfilename(title="효과가 든 캡컷 zip 선택",
                                       filetypes=[("zip 파일", "*.zip")])
        if not p:
            return
        try:
            found = core.scan_zip_for_effects(p)
        except Exception as e:
            messagebox.showerror("오류", str(e))
            return
        added = 0
        for kind in ("transitions", "filters", "video_effects"):
            have = {it["resource_id"] for it in self.catalog.get(kind, [])}
            for it in found.get(kind, []):
                if it["resource_id"] not in have:
                    it["paid"] = False
                    it["enabled"] = False
                    self.catalog.setdefault(kind, []).append(it)
                    added += 1
            self.refresh_tree(kind)
        save_json(CATALOG_FILE, self.catalog)
        if added:
            messagebox.showinfo("완료", str(added) + "개 효과를 새로 등록했어요.\n"
                                "목록에서 클릭해 사용으로 바꾸고, 유료 효과라면 "
                                "[유료↔무료]로 구분을 지정해 주세요.")
        else:
            messagebox.showinfo("알림", "새로 추가할 효과가 없었어요. (이미 모두 등록됨)")

    # ── [로고] 탭 ────────────────────────────────────────────────

    PV_W, PV_H = 384, 216

    def _build_logo(self):
        f = self.tab_logo
        lg = self.settings["logo"]
        top = ttk.Frame(f)
        top.pack(fill="x", padx=16, pady=(12, 2))
        self.logo_use = tk.BooleanVar(value=lg.get("use", False))
        ttk.Checkbutton(top, text="채널 로고 넣기", variable=self.logo_use) \
            .pack(side="left")
        ttk.Button(top, text="🖼 이미지 선택 (PNG 권장)", command=self.select_logo) \
            .pack(side="right")
        self.logo_lbl = ttk.Label(f, text=lg.get("path") or "선택된 이미지 없음",
                                  style="Sub.TLabel", wraplength=600)
        self.logo_lbl.pack(anchor="w", padx=16)

        self.pv = tk.Canvas(f, width=self.PV_W, height=self.PV_H, bg="#0d0e11",
                            highlightthickness=1, highlightbackground="#3a3d46")
        self.pv.pack(padx=16, pady=(6, 2))
        self.pv.bind("<Button-1>", self._on_preview_drag)
        self.pv.bind("<B1-Motion>", self._on_preview_drag)
        ttk.Label(f, text="미리보기: 로고를 마우스로 끌어서 위치를 잡을 수 있어요.",
                  style="Sub.TLabel").pack(anchor="w", padx=16)

        row = ttk.Frame(f)
        row.pack(anchor="w", padx=16, pady=(6, 2))
        ttk.Label(row, text="위치 프리셋").pack(side="left")
        self.logo_preset = ttk.Combobox(row, state="readonly", width=12,
                                        values=list(LOGO_PRESETS) + ["직접 지정"])
        self.logo_preset.set(lg.get("preset", "오른쪽 위"))
        self.logo_preset.pack(side="left", padx=8)
        self.logo_preset.bind("<<ComboboxSelected>>", self.on_logo_preset)

        self.logo_size = self._slider_row(f, "크기", 4, 40, lg.get("size", 15))
        self.logo_x = self._slider_row(f, "가로 위치", -100, 100, lg.get("x", 0.8) * 100)
        self.logo_y = self._slider_row(f, "세로 위치", -100, 100, lg.get("y", 0.8) * 100)
        for var in (self.logo_size, self.logo_x, self.logo_y):
            var.trace_add("write", lambda *_: self.redraw_preview())
        self._pv_cache = {}
        self.redraw_preview()

    def _slider_row(self, parent, label, lo, hi, init, length=300, padx=16,
                    width=8, var=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=padx, pady=2)
        ttk.Label(row, text=label, width=width).pack(side="left")
        if var is None:
            var = tk.DoubleVar(value=float(init))
        ttk.Scale(row, from_=lo, to=hi, variable=var, length=length).pack(side="left")
        return var

    def _draw_video_bg(self, c, W=None, H=None):
        """미리보기 캔버스에 영상 느낌의 회색 그라데이션 배경을 깐다.

        어두운 색/밝은 색 자막·로고가 모두 잘 보이도록 중간 톤으로 채운다.
        """
        c.delete("all")
        W = W or self.PV_W
        H = H or self.PV_H
        top, bot = (150, 155, 163), (52, 56, 64)
        step = 4
        for i in range(0, H, step):
            t = i / H
            col = "#%02x%02x%02x" % tuple(round(a + (b - a) * t)
                                          for a, b in zip(top, bot))
            c.create_rectangle(0, i, W, i + step, fill=col, outline="")
        c.create_rectangle(1, 1, W - 1, H - 1, outline="#3a3d46")

    def _logo_disp(self):
        """프로젝트 기준 로고 표시 크기(px). (없으면 300x120 가정)"""
        path = self.settings["logo"].get("path", "")
        wh = core.image_size(path) if path and os.path.exists(path) else None
        w, h = wh or (300, 120)
        r = min(1920 / w, 1080 / h)
        size = self.logo_size.get() / 100.0
        return w * r * size, h * r * size

    def _logo_photo(self, tw):
        """미리보기용으로 대략 tw 픽셀 폭에 맞춘 PhotoImage (PNG/GIF만)."""
        path = self.settings["logo"].get("path", "")
        if not path or not os.path.exists(path):
            return None
        key = (path, int(tw))
        if key in self._pv_cache:
            return self._pv_cache[key]
        try:
            img = tk.PhotoImage(file=path)
        except tk.TclError:
            self._pv_cache[key] = None
            return None
        factor = max(tw, 8) / max(img.width(), 1)
        best = None
        for z in (1, 2, 3):
            s = max(1, round(z / factor))
            if best is None or abs(z / s - factor) < abs(best[0] / best[1] - factor):
                best = (z, s)
        z, s = best
        if s > 1:
            img = img.subsample(s, s)
        if z > 1:
            img = img.zoom(z, z)
        self._pv_cache.clear()
        self._pv_cache[key] = img
        return img

    def redraw_preview(self):
        pv = self.pv
        self._draw_video_bg(pv)
        W, H, k = self.PV_W, self.PV_H, self.PV_W / 1920.0

        sy = H / 2 - (-0.8) * H / 2
        pv.create_rectangle(W * 0.30, sy - 7, W * 0.70, sy + 7,
                            fill="#26282f", outline="")
        pv.create_text(W / 2, sy, text="자막 위치", fill="#8b9099",
                       font=("맑은 고딕", 7))

        dw, dh = self._logo_disp()
        tw, th = dw * k, dh * k
        cx = W / 2 + (self.logo_x.get() / 100.0) * W / 2
        cy = H / 2 - (self.logo_y.get() / 100.0) * H / 2
        img = self._logo_photo(tw)
        if img is not None:
            pv.create_image(cx, cy, image=img)
            pv.image = img
        else:
            fill = "#26282f" if self.settings["logo"].get("path") else ""
            pv.create_rectangle(cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2,
                                outline=ACC, dash=(3, 2), fill=fill)
            pv.create_text(cx, cy, text="로고", fill=ACC, font=("맑은 고딕", 8))
        pct = round(dw / 1920 * 100)
        pv.create_text(6, 8, anchor="w", fill="#9aa0a6", font=("맑은 고딕", 8),
                       text="화면 가로의 " + str(pct) + "% · 실제 약 " +
                              str(int(dw)) + "×" + str(int(dh)) + "px")

    def _on_preview_drag(self, event):
        W, H = self.PV_W, self.PV_H
        x = (event.x - W / 2) / (W / 2) * 100
        y = (H / 2 - event.y) / (H / 2) * 100
        self.logo_x.set(round(max(-100, min(100, x)), 1))
        self.logo_y.set(round(max(-100, min(100, y)), 1))
        self.logo_preset.set("직접 지정")

    def on_logo_preset(self, _=None):
        name = self.logo_preset.get()
        if name in LOGO_PRESETS:
            x, y = LOGO_PRESETS[name]
            self.logo_x.set(x * 100)
            self.logo_y.set(y * 100)

    def select_logo(self):
        p = filedialog.askopenfilename(
            title="로고 이미지 선택",
            filetypes=[("이미지", "*.png *.jpg *.jpeg"), ("모든 파일", "*.*")])
        if p:
            self.settings["logo"]["path"] = p
            self.logo_lbl.config(text=p)
            self.logo_use.set(True)
            self._pv_cache.clear()
            self.redraw_preview()

    # ── [자막] 탭 ────────────────────────────────────────────────

    def _build_sub(self):
        f = self.tab_sub
        st = self.settings["subtitle"]
        top = ttk.Frame(f)
        top.pack(fill="x", padx=16, pady=(10, 2))
        self.sub_use = tk.BooleanVar(value=st.get("use", False))
        ttk.Label(top, text="자막:").pack(side="left")
        ttk.Radiobutton(top, text="원본 그대로", value=False, variable=self.sub_use,
                        command=self.redraw_sub_preview).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(top, text="설정대로 변경", value=True, variable=self.sub_use,
                        command=self.redraw_sub_preview).pack(side="left", padx=6)
        self.sub_pos_use = tk.BooleanVar(value=st.get("pos_use", False))
        ttk.Label(top, text="   위치:").pack(side="left")
        self.sub_pos_preset = ttk.Combobox(
            top, state="readonly", width=14,
            values=["원본 유지", "하단", "중앙", "상단", "직접 지정(드래그)"])
        self.sub_pos_preset.set(st.get("pos_preset", "원본 유지"))
        self.sub_pos_preset.pack(side="left", padx=6)
        self.sub_pos_preset.bind("<<ComboboxSelected>>", self._on_pos_preset)

        self.sv = tk.Canvas(f, width=self.PV_W, height=self.PV_H, bg="#0d0e11",
                            highlightthickness=1, highlightbackground="#3a3d46")
        self.sv.pack(padx=16, pady=(4, 2))
        self.sv.bind("<Button-1>", self._on_sub_drag)
        self.sv.bind("<B1-Motion>", self._on_sub_drag)

        self.sub_x = tk.DoubleVar(value=st.get("pos_x", 0))
        self.sub_y = tk.DoubleVar(value=st.get("pos_y", -80))

        cols = ttk.Frame(f)
        cols.pack(fill="x", padx=16, pady=(4, 0))
        left = ttk.Frame(cols)
        left.pack(side="left", anchor="n")
        right = ttk.Frame(cols)
        right.pack(side="left", anchor="n", padx=(20, 0))

        self.color_btns = {}
        for key, label in (("text_color", "글자 색"),
                           ("background_color", "배경 색"),
                           ("border_color", "테두리 색")):
            row = ttk.Frame(left)
            row.pack(anchor="w", pady=2, fill="x")
            ttk.Label(row, text=label, width=7).pack(side="left")
            btn = tk.Button(row, text=st.get(key, "#ffffff"), width=9,
                            bg=st.get(key, "#ffffff"), relief="flat",
                            command=lambda k=key: self.pick_color(k))
            btn.pack(side="left")
            self.color_btns[key] = btn
        self.sub_bg_use = tk.BooleanVar(value=st.get("use_background", True))
        ttk.Checkbutton(left, text="배경 상자 사용", variable=self.sub_bg_use,
                        command=self._on_sub_touch).pack(anchor="w", pady=(4, 0))

        self.sub_bg_alpha = self._slider_row(right, "배경 진하기", 0, 100,
                                             st.get("background_alpha", 80),
                                             length=190, padx=0, width=9)
        self.sub_bg_size = self._slider_row(right, "배경 크기", 0, 100,
                                            st.get("bg_size", 0),
                                            length=190, padx=0, width=9)
        self.sub_border = self._slider_row(right, "테두리 두께", 0, 20,
                                           st.get("border_width", 0),
                                           length=190, padx=0, width=9)
        self.sub_size = self._slider_row(right, "글자 크기", 0, 12,
                                         st.get("font_size", 0),
                                         length=190, padx=0, width=9)
        for var in (self.sub_bg_alpha, self.sub_bg_size, self.sub_border,
                    self.sub_size):
            var.trace_add("write", self._on_sub_touch)

        frow = ttk.Frame(f)
        frow.pack(fill="x", padx=16, pady=(6, 0))
        ttk.Label(frow, text="폰트", width=7).pack(side="left")
        self.fonts = system_fonts()
        names = ["원본 유지"] + sorted(self.fonts)
        self.sub_font = ttk.Combobox(frow, state="readonly", width=30, values=names)
        self.sub_font.set(st.get("font_name") if st.get("font_name") in self.fonts
                          else "원본 유지")
        self.sub_font.pack(side="left")
        self.sub_font.bind("<<ComboboxSelected>>",
                           lambda e: self._on_sub_touch())
        self.redraw_sub_preview()

    def _on_sub_touch(self, *_):
        """자막 탭의 어떤 항목이든 조작하면 일괄 변경을 자동으로 켠다."""
        self.sub_use.set(True)
        self.redraw_sub_preview()

    def _on_pos_preset(self, _=None):
        name = self.sub_pos_preset.get()
        presets = {"하단": (0, -80), "중앙": (0, 0), "상단": (0, 75)}
        if name == "원본 유지":
            self.sub_pos_use.set(False)
        elif name in presets:
            x, y = presets[name]
            self.sub_x.set(x)
            self.sub_y.set(y)
            self.sub_pos_use.set(True)
            self.sub_use.set(True)
        self.redraw_sub_preview()

    def _on_sub_drag(self, event):
        W, H = self.PV_W, self.PV_H
        x = (event.x - W / 2) / (W / 2) * 100
        y = (H / 2 - event.y) / (H / 2) * 100
        self.sub_x.set(round(max(-95, min(95, x)), 1))
        self.sub_y.set(round(max(-95, min(95, y)), 1))
        self.sub_pos_use.set(True)
        self.sub_use.set(True)
        self.sub_pos_preset.set("직접 지정(드래그)")
        self.redraw_sub_preview()

    @staticmethod
    def _blend(fg, bg, a):
        """알파 근사: fg를 bg 위에 a 불투명도로 섞은 색."""
        f = [int(fg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        b = [int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        return "#%02x%02x%02x" % tuple(round(a * x + (1 - a) * y)
                                       for x, y in zip(f, b))

    def redraw_sub_preview(self):
        sv = self.sv
        self._draw_video_bg(sv)
        W, H = self.PV_W, self.PV_H
        st = self.settings["subtitle"]
        sample = "이런 식으로 자막이 표시됩니다"
        fam = self.sub_font.get() if hasattr(self, "sub_font") else ""
        if not fam or fam == "원본 유지":
            fam = "맑은 고딕"
        fs = self.sub_size.get() if hasattr(self, "sub_size") else 0

        pt = 11 if fs < 1 else max(6, min(26, round(fs / 5.4 * 11)))
        font = (fam, pt, "bold")
        if self.sub_pos_use.get():
            cx = W / 2 + (self.sub_x.get() / 100.0) * W / 2
            cy = H / 2 - (self.sub_y.get() / 100.0) * H / 2
        else:
            cx, cy = W / 2, H / 2 + 0.8 * H / 2
        cx = max(20, min(W - 20, cx))
        cy = max(14, min(H - 14, cy))
        tmp = sv.create_text(cx, cy, text=sample, font=font)
        x0, y0, x1, y1 = sv.bbox(tmp)
        sv.delete(tmp)
        if self.sub_bg_use.get():
            a = self.sub_bg_alpha.get() / 100.0

            fill = self._blend(st.get("background_color", "#000000"), "#5a5e66", a)
            pad = 6 + self.sub_bg_size.get() / 100.0 * 22
            sv.create_rectangle(x0 - pad, y0 - pad * 0.6, x1 + pad, y1 + pad * 0.6,
                                fill=fill, outline="")
        bw = self.sub_border.get()
        if bw > 0:
            off = max(1, round(bw / 20 * 3))
            bc = st.get("border_color", "#000000")
            for dx, dy in ((-off, 0), (off, 0), (0, -off), (0, off),
                           (-off, -off), (off, off), (-off, off), (off, -off)):
                sv.create_text(cx + dx, cy + dy, text=sample, font=font, fill=bc)
        sv.create_text(cx, cy, text=sample, font=font,
                       fill=st.get("text_color", "#ffffff"))
        if self.sub_use.get():
            pos_txt = ("위치: " + self.sub_pos_preset.get()
                       if self.sub_pos_use.get() else "위치: 원본 그대로")
            size_txt = " · 크기: " + (str(round(fs, 1)) if fs >= 1 else "원본 유지")
            sv.create_text(6, 8, anchor="w", fill="#8fd18f", font=("맑은 고딕", 8, "bold"),
                           text="● 설정대로 변경 모드 · " + pos_txt + size_txt)
        else:
            sv.create_rectangle(0, 0, W, 22, fill="#4a3a17", outline="")
            sv.create_text(6, 11, anchor="w", fill="#f0c05a", font=("맑은 고딕", 8, "bold"),
                           text="⚠ 원본 그대로 모드 — 실행해도 자막은 바뀌지 않아요"
                                " (아래를 만지면 변경 모드로 전환)")

    def pick_color(self, key):
        cur = self.settings["subtitle"].get(key, "#ffffff")
        rgb, hexv = colorchooser.askcolor(color=cur, title="색 선택")
        if hexv:
            self.settings["subtitle"][key] = hexv
            self.color_btns[key].config(text=hexv, bg=hexv)
            self._on_sub_touch()

    # ── [챕터] 탭 ────────────────────────────────────────────────

    CV_W, CV_H = 320, 180      # 챕터 미리보기 크기 (16:9)

    def _build_chapter(self):
        f = self.tab_ch
        cs = self.settings["chapter"]
        self.chapters = []

        top = ttk.Frame(f)
        top.pack(fill="x", padx=16, pady=(10, 2))
        self.ch_use = tk.BooleanVar(value=cs.get("use", False))
        ttk.Checkbutton(top, text="챕터 제목 넣기", variable=self.ch_use) \
            .pack(side="left")
        ttk.Button(top, text="📄 챕터 목록 txt 선택", command=self.select_chapter_txt) \
            .pack(side="right")
        self.ch_lbl = ttk.Label(f, text="선택된 목록 없음", style="Sub.TLabel")
        self.ch_lbl.pack(anchor="w", padx=16)
        ttk.Label(f, text="\"0:00 인트로\" 처럼 한 줄에 하나씩 · 유튜브 설명란 형식 그대로 OK",
                  style="Sub.TLabel").pack(anchor="w", padx=16)
        ttk.Label(f, text="zip 옆에 같은 이름의 txt 를 두면 자동으로 읽어옵니다.",
                  style="Sub.TLabel").pack(anchor="w", padx=16)

        body = ttk.Frame(f)
        body.pack(fill="x", padx=16, pady=(6, 2))
        self.cv = tk.Canvas(body, width=self.CV_W, height=self.CV_H,
                            bg="#0d0e11", highlightthickness=1,
                            highlightbackground="#3a3d46")
        self.cv.pack(side="left")
        tbox = ttk.Frame(body)
        tbox.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(tbox, text="읽어온 챕터 (클릭 = 미리보기)",
                  style="Sub.TLabel").pack(anchor="w")
        self.ch_tree = ttk.Treeview(tbox, columns=("t", "name"),
                                    show="headings", height=7,
                                    selectmode="browse")
        self.ch_tree.heading("t", text="시각")
        self.ch_tree.heading("name", text="제목")
        self.ch_tree.column("t", width=60, anchor="center")
        self.ch_tree.column("name", width=170)
        self.ch_tree.pack(fill="both", expand=True)
        self.ch_tree.bind("<<TreeviewSelect>>",
                          lambda e: self.redraw_ch_preview())
        self.cv.bind("<Button-1>", self._on_ch_drag)
        self.cv.bind("<B1-Motion>", self._on_ch_drag)

        self.ch_x = tk.DoubleVar(value=cs.get("x", -72))
        self.ch_y = tk.DoubleVar(value=cs.get("y", 80))
        self.ch_align = tk.BooleanVar(value=cs.get("align_left", True))

        row = ttk.Frame(f)
        row.pack(fill="x", padx=16, pady=(4, 0))
        ttk.Label(row, text="위치").pack(side="left")
        self.ch_preset = ttk.Combobox(row, state="readonly", width=12,
                                      values=list(CHAPTER_PRESETS) + ["직접 지정"])
        self.ch_preset.set(cs.get("preset", "왼쪽 위"))
        self.ch_preset.pack(side="left", padx=(6, 12))
        self.ch_preset.bind("<<ComboboxSelected>>", self._on_ch_preset)
        ttk.Checkbutton(row, text="제목 길이가 달라도 왼쪽 끝 맞추기",
                        variable=self.ch_align,
                        command=self.redraw_ch_preview).pack(side="left")

        cols = ttk.Frame(f)
        cols.pack(fill="x", padx=16, pady=(2, 0))
        left = ttk.Frame(cols)
        left.pack(side="left", anchor="n")
        right = ttk.Frame(cols)
        right.pack(side="left", anchor="n", padx=(20, 0))

        self.ch_hold = self._slider_row(left, "표시 시간", 1, 15,
                                        cs.get("hold", 5), length=165, padx=0, width=10)
        self.ch_size = self._slider_row(left, "글자 크기", 3, 14,
                                        cs.get("font_size", 7), length=170, padx=0,
                                        width=9)
        self.ch_bg_alpha = self._slider_row(right, "배경 진하기", 0, 100,
                                            cs.get("background_alpha", 45),
                                            length=165, padx=0, width=10)
        self.ch_border = self._slider_row(right, "테두리 두께", 0, 20,
                                          cs.get("border_width", 0),
                                          length=165, padx=0, width=10)

        crow = ttk.Frame(f)
        crow.pack(fill="x", padx=16, pady=(4, 0))
        self.ch_color_btns = {}
        for key, label in (("text_color", "글자 색"), ("background_color", "배경 색"),
                           ("border_color", "테두리 색")):
            ttk.Label(crow, text=label).pack(side="left", padx=(0, 4))
            btn = tk.Button(crow, text=cs.get(key, "#ffffff"), width=8, relief="flat",
                            bg=cs.get(key, "#ffffff"),
                            command=lambda k=key: self.pick_ch_color(k))
            btn.pack(side="left", padx=(0, 10))
            self.ch_color_btns[key] = btn
        self.ch_bg_use = tk.BooleanVar(value=cs.get("use_background", True))
        ttk.Checkbutton(crow, text="배경 상자", variable=self.ch_bg_use,
                        command=self.redraw_ch_preview).pack(side="left")

        frow = ttk.Frame(f)
        frow.pack(fill="x", padx=16, pady=(4, 0))
        ttk.Label(frow, text="폰트").pack(side="left", padx=(0, 6))
        self.ch_font = ttk.Combobox(frow, state="readonly", width=24,
                                    values=["기본 폰트"] + sorted(self.fonts))
        self.ch_font.set(cs.get("font_name") if cs.get("font_name") in self.fonts
                         else "기본 폰트")
        self.ch_font.pack(side="left")
        self.ch_font.bind("<<ComboboxSelected>>", lambda e: self.redraw_ch_preview())

        for var in (self.ch_hold, self.ch_size, self.ch_bg_alpha, self.ch_border):
            var.trace_add("write", lambda *_: self.redraw_ch_preview())

        path = cs.get("txt", "")
        if path and os.path.exists(path):
            self.load_chapter_txt(path, quiet=True)
        else:
            self.redraw_ch_preview()

    def select_chapter_txt(self):
        p = filedialog.askopenfilename(
            title="챕터 목록 txt 선택",
            filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")])
        if p:
            self.load_chapter_txt(p)

    def load_chapter_txt(self, path, quiet=False):
        """챕터 txt 를 읽어 목록/미리보기를 갱신한다."""
        try:
            items = core.read_chapter_file(path)
        except Exception as e:
            if not quiet:
                messagebox.showerror("오류", "챕터 목록을 읽지 못했어요.\n" + str(e))
            return
        if not items:
            if not quiet:
                messagebox.showwarning(
                    "확인", "시각이 들어간 줄을 찾지 못했어요.\n"
                            "\"0:00 인트로\" 처럼 시각 + 제목 형태로 적어 주세요.")
            return
        self.chapters = items
        self.settings["chapter"]["txt"] = path
        self.ch_lbl.config(text="📄 " + os.path.basename(path) +
                                "   (챕터 " + str(len(items)) + "개)")
        self.ch_tree.delete(*self.ch_tree.get_children())
        for us, title in items:
            s = us // core.US
            self.ch_tree.insert("", "end", values=(
                "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60), title))
        if not quiet:
            self.ch_use.set(True)
        self.redraw_ch_preview()

    def _on_ch_preset(self, _=None):
        name = self.ch_preset.get()
        if name in CHAPTER_PRESETS:
            x, y = CHAPTER_PRESETS[name]
            self.ch_x.set(x)
            self.ch_y.set(y)
        self.redraw_ch_preview()

    def _on_ch_drag(self, event):
        W, H = self.CV_W, self.CV_H
        x = (event.x - W / 2) / (W / 2) * 100
        y = (H / 2 - event.y) / (H / 2) * 100
        self.ch_x.set(round(max(-95, min(95, x)), 1))
        self.ch_y.set(round(max(-95, min(95, y)), 1))
        self.ch_preset.set("직접 지정")
        self.ch_use.set(True)
        self.redraw_ch_preview()

    def pick_ch_color(self, key):
        cur = self.settings["chapter"].get(key, "#ffffff")
        _, hexv = colorchooser.askcolor(color=cur, title="색 선택")
        if hexv:
            self.settings["chapter"][key] = hexv
            self.ch_color_btns[key].config(text=hexv, bg=hexv)
            self.ch_use.set(True)
            self.redraw_ch_preview()

    def _ch_sample(self):
        """미리보기에 쓸 제목 (목록에서 고른 것 → 첫 챕터 → 예시)."""
        sel = self.ch_tree.selection() if hasattr(self, "ch_tree") else ()
        if sel:
            return self.ch_tree.item(sel[0], "values")[1]
        if self.chapters:
            return self.chapters[0][1]
        return "여기에 챕터 제목"

    def redraw_ch_preview(self, *_):
        cv = self.cv
        W, H = self.CV_W, self.CV_H
        self._draw_video_bg(cv, W, H)
        cs = self.settings["chapter"]
        sample = self._ch_sample()
        fam = self.ch_font.get() if hasattr(self, "ch_font") else "기본 폰트"
        if not fam or fam == "기본 폰트":
            fam = "맑은 고딕"
        fs = self.ch_size.get()
        pt = max(6, min(30, round(fs / 5.4 * 11)))
        font = (fam, pt, "bold")

        px = W / 2 + (self.ch_x.get() / 100.0) * W / 2
        py = H / 2 - (self.ch_y.get() / 100.0) * H / 2
        anchor = "w" if self.ch_align.get() else "center"
        tmp = cv.create_text(px, py, text=sample, font=font, anchor=anchor)
        x0, y0, x1, y1 = cv.bbox(tmp)
        cv.delete(tmp)
        if self.ch_bg_use.get():
            a = self.ch_bg_alpha.get() / 100.0
            fill = self._blend(cs.get("background_color", "#000000"), "#5a5e66", a)
            pad = 7
            cv.create_rectangle(x0 - pad, y0 - pad * 0.6, x1 + pad, y1 + pad * 0.6,
                                fill=fill, outline="")
        bw = self.ch_border.get()
        if bw > 0:
            off = max(1, round(bw / 20 * 3))
            bc = cs.get("border_color", "#000000")
            for dx, dy in ((-off, 0), (off, 0), (0, -off), (0, off),
                           (-off, -off), (off, off), (-off, off), (off, -off)):
                cv.create_text(px + dx, py + dy, text=sample, font=font,
                               anchor=anchor, fill=bc)
        cv.create_text(px, py, text=sample, font=font, anchor=anchor,
                       fill=cs.get("text_color", "#ffffff"))

        n = len(self.chapters)
        info = ("챕터 " + str(n) + "개 · 시작할 때마다 "
                + str(round(self.ch_hold.get(), 1)) + "초 표시"
                if n else "챕터 목록 txt 를 선택해 주세요")
        cv.create_rectangle(0, H - 18, W, H, fill="#1a1b20", outline="")
        cv.create_text(6, H - 9, anchor="w", font=("맑은 고딕", 8, "bold"),
                       fill="#8fd18f" if n else "#f0c05a", text=info)

    # ── 실행 ────────────────────────────────────────────────────

    def collect_opts(self):
        free_only = self.free_only.get()

        def pick(kind):
            out = []
            for it in self.catalog.get(kind, []):
                if not it.get("enabled"):
                    continue
                if free_only and it.get("paid"):
                    continue
                out.append(it)
            return out

        opts = {
            "snap_mode": self.snap_var.get(),
            "effect_mode": self.fx_mode.get(),
            "transitions": pick("transitions"),
            "filters": pick("filters"),
            "video_effects": pick("video_effects"),
            "logo": None,
            "subtitle": None,
            "chapters": None,
        }
        lg = self.settings["logo"]
        if self.logo_use.get():
            if not lg.get("path") or not os.path.exists(lg["path"]):
                raise RuntimeError("로고 이미지를 선택해 주세요. ([로고] 탭)")
            opts["logo"] = {"path": lg["path"],
                            "x": self.logo_x.get() / 100.0,
                            "y": self.logo_y.get() / 100.0,
                            "size": self.logo_size.get() / 100.0}
        if self.sub_use.get():
            st = self.settings["subtitle"]
            pos_on = self.sub_pos_use.get()
            opts["subtitle"] = {
                "text_color": st.get("text_color", "#ffffff"),
                "use_background": self.sub_bg_use.get(),
                "background_color": st.get("background_color", "#000000"),
                "background_alpha": round(self.sub_bg_alpha.get() / 100.0, 2),
                "border_color": st.get("border_color", "#000000"),
                "border_width": round(self.sub_border.get() / 100.0, 3),
                "bg_size": round(self.sub_bg_size.get() / 100.0 * 0.6, 3),
                "pos_x": round(self.sub_x.get() / 100.0, 3) if pos_on else None,
                "pos_y": round(self.sub_y.get() / 100.0, 3) if pos_on else None,
            }
            sel = self.sub_font.get()
            if sel != "원본 유지" and sel in self.fonts:
                opts["subtitle"]["font_name"] = sel
                opts["subtitle"]["font_path"] = self.fonts[sel]
            fs = self.sub_size.get()
            if fs >= 1:
                opts["subtitle"]["font_size"] = round(fs, 1)
        if self.ch_use.get():
            if not self.chapters:
                raise RuntimeError("챕터 목록 txt를 선택해 주세요. ([챕터] 탭)")
            cs = self.settings["chapter"]
            opts["chapters"] = {
                "items": self.chapters,
                "hold": round(self.ch_hold.get(), 1),
                "x": round(self.ch_x.get() / 100.0, 3),
                "y": round(self.ch_y.get() / 100.0, 3),
                "align_left": self.ch_align.get(),
                "font_size": round(self.ch_size.get(), 1),
                "text_color": cs.get("text_color", "#ffffff"),
                "use_background": self.ch_bg_use.get(),
                "background_color": cs.get("background_color", "#000000"),
                "background_alpha": round(self.ch_bg_alpha.get() / 100.0, 2),
                "border_color": cs.get("border_color", "#000000"),
                "border_width": round(self.ch_border.get() / 100.0, 3),
            }
            sel = self.ch_font.get()
            if sel != "기본 폰트" and sel in self.fonts:
                opts["chapters"]["font_name"] = sel
                opts["chapters"]["font_path"] = self.fonts[sel]
        return opts

    def persist(self):
        self.settings["snap_mode"] = self.snap_var.get()
        self.settings["free_only"] = self.free_only.get()
        self.settings["effect_mode"] = self.fx_mode.get()
        lg = self.settings["logo"]
        lg["use"] = self.logo_use.get()
        lg["preset"] = self.logo_preset.get()
        lg["x"] = round(self.logo_x.get() / 100.0, 3)
        lg["y"] = round(self.logo_y.get() / 100.0, 3)
        lg["size"] = round(self.logo_size.get(), 1)
        st = self.settings["subtitle"]
        st["use"] = self.sub_use.get()
        st["use_background"] = self.sub_bg_use.get()
        st["background_alpha"] = round(self.sub_bg_alpha.get(), 0)
        st["border_width"] = round(self.sub_border.get(), 1)
        st["bg_size"] = round(self.sub_bg_size.get(), 0)
        st["pos_use"] = self.sub_pos_use.get()
        st["pos_preset"] = self.sub_pos_preset.get()
        st["pos_x"] = round(self.sub_x.get(), 1)
        st["pos_y"] = round(self.sub_y.get(), 1)
        st["font_size"] = round(self.sub_size.get(), 1)
        sel = self.sub_font.get()
        st["font_name"] = sel if sel != "원본 유지" else ""
        st["font_path"] = self.fonts.get(sel, "") if sel != "원본 유지" else ""
        cs = self.settings["chapter"]
        cs["use"] = self.ch_use.get()
        cs["preset"] = self.ch_preset.get()
        cs["align_left"] = self.ch_align.get()
        cs["x"] = round(self.ch_x.get(), 1)
        cs["y"] = round(self.ch_y.get(), 1)
        cs["hold"] = round(self.ch_hold.get(), 1)
        cs["font_size"] = round(self.ch_size.get(), 1)
        cs["use_background"] = self.ch_bg_use.get()
        cs["background_alpha"] = round(self.ch_bg_alpha.get(), 0)
        cs["border_width"] = round(self.ch_border.get(), 1)
        csel = self.ch_font.get()
        cs["font_name"] = csel if csel != "기본 폰트" else ""
        cs["font_path"] = self.fonts.get(csel, "") if csel != "기본 폰트" else ""
        save_json(SETTINGS_FILE, self.settings)
        save_json(CATALOG_FILE, self.catalog)

    def start(self):
        if not self.zip_path:
            return
        try:
            opts = self.collect_opts()
        except RuntimeError as e:
            messagebox.showwarning("확인", str(e))
            return
        self.persist()
        self.run_btn.config(state="disabled")
        self.status.config(text="처리 중... (파일이 크면 1~2분 걸려요)")
        threading.Thread(target=self._work, args=(opts,), daemon=True).start()

    def _work(self, opts):
        def cb(cur, total):
            pct = int(cur * 100 / max(total, 1))
            self.after(0, lambda: self.progress.config(value=pct))

        try:
            out, stats = core.process(self.zip_path, opts, progress=cb)
        except Exception as e:
            self.after(0, lambda e=e: self.fail(e))
            return
        self.after(0, lambda: self.done(out, stats))

    def done(self, out, stats):
        self.run_btn.config(state="normal")
        self.progress.config(value=100)
        snaps = stats.get("snap_times", [])
        msg = ["완료! " + str(stats.get("scenes", 0)) + "개 씬에 효과를 넣었어요."]
        msg.append("전환 " + str(stats.get("transitions", 0)) + "개 · 휙 컷 " +
                     str(len(snaps)) + "번" + (" (" + ", ".join(
                       str(int(t // 60)) + "분 " + str(int(t % 60)) + "초"
                       for t in snaps) + ")" if snaps else ""))
        if stats.get("global_fx"):
            msg.append("전체 적용: " + ", ".join(stats["global_fx"]))
        if stats.get("logo"):
            msg.append("로고 삽입 완료")
        if stats.get("subtitles"):
            msg.append("자막 " + str(stats["subtitles"]) + "개 스타일 변경")
        else:
            msg.append("자막: 원본 그대로")
        if stats.get("chapters"):
            msg.append("챕터 제목 " + str(stats["chapters"]) + "개 표시")
        msg.append("\n새 파일: " + out)
        self.status.config(text=" · ".join(msg[:2]))
        messagebox.showinfo("완료!", "\n".join(msg))
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(out)])
        except Exception:
            pass

    def fail(self, e):
        self.run_btn.config(state="normal")
        self.status.config(text="오류: " + str(e))
        messagebox.showerror("오류", str(e))


if __name__ == "__main__":
    App().mainloop()
