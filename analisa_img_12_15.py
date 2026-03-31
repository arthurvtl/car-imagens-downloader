"""
analisa_img_12_15.py
Análise de cobertura de pixels nas imagens de uso do solo 2012-2015.

Verifica se cada imagem de uso do solo está 100% pintada (sem pixels pretos).
Gera dois relatórios:
  - imagens_cheias_12-15.txt   → imagens com 100% de cobertura
  - imagens_incompletas_12-15.txt → imagens com pixels não pintados + % faltante
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

logger = logging.getLogger(__name__)


def calcular_cobertura(caminho_imagem: Path) -> float:
    """
    Retorna a porcentagem de pixels pintados (não pretos) em uma imagem GeoTIFF RGB.
    Pixel (0, 0, 0) é considerado vazio/sem classe.
    """
    with rasterio.open(caminho_imagem) as src:
        dados = src.read()  # shape: (3, altura, largura)

    mascara_vazio = (dados[0] == 0) & (dados[1] == 0) & (dados[2] == 0)
    total_pixels = mascara_vazio.size
    pixels_vazios = int(np.sum(mascara_vazio))
    pixels_pintados = total_pixels - pixels_vazios

    return (pixels_pintados / total_pixels) * 100.0


def analisar_imagens_uso_solo(
    pasta_imagens: str | Path,
    arquivo_csv: str | Path,
    pasta_relatorios: str | Path,
    qtd_imagens: int | None = None,
    callback_progresso=None,
    callback_status=None,
) -> dict:
    """
    Analisa todas as imagens de uso do solo 2012-2015 quanto à cobertura.

    Para cada imagem:
      - 100% pintada  → linha salva em imagens_cheias_12-15.txt
      - < 100%        → linha salva em imagens_incompletas_12-15.txt com % faltante

    Parâmetros:
        pasta_imagens:      diretório contendo os arquivos *_uso_solo_2012.tif
        arquivo_csv:        CSV original com cod_imovel;x;y
        pasta_relatorios:   onde os .txt de resultado serão salvos
        qtd_imagens:        limitar a N primeiras amostras (None = todas)
        callback_progresso: função(modo, value, maximum) para atualizar GUI
        callback_status:    função(mensagem) para atualizar GUI

    Retorna:
        {"cheias": int, "incompletas": int, "sem_arquivo": int, "total": int}
    """
    pasta_imagens = Path(pasta_imagens)
    pasta_relatorios = Path(pasta_relatorios)
    pasta_relatorios.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(arquivo_csv, sep=";")
    if qtd_imagens is not None and qtd_imagens > 0:
        df = df.head(qtd_imagens)

    total_linhas = len(df)

    caminho_cheias = pasta_relatorios / "imagens_cheias_12-15.txt"
    caminho_incompletas = pasta_relatorios / "imagens_incompletas_12-15.txt"

    contagem = {"cheias": 0, "incompletas": 0, "sem_arquivo": 0, "total": total_linhas}

    if callback_status:
        callback_status("Analisando cobertura das imagens 2012-2015...")
    if callback_progresso:
        callback_progresso("determinate", value=0, maximum=total_linhas)

    with (
        open(caminho_cheias, "w", encoding="utf-8") as f_cheias,
        open(caminho_incompletas, "w", encoding="utf-8") as f_incompletas,
    ):
        f_cheias.write("cod_imovel;x;y\n")
        f_incompletas.write("cod_imovel;x;y;porcentagem_faltando\n")

        for idx, row in df.iterrows():
            numero_amostra = idx + 1
            nome_arquivo = f"amostra_{numero_amostra}_uso_solo_2012.tif"
            caminho_img = pasta_imagens / nome_arquivo

            if not caminho_img.exists():
                logger.warning(f"[analise] Imagem não encontrada: {caminho_img}")
                contagem["sem_arquivo"] += 1
                if callback_progresso:
                    callback_progresso("determinate", value=numero_amostra, maximum=total_linhas)
                continue

            cobertura = calcular_cobertura(caminho_img)

            cod_imovel = str(row["cod_imovel"])
            x = row["x"]
            y = row["y"]

            if cobertura >= 100.0:
                f_cheias.write(f"{cod_imovel};{x};{y}\n")
                contagem["cheias"] += 1
                logger.info(f"[analise][amostra_{numero_amostra}] 100% pintada")
            else:
                faltando = round(100.0 - cobertura, 2)
                f_incompletas.write(f"{cod_imovel};{x};{y};{faltando}\n")
                contagem["incompletas"] += 1
                logger.info(
                    f"[analise][amostra_{numero_amostra}] {cobertura:.2f}% pintada — falta {faltando}%"
                )

            if callback_progresso:
                callback_progresso("determinate", value=numero_amostra, maximum=total_linhas)

    logger.info(
        f"[analise] Concluido: {contagem['cheias']} cheias, "
        f"{contagem['incompletas']} incompletas, "
        f"{contagem['sem_arquivo']} sem arquivo "
        f"(de {contagem['total']} total)"
    )
    logger.info(f"[analise] Relatorio cheias:      {caminho_cheias}")
    logger.info(f"[analise] Relatorio incompletas: {caminho_incompletas}")

    if callback_status:
        callback_status(
            f"Analise concluida: {contagem['cheias']} cheias, "
            f"{contagem['incompletas']} incompletas."
        )

    return contagem
