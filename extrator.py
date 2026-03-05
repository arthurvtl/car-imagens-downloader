# extrator.py
# Script principal do pipeline de extração de imagens IntegraCar.
#
# Uso:
#   python extrator.py --csv coordenadas.csv --caminho ./saida
#   python extrator.py --csv coordenadas.csv --caminho ./saida --buffer 512 --largura 512 --altura 512 --qtd 500
#
# Todos os parâmetros têm valores padrão definidos em configuracoes.py.

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import aiohttp
import pandas as pd
from tqdm import tqdm

from configuracoes import CONFIGURACOES
from utils.manifesto import (
    inicializar_manifesto,
    registrar_resultado,
)
from utils.wms import baixar_imagem_async, calcular_bbox_latlon, conectar_wms, validar_camada


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def criar_parser() -> argparse.ArgumentParser:
    """Define e retorna o parser de argumentos da linha de comando."""

    parser = argparse.ArgumentParser(
        prog="extrator.py",
        description=(
            "Pipeline de extração de imagens georreferenciadas do GeoBases.\n"
            "Gera dois conjuntos de imagens GeoTIFF a partir de um CSV de coordenadas:\n"
            "  • SATELITE  — ortofotomosaico (imagem bruta do satélite)\n"
            "  • SEGMENTADO — mapa de uso e cobertura do solo\n\n"
            "Exemplo rápido:\n"
            "  python extrator.py --csv coordenadas.csv --caminho ./saida\n\n"
            "Exemplo completo:\n"
            "  python extrator.py \\\\\n"
            "    --csv coordenadas.csv \\\\\n"
            "    --caminho ./saida \\\\\n"
            "    --buffer 512 \\\\\n"
            "    --largura 512 \\\\\n"
            "    --altura 512 \\\\\n"
            "    --qtd 1000"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- Entrada obrigatória ---
    parser.add_argument(
        "--csv",
        metavar="ARQUIVO",
        required=True,
        help=(
            "Caminho para o arquivo CSV com as coordenadas.\n"
            "O arquivo deve conter as colunas: cod_imovel, x, y\n"
            "separadas por ponto-e-vírgula (;).\n"
            "Exemplo: coordenadas_treino_amostra.csv"
        ),
    )

    # --- Saída obrigatória ---
    parser.add_argument(
        "--caminho",
        metavar="PASTA",
        required=True,
        help=(
            "Pasta de destino das imagens extraídas.\n"
            "Serão criadas automaticamente duas subpastas:\n"
            "  • <PASTA>/SATELITE/   — imagens do ortofotomosaico\n"
            "  • <PASTA>/SEGMENTADO/ — imagens de uso do solo\n"
            "Exemplo: ./saida  ou  /tmp/imagens"
        ),
    )

    # --- Parâmetros de recorte ---
    parser.add_argument(
        "--buffer",
        metavar="METROS",
        type=int,
        default=CONFIGURACOES["buffer_metros"],
        help=(
            "Buffer em metros ao redor de cada ponto central.\n"
            "Define metade do lado do quadrado recortado.\n"
            f"Padrão: {CONFIGURACOES['buffer_metros']} m\n"
            "Exemplo: --buffer 512"
        ),
    )

    parser.add_argument(
        "--largura",
        metavar="PIXELS",
        type=int,
        default=CONFIGURACOES["largura_pixels"],
        help=(
            "Largura da imagem de saída em pixels.\n"
            f"Padrão: {CONFIGURACOES['largura_pixels']} px\n"
            "Exemplo: --largura 512"
        ),
    )

    parser.add_argument(
        "--altura",
        metavar="PIXELS",
        type=int,
        default=CONFIGURACOES["altura_pixels"],
        help=(
            "Altura da imagem de saída em pixels.\n"
            f"Padrão: {CONFIGURACOES['altura_pixels']} px\n"
            "Exemplo: --altura 512"
        ),
    )

    # --- Limite de processamento ---
    parser.add_argument(
        "--qtd",
        metavar="N",
        type=int,
        default=None,
        help=(
            "Número máximo de coordenadas a processar.\n"
            "Processa sempre as primeiras N linhas do CSV.\n"
            "Se omitido, processa todas as linhas.\n"
            "Exemplo: --qtd 1000  (processa apenas as 1000 primeiras)"
        ),
    )

    # --- Paralelismo (avançado) ---
    parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=CONFIGURACOES["workers_paralelos"],
        help=(
            "Número de downloads simultâneos (avançado).\n"
            f"Padrão: {CONFIGURACOES['workers_paralelos']}\n"
            "Reduza se tiver erros de timeout ou conexão recusada."
        ),
    )

    return parser


def validar_args(args: argparse.Namespace) -> None:
    """Valida os argumentos e encerra com mensagem clara em caso de erro."""

    # CSV
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"\n❌  ERRO: Arquivo CSV não encontrado: {csv_path.resolve()}", file=sys.stderr)
        print("     Verifique o caminho informado em --csv\n", file=sys.stderr)
        sys.exit(1)
    if csv_path.suffix.lower() not in {".csv", ".txt"}:
        print(f"\n⚠️   AVISO: O arquivo '{csv_path.name}' não tem extensão .csv.", file=sys.stderr)
        print("     Continuando mesmo assim...\n", file=sys.stderr)

    # Dimensões positivas
    for nome, valor in [("--buffer", args.buffer), ("--largura", args.largura), ("--altura", args.altura)]:
        if valor <= 0:
            print(f"\n❌  ERRO: {nome} deve ser um número inteiro positivo (recebido: {valor})\n", file=sys.stderr)
            sys.exit(1)

    # Quantidade
    if args.qtd is not None and args.qtd <= 0:
        print(f"\n❌  ERRO: --qtd deve ser um número inteiro positivo (recebido: {args.qtd})\n", file=sys.stderr)
        sys.exit(1)

    # Workers
    if args.workers <= 0:
        print(f"\n❌  ERRO: --workers deve ser um número inteiro positivo (recebido: {args.workers})\n", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def configurar_logging(pasta_logs: str, nome_log: str) -> None:
    """Configura o sistema de logging para gravar em arquivo e exibir no terminal."""
    Path(pasta_logs).mkdir(parents=True, exist_ok=True)
    caminho_log = Path(pasta_logs) / nome_log

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(caminho_log, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


async def _baixar_uma_imagem_async(
    sessao: aiohttp.ClientSession, cfg: dict, camada: str, bbox: tuple, caminho: Path
) -> str:
    """Baixa uma única imagem e retorna 'ok' ou 'erro'."""
    try:
        await baixar_imagem_async(
            sessao=sessao,
            wms_url=cfg["wms_url"],
            camada=camada,
            bbox=bbox,
            caminho_saida=caminho,
            largura_pixels=cfg["largura_pixels"],
            altura_pixels=cfg["altura_pixels"],
            srid=cfg["srid_wms"],
            wms_versao=cfg["wms_versao"],
            formato=cfg["formato_wms"],
            transparente=cfg["transparente"],
            epsg_codigo=cfg["epsg_codigo_saida"],
            timeout=cfg["timeout_requisicao"],
            tentativas=cfg["tentativas_por_imagem"],
            pausa_entre_tentativas=cfg["pausa_entre_tentativas"],
        )
        return "ok"
    except Exception as erro:
        logging.getLogger(__name__).error(f"Falha: {caminho.name} - {erro}")
        return "erro"


async def processar_amostra_async(
    sessao: aiohttp.ClientSession,
    semaforo: asyncio.Semaphore,
    numero_amostra: int,
    cod_imovel: str,
    x: float,
    y: float,
    configuracoes: dict,
) -> dict:
    """
    Processa uma única amostra: calcula o bbox, baixa SATELITE e SEGMENTADO
    em paralelo via asyncio.gather, e retorna o resultado.
    """
    async with semaforo:
        logger = logging.getLogger(__name__)
        cfg = configuracoes

        prefixo = cfg["prefixo_arquivo"]
        nome_arquivo = f"{prefixo}_{numero_amostra}.tif"

        pasta_satelite = Path(cfg["pasta_saida"]) / cfg["nome_pasta_satelite"]
        pasta_segmentado = Path(cfg["pasta_saida"]) / cfg["nome_pasta_segmentado"]

        caminho_satelite = pasta_satelite / nome_arquivo
        caminho_segmentado = pasta_segmentado / nome_arquivo

        # Calcular bbox em lat/lon
        bbox = calcular_bbox_latlon(x, y, cfg["buffer_metros"], cfg["srid_entrada"])

        # Baixar SATELITE e SEGMENTADO em paralelo
        status_satelite, status_segmentado = await asyncio.gather(
            _baixar_uma_imagem_async(
                sessao, cfg, cfg["camada_satelite"], bbox, caminho_satelite
            ),
            _baixar_uma_imagem_async(
                sessao, cfg, cfg["camada_uso_solo"], bbox, caminho_segmentado
            ),
        )

        if status_satelite == "ok":
            logger.info(f"[amostra_{numero_amostra}] SATELITE OK")
        if status_segmentado == "ok":
            logger.info(f"[amostra_{numero_amostra}] SEGMENTADO OK")

        return {
            "numero_amostra": numero_amostra,
            "cod_imovel": cod_imovel,
            "x": x,
            "y": y,
            "bbox": bbox,
            "status_satelite": status_satelite,
            "status_uso_solo": status_segmentado,
        }


async def executar_pipeline_async(cfg: dict) -> None:
    """
    Função principal assíncrona do pipeline. Orquestra conexão WMS, leitura do CSV,
    downloads assíncronos com aiohttp e registro no manifesto.
    """
    configurar_logging(CONFIGURACOES["pasta_logs"], CONFIGURACOES["nome_log"])
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Iniciando pipeline de extração IntegraCar")
    logger.info(f"  CSV           : {cfg['arquivo_csv']}")
    logger.info(f"  Pasta saída   : {cfg['pasta_saida']}")
    logger.info(f"  Buffer        : {cfg['buffer_metros']} m")
    logger.info(f"  Dimensões     : {cfg['largura_pixels']} x {cfg['altura_pixels']} px")
    if cfg.get("limite_amostras"):
        logger.info(f"  Limite        : primeiras {cfg['limite_amostras']} coordenadas")
    logger.info(f"  Workers       : {cfg['workers_paralelos']}")
    logger.info("=" * 60)

    # ---- Passo 1: Conectar ao serviço WMS do GeoBases ----
    wms = conectar_wms(cfg["wms_url"], cfg["wms_versao"])

    for nome_camada in [cfg["camada_satelite"], cfg["camada_uso_solo"]]:
        if validar_camada(wms, nome_camada):
            logger.info(f"Camada validada: {nome_camada}")
        else:
            logger.warning(f"Camada NÃO encontrada: {nome_camada}")

    # ---- Passo 2: Inicializar manifesto ----
    caminho_manifesto = Path(CONFIGURACOES["pasta_artifacts"]) / CONFIGURACOES["nome_manifesto"]
    inicializar_manifesto(caminho_manifesto)

    # ---- Passo 3: Ler CSV de coordenadas ----
    dataframe = pd.read_csv(cfg["arquivo_csv"], sep=CONFIGURACOES["separador_csv"])
    total_csv = len(dataframe)
    logger.info(f"CSV carregado: {total_csv} coordenadas encontradas")

    # Aplicar limite de quantidade, se informado
    limite = cfg.get("limite_amostras")
    if limite and limite < total_csv:
        dataframe = dataframe.head(limite)
        logger.info(f"Processando apenas as primeiras {limite} coordenadas (de {total_csv})")

    dataframe["numero_amostra"] = range(1, len(dataframe) + 1)

    # ---- Passo 4: Criar pastas de saída ----
    pasta_satelite = Path(cfg["pasta_saida"]) / cfg["nome_pasta_satelite"]
    pasta_segmentado = Path(cfg["pasta_saida"]) / cfg["nome_pasta_segmentado"]
    pasta_satelite.mkdir(parents=True, exist_ok=True)
    pasta_segmentado.mkdir(parents=True, exist_ok=True)
    logger.info(f"Pasta SATELITE  : {pasta_satelite.resolve()}")
    logger.info(f"Pasta SEGMENTADO: {pasta_segmentado.resolve()}")

    # ---- Passo 5: Processar amostras de forma assíncrona ----
    contagem_sucesso = 0
    contagem_erro = 0

    semaforo = asyncio.Semaphore(cfg["workers_paralelos"])
    conector = aiohttp.TCPConnector(
        limit=cfg["workers_paralelos"] * 2 + 4,
        limit_per_host=cfg["workers_paralelos"] * 2 + 4,
    )

    async with aiohttp.ClientSession(connector=conector) as sessao:
        tarefas = [
            processar_amostra_async(
                sessao=sessao,
                semaforo=semaforo,
                numero_amostra=row["numero_amostra"],
                cod_imovel=row["cod_imovel"],
                x=row["x"],
                y=row["y"],
                configuracoes=cfg,
            )
            for _, row in dataframe.iterrows()
        ]

        with tqdm(total=len(tarefas), desc="Baixando imagens", unit="img") as barra:
            for coroutine in asyncio.as_completed(tarefas):
                resultado = await coroutine

                registrar_resultado(
                    caminho_manifesto=caminho_manifesto,
                    numero_amostra=resultado["numero_amostra"],
                    cod_imovel=resultado["cod_imovel"],
                    x=resultado["x"],
                    y=resultado["y"],
                    bbox=resultado["bbox"],
                    status_satelite=resultado["status_satelite"],
                    status_uso_solo=resultado["status_uso_solo"],
                )

                if resultado["status_satelite"] == "ok" and resultado["status_uso_solo"] == "ok":
                    contagem_sucesso += 1
                else:
                    contagem_erro += 1

                barra.update(1)

    logger.info("=" * 60)
    logger.info("Pipeline concluído.")
    logger.info(f"  Pares completos (ok/ok) : {contagem_sucesso}")
    logger.info(f"  Com erro                 : {contagem_erro}")
    logger.info(f"  Manifesto salvo em       : {caminho_manifesto}")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = criar_parser()
    args = parser.parse_args()
    validar_args(args)

    # Construir configuração mesclando defaults com argumentos do usuário
    cfg = dict(CONFIGURACOES)
    cfg["arquivo_csv"] = args.csv
    cfg["pasta_saida"] = args.caminho
    cfg["buffer_metros"] = args.buffer
    cfg["largura_pixels"] = args.largura
    cfg["altura_pixels"] = args.altura
    cfg["workers_paralelos"] = args.workers
    cfg["limite_amostras"] = args.qtd  # None = sem limite

    # Nomes das pastas de saída (fixos, padronizados)
    cfg["nome_pasta_satelite"] = "SATELITE"
    cfg["nome_pasta_segmentado"] = "SEGMENTADO"

    asyncio.run(executar_pipeline_async(cfg))


if __name__ == "__main__":
    main()
