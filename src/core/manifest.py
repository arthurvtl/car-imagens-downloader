"""
src.core.manifest
Gerenciamento do manifesto CSV do dataset.
Evolução de utils/manifesto.py para suportar multi-satélite.
"""

from __future__ import annotations

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
    "satelite",
    "status_satelite",
    "status_segmentada",
    "item_id",
    "cloud_cover",
    "data_download",
]


def inicializar_manifesto(caminho: str | Path) -> None:
    """Cria o manifesto com cabeçalho se não existir."""
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        with open(p, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUNAS_MANIFESTO, delimiter=";").writeheader()


def registrar_resultado(
    caminho: str | Path,
    numero_amostra: int,
    cod_imovel: str,
    x: float,
    y: float,
    bbox: tuple[float, float, float, float],
    satelite: str,
    status_satelite: str,
    status_segmentada: str = "n/a",
    item_id: str = "",
    cloud_cover: float | str = "",
) -> None:
    """Acrescenta uma linha ao manifesto."""
    row = {
        "numero_amostra": numero_amostra,
        "cod_imovel": cod_imovel,
        "x": x,
        "y": y,
        "bbox_xmin": bbox[0],
        "bbox_ymin": bbox[1],
        "bbox_xmax": bbox[2],
        "bbox_ymax": bbox[3],
        "satelite": satelite,
        "status_satelite": status_satelite,
        "status_segmentada": status_segmentada,
        "item_id": item_id,
        "cloud_cover": cloud_cover,
        "data_download": datetime.now().isoformat(timespec="seconds"),
    }
    with open(Path(caminho), "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUNAS_MANIFESTO, delimiter=";").writerow(row)


def carregar_amostras_processadas(caminho: str | Path) -> set[int]:
    """Retorna conjunto de amostras já processadas com sucesso."""
    p = Path(caminho)
    done: set[int] = set()
    if not p.exists():
        return done
    with open(p, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row.get("status_satelite") == "ok":
                done.add(int(row["numero_amostra"]))
    return done
