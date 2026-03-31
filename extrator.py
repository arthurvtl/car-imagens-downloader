"""
A GUI permite:
- Selecionar o CSV de entrada
- Escolher a pasta de saída
- Definir o buffer em metros e a quantidade de imagens
- Selecionar o ano de processamento (2012 ou 2019-2020)
- Opcionalmente manter os arquivos do shapefile temporário (apenas 2012)
"""

import asyncio
import logging
import os
import threading
import time
import zipfile
from pathlib import Path

import aiohttp
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.features import rasterize
from shapely.geometry import Point
from tqdm import tqdm

from configuracoes import CONFIGURACOES
from utils.manifesto import (
    inicializar_manifesto,
    registrar_resultado,
)
from utils.wms import baixar_imagem_async, calcular_bbox_latlon, conectar_wms, validar_camada
from analisa_img_12_15 import analisar_imagens_uso_solo

import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ---------------------------------------------------------------------------
# Paleta oficial de cores do uso do solo 2012 (RGB)
# ---------------------------------------------------------------------------

CORES_CLASSES_RGB = {
    # Nomes padrão do WMS (2019-2020) com as novas cores
    "Afloramento Rochoso": (150, 150, 150),
    "Área Edificada": (251, 154, 153),
    "Brejo": (69, 175, 213),
    "Campo Rupestre/Altitude": (150, 109, 207),
    "Cultivo Agrícola - Abacaxi": (128, 214, 16),
    "Cultivo Agrícola - Banana": (247, 223, 8),
    "Cultivo Agrícola - Café": (119, 9, 29),
    "Cultivo Agrícola - Cana-de-Açúcar": (209, 163, 117),
    "Cultivo Agrícola - Coco-da-Baía": (231, 67, 97),
    "Cultivo Agrícola - Mamão": (245, 141, 23),
    "Outros Cultivos Permanentes": (55, 196, 201),
    "Outros Cultivos Temporários": (225, 175, 38),
    "Extração Mineração": (81, 77, 77),
    "Macega": (211, 127, 122),
    "Mangue": (156, 68, 203),
    "Massa D'Água": (133, 196, 221),
    "Mata Nativa": (13, 103, 19),
    "Mata em Regeneração": (51, 160, 44),
    "Outros": (31, 205, 170),
    "Pastagem": (178, 214, 32),
    "Eucalipto": (207, 103, 65),
    "Pinus": (243, 184, 129),
    "Seringueira": (151, 132, 233),
    "Restinga": (63, 231, 161),
    "Solo Exposto": (245, 222, 193),

    # ---> MAPEAMENTO DE NOMES ANTIGOS (SHAPEFILE 2012) <---
    # Apontando para as mesmas cores novas acima
    "Mata Nativa em Estágio Inicial de Regeneração": (51, 160, 44),  # Vai para Mata em Regeneração
    "Cultivo Agrícola - Outros Cultivos Permanentes": (55, 196, 201),
    "Reflorestamento - Eucalipto": (207, 103, 65),
    "Cultivo Agrícola - Coco-Da-Baía": (231, 67, 97),  # Diferença no "Da" maiúsculo
    "Cultivo Agrícola - Cana-De-Açúcar": (209, 163, 117),  # Diferença no "De" maiúsculo
    "Reflorestamento - Seringueira": (151, 132, 233),
    "Reflorestamento - Pinus": (243, 184, 129),
    "Cultivo Agrícola - Outros Cultivos Temporários": (225, 175, 38),
}

