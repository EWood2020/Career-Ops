# Alza.cz Local Scraper

Scraper local (gratis) para extraer productos de Alza.cz y generar un archivo maestro CSV/XLSX con datos normalizados para importación a WooCommerce.

## 📁 Estructura del Proyecto

```
alza-local/
├── local.js              # Script principal del scraper
├── package.json          # Dependencias del proyecto
├── README.md            # Este archivo
│
├── helpers/             # Funciones auxiliares
│   ├── familyModel.js   # Lógica para derivar Family/Model
│   └── taxonomy.js      # Sistema de clasificación inteligente de categorías
│
├── scripts/            # Scripts de post-procesamiento
│   └── clean_to_master.js  # Limpia CSVs existentes aplicando reglas
│
├── output/             # Archivos de salida (SOLO CSV y XLSX finales)
│   ├── flexnology_master.csv   # ⭐ Archivo maestro CSV
│   ├── flexnology_master.xlsx   # ⭐ Archivo maestro Excel
│   ├── backups/        # Backups automáticos (no tocar)
│   │   └── flexnology_master.YYYYMMDDHHMMSS.bak.csv
│   └── logs/          # Logs de merge (no tocar)
│       └── merge-YYYY-MM-DD-HH-mm-ss.log
│
└── storage/            # Datos temporales de Crawlee (no tocar)
```

## 🚀 Inicio Rápido

### 1. Instalación

```bash
# Instalar dependencias
npm install

# Instalar navegador de Playwright (solo primera vez)
npx playwright install chromium
```

### 2. Configuración

Edita `local.js` y ajusta:

```javascript
const START_URLS = [
  'https://www.alza.cz/EN/laptops/18842920.htm',
  'https://www.alza.cz/EN/lcd-monitors/18842948.htm',
  // ... más categorías
];

const MAX_PER_CAT = 80; // Productos por categoría
```

### 3. Ejecutar

```bash
node local.js
```

## 📊 Archivos de Salida

### Archivos Principales (en `output/`)

- **`flexnology_master.csv`** - Archivo maestro CSV con todos los productos
- **`flexnology_master.xlsx`** - Versión Excel del mismo archivo

**Estos son los únicos archivos que necesitas.** El resto (backups y logs) se generan automáticamente.

### Archivos Automáticos (no necesitas tocarlos)

- **`output/backups/`** - Backups automáticos antes de cada merge
- **`output/logs/`** - Logs de cambios en cada merge

## 🔄 Cómo Funciona

### Clasificación Inteligente de Categorías

El scraper usa un sistema de **scoring inteligente** para clasificar productos:

1. **Analiza múltiples señales**:
   - **Breadcrumbs** (peso alto: 4 puntos)
   - **URL path** (peso medio: 3 puntos)
   - **Keywords en nombre/descripción** (peso medio: 2 puntos)

2. **Elige la mejor categoría** según puntuación total (mínimo 3 puntos)

3. **Evita genéricos** como "Computers & Tablets" cuando hay señales claras (ej: "projector" → "TV, Photo, Audio & Video > Projectors")

**Ejemplo**: Un proyector con "DLP laser", "4K UHD", "ANSI lm" en la descripción y `/projectors/` en la URL obtendrá:
- +2 puntos por keywords
- +3 puntos por URL
- **Total: 5 puntos** → Categoría correcta: "TV, Photo, Audio & Video > Projectors"

Las reglas están en `helpers/taxonomy.js` y son fácilmente editables.

### Filtro de Imágenes Mejorado

Solo se guardan imágenes de producto reales:
- ✅ Debe ser de `image.alza.cz`
- ✅ Debe contener `/products/` en la ruta
- ❌ Excluye: `/ikony/`, `/icons/`, `/bannery/`, `/variants/`, `/awards/`

### Smart Merge

El scraper usa un sistema de **smart merge** que:

1. **Carga el archivo maestro** existente (si existe)
2. **Fusiona nuevos productos** con reglas inteligentes:
   - ✅ **Preserva** tus ediciones manuales (Family, Model, Category, etc.)
   - ✅ **Actualiza** campos volátiles (Price, Links)
   - ✅ **Completa** campos vacíos desde nuevos datos
   - ✅ **Evita duplicados** por EAN, SKU o URL
3. **Crea backup** automático antes de escribir
4. **Genera changelog** con los cambios realizados

### Filtrado Inteligente

- ✅ Solo procesa **páginas de producto** (no landings/catálogos)
- ✅ Valida señales de producto (JSON-LD, precio, botón "Add to cart")
- ✅ Descarta filas sin datos mínimos (name + price + SKU/EAN/URL)

## 📝 Columnas del Archivo Maestro

El CSV/XLSX tiene 18 columnas normalizadas:

| Columna | Descripción |
|---------|-------------|
| `SKU` | Código SKU del producto |
| `EAN` | Código EAN/GTIN |
| `Brand` | Marca del producto |
| `Family` | Línea de producto (ej: "iPad", "Nintendo Switch 2") |
| `Model` | Modelo específico (ej: "iPad Air (M3)") |
| `Description General` | Descripción del producto |
| `Category` | Categoría principal |
| `Subcategory` | Subcategoría |
| `Option Storage` | Almacenamiento (si aplica) |
| `Option Color` | Color (si aplica) |
| `Watch Size` | Talla de reloj (si aplica) |
| `Band` | Pulsera (si aplica) |
| `Sizes` | Tallas (si aplica) |
| `Inch` | Pulgadas (monitores, etc.) |
| `Connectivity` | Conectividad (HDMI, USB-C, etc.) |
| `Tags` | Tags para WooCommerce |
| `Price` | Precio en formato CZK12345.00 |
| `Links` | URL del producto en Alza |
| `Image` | URL de imagen principal |
| `Images` | URLs de todas las imágenes (separadas por coma) |
| `WooCategoryPath` | Ruta de categoría para WooCommerce |

