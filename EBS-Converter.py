import os
import sys
import json
import subprocess
import threading
import concurrent.futures
import queue
import tkinter as tk
from tkinter import filedialog, messagebox
from ttkbootstrap import Style
from ttkbootstrap.widgets import Button, Progressbar, Label, Frame, Entry, Combobox, Checkbutton
from tkinter import Text

# Drag & Drop opsiyonel (tkinterdnd2 varsa aktif olacak)
HAS_DND = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # pip install tkinterdnd2
    HAS_DND = True
except Exception:
    HAS_DND = False

APP_TITLE = "🎵 Evrensel MP3 Dönüştürücü Pro"
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".mp3_converter_pro.json")
SUPPORTED = (".mp4",".avi",".mov",".mkv",".flv",".webm",
             ".wav",".aac",".m4a",".ogg",".flac",".wma",".mp3",".3gp")

def which(prog):
    exts = [""] if os.name != "nt" else [".exe", ".bat", ".cmd", ""]
    paths = os.environ.get("PATH","").split(os.pathsep)
    for p in paths:
        for e in exts:
            cand = os.path.join(p, prog + e)
            if os.path.isfile(cand):
                return cand
    return None

def ffprobe_duration(path):
    try:
        cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", path]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
        return float(out.strip())
    except Exception:
        return None

