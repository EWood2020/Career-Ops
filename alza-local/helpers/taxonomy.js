// helpers/taxonomy.js
// Sistema de clasificación inteligente de categorías usando scoring
// Taxonomía v1.0 para Flexnology - Estructura completa

export const TAXO_RULES = {
  "Toys & Games": {
    LEGO: {
      kw: [
        "lego", "brickheadz", "technic", "ninjago", "minecraft", "star wars", 
        "speed champions", "lego city", "lego icons", "lego set", "lego technic",
        "lego ninjago", "lego star wars", "lego minecraft", "lego speed champions"
      ],
      url: ["toys/lego", "lego"],
      score: { kw: 3, url: 3, bc: 4 },
      family: "LEGO"
    },
    "Party & Card Games": {
      kw: [
        "board game", "party game", "card game", "expansion pack", "tabletop game",
        "card games", "party games", "board games", "strategy game", "cooperative game"
      ],
      url: ["party-games", "board-games", "card-games", "tabletop-games"],
      score: { kw: 2, url: 3, bc: 4 }
    }
  },
  "Computers": {
    Laptops: {
      kw: [
        "laptop", "notebook", "macbook", "thinkpad", "ideapad", "zenbook", 
        "victus", "omen", "msi", "vivobook", "legion", "aspire", "surface", 
        "probook", "chromebook", "gaming laptop", "ultrabook", "workstation"
      ],
      url: ["laptops", "gaming-laptops", "business-laptops", "ultrabooks"],
      score: { kw: 2, url: 3, bc: 4 }
    },
    Monitors: {
      kw: [
        "monitor", "lcd", "oled monitor", "uhd", "ips", "curved", "displayport", 
        "gaming monitor", "4k monitor", "ultrawide", "hz", "144hz", "240hz", 
        "smart monitor", "portable monitor", "professional monitor", "large format",
        "display", "screen", "led monitor", "qhd", "fhd", "full hd"
      ],
      url: [
        "lcd-monitors", "curved-monitors", "4k-monitors", "gaming-monitors", 
        "smart-monitors", "portable-monitors", "large-format-displays", "professional-monitors"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    },
    "VR Glasses": {
      kw: [
        "vr", "virtual reality", "quest", "meta quest", "ps vr", "mixed reality", 
        "vr headset", "vr glasses", "oculus", "htc vive", "pico", "standalone vr",
        "vr for pc", "vr for console", "vr for drone", "vr accessories"
      ],
      url: [
        "vr-glasses", "virtual-reality-glasses", "vr-headsets", "vr-for-pc",
        "vr-for-consoles", "standalone-vr", "vr-accessories"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    }
  },
  "Phones & Tablets": {
    Phones: {
      kw: [
        "iphone", "smartphone", "smart phone", "android phone", "mobile phone",
        "samsung galaxy", "google pixel", "xiaomi", "oneplus", "huawei"
      ],
      url: ["smartphones", "mobile-phones", "iphone", "android-phones"],
      score: { kw: 3, url: 3, bc: 4 }
    },
    Tablets: {
      kw: [
        "ipad", "tablet", "android tablet", "samsung tablet", "galaxy tab",
        "surface tablet", "tablet pc", "convertible tablet"
      ],
      url: ["tablets", "ipad", "android-tablets", "tablet-pcs"],
      score: { kw: 3, url: 3, bc: 4 }
    }
  },
  "TV, Photo, Audio & Video": {
    Projectors: {
      kw: [
        "projector", "beamer", "short throw", "ansi lm", "ansi lumens", "dlp projector", 
        "lcd projector", "laser projector", "mini projector", "home theater projector", 
        "interactive projector", "dangbei", "xgimi", "optoma", "epson projector", 
        "viewsonic projector", "4k uhd projector", "led projector", "projector screen",
        "projector mount", "projector accessories", "uhd projector", "hdr projector"
      ],
      url: [
        "projectors", "mini-projectors", "home-cinema-projectors", "led-projectors", 
        "laser-projectors", "short-throw-projectors", "interactive-projectors", 
        "smart-projectors", "projector-screens", "projector-mounts", "projector-accessories"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    },
    Drones: {
      kw: [
        "drone", "uav", "gimbal", "fly more combo", "rc-n3", "rc-2", "rc-n2", 
        "mavic", "avata", "mini 4", "mini 5", "neo", "flip", "air 3s", "air 3", 
        "dji", "fpv", "gps drone", "camera drone", "foldable drone", "professional drone",
        "enterprise drone", "mini drone", "drone with gps", "drone accessories"
      ],
      url: [
        "drones", "camera-drones", "mini-drones", "foldable-drones", 
        "professional-drones", "beginner-drones", "drones-with-gps", "fpv-goggles",
        "enterprise-drones", "drone-accessories"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    },
    Headphones: {
      kw: [
        "headphones", "headset", "over-ear", "on-ear", "true wireless", "anc", 
        "noise cancelling", "wf-1000xm", "wh-1000xm", "airpods", "earbuds", 
        "wireless earbuds", "gaming headset", "bone conduction", "sports headphones", 
        "with mic", "wireless headphones", "bluetooth headphones", "qc", "quietcomfort",
        "bose", "sony wh", "sony wf", "in-ear", "earphones"
      ],
      url: [
        "headphones", "gaming-headsets", "true-wireless-headphones", 
        "wireless-headphones", "over-ear-headphones", "in-ear-wireless-headphones", 
        "sports-headphones", "bone-conduction-headphones", "headphone-accessories"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    }
  },
  "Gaming & Entertainment": {
    PlayStation: {
      kw: [
        "playstation 5", "ps5", "dualsense", "ps5 pro", "playstation vr", "ps vr2", 
        "psvr2", "playstation controller", "ps5 console", "playstation game", 
        "ps5 game", "playstation accessory", "dualsense edge"
      ],
      url: [
        "playstation", "gaming/playstation", "playstation-5", "ps5", 
        "playstation-games", "playstation-accessories", "playstation-vr"
      ],
      score: { kw: 3, url: 3, bc: 4 },
      family: "PlayStation"
    },
    Xbox: {
      kw: [
        "xbox series", "xbox controller", "game pass", "xbox series x", 
        "xbox series s", "xbox console", "xbox game", "xbox accessory",
        "xbox wireless controller", "xbox elite controller"
      ],
      url: [
        "xbox", "gaming/xbox", "xbox-series-x", "xbox-series-s", 
        "xbox-games", "xbox-accessories", "xbox-controllers"
      ],
      score: { kw: 3, url: 3, bc: 4 },
      family: "Xbox"
    },
    "Nintendo Switch": {
      kw: [
        "nintendo switch", "switch 2", "joy-con", "pokemon legends", "mario kart", 
        "nintendo switch 2", "ns2hw", "nintendo switch oled", "nintendo switch lite",
        "switch console", "nintendo game", "switch game", "switch accessory",
        "nintendo switch pro controller"
      ],
      url: [
        "nintendo-switch", "nintendo-switch-2", "gaming/nintendo-switch",
        "switch-2", "nintendo-switch-games", "nintendo-switch-accessories"
      ],
      score: { kw: 3, url: 3, bc: 4 },
      family: "Nintendo Switch"
    }
  },
  "Pet Supplies": {
    Dogs: {
      kw: [
        "dog", "canine", "puppy", "kennel", "kibble", "dog food", "dog treats", 
        "dog bed", "dog bowl", "dog toy", "dog leash", "dog collar", "dog hygiene",
        "dog supplement", "dog travel", "dog veterinary", "dog accessory"
      ],
      url: [
        "pet-supplies-for-dogs", "dog-food", "dog-treats", "dog-beds", 
        "dog-bowls", "dog-toys", "dog-leashes", "dog-collars", "dog-hygiene",
        "dog-supplements", "dog-travel"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    },
    Cats: {
      kw: [
        "cat", "feline", "kitten", "litter", "cat food", "cat treats", "cat bed", 
        "cat bowl", "cat toy", "scratching post", "cat toilet", "cat hygiene",
        "cat supplement", "cat travel", "cat veterinary", "cat accessory"
      ],
      url: [
        "pet-supplies-for-cats", "cat-food", "cat-treats", "cat-beds", 
        "cat-toilets", "cat-toys", "litter", "scratching-posts", "cat-hygiene",
        "cat-supplements", "cat-travel"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    }
  },
  "Household & Personal Appliances": {
    "Robotic Vacuum Cleaners": {
      kw: [
        "robot vacuum", "vacuum robot", "roborock", "deebot", "dreame", "auto-wash", 
        "omni", "robot vacuum cleaner", "robotic cleaner", "roomba", "ecovacs", 
        "xiaomi robot", "robot with mop", "low-profile robot", "robot vacuum accessory"
      ],
      url: [
        "robotic-vacuum-cleaners", "robot-vacuum", "robotic-vacuum",
        "robot-vacuum-with-mop", "low-profile-robots", "robot-vacuum-accessories"
      ],
      score: { kw: 2, url: 3, bc: 4 }
    }
  }
};

function normalize(s = '') {
  return s.toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function classifyCategory({ name, description, url, breadcrumbRoot, breadcrumbSub }) {
  const text = normalize(`${name || ''} ${description || ''}`);
  const path = (url || '').toLowerCase();
  const bcRoot = normalize(breadcrumbRoot || '');
  const bcSub = normalize(breadcrumbSub || '');

  let best = { cat: '', sub: '', score: -1, family: '' };

  for (const [cat, subs] of Object.entries(TAXO_RULES)) {
    for (const [sub, rule] of Object.entries(subs)) {
      let score = 0;

      // Breadcrumb (fuerte señal) - 4 puntos
      if (bcRoot && (normalize(cat).includes(bcRoot) || bcRoot.includes(normalize(cat)))) {
        score += rule.score.bc;
      }
      if (bcSub && (normalize(sub).includes(bcSub) || bcSub.includes(normalize(sub)))) {
        score += rule.score.bc;
      }

      // URL path - 3 puntos
      if (rule.url?.some(u => path.includes(normalize(u)))) {
        score += rule.score.url;
      }

      // Keywords en texto - 2 puntos
      if (rule.kw?.some(k => text.includes(normalize(k)))) {
        score += rule.score.kw;
      }

      if (score > best.score) {
        best = { cat, sub, score, family: rule.family || '' };
      }
    }
  }

  // Forzar categorías específicas si hay señales muy claras (evitar "Computers & Tablets" genérico)
  const hasProjectorSignals = 
    text.includes('projector') || 
    text.includes('beamer') || 
    text.includes('ansi lm') || 
    text.includes('ansi lumens') ||
    text.includes('dlp') || 
    text.includes('laser projector') ||
    path.includes('projector');
    
  const hasDroneSignals = 
    text.includes('drone') || 
    text.includes('mavic') || 
    text.includes('dji') || 
    text.includes('avata') ||
    path.includes('drone');
    
  const hasHeadphoneSignals = 
    text.includes('headphone') || 
    text.includes('headset') || 
    text.includes('wh-') || 
    text.includes('wf-') ||
    text.includes('airpods') ||
    path.includes('headphone');
  
  // Forzar Projectors a "TV, Photo, Audio & Video" (no "Computers & Tablets")
  if (hasProjectorSignals) {
    if (best.cat !== 'TV, Photo, Audio & Video' || best.sub !== 'Projectors') {
      best = { cat: 'TV, Photo, Audio & Video', sub: 'Projectors', score: Math.max(best.score, 5), family: '' };
    }
  }
  
  // Forzar Drones a "TV, Photo, Audio & Video"
  if (hasDroneSignals) {
    if (best.cat !== 'TV, Photo, Audio & Video' || best.sub !== 'Drones') {
      best = { cat: 'TV, Photo, Audio & Video', sub: 'Drones', score: Math.max(best.score, 5), family: '' };
    }
  }
  
  // Forzar Headphones a "TV, Photo, Audio & Video"
  if (hasHeadphoneSignals) {
    if (best.cat !== 'TV, Photo, Audio & Video' || best.sub !== 'Headphones') {
      best = { cat: 'TV, Photo, Audio & Video', sub: 'Headphones', score: Math.max(best.score, 5), family: '' };
    }
  }

  // Umbral mínimo para aceptar clasificación (3 puntos)
  if (best.score >= 3) {
    return best;
  }

  return { cat: '', sub: '', score: 0, family: '' };
}
