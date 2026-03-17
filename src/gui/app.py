"""
src.gui.app
Interface gráfica Tkinter do pipeline multi-satélite IntegraCar.

A GUI é um wrapper sobre o pipeline core — NÃO duplica lógica.
Toda execução passa por src.core.pipeline.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from src.core.config import load_config, PipelineConfig
from src.satellites.registry import list_satellites

logger = logging.getLogger(__name__)


class LogHandler(logging.Handler):
    """Handler de logging que envia registros para uma fila thread-safe."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.log_queue.put(msg)


class IntegraCARApp:
    """Interface gráfica principal do pipeline multi-satélite."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IntegraCar — Pipeline Multi-Satélite")
        self.root.resizable(True, True)
        self.root.minsize(700, 580)

        self.config = load_config()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        # Variáveis da interface
        self.csv_var = tk.StringVar()
        self.output_var = tk.StringVar(value="saida")
        self.satellite_var = tk.StringVar(value="kompsat")
        self.layer_var = tk.BooleanVar(value=False)
        self.cloud_var = tk.StringVar(value=str(self.config.cloud_cover_max))
        self.buffer_var = tk.StringVar(value=str(self.config.buffer_metros))
        self.width_var = tk.StringVar(value=str(self.config.largura_pixels))
        self.height_var = tk.StringVar(value=str(self.config.altura_pixels))
        self.limit_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Pronto.")

        self._build_ui()
        self._setup_log_handler()
        self._poll_log_queue()

    def _build_ui(self) -> None:
        """Monta todos os componentes visuais."""
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        row = 0

        # --- Título ---
        title = ttk.Label(
            main, text="IntegraCar — Pipeline Multi-Satélite",
            font=("Helvetica", 14, "bold"),
        )
        title.grid(row=row, column=0, columnspan=3, pady=(0, 10))
        row += 1

        # --- CSV ---
        ttk.Label(main, text="Arquivo CSV:").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.csv_var, width=50, state="readonly").grid(
            row=row, column=1, padx=5, pady=3, sticky="ew"
        )
        ttk.Button(main, text="Selecionar...", command=self._select_csv).grid(
            row=row, column=2, padx=5
        )
        row += 1

        # --- Pasta de saída ---
        ttk.Label(main, text="Pasta de Saída:").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.output_var, width=50, state="readonly").grid(
            row=row, column=1, padx=5, pady=3, sticky="ew"
        )
        ttk.Button(main, text="Selecionar...", command=self._select_output).grid(
            row=row, column=2, padx=5
        )
        row += 1

        # --- Satélite ---
        ttk.Label(main, text="Satélite:").grid(row=row, column=0, sticky="w")
        combo = ttk.Combobox(
            main, textvariable=self.satellite_var,
            values=list_satellites(), state="readonly", width=20,
        )
        combo.grid(row=row, column=1, padx=5, pady=3, sticky="w")
        row += 1

        # --- Checkbox: Camada Segmentada ---
        chk = ttk.Checkbutton(
            main, text="Baixar camada segmentada (apenas GeoBases ES)",
            variable=self.layer_var,
        )
        chk.grid(row=row, column=0, columnspan=3, sticky="w", pady=(5, 5))
        row += 1

        # --- Parâmetros (grid 2x2) ---
        params_frame = ttk.LabelFrame(main, text="Parâmetros", padding=8)
        params_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=5)
        row += 1

        ttk.Label(params_frame, text="Cloud Cover (%):").grid(row=0, column=0, sticky="w")
        ttk.Entry(params_frame, textvariable=self.cloud_var, width=10).grid(
            row=0, column=1, padx=5, pady=2, sticky="w"
        )

        ttk.Label(params_frame, text="Buffer (m):").grid(row=0, column=2, sticky="w", padx=(15, 0))
        ttk.Entry(params_frame, textvariable=self.buffer_var, width=10).grid(
            row=0, column=3, padx=5, pady=2, sticky="w"
        )

        ttk.Label(params_frame, text="Largura (px):").grid(row=1, column=0, sticky="w")
        ttk.Entry(params_frame, textvariable=self.width_var, width=10).grid(
            row=1, column=1, padx=5, pady=2, sticky="w"
        )

        ttk.Label(params_frame, text="Altura (px):").grid(row=1, column=2, sticky="w", padx=(15, 0))
        ttk.Entry(params_frame, textvariable=self.height_var, width=10).grid(
            row=1, column=3, padx=5, pady=2, sticky="w"
        )

        ttk.Label(params_frame, text="Limite amostras:").grid(row=2, column=0, sticky="w")
        ttk.Entry(params_frame, textvariable=self.limit_var, width=10).grid(
            row=2, column=1, padx=5, pady=2, sticky="w"
        )

        # --- Botão Iniciar ---
        self.btn_start = ttk.Button(
            main, text="INICIAR", command=self._start_pipeline,
        )
        self.btn_start.grid(row=row, column=0, columnspan=3, pady=(10, 5), ipadx=30, ipady=5)
        row += 1

        # --- Barra de progresso ---
        self.progress = ttk.Progressbar(
            main, orient="horizontal", mode="indeterminate", length=400,
        )
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew", pady=5)
        row += 1

        # --- Log em tempo real ---
        ttk.Label(main, text="Log:").grid(row=row, column=0, sticky="w")
        row += 1

        self.log_text = scrolledtext.ScrolledText(
            main, height=10, width=80, state="disabled",
            font=("Consolas", 9),
        )
        self.log_text.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(0, 5))
        main.rowconfigure(row, weight=1)
        main.columnconfigure(1, weight=1)
        row += 1

        # --- Status ---
        status_frame = ttk.Frame(main)
        status_frame.grid(row=row, column=0, columnspan=3, sticky="ew")
        ttk.Label(status_frame, textvariable=self.status_var).grid(
            row=0, column=0, sticky="w"
        )

    def _setup_log_handler(self) -> None:
        """Instala handler de log que alimenta a caixa de texto."""
        handler = LogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(handler)

    def _poll_log_queue(self) -> None:
        """Drena a fila de log para a caixa de texto (chamado periodicamente)."""
        while not self.log_queue.empty():
            try:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
            except queue.Empty:
                break
        self.root.after(100, self._poll_log_queue)

    def _select_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione o CSV de coordenadas",
            filetypes=[("CSV", "*.csv;*.txt"), ("Todos", "*.*")],
        )
        if path:
            self.csv_var.set(path)

    def _select_output(self) -> None:
        path = filedialog.askdirectory(title="Selecione a pasta de saída")
        if path:
            self.output_var.set(path)

    def _validate_inputs(self) -> PipelineConfig | None:
        """Valida entradas e retorna PipelineConfig ou None se inválido."""
        csv_path = self.csv_var.get().strip()
        if not csv_path:
            messagebox.showerror("Erro", "Selecione o arquivo CSV.")
            return None

        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror("Erro", "Selecione a pasta de saída.")
            return None

        try:
            cloud = int(self.cloud_var.get())
            if not (0 <= cloud <= 100):
                raise ValueError
        except ValueError:
            messagebox.showerror("Erro", "Cloud Cover deve ser inteiro entre 0 e 100.")
            return None

        try:
            buffer_m = int(self.buffer_var.get())
            if buffer_m <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Erro", "Buffer deve ser inteiro positivo.")
            return None

        try:
            w = int(self.width_var.get())
            h = int(self.height_var.get())
            if w <= 0 or h <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Erro", "Largura e Altura devem ser inteiros positivos.")
            return None

        limit = None
        limit_txt = self.limit_var.get().strip()
        if limit_txt:
            try:
                limit = int(limit_txt)
                if limit <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Erro", "Limite deve ser inteiro positivo.")
                return None

        config = load_config()
        config.arquivo_csv = csv_path
        config.pasta_saida = output_path
        config.satellite_name = self.satellite_var.get()
        config.download_segmentada = self.layer_var.get()
        config.cloud_cover_max = cloud
        config.buffer_metros = buffer_m
        config.largura_pixels = w
        config.altura_pixels = h
        config.limite_amostras = limit

        return config

    def _update_status(self, msg: str) -> None:
        self.root.after(0, lambda: self.status_var.set(msg))

    def _update_progress(self, current: int, total: int) -> None:
        def _set():
            try:
                self.progress.stop()
                if total > 0:
                    self.progress.configure(
                        mode="determinate", maximum=max(total, 1), value=current,
                    )
            except tk.TclError:
                pass
        self.root.after(0, _set)

    def _start_pipeline(self) -> None:
        """Valida e inicia o pipeline em thread separada."""
        if self.running:
            messagebox.showwarning("Aviso", "Pipeline já está em execução.")
            return

        config = self._validate_inputs()
        if config is None:
            return

        self.running = True
        self.btn_start.configure(state="disabled")
        try:
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
        except tk.TclError:
            pass
        self._update_status("Executando pipeline...")

        def worker():
            try:
                from src.core.pipeline import run_pipeline
                result = run_pipeline(
                    config,
                    progress_callback=self._update_progress,
                    log_callback=lambda msg: logger.info(msg),
                )
                self._update_status(
                    f"Concluído: {result['sucesso']} ok, "
                    f"{result['erro']} erro, {result['total']} total"
                )
            except Exception as e:
                err_msg = str(e)
                self._update_status(f"Erro: {err_msg}")
                self.root.after(0, lambda: messagebox.showerror("Erro", err_msg))
            finally:
                self.running = False

                def _cleanup():
                    try:
                        self.progress.stop()
                        self.progress.configure(
                            mode="determinate", maximum=100, value=0,
                        )
                        self.btn_start.configure(state="normal")
                    except tk.TclError:
                        pass

                self.root.after(0, _cleanup)

        threading.Thread(target=worker, daemon=True).start()


def main_gui() -> None:
    """Ponto de entrada da GUI."""
    root = tk.Tk()
    IntegraCARApp(root)
    root.mainloop()


if __name__ == "__main__":
    main_gui()
