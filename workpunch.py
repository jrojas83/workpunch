#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkPunch - Monitor Global de Inactividad de Mouse y Teclado para Windows
Autor: Juan Andrés Rojas Herrera (jrojas83)
Descripción:
    Detecta globalmente cuando el usuario lleva más de 5 minutos (o el tiempo
    configurado) sin usar el mouse ni el teclado mediante la API nativa de
    Windows (user32.GetLastInputInfo) y dispara una alerta personalizable:
    - Alarma sonora preconfigurada (Estándar, Urgente, Sirena, Pulso Suave)
    - Archivo de audio personalizado (.wav, .mp3)
    - Archivo de video personalizado (.mp4, .mkv, .avi, .webm)
"""

import ctypes
from ctypes import Structure, windll, c_uint, sizeof, byref
import json
import os
import platform
import subprocess
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

if platform.system() == "Windows":
    import winsound
else:
    winsound = None

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workpunch_config.json")

DEFAULT_CONFIG = {
    "idle_limit_seconds": 300,
    "alert_mode": "preset",
    "preset_name": "Urgente",
    "audio_path": "",
    "video_path": "",
    "repeat_alert_seconds": 60
}


class LASTINPUTINFO(Structure):
    _fields_ = [
        ("cbSize", c_uint),
        ("dwTime", c_uint),
    ]


def get_idle_duration_seconds() -> float:
    if platform.system() == "Windows":
        lastInputInfo = LASTINPUTINFO()
        lastInputInfo.cbSize = sizeof(lastInputInfo)
        if windll.user32.GetLastInputInfo(byref(lastInputInfo)):
            tick_count = windll.kernel32.GetTickCount()
            elapsed_ms = (tick_count - lastInputInfo.dwTime) & 0xFFFFFFFF
            return elapsed_ms / 1000.0
    return 0.0


def play_preset_alarm(preset_name: str, stop_event: threading.Event):
    if not winsound:
        print("\a")
        return

    patterns = {
        "Estándar": [(1000, 400), (800, 400), (1000, 400), (800, 400)],
        "Urgente": [(1500, 200), (1800, 200), (1500, 200), (1800, 200), (2000, 400)],
        "Sirena": [(700, 300), (1200, 300), (700, 300), (1200, 300), (1500, 500)],
        "Pulso Suave": [(600, 500), (900, 500), (600, 500)]
    }
    sequence = patterns.get(preset_name, patterns["Estándar"])

    for freq, duration in sequence:
        if stop_event.is_set():
            break
        try:
            winsound.Beep(freq, duration)
            time.sleep(0.08)
        except RuntimeError:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            break


def play_custom_audio(audio_path: str):
    if not audio_path or not os.path.isfile(audio_path):
        if winsound:
            winsound.MessageBeep(winsound.MB_ICONHAND)
        return

    if platform.system() == "Windows":
        ext = os.path.splitext(audio_path)[1].lower()
        if ext == ".wav" and winsound:
            winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return

        alias = "workpunch_audio"
        windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
        cmd_open = f'open "{os.path.abspath(audio_path)}" type mpegvideo alias {alias}'
        res = windll.winmm.mciSendStringW(cmd_open, None, 0, None)
        if res == 0:
            windll.winmm.mciSendStringW(f"play {alias}", None, 0, None)
        else:
            os.startfile(os.path.abspath(audio_path))
    else:
        subprocess.Popen(["xdg-open", audio_path])


def stop_custom_audio():
    if platform.system() == "Windows":
        windll.winmm.mciSendStringW("close workpunch_audio", None, 0, None)
        if winsound:
            winsound.PlaySound(None, winsound.SND_PURGE)


def play_custom_video(video_path: str):
    if not video_path or not os.path.isfile(video_path):
        if winsound:
            winsound.MessageBeep(winsound.MB_ICONHAND)
        return

    if platform.system() == "Windows":
        os.startfile(os.path.abspath(video_path))
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", video_path])
    else:
        subprocess.Popen(["xdg-open", video_path])


class WorkPunchApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WorkPunch - Detector de Inactividad")
        self.root.geometry("620x580")
        self.root.resizable(False, False)
        self.root.configure(bg="#0f172a")

        self.config = self.load_config()
        self.monitoring = True
        self.alert_active = False
        self.last_alert_time = 0.0
        self.stop_sound_event = threading.Event()
        self.alert_window = None

        self._setup_styles()
        self._build_ui()
        self._update_loop()

    def load_config(self) -> dict:
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(data)
                return cfg
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            minutes = float(self.minutes_var.get())
            if minutes <= 0:
                raise ValueError
            self.config["idle_limit_seconds"] = int(minutes * 60)
        except ValueError:
            messagebox.showerror("Valor inválido", "Ingresa un número válido de minutos (por ejemplo, 5 o 0.5).")
            return

        self.config["alert_mode"] = self.mode_var.get()
        self.config["preset_name"] = self.preset_var.get()
        self.config["audio_path"] = self.audio_var.get().strip()
        self.config["video_path"] = self.video_var.get().strip()

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            self.log_event(f"Configuración guardada ({self.config['idle_limit_seconds']} s, modo: {self.config['alert_mode']}).")
        except Exception as e:
            messagebox.showerror("Error al guardar", f"No se pudo guardar la configuración:\n{e}")

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0f172a")
        style.configure("Card.TFrame", background="#1e293b")
        style.configure("TLabel", background="#1e293b", foreground="#f8fafc", font=("Segoe UI", 10))
        style.configure("Header.TLabel", background="#0f172a", foreground="#38bdf8", font=("Segoe UI", 16, "bold"))
        style.configure("SubHeader.TLabel", background="#0f172a", foreground="#94a3b8", font=("Segoe UI", 9))
        style.configure("Timer.TLabel", background="#1e293b", foreground="#22c55e", font=("Consolas", 24, "bold"))
        style.configure("TRadiobutton", background="#1e293b", foreground="#f8fafc", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=6)
        style.configure("Horizontal.TProgressbar", troughcolor="#0f172a", background="#38bdf8", thickness=14)

    def _build_ui(self):
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill="x", padx=20, pady=(15, 5))
        ttk.Label(header_frame, text="WorkPunch · Monitor Global de Inactividad", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header_frame,
            text="Monitoreo en tiempo real de hardware (Mouse y Teclado) en Windows",
            style="SubHeader.TLabel"
        ).pack(anchor="w")

        status_card = ttk.Frame(self.root, style="Card.TFrame", padding=15)
        status_card.pack(fill="x", padx=20, pady=8)

        top_status = ttk.Frame(status_card, style="Card.TFrame")
        top_status.pack(fill="x")

        self.state_label = ttk.Label(top_status, text="ESTADO: MONITOREANDO", font=("Segoe UI", 10, "bold"))
        self.state_label.pack(side="left")

        self.timer_label = ttk.Label(top_status, text="00:00 / 05:00", style="Timer.TLabel")
        self.timer_label.pack(side="right")

        self.progress = ttk.Progressbar(status_card, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(10, 8))

        btn_row = ttk.Frame(status_card, style="Card.TFrame")
        btn_row.pack(fill="x")

        self.toggle_btn = tk.Button(
            btn_row, text="Pausar Monitoreo", bg="#f59e0b", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=5,
            command=self.toggle_monitoring
        )
        self.toggle_btn.pack(side="left", padx=(0, 8))

        tk.Button(
            btn_row, text="Probar Alerta Ahora", bg="#38bdf8", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=5,
            command=lambda: self.trigger_alert(test=True)
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_row, text="Detener Sonido", bg="#ef4444", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=5,
            command=self.dismiss_alert
        ).pack(side="right")

        cfg_card = ttk.Frame(self.root, style="Card.TFrame", padding=15)
        cfg_card.pack(fill="x", padx=20, pady=8)

        time_row = ttk.Frame(cfg_card, style="Card.TFrame")
        time_row.pack(fill="x", pady=(0, 10))
        ttk.Label(time_row, text="Tiempo límite de inactividad (minutos):").pack(side="left")

        init_mins = round(self.config["idle_limit_seconds"] / 60.0, 2)
        self.minutes_var = tk.StringVar(value=str(int(init_mins) if init_mins.is_integer() else init_mins))
        tk.Entry(time_row, textvariable=self.minutes_var, width=8, font=("Segoe UI", 10)).pack(side="left", padx=10)

        ttk.Label(cfg_card, text="Tipo de alerta al superar el límite:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        self.mode_var = tk.StringVar(value=self.config["alert_mode"])

        preset_row = ttk.Frame(cfg_card, style="Card.TFrame")
        preset_row.pack(fill="x", pady=4)
        ttk.Radiobutton(
            preset_row, text="Alarma preconfigurada:", variable=self.mode_var, value="preset"
        ).pack(side="left")
        self.preset_var = tk.StringVar(value=self.config["preset_name"])
        preset_combo = ttk.Combobox(
            preset_row, textvariable=self.preset_var,
            values=["Estándar", "Urgente", "Sirena", "Pulso Suave"],
            state="readonly", width=18
        )
        preset_combo.pack(side="left", padx=10)

        audio_row = ttk.Frame(cfg_card, style="Card.TFrame")
        audio_row.pack(fill="x", pady=4)
        ttk.Radiobutton(
            audio_row, text="Audio personalizado:", variable=self.mode_var, value="audio"
        ).pack(side="left")
        self.audio_var = tk.StringVar(value=self.config["audio_path"])
        tk.Entry(audio_row, textvariable=self.audio_var, width=32, font=("Segoe UI", 9)).pack(side="left", padx=8)
        tk.Button(
            audio_row, text="Buscar...", bg="#334155", fg="#f8fafc", relief="flat",
            command=self.browse_audio
        ).pack(side="left")

        video_row = ttk.Frame(cfg_card, style="Card.TFrame")
        video_row.pack(fill="x", pady=4)
        ttk.Radiobutton(
            video_row, text="Video personalizado:", variable=self.mode_var, value="video"
        ).pack(side="left")
        self.video_var = tk.StringVar(value=self.config["video_path"])
        tk.Entry(video_row, textvariable=self.video_var, width=32, font=("Segoe UI", 9)).pack(side="left", padx=8)
        tk.Button(
            video_row, text="Buscar...", bg="#334155", fg="#f8fafc", relief="flat",
            command=self.browse_video
        ).pack(side="left")

        tk.Button(
            cfg_card, text="Guardar Configuración", bg="#22c55e", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=14, pady=5,
            command=self.save_config
        ).pack(anchor="e", pady=(10, 0))

        log_card = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        log_card.pack(fill="both", expand=True, padx=20, pady=(4, 15))
        ttk.Label(log_card, text="Registro de eventos:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        self.log_box = tk.Text(
            log_card, height=6, bg="#0f172a", fg="#cbd5e1",
            font=("Consolas", 9), relief="flat", state="disabled"
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_event("WorkPunch iniciado. Monitoreando mouse y teclado globalmente.")

    def browse_audio(self):
        path = filedialog.askopenfilename(
            title="Seleccionar archivo de audio",
            filetypes=[("Archivos de audio", "*.wav *.mp3 *.ogg *.flac"), ("Todos los archivos", "*.*")]
        )
        if path:
            self.audio_var.set(path)
            self.mode_var.set("audio")

    def browse_video(self):
        path = filedialog.askopenfilename(
            title="Seleccionar archivo de video",
            filetypes=[("Archivos de video", "*.mp4 *.mkv *.avi *.webm *.mov"), ("Todos los archivos", "*.*")]
        )
        if path:
            self.video_var.set(path)
            self.mode_var.set("video")

    def toggle_monitoring(self):
        self.monitoring = not self.monitoring
        if self.monitoring:
            self.state_label.configure(text="ESTADO: MONITOREANDO", foreground="#f8fafc")
            self.toggle_btn.configure(text="Pausar Monitoreo", bg="#f59e0b")
            self.log_event("Monitoreo reanudado.")
        else:
            self.state_label.configure(text="ESTADO: EN PAUSA", foreground="#f59e0b")
            self.toggle_btn.configure(text="Reanudar Monitoreo", bg="#22c55e")
            self.log_event("Monitoreo en pausa.")

    def log_event(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def trigger_alert(self, test: bool = False):
        mode = self.mode_var.get()
        preset = self.preset_var.get()
        audio_path = self.audio_var.get().strip()
        video_path = self.video_var.get().strip()

        prefix = "[PRUEBA] " if test else "[ALERTA] "
        self.log_event(f"{prefix}Inactividad detectada. Ejecutando alerta ({mode}).")

        self.stop_sound_event.clear()

        if mode == "preset":
            threading.Thread(
                target=play_preset_alarm,
                args=(preset, self.stop_sound_event),
                daemon=True
            ).start()
        elif mode == "audio":
            threading.Thread(target=play_custom_audio, args=(audio_path,), daemon=True).start()
        elif mode == "video":
            threading.Thread(target=play_custom_video, args=(video_path,), daemon=True).start()

        self._show_alert_popup(test=test)

    def _show_alert_popup(self, test: bool = False):
        if self.alert_window and self.alert_window.winfo_exists():
            self.alert_window.lift()
            return

        self.alert_window = tk.Toplevel(self.root)
        self.alert_window.title("¡Alerta de Inactividad - WorkPunch!")
        self.alert_window.geometry("420x210")
        self.alert_window.configure(bg="#7f1d1d")
        self.alert_window.attributes("-topmost", True)
        self.alert_window.resizable(False, False)

        title_text = "PRUEBA DE ALERTA" if test else "¡MÁS DE 5 MINUTOS SIN ACTIVIDAD!"
        tk.Label(
            self.alert_window, text=title_text,
            bg="#7f1d1d", fg="#fef08a", font=("Segoe UI", 13, "bold")
        ).pack(pady=(22, 8))

        tk.Label(
            self.alert_window,
            text="No se ha detectado uso del mouse ni del teclado.\nMueve el mouse o presiona el botón para descartar.",
            bg="#7f1d1d", fg="#ffffff", font=("Segoe UI", 10), justify="center"
        ).pack(pady=6)

        tk.Button(
            self.alert_window, text="Entendido / Detener Alerta",
            bg="#fef08a", fg="#7f1d1d", font=("Segoe UI", 10, "bold"),
            relief="flat", padx=16, pady=6, command=self.dismiss_alert
        ).pack(pady=16)

    def dismiss_alert(self):
        self.stop_sound_event.set()
        stop_custom_audio()
        if self.alert_window and self.alert_window.winfo_exists():
            self.alert_window.destroy()
        self.alert_active = False

    def _update_loop(self):
        if self.monitoring:
            idle_sec = get_idle_duration_seconds()
            limit_sec = max(5, int(self.config.get("idle_limit_seconds", 300)))

            mins_cur, secs_cur = divmod(int(idle_sec), 60)
            mins_lim, secs_lim = divmod(limit_sec, 60)
            self.timer_label.configure(text=f"{mins_cur:02d}:{secs_cur:02d} / {mins_lim:02d}:{secs_lim:02d}")

            pct = min(100.0, (idle_sec / limit_sec) * 100.0)
            self.progress["value"] = pct

            if idle_sec >= limit_sec:
                self.timer_label.configure(foreground="#ef4444")
                now = time.time()
                if not self.alert_active or (now - self.last_alert_time >= self.config["repeat_alert_seconds"]):
                    self.alert_active = True
                    self.last_alert_time = now
                    self.trigger_alert(test=False)
            else:
                self.timer_label.configure(foreground="#22c55e")
                if self.alert_active and idle_sec < 2.0:
                    self.dismiss_alert()
                    self.log_event("Actividad detectada nuevamente. Contador reiniciado.")

        self.root.after(500, self._update_loop)


if __name__ == "__main__":
    root = tk.Tk()
    app = WorkPunchApp(root)
    root.mainloop()
