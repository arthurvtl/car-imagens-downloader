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


def carregar_amostras_processadas(caminho_manifesto: str | Path) -> set[int]:
    """
    Lê o manifesto e retorna um conjunto com os números de amostra que já foram
    processados com status 'ok' em ambas as imagens. Usado para downloads idempotentes.
    """
    caminho = Path(caminho_manifesto)
    amostras_completas = set()
    if not caminho.exists():
        return amostras_completas
    with open(caminho, "r", encoding="utf-8") as arquivo_csv:
        reader = csv.DictReader(arquivo_csv, delimiter=";")
        for linha in reader:
            if linha["status_satelite"] == "ok" and linha["status_uso_solo"] == "ok":
                amostras_completas.add(int(linha["numero_amostra"]))
    return amostras_completas


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
