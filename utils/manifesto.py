# utils/manifesto.py
# Gerencia o arquivo CSV de manifesto do dataset.

import csv
from datetime import datetime
from pathlib import Path

COLUNAS_MANIFESTO = [
    "numero_amostra",
    "cod_imovel",
    "x",
    "y",
    "bbox_xmin",
    "bbox_ymin",
    "bbox_xmax",
    "bbox_ymax",
    "status_satelite",
    "status_uso_solo",
    "data_download",
]


def inicializar_manifesto(caminho_manifesto: str | Path) -> None:
    """
    Cria o arquivo de manifesto com o cabeçalho se ele ainda não existir.
    Não sobrescreve um manifesto existente.
    """
    caminho = Path(caminho_manifesto)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        with open(caminho, "w", newline="", encoding="utf-8") as arquivo_csv:
            writer = csv.DictWriter(arquivo_csv, fieldnames=COLUNAS_MANIFESTO, delimiter=";")
            writer.writeheader()


def registrar_resultado(
    caminho_manifesto: str | Path,
    numero_amostra: int,
    cod_imovel: str,
    x: float,
    y: float,
    bbox: tuple[float, float, float, float],
    status_satelite: str,
    status_uso_solo: str,
) -> None:
    """
    Acrescenta uma linha ao manifesto com o resultado do processamento de uma amostra.

    Parâmetros:
        numero_amostra: número sequencial da amostra (1, 2, 3, ...)
        bbox: tupla (xmin, ymin, xmax, ymax) em metros EPSG:31984
        status_*: 'ok', 'erro' ou 'pulado'
    """
    caminho = Path(caminho_manifesto)
    linha = {
        "numero_amostra": numero_amostra,
        "cod_imovel": cod_imovel,
        "x": x,
        "y": y,
        "bbox_xmin": bbox[0],
        "bbox_ymin": bbox[1],
        "bbox_xmax": bbox[2],
        "bbox_ymax": bbox[3],
        "status_satelite": status_satelite,
        "status_uso_solo": status_uso_solo,
        "data_download": datetime.now().isoformat(timespec="seconds"),
    }
    with open(caminho, "a", newline="", encoding="utf-8") as arquivo_csv:
        writer = csv.DictWriter(arquivo_csv, fieldnames=COLUNAS_MANIFESTO, delimiter=";")
        writer.writerow(linha)
