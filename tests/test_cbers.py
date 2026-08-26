from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin

from utils.cbers import (
    ConfiguracaoExtracao,
    PontoEntrada,
    calcular_indice,
    carregar_pontos,
    executar_extracao,
    href_para_https,
    proxima_pasta_imagens,
    recortar_assets,
    selecionar_item,
    validar_configuracao,
)


def item_stac(item_id: str, data: str, nuvens: float | None) -> dict:
    propriedades = {"datetime": data}
    if nuvens is not None:
        propriedades["eo:cloud_cover"] = nuvens
    return {
        "type": "Feature",
        "id": item_id,
        "bbox": [-41, -20, -40, -18],
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-41, -20],
                    [-40, -20],
                    [-40, -18],
                    [-41, -18],
                    [-41, -20],
                ]
            ],
        },
        "properties": propriedades,
        "assets": {"B4": {"href": "https://example.test/B4.tif"}},
    }


class TesteCBERS(unittest.TestCase):
    def test_converte_s3_publico(self):
        href = (
            "s3://brazil-eosats/CBERS4A/WPM/cena/"
            "CBERS_4A_WPM_BAND4.tif"
        )
        self.assertEqual(
            href_para_https(href),
            "https://brazil-eosats.s3.us-west-2.amazonaws.com/"
            "CBERS4A/WPM/cena/CBERS_4A_WPM_BAND4.tif",
        )

    def test_seleciona_menor_nuvem_ou_mais_recente(self):
        antigo_limpo = item_stac(
            "antigo-limpo", "2025-01-01T00:00:00Z", 2.0
        )
        novo_nublado = item_stac(
            "novo-nublado", "2026-01-01T00:00:00Z", 40.0
        )
        bbox = (-40.8, -19.1, -40.7, -19.0)
        self.assertEqual(
            selecionar_item(
                [novo_nublado, antigo_limpo],
                bbox,
                ("B4",),
                "menor-nuvem",
                None,
            )["id"],
            "antigo-limpo",
        )
        self.assertEqual(
            selecionar_item(
                [novo_nublado, antigo_limpo],
                bbox,
                ("B4",),
                "mais-recente",
                None,
            )["id"],
            "novo-nublado",
        )

    def test_le_csv(self):
        with tempfile.TemporaryDirectory() as temporario:
            csv_path = Path(temporario) / "pontos.csv"
            csv_path.write_text(
                "cod_imovel;x;y\nABC;317411.5;7898046.9\n",
                encoding="utf-8",
            )
            pontos = carregar_pontos(csv_path)
        self.assertEqual(len(pontos), 1)
        self.assertEqual(pontos[0].cod_imovel, "ABC")
        self.assertEqual(pontos[0].x, 317411.5)

    def test_recorta_nir_e_rgb_local(self):
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            transformacao = from_origin(300000, 7900000, 8, 8)
            fontes = []
            for indice, valor in enumerate((100, 200, 300), start=1):
                caminho = pasta / f"banda_{indice}.tif"
                with rasterio.open(
                    caminho,
                    "w",
                    driver="GTiff",
                    width=512,
                    height=512,
                    count=1,
                    dtype="int16",
                    crs="EPSG:32724",
                    transform=transformacao,
                    nodata=0,
                    tiled=True,
                    blockxsize=256,
                    blockysize=256,
                ) as dst:
                    dst.write(
                        np.full((512, 512), valor, dtype=np.int16), 1
                    )
                fontes.append(caminho)

            ponto = PontoEntrada(
                numero=1,
                cod_imovel="TESTE",
                x=302048,
                y=7897952,
            )
            csv_falso = pasta / "pontos.csv"
            csv_falso.write_text(
                "cod_imovel;x;y\nTESTE;302048;7897952\n",
                encoding="utf-8",
            )
            cfg = ConfiguracaoExtracao(
                arquivo_csv=csv_falso,
                pasta_saida=pasta,
                produto="nir",
                fonte="aws",
                sensor="wpm",
                data_inicial="2025-01-01",
                data_final="2025-12-31",
                buffer_metros=128,
                epsg_entrada="EPSG:32724",
            )

            nir = pasta / "nir.tif"
            recortar_assets(
                [("NIR", str(fontes[0]))],
                nir,
                ponto,
                cfg,
                escala=0.0001,
                tags={"item_id": "teste"},
            )
            with rasterio.open(nir) as src:
                self.assertEqual((src.width, src.height, src.count), (32, 32, 1))
                self.assertEqual(src.scales, (0.0001,))
                self.assertTrue(np.all(src.read(1) == 100))
                self.assertEqual(src.tags()["item_id"], "teste")

            rgb = pasta / "rgb.tif"
            cfg_rgb = ConfiguracaoExtracao(
                **{
                    **cfg.__dict__,
                    "produto": "rgb",
                    "largura_pixels": 64,
                    "altura_pixels": 64,
                }
            )
            recortar_assets(
                [
                    ("RED", str(fontes[0])),
                    ("GREEN", str(fontes[1])),
                    ("BLUE", str(fontes[2])),
                ],
                rgb,
                ponto,
                cfg_rgb,
                escala=1.0,
                tags={},
            )
            with rasterio.open(rgb) as src:
                self.assertEqual((src.width, src.height, src.count), (64, 64, 3))
                self.assertEqual(
                    src.colorinterp,
                    (ColorInterp.red, ColorInterp.green, ColorInterp.blue),
                )
                self.assertEqual([int(src.read(i).mean()) for i in (1, 2, 3)], [100, 200, 300])

    def test_calcula_ndvi_e_ndwi_pixel_a_pixel(self):
        nir = np.array([[300.0]], dtype=np.float32)
        red = np.array([[100.0]], dtype=np.float32)
        ndvi = calcular_indice(nir, red, "ndvi")
        self.assertAlmostEqual(float(ndvi[0, 0]), 0.5, places=5)

        green = np.array([[100.0]], dtype=np.float32)
        ndwi = calcular_indice(nir, green, "ndwi")
        self.assertAlmostEqual(float(ndwi[0, 0]), -0.5, places=5)

    def test_escala_do_sensor_nao_afeta_o_indice(self):
        # NDVI e uma razao: multiplicar as 2 bandas pelo mesmo fator de escala
        # (DN -> reflectancia) nao pode mudar o resultado.
        nir = np.array([[3000.0]], dtype=np.float32)
        red = np.array([[1000.0]], dtype=np.float32)
        sem_escala = calcular_indice(nir, red, "ndvi")
        com_escala = calcular_indice(nir * 0.0001, red * 0.0001, "ndvi")
        self.assertAlmostEqual(float(sem_escala[0, 0]), float(com_escala[0, 0]), places=5)

    def test_baixa_e_calcula_ndvi_com_bandas_alinhadas(self):
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            transformacao = from_origin(300000, 7900000, 8, 8)
            valores_banda = {"B4": 300, "B3": 100}  # NIR, RED -> NDVI = 0.5
            hrefs: dict[str, str] = {}
            for nome, valor in valores_banda.items():
                caminho = pasta / f"{nome}.tif"
                with rasterio.open(
                    caminho,
                    "w",
                    driver="GTiff",
                    width=512,
                    height=512,
                    count=1,
                    dtype="int16",
                    crs="EPSG:32724",
                    transform=transformacao,
                    nodata=0,
                    tiled=True,
                    blockxsize=256,
                    blockysize=256,
                ) as dst:
                    dst.write(np.full((512, 512), valor, dtype=np.int16), 1)
                hrefs[nome] = str(caminho)

            csv_falso = pasta / "pontos.csv"
            csv_falso.write_text(
                "cod_imovel;x;y\nTESTE;302048;7897952\n", encoding="utf-8"
            )
            pasta_saida = pasta / "saida"
            cfg = ConfiguracaoExtracao(
                arquivo_csv=csv_falso,
                pasta_saida=pasta_saida,
                produto="ndvi",
                fonte="aws",
                sensor="wpm",
                data_inicial="2025-01-01",
                data_final="2025-12-31",
                buffer_metros=128,
            )

            item_falso = {
                "type": "Feature",
                "id": "item-teste",
                "bbox": [-180, -90, 180, 90],
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-180, -90],
                            [180, -90],
                            [180, 90],
                            [-180, 90],
                            [-180, -90],
                        ]
                    ],
                },
                "properties": {"datetime": "2025-06-01T00:00:00Z"},
                "assets": {
                    "B4": {"href": hrefs["B4"]},
                    "B3": {"href": hrefs["B3"]},
                },
            }

            with mock.patch(
                "utils.cbers.consultar_itens_stac", return_value=[item_falso]
            ):
                resultados = executar_extracao(cfg)

            self.assertEqual(resultados[0].status, "ok")
            nir_tif = pasta_saida / "IMAGENS" / "NIR" / "amostra_1_cbers_nir.tif"
            ndvi_tif = pasta_saida / "IMAGENS" / "NDVI" / "amostra_1_cbers_ndvi.tif"
            self.assertTrue(nir_tif.exists())
            self.assertTrue(ndvi_tif.exists())
            with rasterio.open(nir_tif) as src:
                self.assertTrue(np.all(src.read(1) == 300))
            with rasterio.open(ndvi_tif) as src:
                self.assertAlmostEqual(float(src.read(1).mean()), 0.5, places=4)

    def test_completo_baixa_3_bandas_e_versiona_pasta_imagens(self):
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            transformacao = from_origin(300000, 7900000, 8, 8)
            # NIR=B4, RED=B3, GREEN=B2 (ordem bandas_rgb do sensor wpm/aws)
            valores_banda = {"B4": 300, "B3": 100, "B2": 150}
            hrefs: dict[str, str] = {}
            for nome, valor in valores_banda.items():
                caminho = pasta / f"{nome}.tif"
                with rasterio.open(
                    caminho,
                    "w",
                    driver="GTiff",
                    width=512,
                    height=512,
                    count=1,
                    dtype="int16",
                    crs="EPSG:32724",
                    transform=transformacao,
                    nodata=0,
                    tiled=True,
                    blockxsize=256,
                    blockysize=256,
                ) as dst:
                    dst.write(np.full((512, 512), valor, dtype=np.int16), 1)
                hrefs[nome] = str(caminho)

            csv_falso = pasta / "pontos.csv"
            csv_falso.write_text(
                "cod_imovel;x;y\nTESTE;302048;7897952\n", encoding="utf-8"
            )
            pasta_saida = pasta / "saida"
            # Pasta IMAGENS ja existe de uma rodada anterior -> deve versionar
            (pasta_saida / "IMAGENS").mkdir(parents=True)

            cfg = ConfiguracaoExtracao(
                arquivo_csv=csv_falso,
                pasta_saida=pasta_saida,
                produto="completo",
                fonte="aws",
                sensor="wpm",
                data_inicial="2025-01-01",
                data_final="2025-12-31",
                buffer_metros=128,
            )

            item_falso = {
                "type": "Feature",
                "id": "item-teste",
                "bbox": [-180, -90, 180, 90],
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-180, -90],
                            [180, -90],
                            [180, 90],
                            [-180, 90],
                            [-180, -90],
                        ]
                    ],
                },
                "properties": {"datetime": "2025-06-01T00:00:00Z"},
                "assets": {
                    "B4": {"href": hrefs["B4"]},
                    "B3": {"href": hrefs["B3"]},
                    "B2": {"href": hrefs["B2"]},
                },
            }

            with mock.patch(
                "utils.cbers.consultar_itens_stac", return_value=[item_falso]
            ):
                resultados = executar_extracao(cfg)

            self.assertEqual(resultados[0].status, "ok")
            raiz = pasta_saida / "IMAGENS 2"
            self.assertTrue(raiz.exists())
            valores_esperados = {
                "NIR": 300.0,
                "NDVI": 0.5,
                "GNDVI": (300 - 150) / (300 + 150),
                "NDWI": (150 - 300) / (150 + 300),
            }
            for subpasta, esperado in valores_esperados.items():
                sufixo = "nir" if subpasta == "NIR" else subpasta.lower()
                caminho = raiz / subpasta / f"amostra_1_cbers_{sufixo}.tif"
                self.assertTrue(caminho.exists(), f"faltando {caminho}")
                with rasterio.open(caminho) as src:
                    self.assertAlmostEqual(
                        float(src.read(1).mean()), esperado, places=4
                    )
            # pasta original nao foi tocada
            self.assertEqual(list((pasta_saida / "IMAGENS").iterdir()), [])

    def test_proxima_pasta_imagens_incrementa(self):
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            self.assertEqual(proxima_pasta_imagens(pasta), "IMAGENS")
            (pasta / "IMAGENS").mkdir()
            self.assertEqual(proxima_pasta_imagens(pasta), "IMAGENS 2")
            (pasta / "IMAGENS 2").mkdir()
            self.assertEqual(proxima_pasta_imagens(pasta), "IMAGENS 3")

    def test_valida_sensor_na_fonte(self):
        with tempfile.TemporaryDirectory() as temporario:
            csv_path = Path(temporario) / "pontos.csv"
            csv_path.write_text(
                "cod_imovel;x;y\nA;1;2\n", encoding="utf-8"
            )
            cfg = ConfiguracaoExtracao(
                arquivo_csv=csv_path,
                pasta_saida=Path(temporario),
                produto="nir",
                fonte="aws",
                sensor="mux4a",
                data_inicial="2025-01-01",
                data_final="2025-12-31",
            )
            with self.assertRaisesRegex(Exception, "indisponivel"):
                validar_configuracao(cfg)


if __name__ == "__main__":
    unittest.main()

