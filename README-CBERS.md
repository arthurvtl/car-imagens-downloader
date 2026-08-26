# Extrator CBERS

Baixa recortes georreferenciados do CBERS para cada ponto de um CSV.

Produtos:

- `nir`: infravermelho proximo, uma banda;
- `rgb`: imagem colorida em vermelho, verde e azul;
- `ndvi` / `gndvi` / `ndwi`: baixa NIR + a banda extra que a formula usa (da
  mesma cena, pixel a pixel alinhado) e ja calcula o indice espectral;
- `completo`: baixa NIR + Vermelho + Verde numa unica consulta e calcula os
  3 indices (NDVI, GNDVI, NDWI) de uma vez.

Fontes:

- `inpe`: `https://data.inpe.br/bdc/stac/v1/`;
- `aws`: `https://stac.scitekno.com.br/v100`.

As fontes nao exigem login ou chave.

## Instalar

```bash
cd /Users/arthurvtl/IFES/IC/EXTRATOR-CBERS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Abrir a interface

```bash
python interface_tk.py
```

Ou:

```bash
python extrator.py
```

A primeira tela pede `INFRAVERMELHO (NIR)` ou `COLORIDA (RGB)`. Depois:

1. selecione CSV;
2. selecione pasta de saida;
3. escolha INPE ou AWS;
4. escolha sensor;
5. informe periodo e buffer;
6. clique em `Baixar imagens`.

Largura e altura vazias preservam resolucao original do sensor.

## Usar pelo terminal

### NIR pelo AWS, WPM 8 m

```bash
python cli.py \
  --csv coordenadas_treino_amostra.csv \
  --caminho ./saida \
  --produto nir \
  --fonte aws \
  --sensor wpm \
  --data-inicial 2024-01-01 \
  --data-final 2026-07-30 \
  --buffer 1024
```

### NIR pelo INPE, MUX reflectancia 20 m

```bash
python cli.py \
  --csv coordenadas_treino_amostra.csv \
  --caminho ./saida \
  --produto nir \
  --fonte inpe \
  --sensor mux4 \
  --data-inicial 2024-01-01 \
  --data-final 2026-07-30 \
  --buffer 1024 \
  --criterio menor-nuvem \
  --max-nuvens 30
```

### RGB colorido

```bash
python cli.py \
  --csv coordenadas_treino_amostra.csv \
  --caminho ./saida \
  --produto rgb \
  --fonte aws \
  --sensor wpm \
  --data-inicial 2024-01-01 \
  --data-final 2026-07-30 \
  --buffer 1024
```

### NDVI (baixa NIR+Vermelho e ja calcula)

```bash
python cli.py \
  --csv coordenadas_treino_amostra.csv \
  --caminho ./saida \
  --produto ndvi \
  --fonte aws \
  --sensor wpm \
  --data-inicial 2024-01-01 \
  --data-final 2026-07-30 \
  --buffer 1024 \
  --resolucao-m 2
```

Mesma coisa para `--produto gndvi` e `--produto ndwi`.

### Completo: NIR + os 3 indices numa rodada so

```bash
python cli.py \
  --csv coordenadas_treino_amostra.csv \
  --caminho ./saida \
  --produto completo \
  --fonte aws \
  --sensor wpm \
  --data-inicial 2024-01-01 \
  --data-final 2026-07-30 \
  --buffer 1024 \
  --resolucao-m 2
```

`--resolucao-m 2` calcula largura/altura em pixels a partir do `--buffer`
para fechar em 2 m/pixel (nao combinar com `--largura`/`--altura`).

Tambem funciona por `extrator.py`:

```bash
python extrator.py --csv ... --caminho ... --produto nir
```

Ajuda:

```bash
python cli.py --help
python cli.py --listar-opcoes
```

## CSV

Separador padrao: ponto e virgula.

```csv
cod_imovel;x;y
ES-3200136-EXEMPLO;317411.43;7898046.95
```

CRS padrao: `EPSG:31984`. Use `--epsg-entrada` para outro CRS.

## Sensores

| Codigo | Sensor | Resolucao | INPE | AWS |
|---|---|---:|---:|---:|
| `wpm` | CBERS-4A WPM | 8 m NIR/RGB | sim | sim |
| `mux4a` | CBERS-4A MUX | 16 m | sim | nao |
| `mux4` | CBERS-4 MUX | 20 m | sim | sim |
| `wfi4a` | CBERS-4A WFI | 55 m | sim | sim |

No INPE, MUX e WFI L4 SR sao reflectancia de superficie. WPM e produto DN.

## Saida

```text
saida/
  IMAGENS/
    NIR/
      amostra_1_cbers_nir.tif
    RGB/
      amostra_1_cbers_rgb.tif
    NDVI/
      amostra_1_cbers_ndvi.tif
    GNDVI/
      amostra_1_cbers_gndvi.tif
    NDWI/
      amostra_1_cbers_ndwi.tif
  artifacts/
    dataset_cbers_manifesto.csv
```

Cada GeoTIFF guarda CRS, transformacao, nodata, escala, bandas, colecao, cena
e data de aquisicao. O manifesto registra sucesso ou erro de cada linha.
Os arquivos de indice (`NDVI`/`GNDVI`/`NDWI`) sao float32, valores -1..+1
(nodata = NaN).

`--produto completo` versiona a pasta `IMAGENS` sozinho: se ela ja existir na
pasta de saida (de uma rodada anterior), cria `IMAGENS 2`, `IMAGENS 3`... em
vez de misturar ou sobrescrever. Os outros produtos usam sempre `IMAGENS/`
fixo (pulam o download se o arquivo ja existe, a menos que `--sobrescrever`).

## Notebook 5 x 3

O notebook `amostra_5x3.ipynb` compara cinco amostras:

| Coluna 1 | Coluna 2 | Coluna 3 |
|---|---|---|
| Satelite RGB | Segmentado | Infravermelho NIR |

Abrir:

```bash
cd /Users/arthurvtl/IFES/IC/EXTRATOR-CBERS
source .venv/bin/activate
jupyter lab amostra_5x3.ipynb
```

Execute todas as celulas. A figura tambem sera salva em:

```text
artifacts/amostra_5x3.png
```

Pastas configuradas no notebook:

```text
/Users/arthurvtl/IFES/IC/ORIGINAL
/Users/arthurvtl/IFES/IC/SEGMENTADO
/Users/arthurvtl/IFES/IC/INFRAVERMELHO/NIR
```

## Tamanho

`--buffer 1024` cria recorte de aproximadamente 2.048 x 2.048 metros.

Sem `--largura` e `--altura`, pixels seguem resolucao nativa. Para forcar
dimensao:

```bash
--largura 256 --altura 256
```

Isso reamostra a imagem; nao cria detalhe espacial novo.
