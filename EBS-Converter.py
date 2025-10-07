import os
import sys
import json
import glob
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from ttkbootstrap import Style
from ttkbootstrap.widgets import Button, Progressbar, Label, Frame, Entry, Combobox, Checkbutton
from tkinter import Text


APP_TITLE = "🎵 Evrensel MP3 Dönüştürücü Pro"
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".mp3_converter_pro.json")
SUPPORTED = (".mp4",".avi",".mov",".mkv",".flv",".webm",
             ".wav",".aac",".m4a",".ogg",".flac",".wma",".mp3",".3gp")

def which(prog):
    # Windows'ta ffmpeg.exe/ffprobe.exe PATH'te mi?
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
        self.root.geometry("900x640")
        self.style = Style(theme="darkly")

        self.files = []
        self.stop_flag = False
        self.settings = self.load_settings()

        # Üst başlık
        Label(root, text="🎧 Tüm Formatları MP3'e Dönüştür – Pro", font=("Segoe UI", 16, "bold")).pack(pady=10)

        # Üst kontrol satırı
        top = Frame(root)
        top.pack(fill="x", padx=12)

        Button(top, text="📂 Dosya Ekle", bootstyle="primary", command=self.select_files).pack(side="left", padx=5, pady=5)
        Button(top, text="🗃️ Klasör Ekle", bootstyle="secondary", command=self.select_folder).pack(side="left", padx=5, pady=5)
        Button(top, text="🧹 Temizle", bootstyle="danger", command=self.clear_files).pack(side="left", padx=5, pady=5)

        # Çıktı klasörü & şablon
        out_fr = Frame(root)
        out_fr.pack(fill="x", padx=12, pady=6)
        Label(out_fr, text="Çıktı Klasörü:").pack(side="left", padx=(0,6))
        self.output_dir_var = tk.StringVar(value=self.settings.get("output_dir",""))
        Entry(out_fr, textvariable=self.output_dir_var, width=50).pack(side="left", padx=5)
        Button(out_fr, text="Seç", command=self.choose_output_dir).pack(side="left", padx=5)

        Label(out_fr, text="İsim Şablonu:").pack(side="left", padx=(15,6))
        self.name_tpl_var = tk.StringVar(value=self.settings.get("name_tpl","{name}.mp3"))
        Entry(out_fr, textvariable=self.name_tpl_var, width=25).pack(side="left", padx=5)
        # {name}, {bitrate}, {mode} kullanılabilir

        # Kodlama seçenekleri
        opt = Frame(root)
        opt.pack(fill="x", padx=12, pady=6)

        Label(opt, text="Mod:").pack(side="left")
        self.mode_var = tk.StringVar(value=self.settings.get("mode","CBR"))
        Combobox(opt, values=["CBR","VBR"], textvariable=self.mode_var, width=6, state="readonly").pack(side="left", padx=5)

        Label(opt, text="Bitrate/Quality:").pack(side="left", padx=(10,0))
        # CBR'de kbps (128/192/256/320), VBR'de q (0-9)
        self.rate_var = tk.StringVar(value=self.settings.get("rate","192"))
        Combobox(opt, values=["128","160","192","256","320","q0","q2","q4","q5","q7","q9"], textvariable=self.rate_var, width=6, state="readonly").pack(side="left", padx=5)

        Label(opt, text="Sample Rate:").pack(side="left", padx=(10,0))
        self.sr_var = tk.StringVar(value=self.settings.get("sample_rate","44100"))
        Combobox(opt, values=["32000","44100","48000"], textvariable=self.sr_var, width=7, state="readonly").pack(side="left", padx=5)

        self.loudnorm_var = tk.BooleanVar(value=self.settings.get("loudnorm", False))
        Checkbutton(opt, text="Loudness Normalize (EBU R128)", variable=self.loudnorm_var, bootstyle="success").pack(side="left", padx=15)

        # Meta veri
        meta = Frame(root)
        meta.pack(fill="x", padx=12, pady=6)
        Label(meta, text="Başlık:").pack(side="left")
        self.meta_title = tk.StringVar()
        Entry(meta, textvariable=self.meta_title, width=24).pack(side="left", padx=5)

        Label(meta, text="Sanatçı:").pack(side="left")
        self.meta_artist = tk.StringVar()
        Entry(meta, textvariable=self.meta_artist, width=24).pack(side="left", padx=5)

        Label(meta, text="Albüm:").pack(side="left")
        self.meta_album = tk.StringVar()
        Entry(meta, textvariable=self.meta_album, width=24).pack(side="left", padx=5)

        cover = Frame(root)
        cover.pack(fill="x", padx=12, pady=6)
        Label(cover, text="Kapak Görseli (JPG/PNG):").pack(side="left")
        self.cover_path = tk.StringVar()
        Entry(cover, textvariable=self.cover_path, width=50).pack(side="left", padx=5)
        Button(cover, text="Seç", command=self.choose_cover).pack(side="left", padx=5)

        # Var olan dosya politikası
        pol = Frame(root)
        pol.pack(fill="x", padx=12, pady=6)
        Label(pol, text="Çakışma:").pack(side="left")
        self.collision_var = tk.StringVar(value=self.settings.get("collision","Atla"))
        Combobox(pol, values=["Atla","Yeniden Yaz","Numaralandır"], textvariable=self.collision_var, width=14, state="readonly").pack(side="left", padx=5)

        # Liste & Konsol
        mid = Frame(root)
        mid.pack(fill="both", expand=True, padx=12, pady=6)
        left = Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        right = Frame(mid)
        right.pack(side="left", fill="both", expand=True, padx=(8,0))

        Label(left, text="Sıradaki Dosyalar").pack(anchor="w")
        self.file_listbox = tk.Listbox(left, height=12, selectmode=tk.SINGLE, bg="#222", fg="white", font=("Consolas", 10))
        self.file_listbox.pack(fill="both", expand=True)

        Label(right, text="Konsol / Log").pack(anchor="w")
        self.log = Text(right, height=12, bg="#111", fg="#ddd", insertbackground="#ddd")
        self.log.pack(fill="both", expand=True)

        # Alt kontrol çubuğu
        bottom = Frame(root)
        bottom.pack(fill="x", padx=12, pady=6)
        self.status_label = Label(bottom, text="Hazır")
        self.status_label.pack(side="left")
        Button(bottom, text="🚀 Dönüştür", bootstyle="success", command=self.start_conversion).pack(side="right", padx=5)
        Button(bottom, text="⛔ Durdur", bootstyle="danger", command=self.stop_conversion).pack(side="right", padx=5)

        self.progress = Progressbar(root, bootstyle="info-striped", mode="determinate")
        self.progress.pack(fill="x", padx=12, pady=(0,10))

        # FFmpeg kontrolü
        self.ensure_ffmpeg()

        # Başlangıç ayarları
        if self.settings.get("last_files"):
            for f in self.settings["last_files"]:
                if os.path.exists(f):
                    self.files.append(f)
                    self.file_listbox.insert(tk.END, os.path.basename(f))

    def log_write(self, text):
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def ensure_ffmpeg(self):
        # Önce aynı klasörde kontrol et
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
            for f in files:
                if f not in self.files:
                    self.files.append(f)
                    self.file_listbox.insert(tk.END, os.path.basename(f))
            self.status_label.config(text=f"{len(self.files)} dosya seçildi.")
            self.save_settings()

    def select_folder(self):
        d = filedialog.askdirectory(title="Klasör seç (tüm alt klasörler taranır)")
        if not d:
            return
        count = 0
        for root, _, files in os.walk(d):
            for name in files:
                if os.path.splitext(name)[1].lower() in SUPPORTED:
                    path = os.path.join(root, name)
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
        threading.Thread(target=self.convert_files, daemon=True).start()

    def build_cmd(self, infile, outfile):
        # Mode & rate
        mode = self.mode_var.get()
        rate = self.rate_var.get()
        sr = self.sr_var.get()

        cmd = ["ffmpeg", "-y", "-i", infile, "-vn"]  # video yok

        # loudness normalize
        if self.loudnorm_var.get():
            # Standart loudnorm ayarları – tek geçiş pratik kullanım
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]

        if mode == "CBR":
            # libmp3lame CBR
            if rate.startswith("q"):
                # yanlış seçim olursa fallback
                rate = "192"
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{rate}k"]
        else:
            # VBR (LAME q0..q9) -> -q:a 0 (en yüksek kalite) .. 9
            q = 4
            if rate.startswith("q"):
                try:
                    q = int(rate[1:])
                except:
                    q = 4
            cmd += ["-c:a", "libmp3lame", "-q:a", str(q)]

        # Sample rate
        if sr:
            cmd += ["-ar", sr]

        # Meta veriler
        if self.meta_title.get().strip():
            cmd += ["-metadata", f"title={self.meta_title.get().strip()}"]
        if self.meta_artist.get().strip():
            cmd += ["-metadata", f"artist={self.meta_artist.get().strip()}"]
        if self.meta_album.get().strip():
            cmd += ["-metadata", f"album={self.meta_album.get().strip()}"]

        # Kapak (mümkünse)
        cover = self.cover_path.get().strip()
        if cover and os.path.isfile(cover):
            # mp3'e kapak ekleme (APIC). İkinci input olarak görseli al
            # Not: Bazı ffmpeg sürümlerinde mp3 + cover için -map şart
            cmd = ["ffmpeg", "-y", "-i", infile, "-i", cover, "-map", "0:a", "-map", "1:v",
                   "-c:a"] + cmd[cmd.index("-c:a")+1:cmd.index("-c:a")+3] + \
                  ["-ar", sr, "-id3v2_version", "3", "-metadata:s:v", "title=Album cover",
                   "-metadata:s:v", "comment=Cover (front)", outfile]
            # Yukarıda -c:a ve -ar tekrarlandıysa sorun çıkarma; basit yaklaşım.
            # Alternatif: önce ses stream'i üretip sonra kapak göm.
            return cmd

        cmd += [outfile]
        return cmd

    def unique_or_policy(self, base_out):
        """Çakışma politikasına göre çıktı dosya yolunu belirle"""
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
        rate = self.rate_var.get().replace("q","q")  # zaten uygun
        tpl = self.name_tpl_var.get().strip() or "{name}.mp3"
        fname = tpl.format(name=name, bitrate=rate if rate.isdigit() else rate, mode=mode)
        if not fname.lower().endswith(".mp3"):
            fname += ".mp3"
        return os.path.join(outdir, fname)

    def convert_files(self):
        total = len(self.files)
        self.progress["maximum"] = total
        self.progress["value"] = 0
        self.status_label.config(text="Dönüştürme başladı…")
        self.log_write("=== DÖNÜŞTÜRME BAŞLADI ===")

        done = 0
        for idx, infile in enumerate(self.files, start=1):
            if self.stop_flag:
                self.log_write("⛔ Durduruldu.")
                break
            try:
                # Hedef yol
                base_out = self.make_output_path(infile)
                outpath = self.unique_or_policy(base_out)
                if outpath is None:
                    self.log_write(f"Atlandı (mevcut): {base_out}")
                    self.progress["value"] = idx
                    done += 1
                    continue

                # Zaten mp3 ise ve “yeniden kodlama” istemiyorsan, kopyalama alternatifi (basit)
                if os.path.splitext(infile)[1].lower() == ".mp3":
                    # Re-encode yerine yeniden yaz politikasına göre kopyala
                    cmd = ["ffmpeg","-y","-i", infile, "-c:a", "copy", outpath]
                    self.log_write(f"[{idx}/{total}] Kopyala (MP3): {os.path.basename(infile)} -> {os.path.basename(outpath)}")
                else:
                    cmd = self.build_cmd(infile, outpath)
                    self.log_write(f"[{idx}/{total}] Kodla: {os.path.basename(infile)} -> {os.path.basename(outpath)}")

                # ETA için süre bilgisi
                dur = ffprobe_duration(infile)
                if dur:
                    mins = int(dur // 60); secs = int(dur % 60)
                    self.log_write(f"  Süre: ~{mins}m{secs}s")

                self.log_write("  Komut: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                if proc.returncode != 0:
                    self.log_write("  HATA: " + (proc.stderr[-4000:] if proc.stderr else "Bilinmeyen hata"))
                    messagebox.showerror("Hata", f"{os.path.basename(infile)} başarısız oldu.\nDetay için Konsol'a bakın.")
                else:
                    self.log_write("  ✔ Tamamlandı")

            except Exception as e:
                self.log_write(f"  İstisna: {e}")
                messagebox.showerror("Hata", f"{os.path.basename(infile)} dönüştürülürken hata:\n{e}")

            self.progress["value"] = idx
            self.status_label.config(text=f"{idx}/{total} tamamlandı")
            done += 1

        if not self.stop_flag:
            self.status_label.config(text=f"✅ Tamamlandı: {done}/{total}")
            self.log_write("=== DÖNÜŞTÜRME BİTTİ ===")
            messagebox.showinfo("Bitti", "Tüm uygun dosyalar işlendi.")
        else:
            self.status_label.config(text=f"⛔ Durduruldu: {done}/{total} tamamlandı")
        self.save_settings()

if __name__ == "__main__":
    root = tk.Tk()
    app = MP3ConverterApp(root)
    root.mainloop()
