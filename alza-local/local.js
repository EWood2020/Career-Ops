// local.js - Scraper local (gratis) con guardado incremental CSV

import fs from 'fs';
import path from 'path';
import { PlaywrightCrawler, log } from 'crawlee';
import * as XLSX from 'xlsx';
import { deriveFamilyModel } from './helpers/familyModel.js';
import { classifyCategory } from './helpers/taxonomy.js';

// ---------- CONFIG EDITABLE ----------
const START_URLS = [
  // A) Toys & Games
  'https://www.alza.cz/EN/toys/lego/18851136.htm',
  // TODO: añadir subcategorías Party/Card games desde el menú EN

  // B) Computers & Laptops
  'https://www.alza.cz/EN/laptops/18842920.htm',
  // TODO: añadir Gaming/Home-Office/Professional/Apple/Lenovo/HP/Dell/Acer/Asus/MSI/Surface
  'https://www.alza.cz/EN/lcd-monitors/18842948.htm',
  // TODO: añadir Curved/Gaming/4K/Portable/Large/Smart/Used/Accessories
  'https://www.alza.cz/EN/gaming/vr-glasses/18859989.htm',
  // TODO: añadir subcategorías VR por dispositivo (PC/Console/Mobile/Drones)
  'https://www.alza.cz/EN/projectors/18843223.htm',
  // TODO: añadir pantallas/accesorios si se comercializan

  // C) TV, Photo, Audio & Video
  'https://www.alza.cz/EN/drones/18855539.htm',
  'https://www.alza.cz/EN/headphones/18843602.htm',
  // TODO: añadir Wireless/TWS/In-Ear/Over-Ear/Gaming/Bone Conduction/Sports/With Mic/Accessories

  // D) Gaming & Entertainment
  'https://www.alza.cz/EN/gaming/playstation/18915789.htm',
  'https://www.alza.cz/EN/gaming/xbox/18892642.htm',
  'https://www.alza.cz/EN/gaming/nintendo-switch/18860896.htm',
  // TODO: añadir Accessories/Games para cada plataforma

  // E) Pet Supplies
  'https://www.alza.cz/EN/pet/pet-supplies-for-dogs/18869014.htm',
  'https://www.alza.cz/EN/pet/pet-supplies-for-cats/18869016.htm',
  // TODO: añadir Food/Treats/Beds si se necesitan colecciones específicas

  // F) Household & Personal Appliances
  'https://www.alza.cz/EN/robotic-vacuum-cleaners/18850167.htm',
  // TODO: añadir accesorios de aspiradoras robot si procede
];

const MAX_PER_CAT = 80; // 60–80 como pediste
const MAX_REQUESTS = START_URLS.length * MAX_PER_CAT + 100; // techo razonable

// ---------- SMART MERGE CONFIG ----------
const SINGLE_OUTPUT = true;
const OUT_DIR = 'output';
const MASTER_CSV = `${OUT_DIR}/flexnology_master.csv`;
const MASTER_XLSX = `${OUT_DIR}/flexnology_master.xlsx`;
const BACKUP_ON_WRITE = true;

// Legacy support (for backward compatibility)
const OUT_CSV = SINGLE_OUTPUT ? MASTER_CSV : `output/flexnology_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.csv`;
const OUT_XLSX = SINGLE_OUTPUT ? MASTER_XLSX : OUT_CSV.replace(/\.csv$/i, '.xlsx');
const APPEND_TO_EXISTING = true; // mantener historial previo
// -------------------------------------

// ---------- PRODUCT URL FILTERS ----------
// URLs must match product page pattern
const PRODUCT_ALLOW = /(\/[a-z0-9-]+-d\d+\.htm$)|(\/\d+\.htm$)|(-d\d+\.htm$)/i;
const DENY_PATTERNS = [
  /\/(software|media|promo|article|brand|campaign|tips|reviews|best|luxurious|cheap|bestsellers)\/\d+\.htm$/i,
  /[?&](o|banner|utm|fbclid)=/i,
];

function isAllowedProductUrl(u) {
  if (!PRODUCT_ALLOW.test(u)) return false;
  return !DENY_PATTERNS.some(rx => rx.test(u));
}

function isBadLandingRow(row) {
  const u = (row.Links || row.URL || '').toLowerCase();
  // Has /software/ but not a product page pattern
  return /\/software\//i.test(u) && !PRODUCT_ALLOW.test(u);
}
// -------------------------------------

const csvSafeSplit = (line) => line.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/);

// ---------- SMART MERGE FUNCTIONS ----------
function readCsvAsRows(p) {
  if (!fs.existsSync(p)) return [];
  const text = fs.readFileSync(p, 'utf8').split(/\r?\n/).filter(Boolean);
  if (text.length <= 1) return [];
  const headers = csvSafeSplit(text[0]).map(h => h.replace(/^"|"$/g, '').trim());
  return text.slice(1).map(line => {
    const cols = csvSafeSplit(line);
    const obj = {};
    headers.forEach((h, i) => {
      const raw = (cols[i] ?? '').replace(/^"|"$/g, '').replace(/""/g, '"');
      obj[h] = raw;
    });
    return obj;
  });
}

function writeRowsToCsv(p, rows) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const esc = (s) => {
    const str = (s ?? '').toString();
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  const lines = [
    headers.join(','),
    ...rows.map(r => headers.map(h => esc((r[h] ?? '').toString())).join(','))
  ];
  fs.writeFileSync(p, lines.join('\n') + '\n', 'utf8');
}

function backupFile(p) {
  if (!fs.existsSync(p)) return;
  const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15);
  const backupDir = path.join(OUT_DIR, 'backups');
  if (!fs.existsSync(backupDir)) {
    fs.mkdirSync(backupDir, { recursive: true });
  }
  const base = path.basename(p, '.csv');
  const bak = path.join(backupDir, `${base}.${ts}.bak.csv`);
  fs.copyFileSync(p, bak);
  console.log(`✓ Backup creado → ${bak}`);
}

function makeKey(r) {
  return (r.EAN && `EAN:${r.EAN}`) || (r.SKU && `SKU:${r.SKU}`) || (r.Links && `URL:${r.Links}`) || null;
}

