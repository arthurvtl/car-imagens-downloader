"""
src.core.pipeline
Orquestrador principal do pipeline multi-satélite.

Para cada coordenada do CSV:
  1. Calcula bbox
  2. Busca imagens (STAC ou WMS)
  3. Seleciona melhor cena (menor nuvem)
  4. Baixa bandas necessárias
  5. Salva GeoTIFF
  6. Opcionalmente baixa camada segmentada (WMS)
  7. Registra no manifesto
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

import aiohttp
import pandas as pd
from tqdm import tqdm

from src.core.config import PipelineConfig, load_config
from src.core.manifest import (
    carregar_amostras_processadas,
    inicializar_manifesto,
    registrar_resultado,
)
from src.processing.coordinates import calcular_bbox_latlon
from src.satellites.base import BaseSatellite
from src.satellites.kompsat import KompsatProvider, _build_wms_params
from src.satellites.registry import get_provider

logger = logging.getLogger(__name__)


def configurar_logging(pasta_logs: str, nome_log: str) -> None:
    """Configura logging em arquivo + terminal."""
    Path(pasta_logs).mkdir(parents=True, exist_ok=True)
    caminho = Path(pasta_logs) / nome_log

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        root.addHandler(logging.FileHandler(caminho, encoding="utf-8"))
        root.addHandler(logging.StreamHandler())
        for h in root.handlers:
            h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))


async def _download_segmented_layer(
    session: aiohttp.ClientSession,
    config: PipelineConfig,
    bbox: tuple[float, float, float, float],
    output_path: Path,
) -> str:
    """Baixa camada segmentada via WMS (GeoBases ES)."""
    from src.processing.geotiff import save_png_as_geotiff

    params = _build_wms_params(
        camada=config.camada_segmentada,
        bbox=bbox,
        width=config.largura_pixels,
        height=config.altura_pixels,
        srid="EPSG:4326",
        versao=config.wms_versao,
        formato=config.wms_formato,
        transparente=config.wms_transparente,
    )

    timeout = aiohttp.ClientTimeout(total=config.timeout_requisicao)

    for attempt in range(1, config.tentativas_por_imagem + 1):
        try:
            async with session.get(
                config.wms_url, params=params, timeout=timeout
            ) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "")
                if "xml" in ct or "text" in ct:
                    body = await resp.text()
                    raise RuntimeError(f"WMS retornou erro: {body[:300]}")
                content = await resp.read()

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                save_png_as_geotiff,
                content, output_path, bbox,
                config.largura_pixels, config.altura_pixels, config.epsg_saida,
            )
            return "ok"

        except Exception as e:
            logger.warning(f"Segmentada tentativa {attempt}: {e}")
            if attempt < config.tentativas_por_imagem:
                await asyncio.sleep(config.pausa_entre_tentativas)

    return "erro"


async def processar_amostra(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    provider: BaseSatellite,
    config: PipelineConfig,
    numero: int,
    cod_imovel: str,
    x: float,
    y: float,
) -> dict[str, Any]:
    """Processa uma única coordenada: busca → download satélite [→ segmentada]."""
    async with semaphore:
        prefixo = config.prefixo_arquivo
        nome = f"{prefixo}_{numero}.tif"

        pasta_sat = Path(config.pasta_saida) / "SATELITE"
        caminho_sat = pasta_sat / nome

        bbox = calcular_bbox_latlon(x, y, config.buffer_metros, config.srid_entrada)
        date_range = f"{config.date_start}/{config.date_end}"

        # --- Busca e seleção ---
        items = provider.search(bbox, date_range, config.cloud_cover_max)
        best = provider.select_best_item(items)

        item_id = ""
        cloud = ""

        if best is None and provider.satellite_type == "stac":
            logger.warning(f"[amostra_{numero}] Nenhuma cena encontrada.")
            return {
                "numero_amostra": numero,
                "cod_imovel": cod_imovel,
                "x": x, "y": y,
                "bbox": bbox,
                "status_satelite": "sem_cena",
                "status_segmentada": "n/a",
                "item_id": "",
                "cloud_cover": "",
            }

        if best is not None and hasattr(best, "id"):
            item_id = best.id
            cloud = best.properties.get("eo:cloud_cover", "")

        assets = provider.get_assets(best)

        # --- Download satélite ---
        status_sat = await provider.download(
            session, assets, caminho_sat, bbox,
            config.largura_pixels, config.altura_pixels,
        )
        if status_sat == "ok":
            logger.info(f"[amostra_{numero}] {provider.name.upper()} OK")

        # --- Download segmentada (opcional) ---
        status_seg = "n/a"
        if config.download_segmentada:
            pasta_seg = Path(config.pasta_saida) / "SEGMENTADO"
            pasta_seg.mkdir(parents=True, exist_ok=True)
            caminho_seg = pasta_seg / nome
            status_seg = await _download_segmented_layer(
                session, config, bbox, caminho_seg,
            )
            if status_seg == "ok":
                logger.info(f"[amostra_{numero}] SEGMENTADO OK")

        return {
            "numero_amostra": numero,
            "cod_imovel": cod_imovel,
            "x": x, "y": y,
            "bbox": bbox,
            "status_satelite": status_sat,
            "status_segmentada": status_seg,
            "item_id": item_id,
            "cloud_cover": cloud,
        }


async def executar_pipeline(
    config: PipelineConfig,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """
    Pipeline principal assíncrono multi-satélite.

    Retorna contadores {"sucesso": N, "erro": M, "total": T}.
    """
    configurar_logging(config.pasta_logs, config.nome_log)

    logger.info("=" * 60)
    logger.info("Pipeline Multi-Satélite IntegraCar")
    logger.info(f"  Satélite      : {config.satellite_name}")
    logger.info(f"  CSV           : {config.arquivo_csv}")
    logger.info(f"  Pasta saída   : {config.pasta_saida}")
    logger.info(f"  Buffer        : {config.buffer_metros} m")
    logger.info(f"  Dimensões     : {config.largura_pixels}x{config.altura_pixels} px")
    logger.info(f"  Cloud max     : {config.cloud_cover_max}%")
    logger.info(f"  Segmentada    : {'sim' if config.download_segmentada else 'não'}")
    logger.info(f"  Workers       : {config.workers_paralelos}")
    logger.info("=" * 60)

    if log_callback:
        log_callback(f"Satélite: {config.satellite_name} | Iniciando pipeline...")

    # Instanciar provedor
    provider = get_provider(config.satellite_name, config)

    # Manifesto
    caminho_manifesto = Path(config.pasta_artifacts) / config.nome_manifesto
    inicializar_manifesto(caminho_manifesto)
    ja_processadas = carregar_amostras_processadas(caminho_manifesto)

    # Ler CSV
    df = pd.read_csv(config.arquivo_csv, sep=config.separador_csv)
    total_csv = len(df)
    logger.info(f"CSV carregado: {total_csv} coordenadas")

    if config.limite_amostras and config.limite_amostras < total_csv:
        df = df.head(config.limite_amostras)
        logger.info(f"Limitado a {config.limite_amostras} coordenadas")

    df["numero_amostra"] = range(1, len(df) + 1)

    # Filtrar já processadas
    df = df[~df["numero_amostra"].isin(ja_processadas)]
    if df.empty:
        logger.info("Todas as amostras já foram processadas.")
        return {"sucesso": 0, "erro": 0, "total": 0}

    # Criar pastas
    pasta_sat = Path(config.pasta_saida) / "SATELITE"
    pasta_sat.mkdir(parents=True, exist_ok=True)

    if config.download_segmentada:
        pasta_seg = Path(config.pasta_saida) / "SEGMENTADO"
        pasta_seg.mkdir(parents=True, exist_ok=True)

    # Pipeline assíncrono
    semaphore = asyncio.Semaphore(config.workers_paralelos)
    connector = aiohttp.TCPConnector(
        limit=config.workers_paralelos * 2 + 4,
        limit_per_host=config.workers_paralelos * 2 + 4,
    )

    sucesso = 0
    erro = 0
    total = len(df)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            processar_amostra(
                session=session,
                semaphore=semaphore,
                provider=provider,
                config=config,
                numero=row["numero_amostra"],
                cod_imovel=str(row.get("cod_imovel", "")),
                x=row["x"],
                y=row["y"],
            )
            for _, row in df.iterrows()
        ]

        with tqdm(total=total, desc=f"Baixando ({provider.name})", unit="img") as bar:
            for coro in asyncio.as_completed(tasks):
                result = await coro

                registrar_resultado(
                    caminho=caminho_manifesto,
                    numero_amostra=result["numero_amostra"],
                    cod_imovel=result["cod_imovel"],
                    x=result["x"],
                    y=result["y"],
                    bbox=result["bbox"],
                    satelite=config.satellite_name,
                    status_satelite=result["status_satelite"],
                    status_segmentada=result["status_segmentada"],
                    item_id=result.get("item_id", ""),
                    cloud_cover=result.get("cloud_cover", ""),
                )

                if result["status_satelite"] == "ok":
                    sucesso += 1
                else:
                    erro += 1

                bar.update(1)
                if progress_callback:
                    progress_callback(sucesso + erro, total)

    logger.info("=" * 60)
    logger.info("Pipeline concluído.")
    logger.info(f"  Sucesso  : {sucesso}")
    logger.info(f"  Erro     : {erro}")
    logger.info(f"  Total    : {total}")
    logger.info(f"  Manifesto: {caminho_manifesto}")
    logger.info("=" * 60)

    return {"sucesso": sucesso, "erro": erro, "total": total}


def run_pipeline(
    config: PipelineConfig,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Wrapper síncrono para chamar o pipeline assíncrono."""
    return asyncio.run(executar_pipeline(config, progress_callback, log_callback))
