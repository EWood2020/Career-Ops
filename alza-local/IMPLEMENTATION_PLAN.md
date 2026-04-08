# Implementation Plan: Family & Model Normalization

## Objective (What We're Doing)

We're improving product data extraction so that:
- **Family** = Product line (stable across variants; good for filtering/collections)
- **Model** = Specific variant name (what users see on product pages)

### Examples

| Brand | Family | Model |
|-------|--------|-------|
| Apple | iPad | iPad Air (M3) |
| Apple | iPad | iPad (A16) |
| Nintendo | Nintendo Switch 2 | Nintendo Switch 2 |
| Nintendo | Nintendo Switch 2 | Nintendo Switch 2 + Pokémon Legends: Z-A |
| Sony | Sony 1000X Series | WH-1000XM6 |
| DJI | DJI Mini | Mini 5 Pro Fly More Combo |

## Goal (Done When)

✅ 95%+ of rows have Family and Model filled correctly  
✅ No HTML entities in "Description General" (e.g., `&quot;` → `"`)  
✅ Category/Subcategory follow our agreed taxonomy  
✅ All existing CSV files can be cleaned with post-processor

## Why (Business Value)

1. **Better Navigation**: Users can filter by product line (e.g., "Show all iPad models")
2. **Consistent Product Titles**: Model field shows exact variant name
3. **Easier Deduplication**: Family helps group related products
4. **Better SEO**: Clean taxonomy improves search/filtering
5. **WooCommerce Import**: Clean data maps directly to product categories

## Implementation Steps

### Step 1: Create Helper Function

**File**: `helpers/familyModel.js`

This function takes brand + product name and returns `{ family, model }`.

**Key Rules**:
- Family is the general product line (e.g., "iPad", "Nintendo Switch 2")
- Model keeps the full variant name (e.g., "iPad Air (M3)", "Nintendo Switch 2 + Pokémon...")
- Bundles (after " + ") stay in Model but don't affect Family

**Test Cases**:
1. Apple iPad Air (M3) → Family: "iPad", Model: "iPad Air (M3)"
2. Nintendo Switch 2 + Pokémon... → Family: "Nintendo Switch 2", Model: "Nintendo Switch 2 + Pokémon Legends: Z-A"
3. Sony WH-1000XM6 → Family: "Sony 1000X Series", Model: "WH-1000XM6"
4. DJI Mini 5 Pro Fly More → Family: "DJI Mini", Model: "Mini 5 Pro Fly More Combo"

### Step 2: Update Scraper

**File**: `local.js`

1. Import the helper:
   ```js
   import { deriveFamilyModel } from './helpers/familyModel.js';
   ```

2. Add HTML decoder function:
   ```js
   function decodeHtml(str = '') {
     return str
       .replace(/&quot;/g, '"')
       .replace(/&#39;/g, "'")
       .replace(/&amp;/g, '&')
       .replace(/&lt;/g, '<')
       .replace(/&gt;/g, '>');
   }
   ```

3. In the DETAIL handler, after building `product` object:
   ```js
   const { family, model } = deriveFamilyModel(product.brand || '', product.name || '');
   product.family = family;
   product.model = model || product.name || '';
   ```

4. In `mapToMaster()`, use the derived values:
   ```js
   const { family, model } = deriveFamilyModel(
     product.brand || '',
     product.model || product.name || ''
   );
   
   return {
     'Family': clean(family || product.family || ''),
     'Model': clean(model || product.model || product.name || ''),
     'Description General': decodeHtml(clean(product.description || product.name || '')),
     // ... rest of fields
   };
   ```

### Step 3: Create Post-Processor Script

**File**: `scripts/clean_to_master.js`

This script:
- Reads existing CSV
- Derives Family/Model for each row
- Decodes HTML entities in descriptions
- Normalizes Category/Subcategory
- Outputs clean XLSX

**Usage**:
```bash
node scripts/clean_to_master.js input.csv output.xlsx
```

### Step 4: Test & Validate

1. **Run post-processor on current CSV**:
   ```bash
   node scripts/clean_to_master.js output/flexnology_2025-11-10-16-42-07.csv output/cleaned_master.xlsx
   ```

2. **Spot-check**:
   - Row 475 (NS2HW001) → Family: "Nintendo Switch 2", Model: "Nintendo Switch 2"
   - Pokémon bundle → Family: "Nintendo Switch 2", Model keeps "+ Pokémon..."
   - Check no `&quot;` in Description General

3. **Run scraper again** (next run will have Family/Model from the start)

## Guardrails

- ✅ Never leave Family blank if brand is present (fallback to capitalized brand)
- ✅ Keep bundles intact in Model (everything after " + " stays)
- ✅ Decode HTML entities in description
- ✅ Keep Category/Subcategory mapping exactly as agreed (URL-based rules)

## Files Changed

1. `helpers/familyModel.js` (NEW)
2. `local.js` (UPDATED - import helper, use in DETAIL handler and mapToMaster)
3. `scripts/clean_to_master.js` (NEW - post-processor)

## Checklist

- [ ] Create `helpers/familyModel.js`
- [ ] Update `local.js` to import and use helper
- [ ] Add `decodeHtml()` function
- [ ] Update `mapToMaster()` to use derived Family/Model
- [ ] Create `scripts/clean_to_master.js`
- [ ] Test post-processor on current CSV
- [ ] Verify row 475 and Pokémon bundle
- [ ] Run scraper once to verify new extraction
- [ ] Commit with message: "Normalize Family/Model; decode HTML; keep taxonomy mapping"

## Questions?

If you're stuck:
1. Check the test cases in `helpers/familyModel.js`
2. Compare output before/after post-processor
3. Verify Category/Subcategory mapping matches URL patterns