function smartMergeRow(master, incoming, log) {
  const keepIfFilled = (field) => {
    if (!master[field] && incoming[field]) {
      master[field] = incoming[field];
    }
  };

  const preferIncoming = (field, label = field) => {
    const incVal = (incoming[field] || '').toString().trim();
    const masVal = (master[field] || '').toString().trim();
    if (incVal && incVal !== masVal) {
      log.push(`~ ${label}: "${masVal}" → "${incVal}"`);
      master[field] = incVal;
    }
  };

  const joinTags = () => {
    const a = ((master.Tags || '').toString()).split(',').map(s => s.trim()).filter(Boolean);
    const b = ((incoming.Tags || '').toString()).split(',').map(s => s.trim()).filter(Boolean);
    master.Tags = [...new Set([...a, ...b])].join(', ');
  };

  // Campos que NO se pisan si ya existen (preservar curación manual)
  keepIfFilled('Brand');
  keepIfFilled('Description General');
  keepIfFilled('Family');
  keepIfFilled('Model');
  keepIfFilled('Category');
  keepIfFilled('Subcategory');
  keepIfFilled('Option Storage');
  keepIfFilled('Option Color');
  keepIfFilled('Inch');
  keepIfFilled('Connectivity');

  // Siempre reflejar precio/enlace si cambia (campos volátiles)
  preferIncoming('Price', 'Price');
  preferIncoming('Links', 'Links');

  // Completar vacíos desde incoming
  const fillable = ['Brand', 'Description General', 'Family', 'Model', 'Category', 'Subcategory', 
                    'Option Storage', 'Option Color', 'Inch', 'Connectivity', 'EAN', 'SKU'];
  fillable.forEach(f => {
    if (!master[f] && incoming[f]) master[f] = incoming[f];
  });

  // Tags: unión sin duplicar
  joinTags();

  // Images: añadir si maestro vacío
  if (!master.Image && incoming.Image) master.Image = incoming.Image;
  if (!master.Images && incoming.Images) master.Images = incoming.Images;
  else if (incoming.Images && master.Images) {
    const masImgs = (master.Images || '').split(',').map(s => s.trim()).filter(Boolean);
    const incImgs = (incoming.Images || '').split(',').map(s => s.trim()).filter(Boolean);
    master.Images = [...new Set([...masImgs, ...incImgs])].join(',');
  }

  return master;
}

function smartMergeAll(incomingRows) {
  const log = [];
  const masterRows = readCsvAsRows(MASTER_CSV);
  const byKey = new Map(masterRows.map(r => [makeKey(r), r]));

  let inserted = 0, updated = 0, skippedNoKey = 0, skippedLanding = 0;

  // Filtrar landings antes de procesar
  const cleanIncoming = incomingRows.filter(r => {
    if (isBadLandingRow(r)) {
      skippedLanding++;
      return false;
    }
    return true;
  });

  for (const inc of cleanIncoming) {
    const key = makeKey(inc);
    if (!key) {
      skippedNoKey++;
      continue;
    }

    if (!byKey.has(key)) {
      byKey.set(key, inc);
      inserted++;
      log.push(`+ [${key}] Nuevo producto: ${inc.Model || inc['Description General'] || 'Sin nombre'}`);
    } else {
      const current = byKey.get(key);
      const rowLog = [];
      const merged = smartMergeRow(current, inc, rowLog);
      byKey.set(key, merged);
      if (rowLog.length) {
        updated++;
        log.push(`~ [${key}] ${rowLog.join(' | ')}`);
      }
    }
  }

  const finalRows = Array.from(byKey.values());

  if (BACKUP_ON_WRITE && fs.existsSync(MASTER_CSV)) {
    backupFile(MASTER_CSV);
  }

  writeRowsToCsv(MASTER_CSV, finalRows);

  // Espejo XLSX
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(finalRows), 'Products');
  XLSX.writeFile(wb, MASTER_XLSX);

  // Changelog
  const logsDir = path.join(OUT_DIR, 'logs');
  if (!fs.existsSync(logsDir)) {
    fs.mkdirSync(logsDir, { recursive: true });
  }
  const ts = new Date().toISOString().replace(/[:]/g, '-').slice(0, 19);
  const logPath = path.join(logsDir, `merge-${ts}.log`);
  const logContent = [
    `Merge realizado: ${new Date().toISOString()}`,
    `Inserted: ${inserted}`,
    `Updated: ${updated}`,
    `Skipped (no key): ${skippedNoKey}`,
    `Skipped (landing): ${skippedLanding}`,
    '',
    ...log
  ].join('\n');
  fs.writeFileSync(logPath, logContent, 'utf8');

  console.log(`✓ Smart merge: +${inserted} nuevos, ~${updated} actualizados, ${skippedNoKey} sin clave, ${skippedLanding} landings`);
  console.log(`✓ Changelog → ${logPath}`);

  return { inserted, updated, skippedNoKey, skippedLanding };
}
// -------------------------------------

function loadExistingSeen(csvPath) {
  const seen = new Set();
  if (!fs.existsSync(csvPath)) return seen;
  const text = fs.readFileSync(csvPath, 'utf8');
  const lines = text.split('\n').filter(Boolean);
  if (lines.length <= 1) return seen;
  const headers = csvSafeSplit(lines[0]).map(h => h.trim());
  const idxEAN = headers.indexOf('EAN');
  const idxSKU = headers.indexOf('SKU');
  const idxURL = headers.indexOf('Links');

  for (let i = 1; i < lines.length; i++) {
    const cols = csvSafeSplit(lines[i]);
    const ean = idxEAN >= 0 ? (cols[idxEAN] || '').replace(/^"|"$/g, '').trim() : '';
    const sku = idxSKU >= 0 ? (cols[idxSKU] || '').replace(/^"|"$/g, '').trim() : '';
    const url = idxURL >= 0 ? (cols[idxURL] || '').replace(/^"|"$/g, '').trim() : '';
    const key = (ean && `EAN:${ean}`) || (sku && `SKU:${sku}`) || (url && `URL:${url}`) || null;
    if (key) seen.add(key);
  }
  return seen;
}

