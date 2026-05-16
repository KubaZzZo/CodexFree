"""Lightweight Tkinter GUI for ChatGPT registration.

Features:
  - Config editor with all fields from config.json
  - Real-time registration log with colored output
  - Start/stop batch registration
  - Save logs

Usage:
  python register_gui.py
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import threading
import queue
import sys
import builtins
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).parent
CFG_PATH = ROOT_DIR / "config.json"
CFG_EXAMPLE = ROOT_DIR / "config.example.json"

sys.path.insert(0, str(ROOT_DIR))


class ConfigTab:
    """Tab for editing config.json fields."""

    SCHEMA = [
        ("邮箱 (Mail)", [
            ("mail.provider",       "提供商",        "combo", ["skymail", "shanmail"]),
            ("mail.skymail_api_key", "SkyMail API Key", "text", ""),
            ("mail.shanmail_api_key","ShanMail API Key","text", ""),
        ]),
        ("接码 (SMS)", [
            ("phone_sms.provider",        "提供商",         "combo", ["herosms", "fivesim"]),
            ("phone_sms.herosms_api_key", "HeroSMS API Key", "text", ""),
            ("phone_sms.fivesim_api_key", "5sim API Key",    "text", ""),
            ("phone_sms.max_price",       "最高价格",       "text", "0.08"),
            ("phone_sms.min_price",       "最低价格",       "text", "0.04"),
            ("phone_sms.country",         "指定国家(可空)", "text", ""),
        ]),
        ("ChatGPT", [
            ("chatgpt.auth_base_url",     "Auth Base URL",    "text", "https://auth.openai.com"),
            ("chatgpt.chat_base_url",     "Chat Base URL",    "text", "https://chatgpt.com"),
            ("chatgpt.chat_web_client_id","Web Client ID",    "text", ""),
            ("chatgpt.codex_client_id",   "Codex Client ID",  "text", ""),
            ("chatgpt.mail_domain",       "邮箱域名",        "text", "example.com"),
        ]),
        ("注册 (Registration)", [
            ("registration.password_random_length", "密码长度",   "text", "12"),
            ("registration.password_suffix",        "密码后缀",   "text", "!A1"),
        ]),
        ("超时 (Timeouts)", [
            ("timeouts.page_load",    "页面加载(s)",  "text", "30"),
            ("timeouts.element_wait", "元素等待(s)",  "text", "10"),
            ("timeouts.sms_poll",     "短信轮询(s)",  "text", "120"),
            ("timeouts.email_poll",   "邮件轮询(s)",  "text", "120"),
            ("timeouts.poll_interval","轮询间隔(s)",  "text", "3"),
        ]),
        ("HTTP", [
            ("http.proxy",             "代理地址",     "text", ""),
            ("http.user_agent_chrome", "User-Agent",  "text", ""),
        ]),
        ("输出 (Output)", [
            ("output.directory",        "输出目录",     "text", "output"),
            ("output.filename_pattern", "文件名模式",   "text", "chatgpt_{email}_{timestamp}.json"),
        ]),
    ]

    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.widgets = {}  # key -> tk variable
        self._build()

    def _build(self):
        canvas = tk.Canvas(self.frame)
        scrollbar = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        row = 0
        for section_name, fields in self.SCHEMA:
            lf = ttk.LabelFrame(inner, text=section_name, padding=8)
            lf.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
            inner.columnconfigure(0, weight=1)
            lf.columnconfigure(1, weight=1)

            for i, (key, label, ftype, default) in enumerate(fields):
                ttk.Label(lf, text=label).grid(row=i, column=0, sticky=tk.W, padx=5, pady=2)

                if ftype == "combo":
                    var = tk.StringVar(value=default[0] if isinstance(default, list) else default)
                    cb = ttk.Combobox(lf, textvariable=var, values=default, state="readonly", width=30)
                    cb.grid(row=i, column=1, sticky=tk.EW, padx=5, pady=2)
                else:
                    var = tk.StringVar(value=str(default))
                    ttk.Entry(lf, textvariable=var, width=50).grid(row=i, column=1, sticky=tk.EW, padx=5, pady=2)

                self.widgets[key] = var

            row += 1

        # Buttons
        btn_frame = ttk.Frame(inner)
        btn_frame.grid(row=row, column=0, pady=10)
        ttk.Button(btn_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="重新加载", command=self.load_config).pack(side=tk.LEFT, padx=5)

    def _get_nested(self, cfg, dotkey):
        parts = dotkey.split(".")
        for p in parts:
            if isinstance(cfg, dict):
                cfg = cfg.get(p, "")
            else:
                return ""
        return cfg

    def _set_nested(self, cfg, dotkey, value):
        parts = dotkey.split(".")
        for p in parts[:-1]:
            cfg = cfg.setdefault(p, {})
        # Try to convert numeric values
        try:
            if "." in str(value):
                value = float(value)
            else:
                value = int(value)
        except (ValueError, TypeError):
            pass
        cfg[parts[-1]] = value

    def load_config(self):
        path = CFG_PATH if CFG_PATH.exists() else CFG_EXAMPLE
        if not path.exists():
            return
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            for key, var in self.widgets.items():
                val = self._get_nested(cfg, key)
                var.set(str(val) if val is not None else "")
        except Exception as e:
            messagebox.showerror("错误", f"加载配置失败: {e}")

    def save_config(self):
        cfg = {}
        for key, var in self.widgets.items():
            self._set_nested(cfg, key, var.get())

        # Preserve fields not in the schema
        if CFG_PATH.exists():
            try:
                old = json.loads(CFG_PATH.read_text(encoding="utf-8"))
                for section, val in old.items():
                    if section not in cfg:
                        cfg[section] = val
                    elif isinstance(val, dict):
                        for k, v in val.items():
                            if k not in cfg[section]:
                                cfg[section][k] = v
            except Exception:
                pass

        try:
            CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            messagebox.showinfo("成功", "配置已保存到 config.json")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")


class RegisterTab:
    """Tab for running & monitoring registration."""

    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.msg_queue = queue.Queue()
        self.is_running = False
        self._build()

    def _build(self):
        # Control bar
        ctl = ttk.Frame(self.frame)
        ctl.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(ctl, text="注册数量:").pack(side=tk.LEFT, padx=5)
        self.count_var = tk.StringVar(value="1")
        ttk.Entry(ctl, textvariable=self.count_var, width=6).pack(side=tk.LEFT)

        self.codex_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Codex Token", variable=self.codex_var).pack(side=tk.LEFT, padx=15)

        self.start_btn = ttk.Button(ctl, text="▶ 开始注册", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(ctl, text="■ 停止", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(ctl, text="清空", command=self._clear).pack(side=tk.RIGHT, padx=5)
        ttk.Button(ctl, text="保存日志", command=self._save_log).pack(side=tk.RIGHT, padx=5)

        # Progress
        pf = ttk.Frame(self.frame)
        pf.pack(fill=tk.X, padx=10)
        self.progress_label = tk.StringVar(value="就绪")
        ttk.Label(pf, textvariable=self.progress_label, font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W)
        self.pbar = ttk.Progressbar(pf, mode="indeterminate")
        self.pbar.pack(fill=tk.X, pady=3)
        self.step_label = tk.StringVar(value="等待开始...")
        ttk.Label(pf, textvariable=self.step_label, foreground="#888").pack(anchor=tk.W)

        # Log
        self.log = scrolledtext.ScrolledText(self.frame, wrap=tk.WORD, font=("Consolas", 9))
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.log.tag_config("info",    foreground="black")
        self.log.tag_config("success", foreground="#2e7d32", font=("Consolas", 9, "bold"))
        self.log.tag_config("error",   foreground="#c62828", font=("Consolas", 9, "bold"))
        self.log.tag_config("warn",    foreground="#e65100")
        self.log.tag_config("step",    foreground="#1565c0", font=("Consolas", 9, "bold"))

    # ── logging helpers ──

    def _append(self, text, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{ts}] {text}\n", tag)
        self.log.see(tk.END)

    def _clear(self):
        self.log.delete("1.0", tk.END)

    def _save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            Path(path).write_text(self.log.get("1.0", tk.END), encoding="utf-8")
            self._append(f"日志已保存: {path}", "success")

    # ── queue monitor (called from main thread) ──

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._append(*payload)
                elif kind == "step":
                    self.step_label.set(payload)
                elif kind == "progress":
                    self.progress_label.set(payload)
                elif kind == "done":
                    self._finish()
        except queue.Empty:
            pass

    # ── registration control ──

    def start(self):
        try:
            count = int(self.count_var.get())
            if count < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "注册数量必须是正整数")
            return

        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.pbar.start(10)

        self._append("=" * 55, "step")
        self._append(f"开始注册 — 数量: {count}, Codex: {self.codex_var.get()}", "step")
        self._append("=" * 55, "step")

        t = threading.Thread(target=self._worker, args=(count,), daemon=True)
        t.start()

    def stop(self):
        self.is_running = False
        self._append("用户请求停止...", "warn")

    def _finish(self):
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.pbar.stop()
        self.progress_label.set("完成")
        self.step_label.set("所有任务已结束")
        self._append("=" * 55, "step")
        self._append("注册流程结束", "success")

    # ── worker thread ──

    def _worker(self, count):
        q = self.msg_queue
        original_print = builtins.print

        def _gui_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            tag = "info"
            if any(k in msg for k in ("✓", "SUCCESS", "成功", "Saved")):
                tag = "success"
            elif any(k in msg for k in ("✗", "ERROR", "FAILED", "失败", "Exception")):
                tag = "error"
            elif any(k in msg for k in ("WARNING", "警告", "[!]", "retrying")):
                tag = "warn"
            elif msg.lstrip().startswith("["):
                tag = "step"
            q.put(("log", (msg, tag)))
            original_print(*args, **kwargs)

        builtins.print = _gui_print

        try:
            # Lazy-import so config changes take effect
            import importlib
            import chatgpt_register as reg
            importlib.reload(reg)

            for i in range(count):
                if not self.is_running:
                    q.put(("log", ("注册已被用户停止", "warn")))
                    break

                q.put(("progress", f"正在注册 {i+1}/{count} ..."))
                q.put(("step", f"账号 {i+1}: 初始化"))

                try:
                    account, sd = reg.run_registration()
                    if not account:
                        q.put(("log", (f"✗ 账号 {i+1} 注册失败", "error")))
                        continue

                    reg.save_result({"success": True, **account})
                    q.put(("log", (f"✓ 账号 {i+1} 注册成功: {account.get('phone','')}", "success")))

                    if self.codex_var.get():
                        q.put(("step", f"账号 {i+1}: Codex 登录"))
                        try:
                            token = reg.login_codex(account["phone"], account["password"])
                            data = {"success": True, **account, "token": token}
                            reg.save_result(data, "tokens")
                            q.put(("log", (f"✓ 账号 {i+1} Codex Token 获取成功", "success")))
                        except Exception as e:
                            q.put(("log", (f"✗ Codex 登录失败: {e}", "error")))

                except Exception as e:
                    q.put(("log", (f"✗ 账号 {i+1} 异常: {e}", "error")))

                q.put(("step", f"已完成 {i+1}/{count}"))

        except Exception as e:
            q.put(("log", (f"批量注册异常: {e}", "error")))
        finally:
            builtins.print = original_print
            q.put(("done", None))


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ChatGPT 注册工具")
        self.root.geometry("860x640")

        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Registration
        self.reg_tab = RegisterTab(nb)
        nb.add(self.reg_tab.frame, text="  注册  ")

        # Tab 2: Config
        self.cfg_tab = ConfigTab(nb)
        nb.add(self.cfg_tab.frame, text="  配置  ")
        self.cfg_tab.load_config()

        # Status bar
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X)

        self._poll()

    def _poll(self):
        self.reg_tab.poll_queue()
        self.root.after(100, self._poll)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