## 🛠️ Scripts Adicionales

### Limpiar CSV Existente

Si tienes un CSV antiguo y quieres aplicar las reglas de Family/Model:

```bash
node scripts/clean_to_master.js input.csv output.xlsx
```

Esto aplicará:
- Derivación de Family/Model
- Decodificación de entidades HTML
- Mapeo de categorías según taxonomía

## 🎯 Taxonomía v1.0 - Estructura Completa

El sistema usa una taxonomía estructurada en 6 bloques principales:

### A) Toys & Games
- **LEGO**: Family = "LEGO", Model = nombre del set
- **Party & Card Games**: Board games, party games, card games

### B) Computers & Tablets
- **Laptops**: Gaming, Home & Office, Professional (Family = marca, Model = línea)
- **Monitors & Displays**: Gaming, Professional, Curved, 4K (Family = marca/serie)
- **VR Glasses**: For PC, Consoles, Standalone
- **Projectors**: Mini, Home Theater, Laser (Family = marca, Model = nombre completo)

### C) TV, Photo, Audio & Video
- **Drones**: Camera, Mini, Professional (Family = línea: Mavic/Mini/Air/Avata)
- **Headphones**: True Wireless, Over-Ear, Gaming (Family = serie: Sony WH/WF, Bose QC)

### D) Gaming & Entertainment
- **PlayStation**: Family = "PlayStation", Model = "PS5 Pro", "DualSense..."
- **Xbox**: Family = "Xbox", Model = "Xbox Series X"
- **Nintendo Switch**: Family = "Nintendo Switch", Model = "Nintendo Switch 2 + Pokémon..."

### E) Pet Supplies
- **Dogs**: Food, Treats, Beds, Toys, etc.
- **Cats**: Food, Treats, Litter, Toys, etc.

### F) Household & Personal Appliances
- **Robotic Vacuum Cleaners**: Family = línea (ej: "Roborock Qrevo")

## 🎯 Personalizar Clasificación de Categorías

Las reglas de clasificación están en `helpers/taxonomy.js`. Puedes editarlas fácilmente:

### Añadir Nueva Categoría

```javascript
"TV, Photo, Audio & Video": {
  "Nueva Subcategoría": {
    kw: ["keyword1", "keyword2", "keyword3"],  // Palabras clave en nombre/descripción
    url: ["url-path-1", "url-path-2"],          // Rutas en URL
    score: { kw: 2, url: 3, bc: 4 },            // Puntos por cada señal
    family: "Family Name"                        // Opcional: Family sugerido
  }
}
```

### Ajustar Umbral

En `helpers/taxonomy.js`, función `classifyCategory()`:
- Cambiar `if (best.score >= 3)` a `if (best.score >= 4)` para ser más estricto
- Cambiar `if (best.score >= 3)` a `if (best.score >= 2)` para ser más permisivo

### Reglas de Forzado

El sistema fuerza categorías específicas cuando detecta señales claras:
- **Projectors**: Si encuentra "projector", "beamer", "ANSI lm", "DLP" → fuerza "TV, Photo, Audio & Video > Projectors"
- **Drones**: Si encuentra "drone", "mavic", "dji" → fuerza "TV, Photo, Audio & Video > Drones"
- **Headphones**: Si encuentra "headphone", "headset", "wh-", "wf-" → fuerza "TV, Photo, Audio & Video > Headphones"

Esto evita que productos claramente identificables caigan en "Computers & Tablets" genérico.

## ⚙️ Configuración Avanzada

### Modo Legacy (archivos con timestamp)

Si prefieres crear un nuevo archivo en cada run:

```javascript
const SINGLE_OUTPUT = false; // Cambiar a false
```

### Ajustar Concurrencia

```javascript
maxConcurrency: 1, // Reducir si hay bloqueos
```

### Ajustar Límites

```javascript
const MAX_PER_CAT = 80; // Productos por categoría
const MAX_REQUESTS = START_URLS.length * MAX_PER_CAT + 100;
```

## 🐛 Troubleshooting

### Error: "log.info is not a function"
✅ Ya está arreglado. Usa la versión más reciente.

### Muchos archivos en output/
✅ Los backups y logs ahora van en subcarpetas. Solo quedan CSV y XLSX en `output/`.

### Productos duplicados
✅ El smart merge evita duplicados automáticamente por EAN/SKU/URL.

### Páginas bloqueadas
- Reduce `maxConcurrency` a 1
- Reduce `MAX_PER_CAT` a 40-60
- Aumenta `navigationTimeoutSecs` a 60

## 📚 Más Información

- **Family/Model**: Ver `IMPLEMENTATION_PLAN.md` para detalles sobre la derivación
- **Taxonomía**: Las categorías se mapean automáticamente según URL y contenido
- **Backups**: Se crean automáticamente antes de cada merge (en `output/backups/`)

## 📄 Licencia

ISC