class MP3ConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x700")
        self.style = Style(theme="darkly")

        self.files = []
        self.stop_flag = False

        # --- ÖNCE settings ve UI kuyruğu (ensure_ffmpeg içinde log_write çağrılabilir) ---
        self.settings = self.load_settings()
        self.ui_queue = queue.Queue()

        # === Başlık
        Label(root, text="🎧 Tüm Formatları MP3'e Dönüştür – Pro", font=("Segoe UI", 16, "bold")).pack(pady=10)

        # === Üst kontrol
        top = Frame(root)
        top.pack(fill="x", padx=12)
        Button(top, text="📂 Dosya Ekle", bootstyle="primary", command=self.select_files).pack(side="left", padx=5, pady=5)
        Button(top, text="🗃️ Klasör Ekle", bootstyle="secondary", command=self.select_folder).pack(side="left", padx=5, pady=5)
        Button(top, text="🧹 Temizle", bootstyle="danger", command=self.clear_files).pack(side="left", padx=5, pady=5)

        # === Çıktı klasörü & şablon
        out_fr = Frame(root)
        out_fr.pack(fill="x", padx=12, pady=6)
        Label(out_fr, text="Çıktı Klasörü:").pack(side="left", padx=(0,6))
        self.output_dir_var = tk.StringVar(master=self.root, value=self.settings.get("output_dir",""))
        Entry(out_fr, textvariable=self.output_dir_var, width=50).pack(side="left", padx=5)
        Button(out_fr, text="Seç", command=self.choose_output_dir).pack(side="left", padx=5)

        Label(out_fr, text="İsim Şablonu:").pack(side="left", padx=(15,6))
        self.name_tpl_var = tk.StringVar(master=self.root, value=self.settings.get("name_tpl","{name}.mp3"))
        Entry(out_fr, textvariable=self.name_tpl_var, width=25).pack(side="left", padx=5)
        # {name}, {bitrate}, {mode} kullanılabilir

        # === Kodlama seçenekleri
        opt = Frame(root)
        opt.pack(fill="x", padx=12, pady=6)

        Label(opt, text="Mod:").pack(side="left")
        self.mode_var = tk.StringVar(master=self.root, value=self.settings.get("mode","CBR"))
        Combobox(opt, values=["CBR","VBR"], textvariable=self.mode_var, width=6, state="readonly").pack(side="left", padx=5)

        Label(opt, text="Bitrate/Quality:").pack(side="left", padx=(10,0))
        self.rate_var = tk.StringVar(master=self.root, value=self.settings.get("rate","192"))
        Combobox(opt, values=["128","160","192","256","320","q0","q2","q4","q5","q7","q9"], textvariable=self.rate_var, width=6, state="readonly").pack(side="left", padx=5)

        Label(opt, text="Sample Rate:").pack(side="left", padx=(10,0))
        self.sr_var = tk.StringVar(master=self.root, value=self.settings.get("sample_rate","44100"))
        Combobox(opt, values=["32000","44100","48000"], textvariable=self.sr_var, width=7, state="readonly").pack(side="left", padx=5)

        self.loudnorm_var = tk.BooleanVar(master=self.root, value=bool(self.settings.get("loudnorm", False)))
        Checkbutton(opt, text="Loudness Normalize (EBU R128)", variable=self.loudnorm_var, bootstyle="success").pack(side="left", padx=15)

        # === Yeni: Sessizlik kırpma & Fade
        self.trim_silence = tk.BooleanVar(master=self.root, value=bool(self.settings.get("trim_silence", False)))
        Checkbutton(opt, text="Baş/Son Sessizliği Kırp", variable=self.trim_silence).pack(side="left", padx=10)
        self.fade_in_out  = tk.BooleanVar(master=self.root, value=bool(self.settings.get("fade_in_out", False)))
        Checkbutton(opt, text="Fade In/Out", variable=self.fade_in_out).pack(side="left", padx=10)

        # === Yeni: Paralel iş sayısı (Hızlandırma)
        speed_fr = Frame(root)
        speed_fr.pack(fill="x", padx=12, pady=(0,6))
        Label(speed_fr, text="Eşzamanlı İş (Hızlandırma):").pack(side="left")
        import multiprocessing
        max_workers_default = max(1, min(4, multiprocessing.cpu_count()))
        self.workers_var = tk.IntVar(master=self.root, value=int(self.settings.get("workers", max_workers_default)))
        self.workers_spin = tk.Spinbox(speed_fr, from_=1, to=max(1, multiprocessing.cpu_count()), width=5, textvariable=self.workers_var)
        self.workers_spin.pack(side="left", padx=6)
        Label(speed_fr, text=f"(Önerilen: {max_workers_default})").pack(side="left")

        # === Meta veri
        meta = Frame(root)
        meta.pack(fill="x", padx=12, pady=6)
        Label(meta, text="Başlık:").pack(side="left")
        self.meta_title = tk.StringVar(master=self.root)
        Entry(meta, textvariable=self.meta_title, width=24).pack(side="left", padx=5)

        Label(meta, text="Sanatçı:").pack(side="left")
        self.meta_artist = tk.StringVar(master=self.root)
        Entry(meta, textvariable=self.meta_artist, width=24).pack(side="left", padx=5)

        Label(meta, text="Albüm:").pack(side="left")
        self.meta_album = tk.StringVar(master=self.root)
        Entry(meta, textvariable=self.meta_album, width=24).pack(side="left", padx=5)

        cover = Frame(root)
        cover.pack(fill="x", padx=12, pady=6)
        Label(cover, text="Kapak Görseli (JPG/PNG):").pack(side="left")
        self.cover_path = tk.StringVar(master=self.root)
        Entry(cover, textvariable=self.cover_path, width=50).pack(side="left", padx=5)
        Button(cover, text="Seç", command=self.choose_cover).pack(side="left", padx=5)

        # === Var olan dosya politikası
        pol = Frame(root)
        pol.pack(fill="x", padx=12, pady=6)
        Label(pol, text="Çakışma:").pack(side="left")
        self.collision_var = tk.StringVar(master=self.root, value=self.settings.get("collision","Atla"))
        Combobox(pol, values=["Atla","Yeniden Yaz","Numaralandır"], textvariable=self.collision_var, width=14, state="readonly").pack(side="left", padx=5)

        # === Orta alan: Liste & Log
        mid = Frame(root)
        mid.pack(fill="both", expand=True, padx=12, pady=6)
        left = Frame(mid); left.pack(side="left", fill="both", expand=True)
        right = Frame(mid); right.pack(side="left", fill="both", expand=True, padx=(8,0))

        Label(left, text="Sıradaki Dosyalar").pack(anchor="w")
        self.file_listbox = tk.Listbox(left, height=12, selectmode=tk.SINGLE, bg="#222", fg="white", font=("Consolas", 10))
        self.file_listbox.pack(fill="both", expand=True)

        # Sağ tık menüsü
        self.ctx = tk.Menu(self.root, tearoff=0)
        self.ctx.add_command(label="Klasörde Aç", command=self.open_in_explorer)
        self.ctx.add_command(label="Listeden Kaldır", command=self.remove_selected)
        self.file_listbox.bind("<Button-3>", self.open_context_menu)

        # Drag & Drop (varsa)
        if HAS_DND:
            try:
                self.file_listbox.drop_target_register(DND_FILES)
                self.file_listbox.dnd_bind("<<Drop>>", self.on_drop_files)
            except Exception:
                pass

        Label(right, text="Konsol / Log").pack(anchor="w")
        self.log = Text(right, height=12, bg="#111", fg="#ddd", insertbackground="#ddd")
        self.log.pack(fill="both", expand=True)

        # === Alt kontrol
        bottom = Frame(root)
        bottom.pack(fill="x", padx=12, pady=6)
        self.status_label = Label(bottom, text="Hazır"); self.status_label.pack(side="left")
        Button(bottom, text="📝 Log’u Kaydet", command=self.save_log).pack(side="right", padx=5)
        Button(bottom, text="🚀 Dönüştür", bootstyle="success", command=self.start_conversion).pack(side="right", padx=5)
        Button(bottom, text="⛔ Durdur", bootstyle="danger", command=self.stop_conversion).pack(side="right", padx=5)

        self.progress = Progressbar(root, bootstyle="info-striped", mode="determinate")
        self.progress.pack(fill="x", padx=12, pady=(0,10))

        # UI kuyruğunu tüket
        self.root.after(100, self._drain_ui_queue)

        # FFmpeg kontrolü
        self.ensure_ffmpeg()

        # Başlangıç ayarları
        if self.settings.get("last_files"):
            for f in self.settings["last_files"]:
                if os.path.exists(f):
                    self.files.append(f)
                    self.file_listbox.insert(tk.END, os.path.basename(f))

        if not HAS_DND:
            self.log_write("Bilgi: Drag&Drop için 'pip install tkinterdnd2' yükleyebilirsiniz (opsiyonel).")

    # ---------- Yardımcılar ----------
    def log_write(self, text):
        if hasattr(self, "ui_queue") and self.ui_queue is not None:
            self.ui_queue.put(("log", text))
        else:
            print(text)

    def _drain_ui_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self.log.insert(tk.END, payload + "\n")
                    self.log.see(tk.END)
                elif kind == "status":
                    self.status_label.config(text=payload)
                elif kind == "progress_max":
                    self.progress["maximum"] = payload
                    self.progress["value"] = 0
                elif kind == "progress_inc":
                    self.progress["value"] += payload
        except queue.Empty:
            pass
        self.root.after(100, self._drain_ui_queue)

    def ensure_ffmpeg(self):
        local_dir = os.path.dirname(sys.argv[0])
        ffmpeg_local = os.path.join(local_dir, "ffmpeg.exe")
        ffprobe_local = os.path.join(local_dir, "ffprobe.exe")
        ok1 = os.path.isfile(ffmpeg_local) or which("ffmpeg") is not None
        ok2 = os.path.isfile(ffprobe_local) or which("ffprobe") is not None
        if not (ok1 and ok2):
            messagebox.showwarning("FFmpeg Bulunamadı", "ffmpeg/ffprobe PATH'te veya aynı klasörde görünmüyor. Lütfen kontrol edin.")
        else:
            self.log_write(f"ffmpeg: {'Yerel' if os.path.isfile(ffmpeg_local) else 'PATH'} | ffprobe: {'Yerel' if os.path.isfile(ffprobe_local) else 'PATH'}")

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE,"r",encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_settings(self):
        self.settings["output_dir"] = self.output_dir_var.get()
        self.settings["name_tpl"] = self.name_tpl_var.get()
        self.settings["mode"] = self.mode_var.get()
        self.settings["rate"] = self.rate_var.get()
        self.settings["sample_rate"] = self.sr_var.get()
        self.settings["loudnorm"] = self.loudnorm_var.get()
        self.settings["collision"] = self.collision_var.get()
        self.settings["last_files"] = self.files
        self.settings["trim_silence"] = self.trim_silence.get()
        self.settings["fade_in_out"] = self.fade_in_out.get()
        self.settings["workers"] = int(self.workers_var.get())
        try:
            with open(SETTINGS_FILE,"w",encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def choose_output_dir(self):
        d = filedialog.askdirectory(title="Çıktı klasörü")
        if d:
            self.output_dir_var.set(d)

    def choose_cover(self):
        f = filedialog.askopenfilename(title="Kapak görseli seç", filetypes=[("Images","*.jpg *.jpeg *.png")])
        if f:
            self.cover_path.set(f)

    def select_files(self):
        filetypes = [("Video & Ses"," ".join("*"+ext for ext in SUPPORTED)), ("Tüm Dosyalar","*.*")]
        files = filedialog.askopenfilenames(title="Dönüştürülecek dosyaları seç", filetypes=filetypes)
        if files:
            added = 0
            for f in files:
                if f not in self.files:
                    self.files.append(f)
                    self.file_listbox.insert(tk.END, os.path.basename(f))
                    added += 1
            self.status_label.config(text=f"{added} dosya eklendi. Toplam: {len(self.files)}")
            self.save_settings()

    def select_folder(self):
        d = filedialog.askdirectory(title="Klasör seç (tüm alt klasörler taranır)")
        if not d:
            return
        count = 0
        for root_, _, files in os.walk(d):
            for name in files:
                if os.path.splitext(name)[1].lower() in SUPPORTED:
                    path = os.path.join(root_, name)
                    if path not in self.files:
                        self.files.append(path)
                        self.file_listbox.insert(tk.END, os.path.basename(path))
                        count += 1
        self.status_label.config(text=f"{count} dosya eklendi. Toplam: {len(self.files)}")
        self.save_settings()

    def clear_files(self):
        self.files.clear()
        self.file_listbox.delete(0, tk.END)
        self.status_label.config(text="Dosya listesi temizlendi.")
        self.save_settings()

    def stop_conversion(self):
        self.stop_flag = True
        self.status_label.config(text="Durdurma isteği gönderildi…")
        self.log_write("Kullanıcı: Durdur isteği.")

    def open_context_menu(self, e):
        try:
            self.file_listbox.selection_clear(0, tk.END)
            idx = self.file_listbox.nearest(e.y)
            self.file_listbox.selection_set(idx)
            self.ctx.tk_popup(e.x_root, e.y_root)
        finally:
            self.ctx.grab_release()

    def open_in_explorer(self):
        idx = self.file_listbox.curselection()
        if not idx: return
        path = self.files[idx[0]]
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open","-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    def remove_selected(self):
        idx = self.file_listbox.curselection()
        if not idx: return
        self.file_listbox.delete(idx[0]); self.files.pop(idx[0]); self.save_settings()

    def on_drop_files(self, event):
        try:
            paths = self.root.splitlist(event.data)
        except Exception:
            paths = str(event.data).strip().split()
        added=0
        for p in paths:
            if os.path.isdir(p):
                for r,_,fs in os.walk(p):
                    for n in fs:
                        if os.path.splitext(n)[1].lower() in SUPPORTED:
                            full=os.path.join(r,n)
                            if full not in self.files:
                                self.files.append(full); self.file_listbox.insert(tk.END, os.path.basename(full)); added+=1
            else:
                if os.path.splitext(p)[1].lower() in SUPPORTED and p not in self.files:
                    self.files.append(p); self.file_listbox.insert(tk.END, os.path.basename(p)); added+=1
        self.status_label.config(text=f"{added} öğe eklendi. Toplam: {len(self.files)}"); self.save_settings()

    # ---------- Dönüştürme ----------
    def start_conversion(self):
        if not self.files:
            messagebox.showwarning("Uyarı", "Lütfen en az bir dosya seçin.")
            return
        outdir = self.output_dir_var.get().strip()
        if not outdir:
            messagebox.showwarning("Uyarı", "Lütfen bir çıktı klasörü seçin.")
            return
        if not os.path.isdir(outdir):
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Hata", f"Çıktı klasörü oluşturulamadı:\n{e}")
                return
        self.stop_flag = False
        self.ui_queue.put(("progress_max", len(self.files)))
        self.ui_queue.put(("status", "Dönüştürme başladı…"))
        self.log_write("=== DÖNÜŞTÜRME BAŞLADI ===")

        threading.Thread(target=self._convert_parallel, daemon=True).start()

    def _convert_parallel(self):
        total = len(self.files)
        workers = max(1, int(self.settings.get("workers", self.workers_var.get())))

        def work(idx, infile):
            if self.stop_flag:
                return False
            try:
                base_out = self.make_output_path(infile)
                outpath = self.unique_or_policy(base_out)
                if outpath is None:
                    self.log_write(f"Atlandı (mevcut): {base_out}")
                    return True

                dur = ffprobe_duration(infile)

                if os.path.splitext(infile)[1].lower() == ".mp3":
                    cmd = ["ffmpeg","-y","-i", infile, "-c:a", "copy", "-vn", outpath]
                    self.log_write(f"[{idx}/{total}] Kopyala (MP3): {os.path.basename(infile)} -> {os.path.basename(outpath)}")
                else:
                    cmd = self.build_cmd(infile, outpath, duration=dur)
                    self.log_write(f"[{idx}/{total}] Kodla: {os.path.basename(infile)} -> {os.path.basename(outpath)}")

                if dur:
                    mins = int(dur // 60); secs = int(dur % 60)
                    self.log_write(f"  Süre: ~{mins}m{secs}s")

                self.log_write("  Komut: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if proc.returncode != 0:
                    self.log_write("  HATA: " + (proc.stderr[-4000:] if proc.stderr else "Bilinmeyen hata"))
                    return False
                else:
                    self.log_write("  ✔ Tamamlandı")
                    return True
            except Exception as e:
                self.log_write(f"  İstisna: {e}")
                return False

        ok = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(work, i, f) for i, f in enumerate(self.files, start=1)]
            for fut in concurrent.futures.as_completed(futures):
                if self.stop_flag:
                    break
                res = fut.result()
                ok += 1 if res else 0
                self.ui_queue.put(("progress_inc", 1))
                self.ui_queue.put(("status", f"{ok}/{total} tamamlandı"))

        if not self.stop_flag:
            self.ui_queue.put(("status", f"✅ Tamamlandı: {ok}/{total}"))
            self.log_write("=== DÖNÜŞTÜRME BİTTİ ===")
            try:
                self.root.after(0, lambda: messagebox.showinfo("Bitti", "Tüm uygun dosyalar işlendi."))
            except Exception:
                pass
        else:
            self.ui_queue.put(("status", f"⛔ Durduruldu: {ok}/{total} tamamlandı"))
        self.save_settings()

    def build_cmd(self, infile, outfile, duration=None):
        # Mode & rate
        mode = self.mode_var.get()
        rate = self.rate_var.get()
        sr = self.sr_var.get()

        cmd = ["ffmpeg", "-y", "-i", infile, "-vn"]  # video yok

        # Filtre zinciri
        afilters = []
        if self.loudnorm_var.get():
            afilters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if self.trim_silence.get():
            afilters.append("silenceremove=start_periods=1:start_silence=0.20:start_threshold=-35dB:stop_periods=1:stop_silence=0.40:stop_threshold=-35dB")
        if self.fade_in_out.get():
            if duration and duration > 1.8:
                start_out = max(0.0, duration - 0.8)
                afilters.append(f"afade=t=in:ss=0:d=0.7,afade=t=out:st={start_out:.3f}:d=0.8")
            else:
                afilters.append("afade=t=in:ss=0:d=0.5")

        if afilters:
            cmd += ["-af", ",".join(afilters)]

        # libmp3lame ayarları
        if mode == "CBR":
            if rate.startswith("q"):
                rate = "192"
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{rate}k"]
        else:
            q = 4
            if rate.startswith("q"):
                try:
                    q = int(rate[1:])
                except:
                    q = 4
            cmd += ["-c:a", "libmp3lame", "-q:a", str(q)]

        if sr:
            cmd += ["-ar", sr]

        # Meta veriler
        if self.meta_title.get().strip():
            cmd += ["-metadata", f"title={self.meta_title.get().strip()}"]
        if self.meta_artist.get().strip():
            cmd += ["-metadata", f"artist={self.meta_artist.get().strip()}"]
        if self.meta_album.get().strip():
            cmd += ["-metadata", f"album={self.meta_album.get().strip()}"]

        # Kapak (stabil attached_pic)
        cover = self.cover_path.get().strip()
        if cover and os.path.isfile(cover):
            mode_local = self.mode_var.get()
            rate_local = self.rate_var.get()
            sr_local = self.sr_var.get()

            cmd = ["ffmpeg","-y","-i", infile, "-i", cover, "-map","0:a","-map","1:v:0"]
            if afilters:
                cmd += ["-af", ",".join(afilters)]
            if mode_local == "CBR":
                r = rate_local if rate_local.isdigit() else "192"
                cmd += ["-c:a","libmp3lame","-b:a", f"{r}k"]
            else:
                q = 4
                if rate_local.startswith("q"):
                    try: q = int(rate_local[1:])
                    except: q = 4
                cmd += ["-c:a","libmp3lame","-q:a", str(q)]
            if sr_local:
                cmd += ["-ar", sr_local]

            cmd += ["-id3v2_version","3","-c:v","mjpeg","-disposition:v:0","attached_pic",
                    "-metadata:s:v","title=Album cover","-metadata:s:v","comment=Cover (front)", outfile]
            return cmd

        cmd += [outfile]
        return cmd

    def unique_or_policy(self, base_out):
        policy = self.collision_var.get()
        if not os.path.exists(base_out):
            return base_out
        if policy == "Yeniden Yaz":
            return base_out
        elif policy == "Atla":
            return None
        else:
            root, ext = os.path.splitext(base_out)
            i = 2
            while True:
                cand = f"{root} ({i}){ext}"
                if not os.path.exists(cand):
                    return cand
                i += 1

    def make_output_path(self, infile):
        outdir = self.output_dir_var.get().strip()
        name = os.path.splitext(os.path.basename(infile))[0]
        mode = self.mode_var.get()
        rate = self.rate_var.get().replace("q","q")
        tpl = self.name_tpl_var.get().strip() or "{name}.mp3"
        fname = tpl.format(name=name, bitrate=rate if rate.isdigit() else rate, mode=mode)

        # Windows yasak karakter temizliği
        for bad in '<>:"/\\|?*':
            fname = fname.replace(bad, "_")

        if not fname.lower().endswith(".mp3"):
            fname += ".mp3"
        return os.path.join(outdir, fname)

    def save_log(self):
        f = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text",".txt")])
        if not f: return
        with open(f,"w",encoding="utf-8") as fp:
            fp.write(self.log.get("1.0", tk.END))
        messagebox.showinfo("Kaydedildi","Log dışa aktarıldı.")

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = MP3ConverterApp(root)
    root.mainloop()
