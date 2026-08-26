"""Interface Tkinter para download de recortes CBERS."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from utils.cbers import (
    FONTES,
    INDICES,
    ConfiguracaoExtracao,
    ErroCBERS,
    executar_extracao,
    obter_colecao,
    pixels_para_resolucao,
    resumo_resultados,
    sensores_disponiveis,
    validar_configuracao,
)

ROTULOS_CRITERIO = {
    "Menor cobertura de nuvens": "menor-nuvem",
    "Cena mais recente": "mais-recente",
}

RESOLUCAO_PADRAO_M = 2.0

NOMES_PRODUTO = {
    "nir": "INFRAVERMELHO (NIR)",
    "rgb": "COLORIDA (RGB)",
    "completo": "3 BANDAS (NIR + NDVI + GNDVI + NDWI)",
    **{codigo: cfg.nome for codigo, cfg in INDICES.items()},
}


class AplicacaoCBERS:
    """Janela em duas etapas: produto e parâmetros."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Extrator CBERS - IntegraCAR")
        self.root.geometry("920x760")
        self.root.minsize(820, 680)

        self.produto: str | None = None
        self.eventos: queue.Queue[tuple] = queue.Queue()
        self.cancelamento = threading.Event()
        self.executando = False

        self.csv_var = tk.StringVar()
        self.saida_var = tk.StringVar()
        self.fonte_var = tk.StringVar(value=FONTES["inpe"].nome)
        self.sensor_var = tk.StringVar()
        self.data_inicial_var = tk.StringVar(value="2024-01-01")
        self.data_final_var = tk.StringVar(
            value=datetime.now(timezone.utc).date().isoformat()
        )
        self.buffer_var = tk.StringVar(value="1024")
        self.epsg_var = tk.StringVar(value="EPSG:31984")
        self.criterio_var = tk.StringVar(value="Menor cobertura de nuvens")
        self.max_nuvens_var = tk.StringVar()
        self.largura_var = tk.StringVar()
        self.altura_var = tk.StringVar()
        self.qtd_var = tk.StringVar()
        self.workers_var = tk.StringVar(value="4")
        self.sobrescrever_var = tk.BooleanVar(value=False)
        self.colecao_var = tk.StringVar()
        self.aviso_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto.")

        self._pixels_auto = True
        self._atualizando_pixels = False
        self._atualizar_pixels_automaticos()
        self.buffer_var.trace_add("write", self._on_buffer_alterado)
        self.largura_var.trace_add("write", self._on_pixels_editado)
        self.altura_var.trace_add("write", self._on_pixels_editado)

        self._configurar_estilos()
        self._mostrar_escolha_produto()
        self.root.protocol("WM_DELETE_WINDOW", self._fechar)
        self.root.after(100, self._processar_eventos)

    def _atualizar_pixels_automaticos(self) -> None:
        """Recalcula Largura/Altura px para manter RESOLUCAO_PADRAO_M m/pixel."""
        try:
            buffer = float(self.buffer_var.get().replace(",", "."))
            largura, altura = pixels_para_resolucao(buffer, RESOLUCAO_PADRAO_M)
        except (ValueError, ErroCBERS):
            return
        self._atualizando_pixels = True
        try:
            self.largura_var.set(str(largura))
            self.altura_var.set(str(altura))
        finally:
            self._atualizando_pixels = False

    def _on_buffer_alterado(self, *_args) -> None:
        if self._pixels_auto:
            self._atualizar_pixels_automaticos()

    def _on_pixels_editado(self, *_args) -> None:
        if self._atualizando_pixels:
            return
        # Usuario digitou manualmente em Largura/Altura: para de sobrescrever.
        self._pixels_auto = False

    def _configurar_estilos(self) -> None:
        estilo = ttk.Style(self.root)
        estilo.configure("Titulo.TLabel", font=("", 22, "bold"))
        estilo.configure("Subtitulo.TLabel", font=("", 11))
        estilo.configure("Produto.TButton", font=("", 15, "bold"), padding=(22, 22))
        estilo.configure("Acao.TButton", font=("", 11, "bold"), padding=(16, 9))
        estilo.configure("Aviso.TLabel", foreground="#9A5A00")
        estilo.configure("Status.TLabel", foreground="#334155")

    def _limpar(self) -> None:
        for filho in self.root.winfo_children():
            filho.destroy()

    def _mostrar_escolha_produto(self) -> None:
        if self.executando:
            return
        self._limpar()
        self.root.geometry("760x630")
        quadro = ttk.Frame(self.root, padding=32)
        quadro.pack(fill="both", expand=True)
        quadro.columnconfigure((0, 1), weight=1, uniform="produto")

        ttk.Label(
            quadro,
            text="O que deseja baixar?",
            style="Titulo.TLabel",
        ).grid(row=0, column=0, columnspan=2, pady=(26, 8))
        ttk.Label(
            quadro,
            text="Escolha o tipo de imagem CBERS.",
            style="Subtitulo.TLabel",
        ).grid(row=1, column=0, columnspan=2, pady=(0, 34))

        ttk.Button(
            quadro,
            text="INFRAVERMELHO (NIR)",
            style="Produto.TButton",
            command=lambda: self._selecionar_produto("nir"),
        ).grid(row=2, column=0, sticky="ew", padx=(0, 10), ipady=24)
        ttk.Button(
            quadro,
            text="COLORIDA (RGB)",
            style="Produto.TButton",
            command=lambda: self._selecionar_produto("rgb"),
        ).grid(row=2, column=1, sticky="ew", padx=(10, 0), ipady=24)

        ttk.Label(
            quadro,
            text="NIR: uma banda. RGB: vermelho, verde e azul em um GeoTIFF.",
            style="Subtitulo.TLabel",
        ).grid(row=3, column=0, columnspan=2, pady=(26, 0))

        ttk.Label(
            quadro,
            text="Ou calcular um índice espectral (baixa NIR + a banda "
            "necessária e já calcula):",
            style="Subtitulo.TLabel",
        ).grid(row=4, column=0, columnspan=2, pady=(30, 10))

        indices = ttk.Frame(quadro)
        indices.grid(row=5, column=0, columnspan=2, sticky="ew")
        indices.columnconfigure((0, 1, 2), weight=1, uniform="indice")
        for coluna, codigo in enumerate(INDICES):
            ttk.Button(
                indices,
                text=f"Calcular {INDICES[codigo].nome}",
                style="Acao.TButton",
                command=lambda codigo=codigo: self._selecionar_produto(codigo),
            ).grid(row=0, column=coluna, sticky="ew", padx=6, ipady=10)

        ttk.Button(
            quadro,
            text="Baixar 3 bandas (NIR + NDVI + GNDVI + NDWI de uma vez)",
            style="Acao.TButton",
            command=lambda: self._selecionar_produto("completo"),
        ).grid(row=6, column=0, columnspan=2, sticky="ew", padx=6, pady=(14, 0), ipady=10)

    def _selecionar_produto(self, produto: str) -> None:
        self.produto = produto
        self._mostrar_formulario()

    def _mostrar_formulario(self) -> None:
        self._limpar()
        self.root.geometry("920x760")
        principal = ttk.Frame(self.root, padding=18)
        principal.pack(fill="both", expand=True)
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(3, weight=1)

        topo = ttk.Frame(principal)
        topo.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        topo.columnconfigure(1, weight=1)
        self.botao_alterar = ttk.Button(
            topo, text="Alterar tipo", command=self._mostrar_escolha_produto
        )
        self.botao_alterar.grid(row=0, column=0, sticky="w", padx=(0, 14))
        produto_nome = NOMES_PRODUTO.get(self.produto or "", "")
        ttk.Label(topo, text=produto_nome, style="Titulo.TLabel").grid(
            row=0, column=1, sticky="w"
        )

        arquivos = ttk.LabelFrame(principal, text="Entrada e saída", padding=12)
        arquivos.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        arquivos.columnconfigure(1, weight=1)
        self._linha_arquivo(
            arquivos,
            0,
            "CSV de pontos",
            self.csv_var,
            self._selecionar_csv,
        )
        self._linha_arquivo(
            arquivos,
            1,
            "Pasta de saída",
            self.saida_var,
            self._selecionar_saida,
        )

        opcoes = ttk.LabelFrame(principal, text="Fonte e recorte", padding=12)
        opcoes.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for coluna in (1, 3):
            opcoes.columnconfigure(coluna, weight=1)

        ttk.Label(opcoes, text="Fonte").grid(row=0, column=0, sticky="w")
        self.combo_fonte = ttk.Combobox(
            opcoes,
            textvariable=self.fonte_var,
            values=[fonte.nome for fonte in FONTES.values()],
            state="readonly",
            width=28,
        )
        self.combo_fonte.grid(row=0, column=1, sticky="ew", padx=(8, 18), pady=3)
        self.combo_fonte.bind("<<ComboboxSelected>>", self._fonte_alterada)

        ttk.Label(opcoes, text="Sensor").grid(row=0, column=2, sticky="w")
        self.combo_sensor = ttk.Combobox(
            opcoes,
            textvariable=self.sensor_var,
            state="readonly",
            width=28,
        )
        self.combo_sensor.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=3)
        self.combo_sensor.bind("<<ComboboxSelected>>", self._sensor_alterado)

        self._campo(opcoes, 1, 0, "Data inicial", self.data_inicial_var)
        self._campo(opcoes, 1, 2, "Data final", self.data_final_var)
        self._campo(opcoes, 2, 0, "Buffer (m)", self.buffer_var)
        self._campo(opcoes, 2, 2, "CRS do CSV", self.epsg_var)

        ttk.Label(opcoes, text="Escolha da cena").grid(
            row=3, column=0, sticky="w"
        )
        ttk.Combobox(
            opcoes,
            textvariable=self.criterio_var,
            values=list(ROTULOS_CRITERIO),
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", padx=(8, 18), pady=3)
        self._campo(
            opcoes,
            3,
            2,
            "Máx. nuvens (%)",
            self.max_nuvens_var,
        )

        self._campo(opcoes, 4, 0, "Largura px (2 m/pixel)", self.largura_var)
        self._campo(opcoes, 4, 2, "Altura px (2 m/pixel)", self.altura_var)
        self._campo(opcoes, 5, 0, "Quantidade", self.qtd_var)
        self._campo(opcoes, 5, 2, "Downloads paralelos", self.workers_var)

        ttk.Checkbutton(
            opcoes,
            text="Sobrescrever arquivos existentes",
            variable=self.sobrescrever_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(7, 2))
        ttk.Label(opcoes, textvariable=self.colecao_var).grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(7, 0)
        )
        ttk.Label(
            opcoes,
            textvariable=self.aviso_var,
            style="Aviso.TLabel",
            wraplength=820,
        ).grid(row=8, column=0, columnspan=4, sticky="w", pady=(3, 0))

        execucao = ttk.LabelFrame(principal, text="Execução", padding=12)
        execucao.grid(row=3, column=0, sticky="nsew")
        execucao.columnconfigure(0, weight=1)
        execucao.rowconfigure(2, weight=1)

        self.progresso = ttk.Progressbar(
            execucao, mode="determinate", maximum=100
        )
        self.progresso.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        ttk.Label(
            execucao,
            textvariable=self.status_var,
            style="Status.TLabel",
            wraplength=820,
        ).grid(row=1, column=0, sticky="w", pady=(0, 7))
        self.log_texto = tk.Text(
            execucao,
            height=7,
            wrap="word",
            state="disabled",
            font=("TkFixedFont", 10),
        )
        self.log_texto.grid(row=2, column=0, sticky="nsew")

        acoes = ttk.Frame(principal)
        acoes.grid(row=4, column=0, sticky="e", pady=(12, 0))
        self.botao_cancelar = ttk.Button(
            acoes,
            text="Cancelar",
            command=self._cancelar,
            state="disabled",
        )
        self.botao_cancelar.grid(row=0, column=0, padx=(0, 8))
        if self.produto in INDICES:
            texto_iniciar = f"Baixar e calcular {INDICES[self.produto].nome}"
        elif self.produto == "completo":
            texto_iniciar = "Baixar 3 bandas e calcular tudo"
        else:
            texto_iniciar = "Baixar imagens"
        self.botao_iniciar = ttk.Button(
            acoes,
            text=texto_iniciar,
            style="Acao.TButton",
            command=self._iniciar,
        )
        self.botao_iniciar.grid(row=0, column=1)

        self._atualizar_sensores()

    def _linha_arquivo(
        self,
        pai,
        linha: int,
        rotulo: str,
        variavel: tk.StringVar,
        comando,
    ) -> None:
        ttk.Label(pai, text=rotulo).grid(row=linha, column=0, sticky="w")
        ttk.Entry(pai, textvariable=variavel, state="readonly").grid(
            row=linha, column=1, sticky="ew", padx=8, pady=3
        )
        ttk.Button(pai, text="Selecionar...", command=comando).grid(
            row=linha, column=2, pady=3
        )

    def _campo(
        self,
        pai,
        linha: int,
        coluna: int,
        rotulo: str,
        variavel: tk.StringVar,
    ) -> None:
        ttk.Label(pai, text=rotulo).grid(
            row=linha, column=coluna, sticky="w"
        )
        ttk.Entry(pai, textvariable=variavel).grid(
            row=linha,
            column=coluna + 1,
            sticky="ew",
            padx=(8, 18 if coluna == 0 else 0),
            pady=3,
        )

    def _codigo_fonte(self) -> str:
        for codigo, fonte in FONTES.items():
            if fonte.nome == self.fonte_var.get():
                return codigo
        return "inpe"

    def _codigo_sensor(self) -> str:
        for sensor in sensores_disponiveis(self._codigo_fonte()):
            if sensor.nome == self.sensor_var.get():
                return sensor.codigo
        return sensores_disponiveis(self._codigo_fonte())[0].codigo

    def _fonte_alterada(self, _evento=None) -> None:
        self._atualizar_sensores()

    def _sensor_alterado(self, _evento=None) -> None:
        self._atualizar_colecao()

    def _atualizar_sensores(self) -> None:
        fonte = self._codigo_fonte()
        sensores = sensores_disponiveis(fonte)
        nomes = [sensor.nome for sensor in sensores]
        atual = self.sensor_var.get()
        self.combo_sensor["values"] = nomes
        if atual not in nomes:
            preferido = next(
                (sensor.nome for sensor in sensores if sensor.codigo == "mux4"),
                nomes[0],
            )
            self.sensor_var.set(preferido)
        self._atualizar_colecao()

    def _atualizar_colecao(self) -> None:
        fonte = self._codigo_fonte()
        sensor = self._codigo_sensor()
        colecao = obter_colecao(fonte, sensor)
        if self.produto in INDICES:
            indice_cfg = INDICES[self.produto]
            banda_extra = (
                colecao.bandas_rgb[0]
                if indice_cfg.papel_banda_extra == "vermelho"
                else colecao.bandas_rgb[1]
            )
            bandas = (
                f"{colecao.banda_nir} (NIR) + "
                f"{banda_extra} ({indice_cfg.papel_banda_extra})"
            )
        elif self.produto == "completo":
            bandas = (
                f"{colecao.banda_nir} (NIR), {colecao.bandas_rgb[0]} (vermelho), "
                f"{colecao.bandas_rgb[1]} (verde)"
            )
        elif self.produto == "nir":
            bandas = colecao.banda_nir
        else:
            bandas = ", ".join(colecao.bandas_rgb)
        self.colecao_var.set(
            f"Coleção: {colecao.colecao} | Banda(s): {bandas} | "
            f"{colecao.nivel}"
        )
        if self.produto == "completo":
            self.aviso_var.set(
                "Cria uma pasta IMAGENS nova a cada execução (IMAGENS, "
                "IMAGENS 2, IMAGENS 3...) para não misturar resultados de "
                "rodadas diferentes."
            )
        elif fonte == "inpe" and sensor == "wpm":
            self.aviso_var.set(
                "INPE/WPM funciona, mas o arquivo não é declarado COG e pode "
                "ser mais lento. Para WPM 8 m, AWS é a opção mais eficiente."
            )
        else:
            self.aviso_var.set(
                "Largura e altura vazias preservam a resolução original."
            )

    def _selecionar_csv(self) -> None:
        caminho = filedialog.askopenfilename(
            title="Selecione o CSV",
            filetypes=[("CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if caminho:
            self.csv_var.set(caminho)

    def _selecionar_saida(self) -> None:
        caminho = filedialog.askdirectory(title="Selecione a pasta de saída")
        if caminho:
            self.saida_var.set(caminho)

    @staticmethod
    def _inteiro_opcional(valor: str, campo: str) -> int | None:
        texto = valor.strip()
        if not texto:
            return None
        try:
            numero = int(texto)
        except ValueError as exc:
            raise ErroCBERS(f"{campo} deve ser um número inteiro.") from exc
        if numero <= 0:
            raise ErroCBERS(f"{campo} deve ser maior que zero.")
        return numero

    def _montar_configuracao(self) -> ConfiguracaoExtracao:
        if not self.produto:
            raise ErroCBERS("Escolha NIR ou RGB.")
        if not self.csv_var.get().strip():
            raise ErroCBERS("Selecione o arquivo CSV.")
        if not self.saida_var.get().strip():
            raise ErroCBERS("Selecione a pasta de saída.")
        try:
            buffer_metros = float(self.buffer_var.get().replace(",", "."))
            workers = int(self.workers_var.get())
        except ValueError as exc:
            raise ErroCBERS("Buffer e downloads paralelos devem ser números.") from exc
        max_nuvens = None
        if self.max_nuvens_var.get().strip():
            try:
                max_nuvens = float(
                    self.max_nuvens_var.get().strip().replace(",", ".")
                )
            except ValueError as exc:
                raise ErroCBERS("Máximo de nuvens deve ser um número.") from exc

        cfg = ConfiguracaoExtracao(
            arquivo_csv=Path(self.csv_var.get()).expanduser(),
            pasta_saida=Path(self.saida_var.get()).expanduser(),
            produto=self.produto,
            fonte=self._codigo_fonte(),
            sensor=self._codigo_sensor(),
            data_inicial=self.data_inicial_var.get().strip(),
            data_final=self.data_final_var.get().strip(),
            buffer_metros=buffer_metros,
            epsg_entrada=self.epsg_var.get().strip(),
            criterio=ROTULOS_CRITERIO[self.criterio_var.get()],
            max_nuvens=max_nuvens,
            largura_pixels=self._inteiro_opcional(
                self.largura_var.get(), "Largura"
            ),
            altura_pixels=self._inteiro_opcional(
                self.altura_var.get(), "Altura"
            ),
            quantidade=self._inteiro_opcional(
                self.qtd_var.get(), "Quantidade"
            ),
            workers=workers,
            sobrescrever=self.sobrescrever_var.get(),
        )
        validar_configuracao(cfg)
        return cfg

    def _registrar_log(self, mensagem: str) -> None:
        self.log_texto.configure(state="normal")
        self.log_texto.insert("end", mensagem.rstrip() + "\n")
        self.log_texto.see("end")
        self.log_texto.configure(state="disabled")

    def _iniciar(self) -> None:
        if self.executando:
            return
        try:
            cfg = self._montar_configuracao()
        except ErroCBERS as exc:
            messagebox.showerror("Dados inválidos", str(exc))
            return

        self.executando = True
        self.cancelamento.clear()
        self.progresso["value"] = 0
        self.status_var.set("Iniciando...")
        self.botao_iniciar.configure(state="disabled")
        self.botao_cancelar.configure(state="normal")
        self.botao_alterar.configure(state="disabled")
        self._registrar_log(
            f"Início: {cfg.produto.upper()} | {cfg.fonte} | {cfg.sensor}"
        )

        def status(mensagem: str) -> None:
            self.eventos.put(("status", mensagem))

        def progresso(concluido, total, resultado) -> None:
            self.eventos.put(
                ("progresso", concluido, total, resultado)
            )

        def executar() -> None:
            try:
                resultados = executar_extracao(
                    cfg,
                    atualizar_status=status,
                    atualizar_progresso=progresso,
                    cancelamento=self.cancelamento,
                )
                self.eventos.put(("concluido", cfg, resultados))
            except Exception as exc:  # noqa: BLE001 - exibir falha da thread na GUI
                self.eventos.put(("erro", str(exc)))

        threading.Thread(target=executar, daemon=True).start()

    def _cancelar(self) -> None:
        if self.executando:
            self.cancelamento.set()
            self.status_var.set(
                "Cancelando. Downloads já iniciados podem terminar."
            )
            self.botao_cancelar.configure(state="disabled")

    def _processar_eventos(self) -> None:
        try:
            while True:
                evento = self.eventos.get_nowait()
                tipo = evento[0]
                if tipo == "status":
                    self.status_var.set(evento[1])
                elif tipo == "progresso":
                    _, concluido, total, resultado = evento
                    self.progresso["value"] = concluido * 100 / total
                    detalhe = (
                        f" | {resultado.item_id}" if resultado.item_id else ""
                    )
                    self._registrar_log(
                        f"[{concluido}/{total}] amostra {resultado.numero}: "
                        f"{resultado.status}{detalhe}"
                    )
                elif tipo == "concluido":
                    _, cfg, resultados = evento
                    self._finalizar()
                    resumo = resumo_resultados(resultados)
                    mensagem = (
                        f"{resumo['ok']} processada(s), "
                        f"{resumo['ignorado']} ignorada(s), "
                        f"{resumo['erro']} erro(s), "
                        f"{resumo['cancelado']} cancelada(s).\n\n"
                        f"Saída: {cfg.pasta_saida}"
                    )
                    self.status_var.set("Processamento concluído.")
                    if resumo["erro"]:
                        messagebox.showwarning("Concluído com erros", mensagem)
                    else:
                        messagebox.showinfo("Concluído", mensagem)
                elif tipo == "erro":
                    self._finalizar()
                    self.status_var.set("Falha no processamento.")
                    self._registrar_log(f"ERRO: {evento[1]}")
                    messagebox.showerror("Erro", evento[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._processar_eventos)

    def _finalizar(self) -> None:
        self.executando = False
        self.botao_iniciar.configure(state="normal")
        self.botao_cancelar.configure(state="disabled")
        self.botao_alterar.configure(state="normal")

    def _fechar(self) -> None:
        if self.executando and not messagebox.askyesno(
            "Fechar",
            "Há downloads em andamento. Deseja cancelar e fechar?",
        ):
            return
        self.cancelamento.set()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    AplicacaoCBERS(root)
    root.mainloop()


if __name__ == "__main__":
    main()