# ---------------------------------------------------------------------------
# Logging e pipeline principal (mantido do fluxo original)
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
    Processa uma única amostra: calcula o bbox, baixa SATELITE e USO_SOLO
    em paralelo via asyncio.gather, e retorna o resultado.
    Ambos os arquivos ficam na mesma pasta de saída.
    """
    async with semaforo:
        logger = logging.getLogger(__name__)
        cfg = configuracoes

        pasta = Path(cfg["pasta_saida"])
        caminho_satelite = pasta / f"amostra_{numero_amostra}_satelite_1920.tif"
        caminho_uso_solo = pasta / f"amostra_{numero_amostra}_uso_solo_1920.tif"

        bbox = calcular_bbox_latlon(x, y, cfg["buffer_metros"], cfg["srid_entrada"])

        status_satelite, status_uso_solo = await asyncio.gather(
            _baixar_uma_imagem_async(
                sessao, cfg, cfg["camada_satelite"], bbox, caminho_satelite
            ),
            _baixar_uma_imagem_async(
                sessao, cfg, cfg["camada_uso_solo"], bbox, caminho_uso_solo
            ),
        )

        if status_satelite == "ok":
            logger.info(f"[amostra_{numero_amostra}] SATELITE 1920 OK")
        if status_uso_solo == "ok":
            logger.info(f"[amostra_{numero_amostra}] USO_SOLO 1920 OK")

        return {
            "numero_amostra": numero_amostra,
            "cod_imovel": cod_imovel,
            "x": x,
            "y": y,
            "bbox": bbox,
            "status_satelite": status_satelite,
            "status_uso_solo": status_uso_solo,
        }


async def executar_pipeline_async(cfg: dict) -> None:
    """
    Função principal assíncrona do pipeline WMS (2019-2020).
    Orquestra conexão WMS, leitura do CSV, downloads assíncronos com aiohttp
    e registro no manifesto.
    """
    configurar_logging(CONFIGURACOES["pasta_logs"], CONFIGURACOES["nome_log"])
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Iniciando pipeline de extração IntegraCar (2019-2020)")
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
    caminho_manifesto = (
        Path(CONFIGURACOES["pasta_artifacts"]) / CONFIGURACOES["nome_manifesto"]
    )
    inicializar_manifesto(caminho_manifesto)

    # ---- Passo 3: Ler CSV de coordenadas ----
    dataframe = pd.read_csv(
        cfg["arquivo_csv"], sep=CONFIGURACOES["separador_csv"]
    )
    total_csv = len(dataframe)
    logger.info(f"CSV carregado: {total_csv} coordenadas encontradas")

    # Aplicar limite de quantidade, se informado
    limite = cfg.get("limite_amostras")
    if limite and limite < total_csv:
        dataframe = dataframe.head(limite)
        logger.info(
            f"Processando apenas as primeiras {limite} coordenadas (de {total_csv})"
        )

    dataframe["numero_amostra"] = range(1, len(dataframe) + 1)

    # ---- Passo 4: Criar pasta de saída ----
    pasta_saida = Path(cfg["pasta_saida"])
    pasta_saida.mkdir(parents=True, exist_ok=True)
    logger.info(f"Pasta de saída: {pasta_saida.resolve()}")

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

                if (
                    resultado["status_satelite"] == "ok"
                    and resultado["status_uso_solo"] == "ok"
                ):
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
# Processamento específico por ano
# ---------------------------------------------------------------------------


def processar_ano_2019_2020(
    arquivo_csv: str,
    pasta_saida: str,
    buffer_metros: int,
    qtd_imagens: int | None,
) -> None:
    """
    Mantém o fluxo original do pipeline WMS (2019-2020), apenas recebendo
    os parâmetros a partir da interface gráfica.
    """
    cfg = dict(CONFIGURACOES)
    cfg["arquivo_csv"] = arquivo_csv
    cfg["pasta_saida"] = pasta_saida
    cfg["buffer_metros"] = buffer_metros
    cfg["largura_pixels"] = CONFIGURACOES["largura_pixels"]
    cfg["altura_pixels"] = CONFIGURACOES["altura_pixels"]
    cfg["workers_paralelos"] = CONFIGURACOES["workers_paralelos"]
    cfg["limite_amostras"] = qtd_imagens  # None = sem limite

    asyncio.run(executar_pipeline_async(cfg))


def processar_ano_2012(
    arquivo_csv: str,
    pasta_saida: str,
    buffer_metros: int,
    qtd_imagens: int | None,
    manter_shapefile: bool,
    atualizar_status,
    atualizar_progresso,
) -> None:
    """
    Pipeline de processamento espacial para o ano de 2012.

    Para cada ponto do CSV:
    - Calcula o bbox em EPSG:4326 a partir de x,y em EPSG:31984 e do buffer.
    - (Passo A) Baixa a imagem de satélite 2012 via WMS para esse bbox.
    - (Passo B) Rasteriza o uso do solo (shapefile 2012) dentro do mesmo bbox
      em uma grade com exatamente a mesma dimensão e transformação espacial.
    """
    logger = logging.getLogger(__name__)
    configurar_logging(CONFIGURACOES["pasta_logs"], CONFIGURACOES["nome_log"])

    t_pipeline_inicio = time.time()

    url_zip = CONFIGURACOES["url_shapefile_2012"]
    pasta_temp = Path(CONFIGURACOES["pasta_temp_shapefile"])
    pasta_temp.mkdir(parents=True, exist_ok=True)
    caminho_zip = pasta_temp.with_suffix(".zip")

    largura = CONFIGURACOES["largura_pixels"]
    altura = CONFIGURACOES["altura_pixels"]
    srid_wms = CONFIGURACOES["srid_wms"]
    epsg_saida = CONFIGURACOES["epsg_codigo_saida"]

    # ---------------- Download do ZIP do shapefile ----------------
    t0 = time.time()
    msg = "[ETAPA 1/6] Baixando shapefile 2012..."
    print(msg)
    atualizar_status(msg)
    try:
        with requests.get(url_zip, stream=True) as resposta:
            resposta.raise_for_status()
            tamanho_total = int(resposta.headers.get("Content-Length", 0)) or None
            bytes_baixados = 0
            chunk_size = 8192

            mode_progress = "determinate" if tamanho_total else "indeterminate"
            atualizar_progresso(mode_progress, value=0, maximum=tamanho_total or 100)

            with open(caminho_zip, "wb") as arquivo_zip:
                for chunk in resposta.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    arquivo_zip.write(chunk)
                    if tamanho_total:
                        bytes_baixados += len(chunk)
                        atualizar_progresso(
                            "determinate",
                            value=bytes_baixados,
                            maximum=tamanho_total,
                        )
    except Exception as exc:
        logger.error(f"Falha no download do shapefile 2012: {exc}")
        atualizar_status("Erro ao baixar shapefile 2012. Veja o log.")
        return
    print(f"  -> Shapefile baixado em {time.time() - t0:.1f}s")

    # ---------------- Extração do ZIP ----------------
    t0 = time.time()
    msg = "[ETAPA 2/6] Extraindo shapefile 2012..."
    print(msg)
    atualizar_status(msg)
    with zipfile.ZipFile(caminho_zip, "r") as zip_ref:
        zip_ref.extractall(pasta_temp)

    shapefile_encontrado = None
    for raiz, _, arquivos in os.walk(pasta_temp):
        for nome_arquivo in arquivos:
            if nome_arquivo.lower().endswith(".shp"):
                shapefile_encontrado = Path(raiz) / nome_arquivo
                break
        if shapefile_encontrado:
            break

    if shapefile_encontrado is None:
        logger.error("Nenhum arquivo .shp foi encontrado no ZIP extraído.")
        atualizar_status("Erro: shapefile 2012 não encontrado no ZIP.")
        return
    print(f"  -> Extraído em {time.time() - t0:.1f}s")

    # ---------------- Leitura do CSV ----------------
    msg = "[ETAPA 3/6] Lendo CSV de coordenadas..."
    print(msg)
    atualizar_status(msg)
    df = pd.read_csv(arquivo_csv, sep=";")

    if "x" not in df.columns or "y" not in df.columns:
        raise ValueError("O CSV deve conter as colunas 'x' e 'y'.")

    if qtd_imagens is not None and qtd_imagens > 0:
        df = df.head(qtd_imagens)

    total_pontos = len(df)
    if total_pontos == 0:
        atualizar_status("Nenhum ponto encontrado no CSV para 2012.")
        return
    print(f"  -> {total_pontos} coordenadas para processar")

    # ---------------- Leitura e preparação do shapefile ----------------
    t0 = time.time()
    msg = "[ETAPA 4/6] Carregando shapefile na memória e reprojetando..."
    print(msg)
    atualizar_status(msg)
    gdf_uso_solo = gpd.read_file(shapefile_encontrado)
    print(
        f"  Colunas do shapefile: {gdf_uso_solo.columns.tolist()}"
    )

    if gdf_uso_solo.crs is None:
        raise ValueError("O shapefile 2012 não possui CRS definido.")

    gdf_uso_solo = gdf_uso_solo.to_crs(srid_wms)
    print(f"  -> Shapefile carregado e reprojetado em {time.time() - t0:.1f}s")

    colunas_lower = {
        col.lower().strip(): col for col in gdf_uso_solo.columns
    }
    col_id = colunas_lower.get("código") or colunas_lower.get("codigo") or colunas_lower.get("c")
    col_classe = colunas_lower.get("classe")

    if not col_id or not col_classe:
        raise ValueError(
            "Colunas de ID ou Classe não encontradas. "
            f"Colunas disponíveis no shapefile: {gdf_uso_solo.columns.tolist()}"
        )

    id_para_rgb: dict[int, tuple[int, int, int]] = {0: (0, 0, 0)}
    for _, linha in gdf_uso_solo[[col_id, col_classe]].drop_duplicates().iterrows():
        try:
            classe_id = int(linha[col_id])
        except Exception:
            continue
        nome_classe = str(linha[col_classe]).strip()
        cor = CORES_CLASSES_RGB.get(nome_classe)
        if cor is not None:
            id_para_rgb[classe_id] = cor

    t_preparacao = time.time() - t_pipeline_inicio
    print(f"\n{'='*60}")
    print(f"  Preparação total: {t_preparacao:.1f}s")
    print(f"  Iniciando download das {total_pontos} imagens...")
    print(f"{'='*60}\n")

    pasta_saida_path = Path(pasta_saida)
    pasta_saida_path.mkdir(parents=True, exist_ok=True)

    msg = f"[ETAPA 5/6] Baixando imagens (0/{total_pontos})..."
    print(msg)
    atualizar_status(msg)
    atualizar_progresso("determinate", value=0, maximum=total_pontos)

    # ---------------- Loop por ponto ----------------
    t_imagens_inicio = time.time()
    tempos_por_amostra: list[float] = []

    for idx, row in df.iterrows():
        numero_amostra = idx + 1
        x = float(row["x"])
        y = float(row["y"])
        t_amostra = time.time()

        try:
            minx, miny, maxx, maxy = calcular_bbox_latlon(
                x, y, buffer_metros, CONFIGURACOES["srid_entrada"]
            )

            gdf_recorte = gdf_uso_solo.cx[minx:maxx, miny:maxy]
            if gdf_recorte.empty:
                print(f"  [amostra_{numero_amostra}] PULADA (sem polígono no bbox)")
                logger.warning(
                    f"[2012][amostra_{numero_amostra}] Nenhum polígono de uso do solo no bbox, ponto pulado."
                )
                continue

            caminho_satelite = (
                pasta_saida_path / f"amostra_{numero_amostra}_satelite_2012.tif"
            )
            caminho_uso_solo = (
                pasta_saida_path / f"amostra_{numero_amostra}_uso_solo_2012.tif"
            )

            # Passo A - Satélite via WMS
            async def _baixar_satelite():
                cfg = dict(CONFIGURACOES)
                cfg["largura_pixels"] = largura
                cfg["altura_pixels"] = altura
                async with aiohttp.ClientSession() as sessao:
                    await baixar_imagem_async(
                        sessao=sessao,
                        wms_url=cfg["wms_url"],
                        camada=cfg["camada_satelite_2012"],
                        bbox=(minx, miny, maxx, maxy),
                        caminho_saida=caminho_satelite,
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

            try:
                asyncio.run(_baixar_satelite())
            except Exception as exc:
                print(f"  [amostra_{numero_amostra}] ERRO satélite: {exc}")
                logger.error(
                    f"[2012][amostra_{numero_amostra}] Falha ao baixar satélite via WMS: {exc}"
                )
                continue

            # Passo B - Rasterização do uso do solo
            transform = from_bounds(minx, miny, maxx, maxy, largura, altura)

            shapes = []
            for geom, classe_id_val in zip(
                gdf_recorte.geometry, gdf_recorte[col_id]
            ):
                if geom is None:
                    continue
                try:
                    cid = int(classe_id_val)
                except Exception:
                    continue
                shapes.append((geom, cid))

            if not shapes:
                print(f"  [amostra_{numero_amostra}] PULADA (sem geometrias válidas)")
                logger.warning(
                    f"[2012][amostra_{numero_amostra}] Sem geometrias válidas para rasterizar, ponto pulado."
                )
                continue

            ids_array = rasterize(
                shapes=shapes,
                out_shape=(altura, largura),
                transform=transform,
                fill=0,
                dtype="uint8",
            )

            rgb_array = np.zeros((3, altura, largura), dtype=np.uint8)
            for classe_id, cor in id_para_rgb.items():
                r, g, b = cor
                mascara = ids_array == classe_id
                if not np.any(mascara):
                    continue
                rgb_array[0][mascara] = r
                rgb_array[1][mascara] = g
                rgb_array[2][mascara] = b

            with rasterio.open(
                caminho_uso_solo,
                "w",
                driver="GTiff",
                height=altura,
                width=largura,
                count=3,
                dtype="uint8",
                crs=CRS.from_epsg(epsg_saida),
                transform=transform,
                compress="lzw",
                photometric="RGB",
            ) as dst:
                dst.write(rgb_array)

            dt = time.time() - t_amostra
            tempos_por_amostra.append(dt)
            media = sum(tempos_por_amostra) / len(tempos_por_amostra)
            restante = (total_pontos - numero_amostra) * media

            print(
                f"  [amostra_{numero_amostra}/{total_pontos}] OK em {dt:.1f}s "
                f"(média {media:.1f}s/img — restante ~{restante:.0f}s)"
            )
            logger.info(f"[2012][amostra_{numero_amostra}] OK em {dt:.1f}s")

        except Exception as exc:
            print(f"  [amostra_{numero_amostra}] ERRO: {exc}")
            logger.error(
                f"[2012][amostra_{numero_amostra}] Erro no processamento do ponto: {exc}"
            )
            continue
        finally:
            atualizar_progresso(
                "determinate", value=numero_amostra, maximum=total_pontos
            )

    t_imagens_total = time.time() - t_imagens_inicio
    media_final = t_imagens_total / max(len(tempos_por_amostra), 1)
    print(f"\n{'='*60}")
    print(f"  Imagens processadas: {len(tempos_por_amostra)}/{total_pontos}")
    print(f"  Tempo total imagens: {t_imagens_total:.1f}s")
    print(f"  Média por imagem:    {media_final:.2f}s")
    print(f"{'='*60}\n")

    # ---------------- Análise de cobertura das imagens ----------------
    msg = "[ETAPA 6/6] Analisando cobertura das imagens de uso do solo..."
    print(msg)
    atualizar_status(msg)
    try:
        pasta_relatorios = Path(CONFIGURACOES["pasta_artifacts"])
        resultado_analise = analisar_imagens_uso_solo(
            pasta_imagens=pasta_saida_path,
            arquivo_csv=arquivo_csv,
            pasta_relatorios=pasta_relatorios,
            qtd_imagens=qtd_imagens,
            callback_progresso=atualizar_progresso,
            callback_status=atualizar_status,
        )
        logger.info(
            f"[2012] Análise: {resultado_analise['cheias']} cheias, "
            f"{resultado_analise['incompletas']} incompletas"
        )
    except Exception as exc:
        logger.error(f"Erro na análise de cobertura: {exc}")
        atualizar_status(f"Erro na análise: {exc}")

    # ---------------- Limpeza opcional ----------------
    if not manter_shapefile:
        atualizar_status("Limpando arquivos temporários...")
        try:
            if pasta_temp.exists():
                shutil.rmtree(pasta_temp, ignore_errors=True)
            if caminho_zip.exists():
                caminho_zip.unlink()
        except Exception as exc:
            logger.warning(f"Falha ao limpar arquivos temporários de 2012: {exc}")

    t_total = time.time() - t_pipeline_inicio
    msg_final = (
        f"Pipeline 2012 concluído em {t_total:.0f}s "
        f"(preparação: {t_preparacao:.0f}s + imagens: {t_imagens_total:.0f}s)"
    )
    print(f"\n{msg_final}")
    logger.info(msg_final)
    atualizar_status(msg_final)


# ---------------------------------------------------------------------------
# Interface gráfica (Tkinter)
# ---------------------------------------------------------------------------


class AplicacaoGUI:
    """Janela principal da aplicação IntegraCAR com Tkinter."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Extrator de Dados - IntegraCAR")
        self.root.resizable(False, False)

        # Variáveis de estado da interface
        self.caminho_csv_var = tk.StringVar()
        self.pasta_saida_var = tk.StringVar()
        self.buffer_var = tk.StringVar(value=str(CONFIGURACOES["buffer_metros"]))
        self.qtd_var = tk.StringVar(value="")
        self.ano_var = tk.StringVar(value="2019-2020")
        self.manter_shapefile_var = tk.BooleanVar(value=False)
        self.simultaneo_var = tk.BooleanVar(value=False)
        self.pasta_1215_var = tk.StringVar()
        self.pasta_1920_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto.")

        self._construir_layout()

    def _construir_layout(self) -> None:
        """Monta os componentes visuais da janela principal."""
        frame_principal = ttk.Frame(self.root, padding=10)
        frame_principal.grid(row=0, column=0, sticky="nsew")
        self._frame_principal = frame_principal

        # Linha 0 - Arquivo CSV
        ttk.Label(frame_principal, text="Arquivo CSV de Entrada:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(
            frame_principal, textvariable=self.caminho_csv_var, width=50, state="readonly"
        ).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        ttk.Button(
            frame_principal, text="Selecionar...", command=self._selecionar_csv
        ).grid(row=0, column=2, padx=5, pady=2)

        # Linha 1 - Pasta de saída (modo individual)
        self._lbl_pasta_saida = ttk.Label(frame_principal, text="Pasta de Saída:")
        self._lbl_pasta_saida.grid(row=1, column=0, sticky="w")
        self._entry_pasta_saida = ttk.Entry(
            frame_principal, textvariable=self.pasta_saida_var, width=50, state="readonly"
        )
        self._entry_pasta_saida.grid(row=1, column=1, padx=5, pady=2, sticky="w")
        self._btn_pasta_saida = ttk.Button(
            frame_principal, text="Selecionar...", command=self._selecionar_pasta_saida
        )
        self._btn_pasta_saida.grid(row=1, column=2, padx=5, pady=2)

        # Linha 2 - Buffer
        ttk.Label(frame_principal, text="Buffer (metros):").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Entry(frame_principal, textvariable=self.buffer_var, width=15).grid(
            row=2, column=1, padx=5, pady=2, sticky="w"
        )

        # Linha 3 - Quantidade de imagens
        ttk.Label(frame_principal, text="Quantidade de Imagens:").grid(
            row=3, column=0, sticky="w"
        )
        ttk.Entry(frame_principal, textvariable=self.qtd_var, width=15).grid(
            row=3, column=1, padx=5, pady=2, sticky="w"
        )

        # Linha 4 - Ano (Combobox) — escondido no modo simultâneo
        self._lbl_ano = ttk.Label(frame_principal, text="Ano:")
        self._lbl_ano.grid(row=4, column=0, sticky="w")
        self._combo_ano = ttk.Combobox(
            frame_principal,
            textvariable=self.ano_var,
            values=["2012-2015", "2019-2020"],
            state="readonly",
            width=15,
        )
        self._combo_ano.grid(row=4, column=1, padx=5, pady=2, sticky="w")

        # Linha 5 - Checkbox Download Simultâneo
        check_simultaneo = ttk.Checkbutton(
            frame_principal,
            text="Download simultâneo 12-15, 19-20",
            variable=self.simultaneo_var,
            command=self._alternar_modo_simultaneo,
        )
        check_simultaneo.grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 2))

        # Linha 6 - Pasta 12-15 (inicialmente escondida)
        self._lbl_pasta_1215 = ttk.Label(frame_principal, text="Pasta Saída 12-15:")
        self._entry_pasta_1215 = ttk.Entry(
            frame_principal, textvariable=self.pasta_1215_var, width=50, state="readonly"
        )
        self._btn_pasta_1215 = ttk.Button(
            frame_principal, text="Selecionar...", command=self._selecionar_pasta_1215
        )

        # Linha 7 - Pasta 19-20 (inicialmente escondida)
        self._lbl_pasta_1920 = ttk.Label(frame_principal, text="Pasta Saída 19-20:")
        self._entry_pasta_1920 = ttk.Entry(
            frame_principal, textvariable=self.pasta_1920_var, width=50, state="readonly"
        )
        self._btn_pasta_1920 = ttk.Button(
            frame_principal, text="Selecionar...", command=self._selecionar_pasta_1920
        )

        # Linha 8 - Checkbox Manter Shapefile
        self._check_manter = ttk.Checkbutton(
            frame_principal,
            text="Manter Shapefile (Apenas 2012-2015)",
            variable=self.manter_shapefile_var,
        )
        self._check_manter.grid(row=8, column=0, columnspan=2, sticky="w", pady=(2, 5))

        # Linha 9 - Botão Executar
        ttk.Button(
            frame_principal,
            text="Executar Processamento",
            command=self._iniciar_processamento_thread,
        ).grid(row=9, column=0, columnspan=3, pady=(10, 5))

        # Linha 10 - Barra de progresso
        self.progressbar = ttk.Progressbar(
            frame_principal, orient="horizontal", mode="indeterminate", length=300
        )
        self.progressbar.grid(row=10, column=0, columnspan=3, pady=(5, 5), sticky="we")

        # Linha 11 - Status (rodapé)
        frame_status = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        frame_status.grid(row=1, column=0, sticky="we")
        ttk.Label(frame_status, textvariable=self.status_var).grid(
            row=0, column=0, sticky="w"
        )

    def _alternar_modo_simultaneo(self) -> None:
        """Mostra/esconde campos conforme o checkbox de download simultâneo."""
        if self.simultaneo_var.get():
            # Esconde pasta única e combobox de ano
            self._lbl_pasta_saida.grid_remove()
            self._entry_pasta_saida.grid_remove()
            self._btn_pasta_saida.grid_remove()
            self._lbl_ano.grid_remove()
            self._combo_ano.grid_remove()
            # Mostra as duas pastas
            self._lbl_pasta_1215.grid(row=6, column=0, sticky="w")
            self._entry_pasta_1215.grid(row=6, column=1, padx=5, pady=2, sticky="w")
            self._btn_pasta_1215.grid(row=6, column=2, padx=5, pady=2)
            self._lbl_pasta_1920.grid(row=7, column=0, sticky="w")
            self._entry_pasta_1920.grid(row=7, column=1, padx=5, pady=2, sticky="w")
            self._btn_pasta_1920.grid(row=7, column=2, padx=5, pady=2)
        else:
            # Esconde as duas pastas
            self._lbl_pasta_1215.grid_remove()
            self._entry_pasta_1215.grid_remove()
            self._btn_pasta_1215.grid_remove()
            self._lbl_pasta_1920.grid_remove()
            self._entry_pasta_1920.grid_remove()
            self._btn_pasta_1920.grid_remove()
            # Mostra pasta única e combobox de ano
            self._lbl_pasta_saida.grid(row=1, column=0, sticky="w")
            self._entry_pasta_saida.grid(row=1, column=1, padx=5, pady=2, sticky="w")
            self._btn_pasta_saida.grid(row=1, column=2, padx=5, pady=2)
            self._lbl_ano.grid(row=4, column=0, sticky="w")
            self._combo_ano.grid(row=4, column=1, padx=5, pady=2, sticky="w")

    # ---------------- Callbacks da interface ----------------
    def _selecionar_csv(self) -> None:
        """Abre diálogo para seleção do arquivo CSV de entrada."""
        caminho = filedialog.askopenfilename(
            title="Selecione o arquivo CSV de entrada",
            filetypes=[("Arquivos CSV", "*.csv;*.txt"), ("Todos os arquivos", "*.*")],
        )
        if caminho:
            self.caminho_csv_var.set(caminho)

    def _selecionar_pasta_saida(self) -> None:
        """Abre diálogo para seleção da pasta de saída (modo individual)."""
        pasta = filedialog.askdirectory(title="Selecione a pasta de saída")
        if pasta:
            self.pasta_saida_var.set(pasta)

    def _selecionar_pasta_1215(self) -> None:
        """Abre diálogo para seleção da pasta de saída das imagens 2012-2015."""
        pasta = filedialog.askdirectory(title="Selecione a pasta de saída para 2012-2015")
        if pasta:
            self.pasta_1215_var.set(pasta)

    def _selecionar_pasta_1920(self) -> None:
        """Abre diálogo para seleção da pasta de saída das imagens 2019-2020."""
        pasta = filedialog.askdirectory(title="Selecione a pasta de saída para 2019-2020")
        if pasta:
            self.pasta_1920_var.set(pasta)

    # ---------------- Helpers de atualização de status/progresso ----------------
    def atualizar_status_threadsafe(self, mensagem: str) -> None:
        """Atualiza o label de status de forma segura a partir de qualquer thread."""

        def _atualizar():
            self.status_var.set(mensagem)

        self.root.after(0, _atualizar)

    def atualizar_progresso_threadsafe(
        self,
        modo: str = "indeterminate",
        value: int | float | None = None,
        maximum: int | float | None = None,
    ) -> None:
        """
        Atualiza a barra de progresso de forma segura.
        - modo: "indeterminate" ou "determinate"
        - value/maximum: usados apenas no modo determinate
        """

        def _atualizar():
            self.progressbar.config(mode=modo)
            if modo == "indeterminate":
                self.progressbar.start(10)
            else:
                self.progressbar.stop()
                if maximum is not None:
                    self.progressbar["maximum"] = maximum
                if value is not None:
                    self.progressbar["value"] = value

        self.root.after(0, _atualizar)

    def _iniciar_processamento_thread(self) -> None:
        """
        Valida entradas e inicia o processamento em uma thread separada
        para não bloquear a interface gráfica.
        """
        caminho_csv = self.caminho_csv_var.get().strip()
        modo_simultaneo = self.simultaneo_var.get()
        manter_shapefile = self.manter_shapefile_var.get()

        # Validação: CSV
        if not caminho_csv:
            messagebox.showerror("Erro", "Selecione o arquivo CSV de entrada.")
            return

        # Validação: pastas de saída conforme o modo
        if modo_simultaneo:
            pasta_1215 = self.pasta_1215_var.get().strip()
            pasta_1920 = self.pasta_1920_var.get().strip()
            if not pasta_1215:
                messagebox.showerror("Erro", "Selecione a pasta de saída para 2012-2015.")
                return
            if not pasta_1920:
                messagebox.showerror("Erro", "Selecione a pasta de saída para 2019-2020.")
                return
        else:
            pasta_saida = self.pasta_saida_var.get().strip()
            if not pasta_saida:
                messagebox.showerror("Erro", "Selecione a pasta de saída.")
                return
            ano = self.ano_var.get()

        # Validação: buffer
        try:
            buffer_metros = int(self.buffer_var.get())
            if buffer_metros <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Erro", "O valor de 'Buffer (metros)' deve ser um inteiro positivo."
            )
            return

        # Validação: quantidade
        qtd_imagens = None
        qtd_txt = self.qtd_var.get().strip()
        if qtd_txt:
            try:
                qtd_imagens = int(qtd_txt)
                if qtd_imagens <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Erro",
                    "O valor de 'Quantidade de Imagens' deve ser um inteiro positivo.",
                )
                return

        # Inicia barra de progresso
        self.atualizar_status_threadsafe("Iniciando processamento...")
        self.atualizar_progresso_threadsafe("indeterminate")

        def _executar_2012(pasta_destino: str) -> None:
            """Executa o pipeline 2012-2015 com análise de cobertura."""
            try:
                processar_ano_2012(
                    arquivo_csv=caminho_csv,
                    pasta_saida=pasta_destino,
                    buffer_metros=buffer_metros,
                    qtd_imagens=qtd_imagens,
                    manter_shapefile=manter_shapefile,
                    atualizar_status=self.atualizar_status_threadsafe,
                    atualizar_progresso=self.atualizar_progresso_threadsafe,
                )
            except Exception as exc:
                mensagem_erro = f"Erro no processamento 2012-2015: {exc}"
                self.atualizar_status_threadsafe(mensagem_erro)
                self.root.after(
                    0, lambda: messagebox.showerror("Erro", mensagem_erro)
                )

        def _executar_2019(pasta_destino: str) -> None:
            """Executa o pipeline 2019-2020."""
            try:
                self.atualizar_status_threadsafe(
                    "Executando pipeline WMS (2019-2020)..."
                )
                processar_ano_2019_2020(
                    arquivo_csv=caminho_csv,
                    pasta_saida=pasta_destino,
                    buffer_metros=buffer_metros,
                    qtd_imagens=qtd_imagens,
                )
                self.atualizar_status_threadsafe(
                    "Processamento 2019-2020 concluído com sucesso."
                )
            except Exception as exc:
                mensagem_erro = f"Erro no processamento 2019-2020: {exc}"
                self.atualizar_status_threadsafe(mensagem_erro)
                self.root.after(
                    0, lambda: messagebox.showerror("Erro", mensagem_erro)
                )

        def _worker():
            try:
                if modo_simultaneo:
                    self.atualizar_status_threadsafe(
                        "Executando 2012-2015 e 2019-2020 em paralelo..."
                    )
                    t_2012 = threading.Thread(
                        target=_executar_2012, args=(pasta_1215,), daemon=True
                    )
                    t_2019 = threading.Thread(
                        target=_executar_2019, args=(pasta_1920,), daemon=True
                    )
                    t_2012.start()
                    t_2019.start()
                    t_2012.join()
                    t_2019.join()
                    self.atualizar_status_threadsafe(
                        "Download simultâneo (2012-2015 + 2019-2020) concluído."
                    )
                elif ano == "2012-2015":
                    _executar_2012(pasta_saida)
                elif ano == "2019-2020":
                    _executar_2019(pasta_saida)
            finally:
                self.atualizar_progresso_threadsafe(
                    "determinate", value=0, maximum=100
                )

        threading.Thread(target=_worker, daemon=True).start()


def main_gui() -> None:
    """Função de entrada da aplicação GUI."""
    root = tk.Tk()
    AplicacaoGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main_gui()

