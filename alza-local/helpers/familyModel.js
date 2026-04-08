// helpers/familyModel.js
// Derives Family (product line) and Model (specific variant) from brand and product name

function capitalize(s = '') {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

export function deriveFamilyModel(brand = '', rawName = '', options = {}) {
  const { sku = '', url = '', category = '' } = options;
  const name = rawName.trim();
  
  // Remove bundle extras for Family, but keep them in Model
  const core = name.split(' + ')[0].trim();

  const b = brand.toLowerCase();
  const n = core.toLowerCase();
  const u = url.toLowerCase();
  const c = category.toLowerCase();
  const s = sku.toLowerCase();

  // ----- Nintendo / PlayStation / Xbox (check SKU/URL/Category first) -----
  // Nintendo Switch 2 detection (SKU starts with NS2HW, URL contains switch-2, or Category mentions it)
  if (/^ns2/i.test(s) || /switch-2|switch\s*2/i.test(u) || /switch\s*2/i.test(c)) {
    // If name doesn't contain "Nintendo Switch 2", use it as model
    if (!/nintendo\s+switch\s*2/i.test(name)) {
      return { family: 'Nintendo Switch 2', model: 'Nintendo Switch 2' };
    }
    return { family: 'Nintendo Switch 2', model: name };
  }
  
  if (/nintendo/i.test(brand) || /switch/i.test(core) || /switch/i.test(c)) {
    if (/switch\s*2/i.test(core) || /switch\s*2/i.test(c)) {
      return { family: 'Nintendo Switch 2', model: name || 'Nintendo Switch 2' };
    }
    return { family: 'Nintendo Switch', model: name || 'Nintendo Switch' };
  }
  if (/playstation|ps5|ps4/i.test(core) || /playstation/i.test(c)) {
    return { family: 'PlayStation', model: name };
  }
  if (/xbox/i.test(core) || /xbox/i.test(c)) {
    return { family: 'Xbox', model: name };
  }

  // ----- Apple -----
  if (b === 'apple' || b.includes('apple')) {
    // iPad lines
    if (n.includes('ipad air')) {
      return { family: 'iPad', model: core.replace(/^apple\s*/i, '') };
    }
    if (n.includes('ipad pro')) {
      return { family: 'iPad', model: core.replace(/^apple\s*/i, '') };
    }
    if (/ipad(?!\s*air|\s*pro)/i.test(core)) {
      return { family: 'iPad', model: core.replace(/^apple\s*/i, '') };
    }

    // iPhone lines
    if (/iphone/i.test(core)) {
      const famMatch = core.match(/iphone\s+(?:se|1[0-9](?:\s*pro(?:\s*max)?|\s*plus)?)/i);
      const fam = famMatch ? famMatch[0].replace(/\s{2,}/g, ' ').trim() : 'iPhone';
      return { family: fam.replace(/\bApple\b\s*/i, ''), model: core.replace(/^apple\s*/i, '') };
    }

    // AirPods / Watch
    if (/airpods/i.test(core)) return { family: 'AirPods', model: core.replace(/^apple\s*/i, '') };
    if (/watch/i.test(core)) return { family: 'Apple Watch', model: core.replace(/^apple\s*/i, '') };
  }


  // ----- Headphones (Sony/Marshall/Apple/etc.) -----
  if (/sony/i.test(brand)) {
    // Sony WH-1000XM6 -> Family: "Sony WH", Model: "WH-1000XM6"
    if (/wh-1000xm|wf-1000xm|1000xm/i.test(core)) {
      const modelMatch = name.match(/(wh-|wf-)?1000xm\d+/i);
      if (modelMatch) {
        const prefix = modelMatch[0].startsWith('WH') ? 'WH' : 'WF';
        return { family: `Sony ${prefix}`, model: modelMatch[0].toUpperCase() };
      }
      return { family: 'Sony WH', model: name.replace(/^sony\s*/i, '').trim() };
    }
    // Sony WH-XB910N -> Family: "Sony WH", Model: "WH-XB910N"
    if (/wh-|wf-/i.test(core)) {
      const modelMatch = name.match(/(wh-|wf-)[a-z0-9-]+/i);
      if (modelMatch) {
        const series = modelMatch[0].split('-').slice(0, 2).join('-').toUpperCase();
        const fullModel = modelMatch[0].toUpperCase();
        return { family: `Sony ${series}`, model: fullModel };
      }
    }
  }
  if (/bose/i.test(brand) && /quietcomfort|qc/i.test(core)) {
    // Bose QuietComfort -> Family: "Bose QC", Model: nombre completo
    return { family: 'Bose QC', model: name.replace(/^bose\s*/i, '').trim() };
  }
  if (/marshall/i.test(brand)) {
    return { family: 'Marshall Headphones', model: name };
  }
  // AirPods
  if (/apple/i.test(brand) && /airpods/i.test(core)) {
    return { family: 'AirPods', model: name.replace(/^apple\s*/i, '').trim() };
  }

  // ----- Drones -----
  if (/dji/i.test(brand)) {
    // DJI Mavic 4 Pro -> Family: "DJI Mavic", Model: "Mavic 4 Pro"
    if (/mavic/i.test(core)) {
      const modelMatch = name.match(/mavic\s+([^,]+)/i);
      return { family: 'DJI Mavic', model: modelMatch ? `Mavic ${modelMatch[1].trim()}` : name };
    }
    // DJI Mini 5 -> Family: "DJI Mini", Model: "Mini 5"
    if (/mini/i.test(core)) {
      const modelMatch = name.match(/mini\s+([^,]+)/i);
      return { family: 'DJI Mini', model: modelMatch ? `Mini ${modelMatch[1].trim()}` : name };
    }
    // DJI Air 3S -> Family: "DJI Air", Model: "Air 3S"
    if (/air\b/i.test(core)) {
      const modelMatch = name.match(/air\s+([^,]+)/i);
      return { family: 'DJI Air', model: modelMatch ? `Air ${modelMatch[1].trim()}` : name };
    }
    // DJI Avata 2 -> Family: "DJI Avata", Model: "Avata 2"
    if (/avata/i.test(core)) {
      const modelMatch = name.match(/avata\s+([^,]+)/i);
      return { family: 'DJI Avata', model: modelMatch ? `Avata ${modelMatch[1].trim()}` : name };
    }
    if (/neo/i.test(core)) return { family: 'DJI Neo', model: name };
    if (/flip/i.test(core)) return { family: 'DJI Flip', model: name };
    return { family: 'DJI', model: name };
  }
  
  // ----- Projectors -----
  if (/dangbei/i.test(brand) || /dangbei/i.test(core)) {
    // Extraer modelo: "Dangbei Mars 2 Lite" -> Family: "Dangbei", Model: "Mars 2 Lite"
    const modelMatch = name.match(/dangbei\s+(.+?)(?:\s+projector|\s+dlp|\s+laser|$)/i);
    if (modelMatch) {
      return { family: 'Dangbei', model: modelMatch[1].trim() };
    }
    return { family: 'Dangbei', model: name.replace(/^dangbei\s*/i, '').trim() || name };
  }
  if (/xgimi/i.test(brand) || /xgimi/i.test(core)) {
    // XGIMI: extraer serie/modelo del nombre
    const modelMatch = name.match(/xgimi\s+(.+?)(?:\s+projector|\s+4k|\s+uhd|$)/i);
    if (modelMatch) {
      return { family: 'XGIMI', model: modelMatch[1].trim() };
    }
    return { family: 'XGIMI', model: name.replace(/^xgimi\s*/i, '').trim() || name };
  }
  if (/epson/i.test(brand) && /projector|eh-tw|beamer/i.test(core)) {
    // Epson: extraer modelo (ej. "EH-TW840")
    const modelMatch = name.match(/epson\s+([a-z]{2}-[a-z]{2}\d+|[^,]+?)(?:\s+projector|$)/i);
    if (modelMatch) {
      return { family: 'Epson', model: modelMatch[1].trim() };
    }
    return { family: 'Epson', model: name.replace(/^epson\s*/i, '').trim() || name };
  }
  if (/optoma/i.test(brand) && /projector|photon/i.test(core)) {
    // Optoma: extraer modelo
    const modelMatch = name.match(/optoma\s+([^,]+?)(?:\s+projector|$)/i);
    if (modelMatch) {
      return { family: 'Optoma', model: modelMatch[1].trim() };
    }
    return { family: 'Optoma', model: name.replace(/^optoma\s*/i, '').trim() || name };
  }
  // Otros projectors genéricos
  if (/projector|beamer/i.test(core) && brand) {
    return { family: capitalize(brand), model: name };
  }
  
  // ----- Monitors -----
  if (/samsung/i.test(brand) && /odyssey|viewfinity|smart monitor/i.test(core)) {
    if (/odyssey/i.test(core)) {
      const modelMatch = name.match(/odyssey\s+([^,]+)/i);
      return { family: 'Samsung Odyssey', model: modelMatch ? `Odyssey ${modelMatch[1].trim()}` : name };
    }
    return { family: 'Samsung', model: name };
  }
  if (/lg/i.test(brand) && /ultragear|ultrafine|smart/i.test(core)) {
    if (/ultragear/i.test(core)) {
      return { family: 'LG UltraGear', model: name };
    }
    return { family: 'LG', model: name };
  }

  // ----- Robot vacuums -----
  if (/roborock/i.test(brand)) return { family: 'Roborock', model: name };
  if (/dreame/i.test(brand)) return { family: 'Dreame', model: name };

  // ----- LEGO -----
  if (/lego/i.test(brand) || /lego/i.test(core)) {
    return { family: 'LEGO', model: name };
  }

  // ----- Laptops / Monitors (fallback to brand) -----
  if (brand) {
    return { family: capitalize(brand), model: name };
  }

  return { family: '', model: name };
}

