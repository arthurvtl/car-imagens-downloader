# Guia de Satélites

## KOMPSAT-3/3A

### Descrição
Satélite sul-coreano de observação da Terra operado pela KARI.
No contexto deste projeto, o ortomosaico KOMPSAT disponibilizado
pelo GeoBases ES (Espírito Santo) é acessado via serviço WMS.

### Especificações
- **Resolução espacial**: 0.5m (pancromático), 2m (multiespectral)
- **Bandas no projeto**: RGB (composição colorida)
- **Cobertura**: Estado do Espírito Santo
- **Protocolo**: WMS GetMap
- **Temporalidade**: Mosaico estático (2019-2020)

### Quando Usar
- Análise visual de alta resolução
- Mapeamento urbano e cadastral
- Identificação de edificações e vias
- Combinação com camada segmentada de uso do solo

---

## Sentinel-2

### Descrição
Constelação de dois satélites (2A e 2B) da ESA (Agência Espacial Europeia)
dentro do programa Copernicus. Fornece imagens multiespectrais gratuitas
com resolução de 10-60m e revisita de ~5 dias.

### Especificações
| Banda | Nome    | Comprimento de Onda | Resolução |
|-------|---------|---------------------|-----------|
| B02   | Blue    | 490nm               | 10m       |
| B03   | Green   | 560nm               | 10m       |
| B04   | Red     | 665nm               | 10m       |
| B08   | NIR     | 842nm               | 10m       |
| B11   | SWIR-1  | 1610nm              | 20m       |
| B12   | SWIR-2  | 2190nm              | 20m       |

### Produtos
- **Level-2A (L2A)**: Reflectância de superfície (correção atmosférica aplicada)
- Disponível gratuitamente via Planetary Computer STAC

### Quando Usar
- Monitoramento agrícola (NDVI, índices de vegetação)
- Detecção de desmatamento
- Mapeamento de uso do solo em larga escala
- Análise de corpos d'água
- Séries temporais com alta frequência

### Índices Calculáveis
- **NDVI** = (B08 - B04) / (B08 + B04)
- **NDWI** = (B03 - B08) / (B03 + B08)
- **NBR** = (B08 - B12) / (B08 + B12)

---

## Landsat 8/9

### Descrição
Programa da NASA/USGS com dados contínuos desde 1972. Landsat 8 (OLI/TIRS)
e Landsat 9 fornecem imagens multiespectrais e termais de toda a Terra.
A banda termal (TIR) é o diferencial em relação ao Sentinel-2.

### Especificações
| Banda  | Nome    | Comprimento de Onda | Resolução |
|--------|---------|---------------------|-----------|
| blue   | Blue    | 482nm               | 30m       |
| green  | Green   | 562nm               | 30m       |
| red    | Red     | 655nm               | 30m       |
| nir08  | NIR     | 865nm               | 30m       |
| swir16 | SWIR-1  | 1609nm              | 30m       |
| swir22 | SWIR-2  | 2201nm              | 30m       |
| lwir11 | TIR     | 10895nm             | 100m      |

### Quando Usar
- Análise de temperatura de superfície (banda termal)
- Ilhas de calor urbanas
- Estudos climáticos de longo prazo (arquivo desde 1972)
- Monitoramento de incêndios (combinação SWIR + TIR)
- Evapotranspiração e balanço hídrico

### Nota sobre TIR
A banda termal (lwir11) mede radiância emitida, não refletida.
Pode ser convertida em temperatura de superfície (em Kelvin) com:
```
T = K2 / ln(K1 / L + 1)
```
Onde K1, K2 são constantes de calibração e L é a radiância.

---

## CBERS-4A

### Descrição
Satélite do programa sino-brasileiro (INPE/CRESDA). O sensor WPM
(Wide-sweep Panchromatic and Multispectral) oferece alta resolução
espacial (2m multiespectral) com cobertura focada no Brasil.

### Especificações
| Banda  | Nome    | Comprimento de Onda | Resolução |
|--------|---------|---------------------|-----------|
| BAND1  | Blue    | 485nm               | 2m        |
| BAND2  | Green   | 555nm               | 2m        |
| BAND3  | Red     | 660nm               | 2m        |
| BAND4  | NIR     | 830nm               | 2m        |

### Fonte de Dados
- **Catálogo STAC**: INPE/BDC (Brazil Data Cube)
- URL: `https://data.inpe.br/bdc/stac/v1`
- Não requer assinatura de tokens

### Quando Usar
- Alta resolução espacial (2m) com dados brasileiros
- Monitoramento de desmatamento na Amazônia
- Mapeamento cadastral de imóveis rurais
- Alternativa ao KOMPSAT com cobertura nacional

### Limitações
- Cobertura temporal irregular (depende da programação)
- Catálogo STAC pode estar intermitente
- Menor número de bandas comparado a Sentinel-2

---

## Tabela Comparativa

| Critério        | KOMPSAT  | Sentinel-2 | Landsat  | CBERS-4A |
|-----------------|----------|------------|----------|----------|
| Resolução       | 0.5m     | 10-20m     | 30-100m  | 2m       |
| Bandas          | RGB      | 6+         | 7+       | 4        |
| TIR             | Não      | Não        | **Sim**  | Não      |
| NIR             | Não      | **Sim**    | **Sim**  | **Sim**  |
| SWIR            | Não      | **Sim**    | **Sim**  | Não      |
| Cobertura       | ES       | Global     | Global   | Brasil   |
| Revisita        | Estático | ~5 dias    | ~8 dias  | Variável |
| Custo           | Gratuito | Gratuito   | Gratuito | Gratuito |
| Protocolo       | WMS      | STAC/COG   | STAC/COG | STAC     |
