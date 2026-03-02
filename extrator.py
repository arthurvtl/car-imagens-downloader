# extrator.py
# Script principal do pipeline de extração de imagens IntegraCar.
# Execução: python extrator.py
#
# Otimizado para velocidade máxima:
# - Downloads assíncronos com asyncio + aiohttp (zero overhead de threads)
# - SEM COR e COM COR baixados simultaneamente via asyncio.gather
# - Semaphore para limitar concorrência de amostras
# - GeoTIFF salvo em thread executor (CPU-bound offload)

import asyncio
import logging
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
    Processa uma única amostra: calcula o bbox, baixa SEM COR e COM COR
    em paralelo via asyncio.gather, e retorna o resultado.
    """
    async with semaforo:
        logger = logging.getLogger(__name__)
        cfg = configuracoes

        prefixo = cfg["prefixo_arquivo"]
        nome_arquivo = f"{prefixo}_{numero_amostra}.tif"

        pasta_sem_cor = Path(cfg["pasta_saida"]) / cfg["nome_pasta_sem_cor"]
        pasta_com_cor = Path(cfg["pasta_saida"]) / cfg["nome_pasta_com_cor"]

        caminho_satelite = pasta_sem_cor / nome_arquivo
        caminho_uso_solo = pasta_com_cor / nome_arquivo

        # Calcular bbox em lat/lon
        bbox = calcular_bbox_latlon(x, y, cfg["buffer_metros"], cfg["srid_entrada"])

        # Baixar SEM COR e COM COR em paralelo via asyncio.gather
        status_satelite, status_uso_solo = await asyncio.gather(
            _baixar_uma_imagem_async(
                sessao, cfg, cfg["camada_satelite"], bbox, caminho_satelite
            ),
            _baixar_uma_imagem_async(
                sessao, cfg, cfg["camada_uso_solo"], bbox, caminho_uso_solo
            ),
        )

        if status_satelite == "ok":
            logger.info(f"[amostra_{numero_amostra}] SEM COR OK")
        if status_uso_solo == "ok":
            logger.info(f"[amostra_{numero_amostra}] COM COR OK")

        return {
            "numero_amostra": numero_amostra,
            "cod_imovel": cod_imovel,
            "x": x,
            "y": y,
            "bbox": bbox,
            "status_satelite": status_satelite,
            "status_uso_solo": status_uso_solo,
        }


async def executar_pipeline_async() -> None:
    """
    Função principal assíncrona do pipeline. Orquestra conexão WMS, leitura do CSV,
    downloads assíncronos com aiohttp e registro no manifesto.
    """
    cfg = CONFIGURACOES

    configurar_logging(cfg["pasta_logs"], cfg["nome_log"])
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Iniciando pipeline de extração IntegraCar (modo ASYNC)")
    logger.info(f"Workers paralelos: {cfg['workers_paralelos']}")
    logger.info("=" * 60)

    # ---- Passo 1: Conectar ao serviço WMS do GeoBases ----
    wms = conectar_wms(cfg["wms_url"], cfg["wms_versao"])

    # Validar camadas
    for nome_camada in [cfg["camada_satelite"], cfg["camada_uso_solo"]]:
        if validar_camada(wms, nome_camada):
            logger.info(f"Camada validada: {nome_camada}")
        else:
            logger.warning(f"Camada NÃO encontrada: {nome_camada}")

    # ---- Passo 2: Inicializar manifesto ----
    caminho_manifesto = Path(cfg["pasta_artifacts"]) / cfg["nome_manifesto"]
    inicializar_manifesto(caminho_manifesto)

    # ---- Passo 3: Ler CSV de coordenadas ----
    dataframe = pd.read_csv(cfg["arquivo_csv"], sep=cfg["separador_csv"])
    total_amostras = len(dataframe)
    logger.info(f"CSV carregado: {total_amostras} amostras encontradas")

    dataframe["numero_amostra"] = range(1, total_amostras + 1)

    dataframe_pendente = dataframe

    # ---- Passo 5: Criar pastas de saída ----
    pasta_sem_cor = Path(cfg["pasta_saida"]) / cfg["nome_pasta_sem_cor"]
    pasta_com_cor = Path(cfg["pasta_saida"]) / cfg["nome_pasta_com_cor"]
    pasta_sem_cor.mkdir(parents=True, exist_ok=True)
    pasta_com_cor.mkdir(parents=True, exist_ok=True)

    # ---- Passo 6: Processar amostras de forma assíncrona ----
    contagem_sucesso = 0
    contagem_erro = 0

    # Semáforo limita quantas amostras são processadas simultaneamente
    semaforo = asyncio.Semaphore(cfg["workers_paralelos"])

    # Conector TCP com pool de conexões dimensionado para o paralelismo
    conector = aiohttp.TCPConnector(
        limit=cfg["workers_paralelos"] * 2 + 4,
        limit_per_host=cfg["workers_paralelos"] * 2 + 4,
    )

    async with aiohttp.ClientSession(connector=conector) as sessao:
        logger.info(
            f"Sessão aiohttp criada com pool de "
            f"{cfg['workers_paralelos'] * 2 + 4} conexões"
        )

        # Criar todas as tarefas assíncronas
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
            for _, row in dataframe_pendente.iterrows()
        ]

        # Executar com barra de progresso
        with tqdm(total=len(tarefas), desc="Baixando imagens", unit="amostra") as barra:
            for coroutine in asyncio.as_completed(tarefas):
                resultado = await coroutine

                # Registrar resultado no manifesto (síncrono, rápido)
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
    logger.info(f"Pares completos (ok/ok): {contagem_sucesso}")
    logger.info(f"Com erro: {contagem_erro}")
    logger.info(f"Manifesto salvo em: {caminho_manifesto}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(executar_pipeline_async())