function csvToXlsx(csvPath, xlsxPath) {
  if (!fs.existsSync(csvPath)) return;
  const rows = fs.readFileSync(csvPath, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map(line => csvSafeSplit(line).map(cell => cell.replace(/^"|"$/g, '')));
  if (!rows.length) return;
  const workbook = XLSX.utils.book_new();
  const worksheet = XLSX.utils.aoa_to_sheet(rows);
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Products');
  XLSX.writeFile(workbook, xlsxPath);
  log.info(`✓ Exportado a Excel → ${path.resolve(xlsxPath)}`);
}

const firstAttr = ($, selector, attr) => {
  try {
    const el = $(selector).first();
    if (!el || !el.length) return '';
    const val = el.attr(attr);
    return val ? val.toString().trim() : '';
  } catch {
    return '';
  }
};

function fromDataLayerEAN(dataLayer) {
  try {
    for (const entry of (dataLayer || [])) {
      const flat = JSON.parse(JSON.stringify(entry));
      for (const key of Object.keys(flat)) {
        const value = flat[key];
        if (typeof value === 'string') {
          const digits = value.replace(/\D/g, '');
          if (/^\d{8,14}$/.test(digits)) return digits;
        }
        if (typeof value === 'string' && (key.toLowerCase().includes('ean') || key.toLowerCase().includes('gtin'))) {
          const digits = value.replace(/\D/g, '');
          if (digits.length >= 8) return digits;
        }
      }
    }
  } catch {}
  return '';
}

const normalizeString = (value) => {
  if (value === undefined || value === null) return '';
  return value
    .toString()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
};

const includesNormalized = (source, needle) => normalizeString(source).includes(normalizeString(needle));

function extractSkuFromPage($) {
  const candidates = [
    'div:contains("Order code")',
    'div:contains("Kód zboží")',
    'li:contains("Order code")',
    'li:contains("Kód zboží")',
    'span:contains("Order code")',
    'span:contains("Kód zboží")',
  ];
  for (const selector of candidates) {
    const text = $(selector).first().text().trim();
    if (!text) continue;
    const match = text.match(/(?:Order code|Kód zboží)\s*[:\-]?\s*([A-Z0-9\-_.]+)/i);
    if (match) return match[1];
  }
  const bodyText = $('body').text();
  const fallback = bodyText.match(/(?:Kód|Code)\s*[:\-]?\s*([A-Z0-9\-_.]{3,})/i);
  return fallback ? fallback[1] : '';
}

function getBreadcrumbFromJsonLd(blocks) {
  const breadcrumb = blocks.find(b => b && b['@type'] === 'BreadcrumbList');
  if (!breadcrumb || !Array.isArray(breadcrumb.itemListElement)) return { category: '', subcategory: '' };
  const names = breadcrumb.itemListElement
    .map(item => (item?.name || item?.item?.name || '').toString().trim())
    .filter(Boolean);
  if (!names.length) return { category: '', subcategory: '' };
  return {
    category: names[names.length - 2] || '',
    subcategory: names[names.length - 3] || '',
  };
}

const normalizeNumber = (value) => {
  if (!value && value !== 0) return null;
  const str = String(value).replace(/\s/g, '').replace(/\./g, '').replace(',', '.');
  const num = parseFloat(str);
  return Number.isFinite(num) ? num : null;
};

// Helper: normalize and strip query parameters
function cleanUrl(u, baseUrl) {
  try {
    const url = new URL(u, baseUrl || 'https://www.alza.cz');
    url.search = ''; // drop ?w= etc
    return url.toString();
  } catch {
    return null;
  }
}

// Strong whitelist for Alza product images matching SKU pattern
function isProductImageBySku(url, sku) {
  if (!sku) return false;
  
  try {
    const urlObj = new URL(url);
    const host = urlObj.hostname.toLowerCase();
    const pathname = urlObj.pathname;
    
    // Must be from image.alza.cz
    if (!host.includes('image.alza.cz')) return false;
    
    // Must match pattern: /products/{SKU}/{SKU}(-NN).jpg
    const productRe = new RegExp(
      String.raw`^\/products\/${sku.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\/${sku.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:-\d{2})?\.jpg$`,
      'i'
    );
    
    if (!productRe.test(pathname)) return false;
    
    // Known junk prefixes to exclude (defensive)
    const denyPrefixes = [
      '/Foto/vyrobci/',
      '/Foto/ImgGalery/bannery/',
      '/Foto/Domains/Logistics/',
      '/Styles/full/images/',
      '/ikony/',
      '/icons/',
      '/variants/',
      '/awards/',
      '/styles/',
      '/cookies-',
    ];
    
    if (denyPrefixes.some(p => pathname.includes(p))) return false;
    
    return true;
  } catch {
    return false;
  }
}

async function collectImages(page, $, sku, baseUrl) {
  const rawCandidates = new Set();
  
  // Helper to add URL if valid
  const addCandidate = (url) => {
    if (!url) return;
    const cleaned = cleanUrl(url, baseUrl);
    if (cleaned) rawCandidates.add(cleaned);
  };
  
  // 1. Meta tags (og:image, twitter:image)
  const main = firstAttr($, 'meta[property="og:image"]', 'content') ||
    firstAttr($, 'meta[name="twitter:image"]', 'content') ||
    firstAttr($, 'link[rel="image_src"]', 'href');
  if (main) addCandidate(main);
  
  // 2. <img src> and srcset
  $('img').each((_, el) => {
    const src = $(el).attr('src');
    const srcset = $(el).attr('srcset');
    if (src) addCandidate(src);
    if (srcset) {
      srcset.split(',').forEach(part => {
        const url = part.trim().split(' ')[0];
        if (url) addCandidate(url);
      });
    }
  });
  
  // 3. <source srcset> (picture elements)
  $('source[srcset]').each((_, el) => {
    const srcset = $(el).attr('srcset');
    if (!srcset) return;
    srcset.split(',').forEach(part => {
      const url = part.trim().split(' ')[0];
      if (url) addCandidate(url);
    });
  });
  
  // 4. Links that sometimes carry gallery images
  $('a[href]').each((_, a) => {
    const href = $(a).attr('href');
    if (href && /\.(jpg|jpeg|png|webp)$/i.test(href)) {
      addCandidate(href);
    }
  });
  
  // 5. JSON-LD Product -> images array
  $('script[type="application/ld+json"]').each((_, s) => {
    try {
      const j = JSON.parse($(s).text());
      const arr = Array.isArray(j) ? j : [j];
      arr.forEach(obj => {
        if (obj && obj['@type'] === 'Product') {
          const imgs = obj.image ? (Array.isArray(obj.image) ? obj.image : [obj.image]) : [];
          imgs.forEach(u => addCandidate(u));
        }
      });
    } catch {/* ignore */}
  });
  
  // 6. Also check via page.evaluate for dynamically loaded images
  try {
    const imgUrls = await page.$$eval('img[src], img[data-src]', (imgs) => imgs
      .map((img) => img.getAttribute('data-src') || img.getAttribute('src') || '')
      .filter(Boolean)
      .map((src) => src.split('?')[0]));
    
    imgUrls.forEach((src) => {
      if (/^https?:\/\//i.test(src)) {
        addCandidate(src);
      }
    });
  } catch {}
  
  // Filter to only product images matching SKU pattern
  let productImages = [...rawCandidates]
    .filter(Boolean)
    .filter(u => u.startsWith('https://image.alza.cz/'))
    .filter(u => isProductImageBySku(u, sku));
  
  // Sort: hero (no -NN) first, then -01, -02... in numerical order
  productImages.sort((a, b) => {
    const heroPattern = new RegExp(`${sku.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\.jpg$`, 'i');
    const score = (u) => heroPattern.test(u) ? 0 : 1; // hero first
    if (score(a) !== score(b)) return score(a) - score(b);
    
    // Then numerical order for numbered images
    const num = (u) => {
      const m = u.match(new RegExp(`${sku.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}-(\\d{2})\\.jpg$`, 'i'));
      return m ? parseInt(m[1], 10) : 0;
    };
    return num(a) - num(b);
  });
  
  return {
    image: productImages[0] || '',
    images: productImages,
  };
}

function mapWooCategoryPath(product) {
  const { category = '', subcategory = '', name = '', url = '', tags = '' } = product;
  const catNorm = normalizeString(category);
  const subNorm = normalizeString(subcategory);
  const nameNorm = normalizeString(name);
  const urlNorm = url.toLowerCase();
  const tagsNorm = normalizeString(tags || '');

  const isLego = catNorm.includes('lego') || subNorm.includes('lego') || nameNorm.includes('lego');
  if (isLego) return 'Toys & Games > LEGO';

  if (catNorm.includes('toys') || urlNorm.includes('/toys/')) {
    if (subNorm.includes('party') || subNorm.includes('card') || tagsNorm.includes('party')) {
      return 'Toys & Games > Party & Card Games';
    }
    return 'Toys & Games > LEGO';
  }

  const isLaptop = urlNorm.includes('/laptop') || catNorm.includes('laptop') || tagsNorm.includes('laptop');
  if (isLaptop) {
    if (nameNorm.includes('gaming') || subNorm.includes('gaming') || tagsNorm.includes('gaming')) {
      return 'Computers & Laptops > Laptops > Gaming';
    }
    if (nameNorm.includes('macbook') || subNorm.includes('apple') || urlNorm.includes('/macbook')) {
      return 'Computers & Laptops > Laptops > Apple';
    }
    if (nameNorm.includes('surface') || urlNorm.includes('surface')) {
      return 'Computers & Laptops > Laptops > Microsoft Surface';
    }
    if (nameNorm.includes('professional') || subNorm.includes('professional')) {
      return 'Computers & Laptops > Laptops > Professional';
    }
    return 'Computers & Laptops > Laptops > Home & Office';
  }

  const isMonitor = urlNorm.includes('/lcd-monitors') || catNorm.includes('monitor');
  if (isMonitor) {
    if (subNorm.includes('gaming') || tagsNorm.includes('gaming')) {
      return 'Computers & Laptops > Monitors > Gaming';
    }
    if (subNorm.includes('curved') || tagsNorm.includes('curved')) {
      return 'Computers & Laptops > Monitors > Curved';
    }
    if (subNorm.includes('4k') || tagsNorm.includes('4k') || nameNorm.includes('4k') || nameNorm.includes('uhd')) {
      return 'Computers & Laptops > Monitors > 4K';
    }
    if (subNorm.includes('portable') || tagsNorm.includes('portable')) {
      return 'Computers & Laptops > Monitors > Portable';
    }
    return 'Computers & Laptops > Monitors';
  }

  if (urlNorm.includes('/vr-glasses') || catNorm.includes('virtual reality')) {
    return 'Gaming & Entertainment > VR Glasses';
  }

  if (urlNorm.includes('/projectors/')) {
    return 'TV, Photo, Audio & Video > Projectors';
  }

  if (urlNorm.includes('/drones/')) {
    return 'TV, Photo, Audio & Video > Drones';
  }

  if (urlNorm.includes('/headphones') || catNorm.includes('headphone')) {
    if (subNorm.includes('gaming') || tagsNorm.includes('gaming')) {
      return 'TV, Photo, Audio & Video > Headphones > Gaming';
    }
    if (subNorm.includes('true wireless') || tagsNorm.includes('true wireless') || nameNorm.includes('tws')) {
      return 'TV, Photo, Audio & Video > Headphones > True Wireless';
    }
    if (subNorm.includes('wireless') || tagsNorm.includes('wireless') || nameNorm.includes('wireless')) {
      return 'TV, Photo, Audio & Video > Headphones > Wireless';
    }
    if (subNorm.includes('over-ear') || nameNorm.includes('over ear')) {
      return 'TV, Photo, Audio & Video > Headphones > Over-Ear';
    }
    if (subNorm.includes('in-ear') || nameNorm.includes('in ear')) {
      return 'TV, Photo, Audio & Video > Headphones > In-Ear';
    }
    return 'TV, Photo, Audio & Video > Headphones';
  }

  if (urlNorm.includes('/gaming/playstation')) {
    if (urlNorm.includes('accessories')) return 'Gaming & Entertainment > PlayStation > Accessories';
    if (urlNorm.includes('games')) return 'Gaming & Entertainment > PlayStation > Games';
    return 'Gaming & Entertainment > PlayStation';
  }

  if (urlNorm.includes('/gaming/xbox')) {
    if (urlNorm.includes('accessories')) return 'Gaming & Entertainment > Xbox > Accessories';
    if (urlNorm.includes('games')) return 'Gaming & Entertainment > Xbox > Games';
    return 'Gaming & Entertainment > Xbox';
  }

  if (urlNorm.includes('/gaming/nintendo-switch')) {
    if (urlNorm.includes('accessories')) return 'Gaming & Entertainment > Nintendo Switch > Accessories';
    if (urlNorm.includes('games')) return 'Gaming & Entertainment > Nintendo Switch > Games';
    return 'Gaming & Entertainment > Nintendo Switch';
  }

  if (urlNorm.includes('/pet/pet-supplies-for-dogs') || subNorm.includes('dog')) {
    return 'Pet Supplies > Dogs';
  }

  if (urlNorm.includes('/pet/pet-supplies-for-cats') || subNorm.includes('cat')) {
    return 'Pet Supplies > Cats';
  }

  if (urlNorm.includes('/robotic-vacuum-cleaners')) {
    return 'Household & Personal Appliances > Robotic Vacuum Cleaners';
  }

  return 'Uncategorized';
}

// Decode HTML entities (comprehensive)
function decodeHtml(str = '') {
  if (!str) return '';
  const named = { quot: '"', amp: '&', apos: "'", lt: '<', gt: '>', nbsp: ' ', copy: '©', reg: '®', trade: '™' };
  return String(str).replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, (m, g1) => {
    if (g1[0] === '#') {
      const code = g1[1].toLowerCase() === 'x' ? parseInt(g1.slice(2), 16) : parseInt(g1.slice(1), 10);
      return isFinite(code) ? String.fromCodePoint(code) : m;
    }
    return Object.prototype.hasOwnProperty.call(named, g1) ? named[g1] : m;
  });
}

