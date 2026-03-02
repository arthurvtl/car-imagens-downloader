# Instrução 1 — Viabilidade do Projeto IntegraCar: Automação de Extração de Imagens

## 1. Contexto do Projeto

O **IntegraCar** é um projeto do IFES Serra em parceria com FAPES, IDAF e outros órgãos do Espírito Santo, com foco no cadastramento do **CAR (Cadastro Ambiental Rural)** no estado.

A parte técnica sob responsabilidade desta automação consiste em:

> **Dado um conjunto de coordenadas geográficas (imóveis rurais do CAR-ES), baixar automaticamente, para cada ponto, duas versões de imagem:**
> 1. **Imagem de satélite bruta** (KOMPSAT 2019/2020 — sem segmentação, RGB)
> 2. **Imagem de uso do solo segmentada** (Uso do Solo IJSN — mapa de classes com cores)

Essas duas imagens serão usadas como entrada para um modelo de **segmentação semântica** já desenvolvido por um colega do mestrado.

---

## 2. Fonte de Dados: GeoBases ES

A base de dados é o **GeoBases** — Sistema Integrado de Bases Geoespaciais do Estado do Espírito Santo.

- Portal principal: [https://geobases.es.gov.br](https://geobases.es.gov.br)
- IDE (catálogo de camadas): [https://ide.geobases.es.gov.br](https://ide.geobases.es.gov.br)
- Servidor GeoServer (WMS/WCS/WFS): `https://ide.geobases.es.gov.br/geoserver/ows`
- API REST de camadas: `https://ide.geobases.es.gov.br/api/layers/`
- Total de camadas disponíveis: **879 camadas** (confirmado via API)
- Plataforma: GeoNode 3.1.0 + GeoServer (backend padrão de IDEs brasileiras)

---

## 3. Viabilidade Técnica

### Veredicto: ✅ VIÁVEL

A abordagem é tecnicamente sólida e amplamente utilizada em projetos de geoprocessamento automatizado. Os serviços GeoBases expõem padrões abertos **OGC (Open Geospatial Consortium)**, amplamente suportados por bibliotecas Python.

### Por que é viável?

| Fator | Situação |
|---|---|
| Protocolo de acesso | WMS (Web Map Service) — padrão aberto, sem necessidade de scraping |
| Autenticação | Camadas públicas acessíveis sem credenciais (confirmado via API) |
| Formato de entrada | CSV com `cod_imovel`, `x`, `y` em UTM EPSG:31984 — fácil leitura com pandas |
| Linguagem | Python — bibliotecas maduras para todo o pipeline |
| Paralelismo | Possível baixar múltiplos pares de imagens em paralelo |
| Configurabilidade | Buffer/tamanho do recorte facilmente parametrizável |

---

## 4. As Duas Camadas Alvo

### 4.1 Imagem de Satélite Bruta — KOMPSAT 2019/2020

O satélite **KOMPSAT** (Korea Multi-Purpose Satellite) é um satélite de observação terrestre de alta resolução (~1m/pixel), operado pela KARI (Coreia do Sul). O GeoBases possui mosaicos ortorretificados do ES adquiridos em 2019/2020.

> **Importante:** Durante a pesquisa na API pública do GeoBases, a camada KOMPSAT não apareceu indexada com esse nome exato. Isso pode indicar que:
> - A camada existe com nomenclatura diferente (ex.: `ijsn_ortomosaico_kompsat_...` ou similar)
> - A camada pode requerer acesso autenticado via conta institucional
>
> **Ação necessária antes de implementar:** Confirmar o `typename` exato da camada KOMPSAT no QGIS (basta adicionar a camada WMS e verificar o nome técnico nos metadados da camada).

**Exemplo de URL WMS (a ser ajustada com o typename correto):**
```
https://ide.geobases.es.gov.br/geoserver/ows?
  SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap
  &LAYERS=geonode:NOME_DA_CAMADA_KOMPSAT
  &BBOX=314000,7870000,315000,7871000
  &WIDTH=1024&HEIGHT=1024
  &SRS=EPSG:31984
  &FORMAT=image/tiff
```

### 4.2 Mapa de Uso do Solo — IJSN

O **IJSN (Instituto Jones dos Santos Neves)** é responsável pelo mapeamento de uso e cobertura do solo do ES. Esta é a camada que, quando visualizada no QGIS, gera o mapa colorido por categoria (como na imagem de exemplo fornecida).

> **Ação necessária:** Da mesma forma, confirmar o `typename` da camada Uso do Solo IJSN no QGIS.

**Camada PlanetScope disponível (alternativa/fallback):**  
Foi confirmada na API a existência de uma imagem de satélite recente do estado inteiro:
- Título: `SEAMA - ORTOMOSAICO PLANETSCOPE - RGB - 2025`
- typename: `geonode:seama-mosaico-planetscope-rgb-epsg_32724`
- Suporta: WMS e WCS
- SRID: EPSG:32724 (UTM zona 24S WGS84)
- Cobertura: todo o ES

---

## 5. Como Faremos — Pipeline Proposto

```
CSV de coordenadas
        ↓
  Leitura com pandas
        ↓
  Para cada imóvel (cod_imovel, x, y):
        ↓
  Calcular bounding box (x ± buffer, y ± buffer)
        ↓
  ┌─────────────────────────────┐    ┌──────────────────────────────┐
  │  Requisição WMS — KOMPSAT   │    │  Requisição WMS — Uso do Solo│
  │  (imagem bruta RGB)         │    │  (mapa de classes colorido)  │
  └─────────────────────────────┘    └──────────────────────────────┘
              ↓                                    ↓
     Salvar como GeoTIFF                Salvar como GeoTIFF
     (1024×1024 px, EPSG:31984)         (1024×1024 px, EPSG:31984)
              ↓
  Par de imagens: {cod_imovel}_satelite.tif
                  {cod_imovel}_uso_solo.tif
```

### Estrutura de pastas de saída sugerida:
```
saida/
├── ES-3200136-AED7.../
│   ├── satelite.tif       ← GeoTIFF 1024×1024, RGB, EPSG:31984
│   └── uso_solo.tif      ← GeoTIFF 1024×1024, RGB, EPSG:31984
├── ES-3201001-3619.../
│   ├── satelite.tif
│   └── uso_solo.tif
...
```

---

## 6. Bibliotecas Python Necessárias

| Biblioteca | Finalidade | Obrigatória? |
|---|---|---|
| `pandas` | Leitura e iteração do CSV de coordenadas | ✅ Sim |
| `requests` | Requisições HTTP para os endpoints WMS | ✅ Sim |
| `rasterio` | Salvar GeoTIFF com georreferenciamento real (CRS + transform) | ✅ Sim |
| `numpy` | Manipular arrays de pixels antes de gravar com rasterio | ✅ Sim |
| `tqdm` | Barra de progresso durante download em lote | Recomendada |
| `concurrent.futures` | Download paralelo para acelerar o processo | Recomendada |
| `Pillow (PIL)` | Leitura intermediária da resposta WMS antes de passar ao rasterio | Opcional |
| `pyproj` | Conversão de coordenadas UTM ↔ Lat/Lon se necessário | Opcional |

> **Por que `rasterio` e não `Pillow`?**  
> O formato GeoTIFF vai além de uma imagem comum — ele embute o **sistema de referência (CRS EPSG:31984)** e a **transformação afim** (posição geográfica real de cada pixel). O `rasterio` grava esses metadados espaciais corretamente. O `Pillow` salvaria apenas pixels, sem informação geográfica — inutilizando o TIF para uso em GIS.

---

## 7. Parâmetros Configuráveis (boas práticas)

O código será estruturado com configurações centralizadas e facilmente alteráveis:

```python
# Exemplo de bloco de configuração
CONFIGURACOES = {
    "wms_url": "https://ide.geobases.es.gov.br/geoserver/ows",
    "camada_satelite": "geonode:NOME_KOMPSAT",        # a confirmar no QGIS
    "camada_uso_solo": "geonode:NOME_IJSN_USO_SOLO", # a confirmar no QGIS
    "srid": "EPSG:31984",
    "epsg_codigo": 31984,
    "buffer_metros": 512,       # recorte de ~1024m x 1024m ao redor do ponto
    "largura_pixels": 1024,
    "altura_pixels": 1024,
    "formato_wms": "image/tiff",
    "extensao_saida": ".tif",
    "pasta_saida": "saida/",
    "arquivo_csv": "coordenadas_treino_amostra.csv",
    "separador_csv": ";",
}
```

> **Nota sobre o buffer:** com `buffer_metros = 512` e `1024 pixels`, cada pixel representa **1 metro no terreno** — compatível com a resolução do KOMPSAT (~1m/pixel). Ajuste conforme a resolução real da camada confirmada.

---

## 8. Pontos de Atenção / Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Typename da camada KOMPSAT não confirmado | Média | Verificar no QGIS antes de implementar |
| Camada KOMPSAT pode exigir autenticação institucional | Média | Testar com credenciais do IFES/FAPES |
| Rate limiting do servidor GeoBases | Baixa | Adicionar `time.sleep()` entre requisições ou usar sessões com retry |
| Imagens sem dados (fora da cobertura) | Baixa | Validar se a imagem não é toda branca/transparente após download |
| Diferentes SRIDs entre camadas | Baixa | KOMPSAT em EPSG:31984, PlanetScope em EPSG:32724 — padronizar na requisição |

---

## 9. Próximos Passos

1. **[IMEDIATO]** Abrir o QGIS, adicionar a camada KOMPSAT e a camada Uso do Solo IJSN via WMS do GeoBases
2. **[IMEDIATO]** Capturar os `typename` exatos de cada camada (visível nos metadados no QGIS ou na URL da camada)
3. **[IMEDIATO]** Testar manualmente uma URL WMS no navegador para confirmar o acesso público
4. **[PRÓXIMA FASE]** Implementar o script Python de extração automatizada
5. **[PRÓXIMA FASE]** Validar os pares de imagens gerados com alguns pontos do CSV de amostra

---

## 10. Resumo Executivo

| Item | Status |
|---|---|
| É possível automatizar o download? | ✅ Sim |
| O GeoBases oferece WMS programático? | ✅ Sim, via GeoServer OGC |
| Existem 879 camadas públicas disponíveis? | ✅ Confirmado via API |
| KOMPSAT está confirmado no GeoBases? | ⚠️ Precisa verificar typename exato no QGIS |
| Uso do Solo IJSN está no GeoBases? | ⚠️ Precisa verificar typename exato no QGIS |
| Linguagem: Python? | ✅ Totalmente suportado |
| CSV como entrada? | ✅ Formato já estruturado e pronto |
| Custo de implementação | Baixo — bibliotecas open source |

> **Conclusão:** O projeto é **totalmente viável**. A principal etapa bloqueante antes de escrever o código é confirmar os `typename` exatos das camadas KOMPSAT e Uso do Solo IJSN no GeoBases via QGIS. Com esses nomes em mãos, o script Python pode ser desenvolvido de forma completa e funcional.
