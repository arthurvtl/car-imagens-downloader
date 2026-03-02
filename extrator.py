# extrator.py
# Script principal do pipeline de extração de imagens IntegraCar.
# Execução: python extrator.py
#
# Fluxo:
# 1. Lê o CSV de coordenadas
# 2. Verifica quais imóveis já foram processados (idempotência)
# 3. Para cada imóvel pendente, baixa o par de imagens WMS como GeoTIFF 1024×1024
# 4. Registra o resultado (status + hash SHA256) no manifesto
# 5. Exibe progresso em tempo real e grava log de execução

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from configuracoes import CONFIGURACOES
from utils.integridade import calcular_hash_sha256
from utils.manifesto import (
    inicializar_manifesto,
    carregar_imoveis_processados,
    registrar_resultado,
)
from utils.wms import baixar_imagem, calcular_bbox


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


def processar_imovel(
    cod_imovel: str,
    x: float,
    y: float,
    configuracoes: dict,
) -> dict:
    """
    Processa um único imóvel: calcula o bbox, baixa as duas imagens WMS e as
    salva como GeoTIFF georreferenciado. Retorna um dicionário com os resultados
    para ser gravado no manifesto.

    Parâmetros:
        cod_imovel: identificador único do imóvel (usado como nome da pasta)
        x, y: coordenadas centrais em metros (EPSG:31984)
        configuracoes: dicionário com todas as configurações do pipeline

    Retorna:
        Dicionário com campos do manifesto para este imóvel.
    """
    logger = logging.getLogger(__name__)

    cfg = configuracoes
    pasta_imovel = Path(cfg["pasta_saida"]) / cod_imovel
    caminho_satelite = pasta_imovel / cfg["nome_arquivo_satelite"]
    caminho_uso_solo = pasta_imovel / cfg["nome_arquivo_uso_solo"]

    bbox = calcular_bbox(x, y, cfg["buffer_metros"])

    resultado = {
        "cod_imovel": cod_imovel,
        "x": x,
        "y": y,
        "bbox": bbox,
        "status_satelite": "erro",
        "status_uso_solo": "erro",
        "hash_satelite": "",
        "hash_uso_solo": "",
    }

    # Download da imagem de satélite bruta
    try:
        baixar_imagem(
            wms_url=cfg["wms_url"],
            camada=cfg["camada_satelite"],
            bbox=bbox,
            caminho_saida=caminho_satelite,
            largura_pixels=cfg["largura_pixels"],
            altura_pixels=cfg["altura_pixels"],
            srid=cfg["srid_wms"],
            wms_versao=cfg["wms_versao"],
            formato=cfg["formato_wms"],
            transparente=cfg["transparente"],
            epsg_codigo=cfg["epsg_codigo"],
            timeout=cfg["timeout_requisicao"],
            tentativas=cfg["tentativas_por_imagem"],
            pausa_entre_tentativas=cfg["pausa_entre_tentativas"],
        )
        resultado["status_satelite"] = "ok"
        resultado["hash_satelite"] = calcular_hash_sha256(caminho_satelite)
        logger.info(f"[{cod_imovel}] satelite.tif OK")
    except Exception as erro:
        logger.error(f"[{cod_imovel}] Falha ao baixar satelite.tif: {erro}")

    # Download do mapa de uso do solo
    try:
        baixar_imagem(
            wms_url=cfg["wms_url"],
            camada=cfg["camada_uso_solo"],
            bbox=bbox,
            caminho_saida=caminho_uso_solo,
            largura_pixels=cfg["largura_pixels"],
            altura_pixels=cfg["altura_pixels"],
            srid=cfg["srid_wms"],
            wms_versao=cfg["wms_versao"],
            formato=cfg["formato_wms"],
            transparente=cfg["transparente"],
            epsg_codigo=cfg["epsg_codigo"],
            timeout=cfg["timeout_requisicao"],
            tentativas=cfg["tentativas_por_imagem"],
            pausa_entre_tentativas=cfg["pausa_entre_tentativas"],
        )
        resultado["status_uso_solo"] = "ok"
        resultado["hash_uso_solo"] = calcular_hash_sha256(caminho_uso_solo)
        logger.info(f"[{cod_imovel}] uso_solo.tif OK")
    except Exception as erro:
        logger.error(f"[{cod_imovel}] Falha ao baixar uso_solo.tif: {erro}")

    return resultado


def executar_pipeline() -> None:
    """
    Função principal do pipeline. Orquestra leitura do CSV, filtragem de imóveis
    já processados, downloads paralelos e registro no manifesto.
    """
    cfg = CONFIGURACOES

    configurar_logging(cfg["pasta_logs"], cfg["nome_log"])
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Iniciando pipeline de extração IntegraCar")
    logger.info("=" * 60)

    # Inicializar manifesto (cria arquivo com cabeçalho se ainda não existe)
    caminho_manifesto = Path(cfg["pasta_artifacts"]) / cfg["nome_manifesto"]
    inicializar_manifesto(caminho_manifesto)

    # Ler CSV de coordenadas
    dataframe = pd.read_csv(cfg["arquivo_csv"], sep=cfg["separador_csv"])
    total_imoveis = len(dataframe)
    logger.info(f"CSV carregado: {total_imoveis} imóveis encontrados")

    # Filtrar imóveis já processados com sucesso (idempotência)
    if cfg["pular_se_existir"]:
        ja_processados = carregar_imoveis_processados(caminho_manifesto)
        dataframe_pendente = dataframe[~dataframe["cod_imovel"].isin(ja_processados)]
        logger.info(
            f"Já processados: {len(ja_processados)} | Pendentes: {len(dataframe_pendente)}"
        )
    else:
        dataframe_pendente = dataframe

    if dataframe_pendente.empty:
        logger.info("Todos os imóveis já foram processados. Pipeline encerrado.")
        return

    # Criar pasta de saída principal
    Path(cfg["pasta_saida"]).mkdir(parents=True, exist_ok=True)

    # Processar imóveis com download paralelo
    contagem_sucesso = 0
    contagem_erro = 0

    with ThreadPoolExecutor(max_workers=cfg["workers_paralelos"]) as executor:
        futures = {
            executor.submit(
                processar_imovel,
                row["cod_imovel"],
                row["x"],
                row["y"],
                cfg,
            ): row["cod_imovel"]
            for _, row in dataframe_pendente.iterrows()
        }

        with tqdm(total=len(futures), desc="Baixando imagens", unit="imóvel") as barra_progresso:
            for future in as_completed(futures):
                resultado = future.result()

                registrar_resultado(
                    caminho_manifesto=caminho_manifesto,
                    cod_imovel=resultado["cod_imovel"],
                    x=resultado["x"],
                    y=resultado["y"],
                    bbox=resultado["bbox"],
                    status_satelite=resultado["status_satelite"],
                    status_uso_solo=resultado["status_uso_solo"],
                    hash_satelite=resultado["hash_satelite"],
                    hash_uso_solo=resultado["hash_uso_solo"],
                )

                if resultado["status_satelite"] == "ok" and resultado["status_uso_solo"] == "ok":
                    contagem_sucesso += 1
                else:
                    contagem_erro += 1

                barra_progresso.update(1)

    logger.info("=" * 60)
    logger.info(f"Pipeline concluído.")
    logger.info(f"Pares completos (ok/ok): {contagem_sucesso}")
    logger.info(f"Com erro: {contagem_erro}")
    logger.info(f"Manifesto salvo em: {caminho_manifesto}")
    logger.info("=" * 60)


if __name__ == "__main__":
    executar_pipeline()
