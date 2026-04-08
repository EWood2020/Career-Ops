// scripts/clean_to_master.js
// Post-processor: cleans existing CSV and adds Family/Model columns

import fs from 'fs';
import path from 'path';
import * as XLSX from 'xlsx';
import { deriveFamilyModel } from '../helpers/familyModel.js';

function decodeHtml(s = '') {
  return s
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

function mapCategoryRow(row) {
  const url = (row.Links || row.URL || '').toLowerCase();
  const cat = (row.Category || '').toLowerCase();
  const sub = (row.Subcategory || '').toLowerCase();

  // Gaming & Entertainment
  if (url.includes('/gaming/nintendo-switch/')) {
    return { category: 'Gaming & Entertainment', subcategory: 'Nintendo Switch' };
  }
  if (url.includes('/gaming/playstation/')) {
    return { category: 'Gaming & Entertainment', subcategory: 'PlayStation' };
  }
  if (url.includes('/gaming/xbox/')) {
    return { category: 'Gaming & Entertainment', subcategory: 'Xbox' };
  }

  // TV, Photos, Audio & Video
  if (url.includes('/headphones/')) {
    return { category: 'TV, Photos, Audio & Video', subcategory: 'Headphones' };
  }
  if (url.includes('/drones/')) {
    return { category: 'TV, Photos, Audio & Video', subcategory: 'Drones' };
  }

  // Computers & Laptops
  if (url.includes('/laptops/')) {
    return { category: 'Computers & Laptops', subcategory: 'Laptops' };
  }
  if (url.includes('/lcd-monitors/')) {
    return { category: 'Computers & Laptops', subcategory: 'Monitors' };
  }
  if (url.includes('/projectors/')) {
    return { category: 'Computers & Laptops', subcategory: 'Projectors' };
  }

  // Toys
  if (url.includes('/toys/lego/')) {
    return { category: 'Toys for Kids and Babies', subcategory: 'LEGO' };
  }

  // Pet Supplies
  if (url.includes('/pet/')) {
    if (url.includes('/dog') || sub.includes('dog')) {
      return { category: 'Pet Supplies', subcategory: 'Dogs' };
    }
    if (url.includes('/cat') || sub.includes('cat')) {
      return { category: 'Pet Supplies', subcategory: 'Cats' };
    }
    return { category: 'Pet Supplies', subcategory: '' };
  }

  // Household
  if (url.includes('/robotic-vacuum-cleaners/')) {
    return { category: 'Household & Personal Appliances', subcategory: 'Robotic Vacuum Cleaners' };
  }

  // Fallback: keep existing
  return { category: row.Category || '', subcategory: row.Subcategory || '' };
}

function csvSafeSplit(line) {
  return line.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/);
}

function run(inputCsvPath, outputXlsxPath) {
  const raw = fs.readFileSync(inputCsvPath, 'utf8').split(/\r?\n/).filter(Boolean);
  if (!raw.length) {
    console.error('Empty CSV file');
    process.exit(1);
  }

  const headers = csvSafeSplit(raw[0]).map(h => h.replace(/^"|"$/g, '').trim());
  const idx = (h) => headers.indexOf(h);

  const outRows = [];
  const outHeaders = [
    'SKU', 'EAN', 'Brand', 'Family', 'Model', 'Description General',
    'Category', 'Subcategory', 'Option Storage', 'Option Color', 'Inch',
    'Connectivity', 'Tags', 'Price', 'Links'
  ];

  for (let i = 1; i < raw.length; i++) {
    const cols = csvSafeSplit(raw[i]).map(s => s.replace(/^"|"$/g, ''));
    const row = Object.fromEntries(headers.map((h, j) => [h, cols[j] ?? '']));

    // Get name from Model, Name, or Description General
    const name = (row['Model'] || row['Name'] || row['Description General'] || '').trim();
    
    // Derive Family and Model (with SKU/URL/Category hints)
    const { family, model } = deriveFamilyModel(
      row['Brand'] || '',
      name,
      {
        sku: row['SKU'] || '',
        url: row['Links'] || '',
        category: row['Category'] || ''
      }
    );
    
    // Map category
    const mapped = mapCategoryRow(row);

    outRows.push({
      'SKU': row['SKU'] || '',
      'EAN': row['EAN'] || '',
      'Brand': row['Brand'] || '',
      'Family': family,
      'Model': model,
      'Description General': decodeHtml(row['Description General'] || name || ''),
      'Category': mapped.category,
      'Subcategory': mapped.subcategory,
      'Option Storage': row['Option Storage'] || '',
      'Option Color': row['Option Color'] || row['Color'] || '',
      'Inch': row['Inch'] || row['Sizes'] || '',
      'Connectivity': row['Connectivity'] || '',
      'Tags': row['Tags'] || '',
      'Price': row['Price'] || '',
      'Links': row['Links'] || ''
    });
  }

  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.json_to_sheet(outRows, { header: outHeaders });
  XLSX.utils.book_append_sheet(wb, ws, 'Cleaned');
  XLSX.writeFile(wb, outputXlsxPath);
  console.log(`✓ Exportado → ${outputXlsxPath} (${outRows.length} filas)`);
}

// CLI
const [,, inp, out] = process.argv;
if (!inp || !out) {
  console.error('Usage: node scripts/clean_to_master.js input.csv output.xlsx');
  process.exit(1);
}

run(inp, out);