// Clean whitespace and normalize
function cleanWhitespace(s = '') {
  return s.replace(/\u200B|\u200C|\u200D|\uFEFF/g, '') // zero-widths
    .replace(/\s+/g, ' ')
    .trim();
}

// Normalize inches (e.g., 23.8&quot; → 23.8")
function normalizeInches(s = '') {
  s = decodeHtml(s);
  s = s.replace(/(\d+(\.\d+)?)\s*[""]/g, '$1"');
  s = s.replace(/(\d+(\.\d+)?)\s*['']/g, "$1'");
  return s;
}

// Sanitize text (decode + normalize)
function sanitizeText(s = '') {
  return cleanWhitespace(normalizeInches(decodeHtml(s)));
}

// Find variant links (storage/color options)
function findVariantLinks($, baseUrl) {
  const links = new Set();
  try {
    // Storage options
    $('section:contains("Storage"), .capacity, .variant-capacity, [class*="storage"] a[href]').each((_, el) => {
      const href = $(el).attr('href');
      if (href) links.add(href);
    });
    
    // Color options
    $('section:contains("Color"), .color, .variant-color, [class*="color"] a[href]').each((_, el) => {
      const href = $(el).attr('href');
      if (href) links.add(href);
    });
    
    // Variant buttons/links
    $('a:contains("Configuration"), a:contains("Variant"), .variants a[href], [data-variant] a[href]').each((_, el) => {
      const href = $(el).attr('href');
      if (href) links.add(href);
    });
    
    // Convert to absolute URLs
    return Array.from(links)
      .filter(Boolean)
      .map(u => {
        try {
          return new URL(u, baseUrl).toString();
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

// Get current selected options (storage/color)
function getCurrentSelected($) {
  const storage = $('section:contains("Storage"), .capacity, .variant-capacity, [class*="storage"] .is-selected, .selected, .active').first().text().trim() || '';
  const color = $('section:contains("Color"), .color, .variant-color, [class*="color"] .is-selected, .selected, .active').first().text().trim() || '';
  return { storage: sanitizeText(storage), color: sanitizeText(color) };
}

// globalSeen will be initialized in the main IIFE based on SINGLE_OUTPUT mode
let globalSeen = new Set();

// ---- helpers (tus funciones) ----
function parseAllJsonLd($) {
  const blocks = [];
  $('script[type="application/ld+json"]').each((_, el) => {
    try {
      const txt = $(el).text().trim();
      if (!txt) return;
      const data = JSON.parse(txt);
      if (Array.isArray(data)) blocks.push(...data);
      else blocks.push(data);
    } catch (_) {}
  });
  return blocks;
}

function getItemListUrls(blocks) {
  const urls = new Set();
  for (const b of blocks) {
    if (!b || (b['@type'] !== 'ItemList' && b['@type'] !== 'BreadcrumbList')) continue;
    const arr = b.itemListElement || [];
    for (const el of arr) {
      const u = el?.item?.url || el?.url;
      if (u && typeof u === 'string') urls.add(u);
    }
  }
  return [...urls];
}

function getProductFromJsonLd(blocks) {
  const products = blocks.filter(b => b && b['@type'] === 'Product');
  if (!products.length) return null;
  products.sort((a, b) => {
    const score = (p) => (!!p.offers ? 1 : 0) + (!!p.gtin13 ? 1 : 0) + (!!p.sku ? 1 : 0);
    return score(b) - score(a);
  });
  return products[0];
}

function extractSpecs($) {
  const specs = {};
  const tableSelectors = [
    'table[class*="param"]',
    'table[class*="spec"]',
    'table[class*="tech"]',
    'section[id*="param"] table',
    'section[data-testid*="param"] table',
  ];

  $(tableSelectors.join(',')).each((_, t) => {
    $(t).find('tr').each((__, tr) => {
      const cells = $(tr).find('td,th');
      if (cells.length >= 2) {
        const k = $(cells[0]).text().toLowerCase().trim();
        const v = $(cells[1]).text().trim();
        specs[k] = v;
      }
    });
  });

  $('dl').each((_, dl) => {
    const terms = $(dl).find('dt');
    const defs = $(dl).find('dd');
    terms.each((idx, term) => {
      const key = $(term).text().toLowerCase().trim();
      const value = $(defs.get(idx)).text().trim();
      if (key && value) specs[key] = value;
    });
  });

  return specs;
}

// Comprehensive EAN extraction from multiple HTML sources
function extractEANFromHTML($) {
  const eanCandidates = [];
  
  // Helper to validate and clean EAN
  const cleanEAN = (text) => {
    if (!text) return null;
    // Extract only digits
    const digits = text.replace(/\D/g, '');
    // EAN typically has 8, 13, or 14 digits
    if (digits.length >= 8 && digits.length <= 14) {
      return digits;
    }
    return null;
  };

  // 1. Search in tables (tr > th/td pattern)
  $('table tr').each((_, tr) => {
    const cells = $(tr).find('th, td');
    if (cells.length >= 2) {
      const label = $(cells[0]).text().toLowerCase().trim();
      if (label.includes('ean') || label.includes('čárový') || label.includes('barcode') || label.includes('gtin')) {
        const value = $(cells[1]).text().trim();
        const ean = cleanEAN(value);
        if (ean) eanCandidates.push(ean);
      }
    }
  });

  // 2. Search in definition lists (dl > dt + dd)
  $('dl').each((_, dl) => {
    const terms = $(dl).find('dt');
    const defs = $(dl).find('dd');
    terms.each((idx, term) => {
      const key = $(term).text().toLowerCase().trim();
      if (key.includes('ean') || key.includes('čárový') || key.includes('barcode') || key.includes('gtin')) {
        const value = $(defs.get(idx)).text().trim();
        const ean = cleanEAN(value);
        if (ean) eanCandidates.push(ean);
      }
    });
  });

  // 3. Search in lists (ul/ol > li with "EAN:" pattern)
  $('ul li, ol li').each((_, li) => {
    const text = $(li).text().toLowerCase();
    if (text.includes('ean') || text.includes('čárový') || text.includes('barcode') || text.includes('gtin')) {
      // Try to extract EAN from text like "EAN: 8595602..." or "EAN 8595602..."
      const match = $(li).text().match(/(?:ean|čárový|barcode|gtin)[\s:]+([\d\s]+)/i);
      if (match) {
        const ean = cleanEAN(match[1]);
        if (ean) eanCandidates.push(ean);
      }
    }
  });

  // 4. Search in divs/span with specific classes or data attributes
  $('[class*="ean"], [class*="barcode"], [class*="gtin"], [data-ean], [data-gtin]').each((_, el) => {
    const value = $(el).text().trim() || $(el).attr('data-ean') || $(el).attr('data-gtin') || '';
    const ean = cleanEAN(value);
    if (ean) eanCandidates.push(ean);
  });

  // 5. Search in product info sections
  $('[class*="product"], [class*="detail"], [class*="param"], [id*="param"], [id*="spec"]').each((_, section) => {
    const text = $(section).text();
    // Look for patterns like "EAN: 8595602" or "Čárový kód: 8595602"
    const patterns = [
      /(?:ean|čárový|barcode|gtin)[\s:]+([\d\s]{8,20})/gi,
      /(?:ean|čárový|barcode|gtin)\s*:?\s*([\d\s]{8,20})/gi,
    ];
    patterns.forEach(pattern => {
      const matches = text.matchAll(pattern);
      for (const match of matches) {
        const ean = cleanEAN(match[1]);
        if (ean) eanCandidates.push(ean);
      }
    });
  });

  // Return the first valid EAN found (most likely to be correct)
  // If multiple found, prioritize longer ones (13-14 digits are more common for products)
  if (eanCandidates.length > 0) {
    const sorted = eanCandidates.sort((a, b) => {
      // Prefer 13-14 digits, then 12, then others
      const score = (str) => {
        if (str.length >= 13) return 3;
        if (str.length === 12) return 2;
        return 1;
      };
      return score(b) - score(a);
    });
    return sorted[0];
  }

  return null;
}

function findSpec(specs, keys) {
  for (const key of keys) {
    for (const k in specs) {
      if (includesNormalized(k, key)) return specs[k];
    }
  }
  return null;
}

function extractInch(text) {
  if (!text) return '';
  const m = text.match(/(\d+(?:[.,]\d+)?)\s*(?:["']|inch|inches|-inch)/i);
  return m ? (m[1] || '').replace(',', '.') : '';
}

function extractConnectivity(text) {
  const conn = [];
  const lower = (text || '').toLowerCase();
  if (lower.includes('hdmi')) conn.push('HDMI');
  if (lower.includes('displayport') || lower.includes(' dp ')) conn.push('DisplayPort');
  if (lower.includes('usb-c') || lower.includes('usb c')) conn.push('USB-C');
  if (lower.includes('vga')) conn.push('VGA');
  if (lower.includes('thunderbolt')) conn.push('Thunderbolt');
  if (lower.includes('3.5 mm') || lower.includes('3,5 mm') || lower.includes('aux')) conn.push('3.5mm Jack');
  if (lower.includes('bluetooth 5.3')) conn.push('Bluetooth 5.3');
  else if (lower.includes('bluetooth 5.2')) conn.push('Bluetooth 5.2');
  else if (lower.includes('bluetooth')) conn.push('Bluetooth');
  if (lower.includes('wi-fi 6e') || lower.includes('wifi 6e')) conn.push('Wi-Fi 6E');
  else if (lower.includes('wi-fi 6') || lower.includes('wifi 6')) conn.push('Wi-Fi 6');
  if (lower.includes('rf 2.4') || lower.includes('2.4ghz')) conn.push('RF 2.4GHz');
  return conn.join(', ');
}

function mapToMaster(product) {
  const clean = (v) => (v ?? '').toString().trim();
  const price = product.price;
  const priceStr = price ? `CZK${parseFloat(price).toFixed(2)}` : '';

  let category = clean(product.category || '');
  const titleLower = (product.name || '').toLowerCase();
  const catLower = category.toLowerCase();
  if (catLower.includes('lego') || titleLower.includes('lego')) category = 'Toys & Games';
  else if (catLower.includes('laptop') || catLower.includes('notebook')) category = 'Computers & Tablets';
  else if (catLower.includes('monitor') || catLower.includes('lcd')) category = 'Monitors & Displays';

  let tags = 'alza import';
  if (catLower.includes('lego') || titleLower.includes('lego')) tags += ', lego';
  else if (catLower.includes('laptop') || catLower.includes('notebook')) tags += ', laptop';
  else if (catLower.includes('monitor') || catLower.includes('lcd')) tags += ', monitor';

  let storage = clean(product.storage || '');
  if (storage) {
    const match = storage.match(/(\d+(?:[.,]\d+)?)\s*(GB|TB|MB)/i);
    if (match) {
      const size = match[1].replace(',', '.');
      const unit = match[2].toUpperCase();
      if (unit === 'TB') {
        const numeric = parseFloat(size);
        storage = numeric >= 1 ? `${numeric} TB` : `${(numeric * 1000).toFixed(0)} GB`;
      } else {
        storage = `${parseFloat(size)} ${unit}`;
      }
    }
  }

  const memory = clean(product.memory || '');
  if (memory) {
    const normalizedMemory = memory.match(/(\d+(?:[.,]\d+)?)\s*gb/i);
    if (normalizedMemory) tags += `, ${normalizedMemory[1].replace(',', '.')}GB RAM`;
  }

  if (product.connectivity) tags += `, ${product.connectivity.toLowerCase()}`;
  if (storage) tags += `, storage-${storage.toLowerCase()}`;

  const wooCategoryPath = mapWooCategoryPath({
    category: product.category,
    subcategory: product.subcategory,
    name: product.name,
    url: product.url,
    tags,
  });

  const images = Array.isArray(product.images) ? product.images : [];

  const { family, model } = deriveFamilyModel(
    product.brand || '',
    product.model || product.name || '',
    { sku: product.sku || '', url: product.url || '', category: product.category || '' }
  );

  return {
    'SKU': clean(product.sku || ''),
    'EAN': clean(product.ean || ''),
    'Brand': clean(product.brand || ''),
    'Family': clean(family || product.family || ''),
    'Model': clean(model || product.model || product.name || ''),
    'Description General': sanitizeText(clean(product.description || product.name || '')),
    'Category': category,
    'Subcategory': clean(product.subcategory || ''),
    'Option Storage': storage,
    'Option Color': clean(product.color || ''),
    'Watch Size': '',
    'Band': '',
    'Sizes': clean(product.inch || ''),
    'Inch': clean(product.inch || ''),
    'Connectivity': clean(product.connectivity || ''),
    'Tags': tags,
    'Price': priceStr,
    'Links': clean(product.url || ''),
    'Image': clean(product.image || ''),
    'Images': images.join(','),
    'WooCategoryPath': wooCategoryPath,
  };
}

function toCSV(rows) {
  if (!rows.length) return '';
  const headers = Object.keys(rows[0]);
  const esc = (v) => {
    const s = (v ?? '').toString();
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [
    headers.join(','),
    ...rows.map(r => headers.map(h => esc(r[h])).join(',')),
  ].join('\n');
}

// ---- CSV incremental / Smart Merge ----
let buffer = [];
let wroteHeader = false;

function hasProductSignals($) {
  // Check for JSON-LD Product
  const hasJsonLdProduct = $('script[type="application/ld+json"]').toArray().some(el => {
    try {
      const txt = $(el).text().trim();
      if (!txt) return false;
      const j = JSON.parse(txt);
      const blocks = Array.isArray(j) ? j : [j];
      return blocks.some(x => x && x['@type'] === 'Product');
    } catch {
      return false;
    }
  });

  // Check for price signals
  const hasPriceMeta = $('meta[itemprop="price"]').attr('content');
  const hasOffer = $('[itemprop="offers"], [data-testid*="price"], .price, .c-price, [class*="price"]').length > 0;
  
  // Check for add to cart button
  const addToCart = $('button:contains("Add to cart"), button:contains("Do košíku"), a:contains("Add to cart"), button:contains("Koupit")').length > 0;

  return hasJsonLdProduct || (hasPriceMeta && hasOffer) || addToCart;
}

function minimalOkay(p) {
  return !!(p.name && (p.price || p.currency) && (p.sku || p.ean || p.url));
}

function flushToCsv() {
  if (!buffer.length) return;
  const rows = buffer.map(mapToMaster);
  buffer = [];

  if (SINGLE_OUTPUT) {
    // Smart merge mode: merge into master
    smartMergeAll(rows);
    return;
  }

  // Legacy mode: incremental append
  const fresh = [];
  let skipped = 0;
  for (const r of rows) {
    const key = (r.EAN && `EAN:${r.EAN}`) || (r.SKU && `SKU:${r.SKU}`) || (r.Links && `URL:${r.Links}`) || null;
    if (!key) continue;
    if (globalSeen.has(key)) {
      skipped += 1;
      continue;
    }
    globalSeen.add(key);
    fresh.push(r);
  }

  if (!fresh.length) {
    if (skipped) log.info(`Sin nuevos productos en este lote (omitidos ${skipped} duplicados).`);
    return;
  }

  const csv = toCSV(fresh);
  if (!wroteHeader) {
    fs.writeFileSync(OUT_CSV, csv + '\n');
    wroteHeader = true;
  } else {
    const lines = csv.split('\n');
    lines.shift();
    if (lines.length) fs.appendFileSync(OUT_CSV, lines.join('\n') + '\n');
  }

  log.info(`✓ Guardado incremental → ${OUT_CSV} (+${fresh.length}${skipped ? `, duplicados omitidos: ${skipped}` : ''})`);
}

async function acceptConsent(page) {
  const candidates = [
    '#onetrust-accept-btn-handler',
    'button[aria-label*="Accept"]',
    'button:has-text("Accept")',
    'button:has-text("Souhlasím")',
    'button#c-p-bn',
  ];
  for (const sel of candidates) {
    try {
      const b = await page.$(sel);
      if (b) { await b.click({ timeout: 1000 }).catch(() => {}); break; }
    } catch (_) {}
  }
}

(async () => {
  // Ensure output directory exists
  if (!fs.existsSync(OUT_DIR)) {
    fs.mkdirSync(OUT_DIR, { recursive: true });
  }

  if (SINGLE_OUTPUT) {
    // Smart merge mode: master file always exists (or will be created)
    wroteHeader = fs.existsSync(MASTER_CSV);
    log.info(`Smart merge mode: ${wroteHeader ? 'Actualizando' : 'Creando'} ${MASTER_CSV}`);
    // In smart merge mode, we don't need globalSeen for deduplication (smartMergeAll handles it)
    globalSeen = new Set();
  } else {
    // Legacy mode
    if (APPEND_TO_EXISTING && fs.existsSync(OUT_CSV)) {
      wroteHeader = true;
      globalSeen = loadExistingSeen(OUT_CSV);
    } else {
      if (fs.existsSync(OUT_CSV)) fs.unlinkSync(OUT_CSV);
      wroteHeader = false;
      globalSeen = new Set();
    }
  }

  const seenDetail = new Set();

  const crawler = new PlaywrightCrawler({
    maxConcurrency: 1,
    maxRequestsPerCrawl: MAX_REQUESTS,
    headless: true,
    requestHandlerTimeoutSecs: 60,
    navigationTimeoutSecs: 45,
    preNavigationHooks: [async ({ page }) => {
      await page.setExtraHTTPHeaders({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept-Language': 'cs-CZ,cs;q=0.9,en;q=0.8',
        'Upgrade-Insecure-Requests': '1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
      });
    }],

    async requestHandler({ request, page, enqueueLinks, parseWithCheerio, log: rlog, crawler }) {
      const url = request.loadedUrl || request.url;

      await acceptConsent(page).catch(() => {});
      let $ = await parseWithCheerio();

      if (request.userData.label === 'DETAIL') {
        // Validate this is actually a product page (not a landing/catalog)
        if (!hasProductSignals($)) {
          rlog.warning('Skipped non-product page (landing/catalog).', { url });
          return;
        }

        const blocks = parseAllJsonLd($);
        const prodJson = getProductFromJsonLd(blocks);
        const specs = extractSpecs($);
        let product = {};

        if (prodJson) {
          const offers = Array.isArray(prodJson.offers) ? prodJson.offers[0] : prodJson.offers || {};
          const brand = typeof prodJson.brand === 'string' ? prodJson.brand : prodJson.brand?.name;
          product = {
            url,
            name: prodJson.name || null,
            brand: brand || null,
            sku: prodJson.sku || null,
            ean: prodJson.gtin13 || prodJson.gtin || null,
            model: prodJson.model || null,
            description: prodJson.description || null,
            price: offers.price || null,
            currency: offers.priceCurrency || 'CZK',
          };
        } else {
          const title = sanitizeText($('h1').first().text().trim() || '');
          const priceText = $('[class*="price"], [class*="total"]').first().text().trim() || '';
          const priceMatch = priceText.match(/(\d+(?:[,.]\d+)?)/);
          const price = priceMatch ? parseFloat(priceMatch[1].replace(',', '.')) : null;

          product = {
            url,
            name: title,
            brand: sanitizeText(findSpec(specs, ['brand', 'značka', 'výrobce', 'manufacturer']) || ''),
            sku: findSpec(specs, ['sku', 'kód', 'mpn', 'artikelnummer']),
            ean: findSpec(specs, ['ean', 'ean kód', 'ean code', 'gtin']),
            model: sanitizeText(findSpec(specs, ['model', 'model number', 'označení']) || ''),
            description: sanitizeText($('.description, #desc').first().text().trim() || title),
            price,
            currency: 'CZK',
          };
        }
        
        // Sanitize name and description from JSON-LD too
        if (product.name) product.name = sanitizeText(product.name);
        if (product.description) product.description = sanitizeText(product.description);
        if (product.brand) product.brand = sanitizeText(product.brand);
        if (product.model) product.model = sanitizeText(product.model);

        // Enrich with additional sources - comprehensive EAN extraction
        // Priority order: JSON-LD > Meta tags > HTML extraction > Specs > DataLayer > Next.js data
        const eanMeta = firstAttr($, 'meta[itemprop="gtin13"]', 'content') || firstAttr($, 'meta[itemprop="gtin"]', 'content');
        const eanHTML = extractEANFromHTML($); // New comprehensive HTML extraction
        const eanSpec = findSpec(specs, ['ean', 'ean kód', 'ean code', 'gtin', 'čárový kód', 'barcode']);
        let eanDL = '';
        try {
          const dl = await page.evaluate(() => window.dataLayer || []);
          eanDL = fromDataLayerEAN(dl);
        } catch {}
        let eanNext = '';
        try {
          const nextDataString = await page.evaluate(() => {
            if (typeof window.__NEXT_DATA__ === 'undefined') return '';
            try {
              return JSON.stringify(window.__NEXT_DATA__);
            } catch {
              return '';
            }
          });
          if (nextDataString) {
            const match = nextDataString.match(/"(?:ean|gtin13|gtin)"\s*:\s*"(\d{8,14})"/i);
            if (match) eanNext = match[1];
          }
        } catch {}
        
        // Clean and validate EANs
        const cleanEAN = (val) => {
          if (!val) return null;
          const cleaned = val.toString().replace(/\D/g, '');
          return cleaned.length >= 8 && cleaned.length <= 14 ? cleaned : null;
        };
        
        const cleanSpecEan = eanSpec ? cleanEAN(eanSpec) : null;
        
        // Combine all sources in priority order
        product.ean = product.ean || cleanEAN(eanMeta) || cleanEAN(eanHTML) || cleanSpecEan || cleanEAN(eanDL) || cleanEAN(eanNext) || null;
        
        // Final validation
        if (product.ean) {
          product.ean = cleanEAN(product.ean);
        }

        if (!product.sku) {
          const skuDom = extractSkuFromPage($);
          if (skuDom) product.sku = skuDom;
        }

        if (!product.price) {
          const metaPrice = firstAttr($, 'meta[itemprop="price"]', 'content');
          const normalized = normalizeNumber(metaPrice);
          if (normalized !== null) product.price = normalized;
        }
        if (!product.currency) {
          product.currency = firstAttr($, 'meta[itemprop="priceCurrency"]', 'content') || 'CZK';
        }

        const allText = `${product.name || ''} ${product.description || ''} ${Object.values(specs).join(' ')}`.toLowerCase();
        const inchText = findSpec(specs, ['úhlopříčka', 'uhlopricka', 'screen size', 'velikost obrazovky', 'display size']) || product.name || '';
        product.inch = extractInch(inchText);
        product.connectivity = extractConnectivity(allText);
        const rawStorage = findSpec(specs, ['úložiště', 'storage', 'ssd', 'hdd', 'disk', 'kapacita']) ||
          (allText.match(/(\d+(?:[.,]\d+)?)\s*(tb|gb)\s*(?:ssd|hdd|nvme|storage|uloziste)/i)?.[0] || '');
        product.storage = rawStorage;
        product.memory = findSpec(specs, ['ram', 'paměť', 'pamät', 'memory', 'operační paměť']) ||
          (allText.match(/(\d+(?:[.,]\d+)?)\s*(?:gb)\s*(?:ram|ddr|lpddr)/i)?.[0] || '');
        product.color = findSpec(specs, ['barva', 'color', 'colour']) || '';

        // Obtener breadcrumbs
        const { category: catBL, subcategory: subBL } = getBreadcrumbFromJsonLd(blocks);
        const bc = $('nav[class*="breadcrumb"], ol[class*="breadcrumb"] a').toArray()
          .map(a => $(a).text().trim()).filter(Boolean);
        
        const breadcrumbRoot = catBL || (bc.length >= 2 ? bc[bc.length - 2] : '');
        const breadcrumbSub = subBL || (bc.length >= 3 ? bc[bc.length - 3] : '');

        // Clasificación inteligente usando scoring
        const classification = classifyCategory({
          name: product.name || '',
          description: product.description || '',
          url: url,
          breadcrumbRoot: breadcrumbRoot,
          breadcrumbSub: breadcrumbSub,
        });

        // Solo sobreescribir si la clasificación tiene score suficiente
        if (classification.cat) {
          product.category = classification.cat;
          product.subcategory = classification.sub;
          // Si la clasificación sugiere una family, usarla si no hay una ya
          if (!product.family && classification.family) {
            product.family = classification.family;
          }
        } else {
          // Fallback: usar breadcrumbs si existen
          if (breadcrumbRoot) product.category = product.category || breadcrumbRoot;
          if (breadcrumbSub) product.subcategory = product.subcategory || breadcrumbSub;
          
          // Fallback final: derivar de URL
          if (!product.category) {
            try {
              const parsedUrl = new URL(url);
              const segments = parsedUrl.pathname.split('/').filter(Boolean);
              if (segments.includes('toys') || segments.includes('lego')) product.category = 'Toys & Games';
              else if (segments.includes('laptops')) product.category = 'Computers';
              else if (segments.includes('lcd-monitors')) product.category = 'Computers';
              else if (segments.includes('gaming')) product.category = 'Gaming & Entertainment';
              else if (segments.includes('pet')) product.category = 'Pet Supplies';
              else if (segments.includes('tablets') || segments.includes('ipad')) product.category = 'Phones & Tablets';
              else if (segments.includes('smartphones') || segments.includes('iphone')) product.category = 'Phones & Tablets';
            } catch {}
          }
        }

        const images = await collectImages(page, $, product.sku || '', url);
        product.image = images.image;
        product.images = images.images;

        product.category = product.category ? product.category.trim() : '';
        product.subcategory = product.subcategory ? product.subcategory.trim() : '';

        // Derive Family and Model from brand and name (with SKU/URL/Category hints)
        const { family, model } = deriveFamilyModel(
          product.brand || '',
          product.name || '',
          { sku: product.sku || '', url: product.url || '', category: product.category || '' }
        );
        product.family = family;
        product.model = model || product.name || '';

        // Get current selected options (storage/color) for this variant
        const selected = getCurrentSelected($);
        if (selected.storage) product.storage = selected.storage;
        if (selected.color) product.color = selected.color;

        // Find and enqueue variant links (storage/color options)
        const variantLinks = findVariantLinks($, url);
        if (variantLinks.length > 0) {
          for (const variantUrl of variantLinks) {
            if (!seenDetail.has(variantUrl) && isAllowedProductUrl(variantUrl)) {
              await crawler.addRequests([{
                url: variantUrl,
                userData: { label: 'DETAIL' },
              }]).catch(() => {});
              seenDetail.add(variantUrl);
            }
          }
        }

        // Final validation: must have minimal product data
        if (!minimalOkay(product)) {
          rlog.warning('Discarded row with insufficient product signals.', { url, name: product.name });
          return;
        }

        buffer.push(product);
        if (buffer.length >= 25) flushToCsv();

        rlog.info(`Parsed: ${product.sku || product.ean || product.url} - ${product.name || 'No name'}`);
        return;
      }

      for (let i = 0; i < 8; i++) {
        await page.mouse.wheel(0, 900);
        await page.waitForTimeout(350);
      }
      $ = await parseWithCheerio();
      const blocks = parseAllJsonLd($);

      let urls = getItemListUrls(blocks).map(u => (u.startsWith('http') ? u : new URL(u, url).toString()));

      if (!urls.length) {
        const anchors = await page.$$eval('a[href]', as => as.map(a => a.getAttribute('href')).filter(Boolean));
        urls = anchors.map(h => {
          try { return new URL(h, url).toString(); } catch { return null; }
        }).filter(Boolean);
      }

      // Filter to only product URLs (exclude landings/catalogs)
      urls = [...new Set(urls)]
        .map(u => (u.startsWith('http') ? u : new URL(u, url).toString()))
        .filter(isAllowedProductUrl);

      const limited = urls.filter(u => !seenDetail.has(u)).slice(0, MAX_PER_CAT);
      for (const u of limited) seenDetail.add(u);

      if (limited.length) {
        await enqueueLinks({ urls: limited, userData: { label: 'DETAIL' } });
        rlog.info(`Enqueued ${limited.length} product details from category.`, { category: url });
      } else {
        rlog.warning('No product URLs found on category page.', { url });
      }
    },

    failedRequestHandler({ request }) {
      log.warning(`Failed: ${request.url}`);
    },
  });

  await crawler.addRequests(START_URLS.map(u => ({ url: u })));
  await crawler.run();

  // Final flush
  flushToCsv();
  
  if (SINGLE_OUTPUT) {
    log.info(`RUN DONE → Master: ${path.resolve(MASTER_CSV)}`);
    log.info(`RUN DONE → Excel: ${path.resolve(MASTER_XLSX)}`);
  } else {
    log.info(`RUN DONE → CSV: ${path.resolve(OUT_CSV)}`);
    csvToXlsx(OUT_CSV, OUT_XLSX);
  }
})();

