import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from factory.a1111_manager import A1111Manager
from factory.config import load_settings
from factory.files import import_manual, list_images, move_to_rejected, move_to_selected
from factory.generator import generate_batch
from factory.logger import log
from factory.packer import create_pack
from factory.paths import ensure_dirs
from factory.prompts import generate_prompt_batch, save_prompt_batch
from factory.publisher import publish_pack

SETTINGS = load_settings()
CATEGORIES = SETTINGS["categories"]
THUMB_SIZE = (220, 220)


class ThumbGrid(ttk.Frame):
    def __init__(self, master, approve_callback, reject_callback):
        super().__init__(master)
        self.approve_callback = approve_callback
        self.reject_callback = reject_callback
        self._images = []

        self.canvas = tk.Canvas(self, bg="#151515", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def set_items(self, category: str, source: str, items: list[Path]):
        for child in self.inner.winfo_children():
            child.destroy()
        self._images.clear()

        if not items:
            ttk.Label(self.inner, text="Пусто").grid(row=0, column=0, padx=12, pady=12, sticky="w")
            return

        cols = 3
        for idx, path in enumerate(items):
            row = idx // cols
            col = idx % cols

            frame = ttk.Frame(self.inner, relief="ridge", padding=8)
            frame.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

            try:
                with Image.open(path) as im_src:
                    im = im_src.convert("RGB")
                    im = ImageOps.contain(im, THUMB_SIZE)
                    preview = Image.new("RGB", THUMB_SIZE, (18, 18, 18))
                    x = (THUMB_SIZE[0] - im.width) // 2
                    y = (THUMB_SIZE[1] - im.height) // 2
                    preview.paste(im, (x, y))

                photo = ImageTk.PhotoImage(preview)
                self._images.append(photo)
                ttk.Label(frame, image=photo).pack()
            except Exception:
                ttk.Label(frame, text="preview error").pack()

            ttk.Label(frame, text=path.name, width=30).pack(anchor="w", pady=(8, 4))

            btns = ttk.Frame(frame)
            btns.pack(fill="x")

            if source in ("generated", "manual"):
                ttk.Button(
                    btns,
                    text="В selected",
                    command=lambda p=path, c=category: self.approve_callback(c, p)
                ).pack(side="left", padx=4)

                ttk.Button(
                    btns,
                    text="В rejected",
                    command=lambda p=path, c=category: self.reject_callback(c, p)
                ).pack(side="left", padx=4)

            elif source == "selected":
                ttk.Button(
                    btns,
                    text="Убрать",
                    command=lambda p=path, c=category: self.reject_callback(c, p)
                ).pack(side="left", padx=4)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_dirs()

        self.title("Content Factory")
        self.geometry("1420x940")
        self.minsize(1220, 820)

        self.a1111_manager = A1111Manager()

        self.category_var = tk.StringVar(value=CATEGORIES[0])
        self.backend_var = tk.StringVar(value=SETTINGS["default_backend"])
        self.prompt_prefix_var = tk.StringVar(value="")
        self.batch_count_var = tk.IntVar(value=4)

        self.status_var = tk.StringVar(value="Готово")

        self.pack_title_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="blend")
        self.weight_var = tk.DoubleVar(value=SETTINGS["pack_weight"])
        self.ttl_var = tk.IntVar(value=SETTINGS["pack_ttl_days"])
        self.policy_var = tk.StringVar(value=SETTINGS["replace_policy"])

        self.last_built_zip: Path | None = None
        self.last_built_manifest: Path | None = None

        self._build_ui()
        self.refresh_all()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # --------------------------
    # UI
    # --------------------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Категория:").pack(side="left")
        ttk.Combobox(
            top,
            textvariable=self.category_var,
            values=CATEGORIES,
            width=14,
            state="readonly"
        ).pack(side="left", padx=6)

        ttk.Label(top, text="Backend:").pack(side="left", padx=(12, 0))
        ttk.Combobox(
            top,
            textvariable=self.backend_var,
            values=["automatic1111", "mock"],
            width=16,
            state="readonly"
        ).pack(side="left", padx=6)

        ttk.Button(top, text="Проверить A1111", command=self.check_backend).pack(side="left", padx=4)
        ttk.Button(top, text="Запустить A1111", command=self.start_a1111).pack(side="left", padx=4)
        ttk.Button(top, text="Остановить A1111", command=self.stop_a1111).pack(side="left", padx=4)

        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        gen_tab = ttk.Frame(notebook, padding=12)
        notebook.add(gen_tab, text="1. Генерация")
        self._build_generate_tab(gen_tab)

        review_tab = ttk.Frame(notebook, padding=12)
        notebook.add(review_tab, text="2. Отбор")
        self._build_review_tab(review_tab)

        pack_tab = ttk.Frame(notebook, padding=12)
        notebook.add(pack_tab, text="3. Сборка и публикация")
        self._build_pack_tab(pack_tab)

    def _build_generate_tab(self, root):
        frame = ttk.LabelFrame(root, text="Промпты и генерация", padding=12)
        frame.pack(fill="x")

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=4)

        ttk.Label(row1, text="Префикс / свой текст:").pack(side="left")
        ttk.Entry(row1, textvariable=self.prompt_prefix_var, width=80).pack(
            side="left",
            padx=8,
            fill="x",
            expand=True
        )

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=4)

        ttk.Label(row2, text="Количество промптов:").pack(side="left")
        ttk.Spinbox(row2, from_=1, to=30, textvariable=self.batch_count_var, width=8).pack(
            side="left",
            padx=8
        )

        ttk.Button(row2, text="Сгенерировать промпты", command=self.generate_prompts).pack(side="left", padx=8)
        ttk.Button(row2, text="Сгенерировать изображения", command=self.generate_images).pack(side="left", padx=8)
        ttk.Button(row2, text="Импортировать свои картинки", command=self.import_images).pack(side="left", padx=8)

        self.prompt_box = tk.Text(frame, height=18, wrap="word")
        self.prompt_box.pack(fill="both", expand=True, pady=(8, 0))

    def _build_review_tab(self, root):
        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Обновить списки", command=self.refresh_all).pack(side="left")

        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True)

        generated_wrap = ttk.LabelFrame(panes, text="Generated")
        manual_wrap = ttk.LabelFrame(panes, text="Manual")
        selected_wrap = ttk.LabelFrame(panes, text="Selected")

        panes.add(generated_wrap, weight=1)
        panes.add(manual_wrap, weight=1)
        panes.add(selected_wrap, weight=1)

        self.generated_grid = ThumbGrid(generated_wrap, self.approve_item, self.reject_item)
        self.manual_grid = ThumbGrid(manual_wrap, self.approve_item, self.reject_item)
        self.selected_grid = ThumbGrid(selected_wrap, self.noop_approve, self.remove_selected)

        self.generated_grid.pack(fill="both", expand=True)
        self.manual_grid.pack(fill="both", expand=True)
        self.selected_grid.pack(fill="both", expand=True)

    def _build_pack_tab(self, root):
        form = ttk.LabelFrame(root, text="Параметры пакета", padding=12)
        form.pack(fill="x")

        r1 = ttk.Frame(form)
        r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="Название пакета:").pack(side="left")
        ttk.Entry(r1, textvariable=self.pack_title_var, width=60).pack(side="left", padx=8)

        r2 = ttk.Frame(form)
        r2.pack(fill="x", pady=4)

        ttk.Label(r2, text="Mode:").pack(side="left")
        ttk.Combobox(
            r2,
            textvariable=self.mode_var,
            values=["blend", "priority", "replace", "staged"],
            width=14,
            state="readonly"
        ).pack(side="left", padx=8)

        ttk.Label(r2, text="Weight:").pack(side="left")
        ttk.Entry(r2, textvariable=self.weight_var, width=8).pack(side="left", padx=8)

        ttk.Label(r2, text="TTL days:").pack(side="left")
        ttk.Entry(r2, textvariable=self.ttl_var, width=8).pack(side="left", padx=8)

        ttk.Label(r2, text="Replace policy:").pack(side="left")
        ttk.Combobox(
            r2,
            textvariable=self.policy_var,
            values=["append", "append_then_decay", "replace_all"],
            width=18,
            state="readonly"
        ).pack(side="left", padx=8)

        buttons = ttk.Frame(form)
        buttons.pack(anchor="w", pady=12)

        ttk.Button(buttons, text="Собрать пакет локально", command=self.build_pack).pack(side="left", padx=6)
        ttk.Button(buttons, text="Опубликовать последний пакет в GitHub", command=self.publish_last_pack).pack(side="left", padx=6)
        ttk.Button(buttons, text="Собрать и опубликовать сразу", command=self.build_and_publish).pack(side="left", padx=6)

        self.pack_info = tk.Text(root, height=18, wrap="word")
        self.pack_info.pack(fill="both", expand=True, pady=(10, 0))

    # --------------------------
    # status / close
    # --------------------------
    def set_status(self, msg: str):
        self.status_var.set(msg)
        self.update_idletasks()
        log(msg)

    def on_close(self):
        try:
            if SETTINGS.get("automatic1111_stop_on_exit", True):
                self.a1111_manager.stop()
        finally:
            self.destroy()

    # --------------------------
    # A1111
    # --------------------------
    def check_backend(self):
        if self.backend_var.get() != "automatic1111":
            self.set_status("Текущий backend не требует проверки")
            return

        ok = self.a1111_manager.ping()
        self.set_status("A1111 доступен" if ok else "A1111 недоступен")

    def start_a1111(self):
        def worker():
            try:
                self.set_status("Запуск A1111...")
                self.a1111_manager.ensure_running()
                self.set_status("A1111 запущен и готов")
            except Exception as e:
                err_text = str(e)
                self.after(
                    100,
                    lambda err_text=err_text: messagebox.showerror("Ошибка запуска A1111", err_text)
                )
                self.set_status(f"Ошибка запуска A1111: {err_text}")

        threading.Thread(target=worker, daemon=True).start()

    def stop_a1111(self):
        def worker():
            try:
                self.set_status("Остановка A1111...")
                self.a1111_manager.stop()
                self.set_status("A1111 остановлен")
            except Exception as e:
                err_text = str(e)
                self.after(
                    100,
                    lambda err_text=err_text: messagebox.showerror("Ошибка остановки A1111", err_text)
                )
                self.set_status(f"Ошибка остановки A1111: {err_text}")

        threading.Thread(target=worker, daemon=True).start()

    # --------------------------
    # prompts / generation
    # --------------------------
    def generate_prompts(self):
        category = self.category_var.get()
        count = int(self.batch_count_var.get())
        prefix = self.prompt_prefix_var.get().strip()

        prompts = generate_prompt_batch(category, count, custom_prefix=prefix)
        save_prompt_batch(category, prompts)

        self.prompt_box.delete("1.0", "end")
        self.prompt_box.insert("1.0", "\n".join(prompts))

        self.set_status(f"Сгенерировано промптов: {len(prompts)}")

    def _get_prompts_from_box(self) -> list[str]:
        text = self.prompt_box.get("1.0", "end").strip()
        return [line.strip() for line in text.splitlines() if line.strip()]

    def generate_images(self):
        category = self.category_var.get()
        backend = self.backend_var.get()
        prompts = self._get_prompts_from_box()

        if not prompts:
            messagebox.showwarning("Нет промптов", "Сначала сгенерируй или введи промпты.")
            return

        def worker():
            try:
                if backend == "automatic1111":
                    self.set_status("Проверка / запуск A1111...")
                    self.a1111_manager.ensure_running()

                self.set_status(f"Генерация {len(prompts)} изображений...")
                results = generate_batch(category, prompts, backend_name=backend)

                self.set_status(f"Готово: {len(results)} файлов в generated/{category}")
                self.after(100, self.refresh_all)

            except Exception as e:
                err_text = str(e)
                self.after(
                    100,
                    lambda err_text=err_text: messagebox.showerror("Ошибка генерации", err_text)
                )
                self.set_status(f"Ошибка генерации: {err_text}")

        threading.Thread(target=worker, daemon=True).start()

    def import_images(self):
        category = self.category_var.get()
        files = filedialog.askopenfilenames(
            title="Выбери свои картинки",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")],
        )

        if not files:
            return

        import_manual(files, category)
        self.set_status(f"Импортировано вручную: {len(files)}")
        self.refresh_all()

    # --------------------------
    # review
    # --------------------------
    def approve_item(self, category: str, path: Path):
        move_to_selected([path], category)
        self.set_status(f"Перенесено в selected: {path.name}")
        self.refresh_all()

    def reject_item(self, category: str, path: Path):
        move_to_rejected([path], category)
        self.set_status(f"Перенесено в rejected: {path.name}")
        self.refresh_all()

    def remove_selected(self, category: str, path: Path):
        move_to_rejected([path], category)
        self.set_status(f"Убрано из selected: {path.name}")
        self.refresh_all()

    def noop_approve(self, category: str, path: Path):
        pass

    def refresh_all(self):
        category = self.category_var.get()
        self.generated_grid.set_items(category, "generated", list_images(category, "generated"))
        self.manual_grid.set_items(category, "manual", list_images(category, "manual"))
        self.selected_grid.set_items(category, "selected", list_images(category, "selected"))

    # --------------------------
    # packing / publishing
    # --------------------------
    def _do_build(self):
        zip_path, manifest_path = create_pack(
            title=self.pack_title_var.get().strip(),
            mode=self.mode_var.get(),
            weight=float(self.weight_var.get()),
            ttl_days=int(self.ttl_var.get()),
            replace_policy=self.policy_var.get(),
        )
        self.last_built_zip = zip_path
        self.last_built_manifest = manifest_path
        return zip_path, manifest_path

    def build_pack(self):
        try:
            zip_path, manifest_path = self._do_build()

            self.pack_info.delete("1.0", "end")
            self.pack_info.insert(
                "1.0",
                f"Пакет собран локально.\n\n"
                f"ZIP: {zip_path}\n"
                f"Manifest: {manifest_path}\n\n"
                f"Дальше можно нажать 'Опубликовать последний пакет в GitHub'.\n"
            )

            self.set_status("Пакет собран локально")

        except Exception as e:
            messagebox.showerror("Ошибка упаковки", str(e))
            self.set_status(f"Ошибка упаковки: {e}")

    def publish_last_pack(self):
        if not self.last_built_zip or not self.last_built_manifest:
            messagebox.showwarning("Нет пакета", "Сначала собери пакет локально.")
            return

        def worker():
            try:
                self.set_status("Публикация в GitHub...")
                result = publish_pack(self.last_built_zip, self.last_built_manifest)

                info = (
                    f"Пакет опубликован.\n\n"
                    f"Version: {result['version']}\n"
                    f"ZIP в feed: {result['published_zip']}\n"
                    f"Index: {result['index_json']}\n"
                    f"SHA256: {result['sha256']}\n"
                    f"Size: {result['size']}\n"
                )

                if result.get("public_index_url"):
                    info += f"\nPublic index URL:\n{result['public_index_url']}\n"
                if result.get("public_pack_url"):
                    info += f"\nPublic pack URL:\n{result['public_pack_url']}\n"

                self.after(100, lambda info=info: self.pack_info.delete("1.0", "end"))
                self.after(100, lambda info=info: self.pack_info.insert("1.0", info))
                self.set_status("Пакет опубликован в GitHub feed")

            except Exception as e:
                err_text = str(e)
                self.after(
                    100,
                    lambda err_text=err_text: messagebox.showerror("Ошибка публикации", err_text)
                )
                self.set_status(f"Ошибка публикации: {err_text}")

        threading.Thread(target=worker, daemon=True).start()

    def build_and_publish(self):
        def worker():
            try:
                self.set_status("Сборка пакета...")
                zip_path, manifest_path = self._do_build()

                self.set_status("Публикация в GitHub...")
                result = publish_pack(zip_path, manifest_path)

                info = (
                    f"Пакет собран и опубликован.\n\n"
                    f"Version: {result['version']}\n"
                    f"Локальный ZIP: {zip_path}\n"
                    f"Feed ZIP: {result['published_zip']}\n"
                    f"Index: {result['index_json']}\n"
                    f"SHA256: {result['sha256']}\n"
                    f"Size: {result['size']}\n"
                )

                if result.get("public_index_url"):
                    info += f"\nPublic index URL:\n{result['public_index_url']}\n"
                if result.get("public_pack_url"):
                    info += f"\nPublic pack URL:\n{result['public_pack_url']}\n"

                self.after(100, lambda info=info: self.pack_info.delete("1.0", "end"))
                self.after(100, lambda info=info: self.pack_info.insert("1.0", info))
                self.set_status("Пакет собран и опубликован")

            except Exception as e:
                err_text = str(e)
                self.after(
                    100,
                    lambda err_text=err_text: messagebox.showerror("Ошибка сборки/публикации", err_text)
                )
                self.set_status(f"Ошибка сборки/публикации: {err_text}")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = App()
    app.mainloop()