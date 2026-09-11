// Name <-> ISO3 mapping for the War Map's country layer.
//
// Source of truth for country COVERAGE is world-atlas's countries-110m.json
// (Natural Earth, bundled at build time and rendered by WarMapClient's
// choropleth) — that dataset carries ~175-180 land polygons, each with a
// `properties.name` string. This file maps those name strings to ISO 3166-1
// alpha-3 codes so any clicked country/polygon can be joined against
// World Bank / IMF / UNHCR data, which are keyed by ISO3.
//
// Natural Earth abbreviates several names (e.g. "Dem. Rep. Congo",
// "S. Sudan", "Central African Rep.") — country-threat.json already
// confirmed several of these exact strings work against the live dataset,
// and this file follows the same convention for the rest. Coverage is
// intentionally generous (it lists small/likely-not-rendered-at-110m
// territories too) since an unused entry costs nothing, while resolveIso3()
// below adds a normalization + alias pass so near-miss spellings (official
// names, common alternates, punctuation differences) still resolve instead
// of silently failing closed.
//
// No 'server-only' import here on purpose — this is plain data + pure
// functions, safe to import from both the client (WarMapClient.jsx, to
// resolve an ISO3 before hitting the API) and the server (country-data
// route, to resolve a ?name= query param).

export const NAME_TO_ISO3 = {
  // Africa
  Algeria: 'DZA', Angola: 'AGO', Benin: 'BEN', Botswana: 'BWA', 'Burkina Faso': 'BFA',
  Burundi: 'BDI', Cameroon: 'CMR', 'Central African Rep.': 'CAF', Chad: 'TCD',
  'Dem. Rep. Congo': 'COD', Congo: 'COG', "Côte d'Ivoire": 'CIV', 'Ivory Coast': 'CIV',
  Djibouti: 'DJI', Egypt: 'EGY', 'Eq. Guinea': 'GNQ', Eritrea: 'ERI', eSwatini: 'SWZ',
  Swaziland: 'SWZ', Ethiopia: 'ETH', Gabon: 'GAB', Gambia: 'GMB', 'The Gambia': 'GMB',
  Ghana: 'GHA', Guinea: 'GIN', 'Guinea-Bissau': 'GNB', Kenya: 'KEN', Lesotho: 'LSO',
  Liberia: 'LBR', Libya: 'LBY', Madagascar: 'MDG', Malawi: 'MWI', Mali: 'MLI',
  Mauritania: 'MRT', Mauritius: 'MUS', Morocco: 'MAR', Mozambique: 'MOZ', Namibia: 'NAM',
  Niger: 'NER', Nigeria: 'NGA', Rwanda: 'RWA', Senegal: 'SEN', 'Sierra Leone': 'SLE',
  Somaliland: 'SOM', Somalia: 'SOM', 'South Africa': 'ZAF', 'S. Sudan': 'SSD', Sudan: 'SDN',
  Tanzania: 'TZA', Togo: 'TGO', Tunisia: 'TUN', Uganda: 'UGA', 'W. Sahara': 'ESH',
  Zambia: 'ZMB', Zimbabwe: 'ZWE', 'Cape Verde': 'CPV', 'Cabo Verde': 'CPV', Comoros: 'COM',
  Seychelles: 'SYC',

  // Europe
  Albania: 'ALB', Andorra: 'AND', Austria: 'AUT', Belarus: 'BLR', Belgium: 'BEL',
  'Bosnia and Herz.': 'BIH', Bulgaria: 'BGR', Croatia: 'HRV', Cyprus: 'CYP',
  'N. Cyprus': 'CYP', Czechia: 'CZE', 'Czech Republic': 'CZE', Denmark: 'DNK',
  Estonia: 'EST', Finland: 'FIN', France: 'FRA', Germany: 'DEU', Greece: 'GRC',
  Hungary: 'HUN', Iceland: 'ISL', Ireland: 'IRL', Italy: 'ITA', Kosovo: 'XKX',
  Latvia: 'LVA', Liechtenstein: 'LIE', Lithuania: 'LTU', Luxembourg: 'LUX', Malta: 'MLT',
  Moldova: 'MDA', Monaco: 'MCO', Montenegro: 'MNE', Netherlands: 'NLD',
  'North Macedonia': 'MKD', Macedonia: 'MKD', Norway: 'NOR', Poland: 'POL',
  Portugal: 'PRT', Romania: 'ROU', Russia: 'RUS', 'San Marino': 'SMR', Serbia: 'SRB',
  Slovakia: 'SVK', Slovenia: 'SVN', Spain: 'ESP', Sweden: 'SWE', Switzerland: 'CHE',
  Ukraine: 'UKR', 'United Kingdom': 'GBR', 'Vatican City': 'VAT',

  // Asia
  Afghanistan: 'AFG', Armenia: 'ARM', Azerbaijan: 'AZE', Bahrain: 'BHR',
  Bangladesh: 'BGD', Bhutan: 'BTN', Brunei: 'BRN', Cambodia: 'KHM', China: 'CHN',
  Georgia: 'GEO', India: 'IND', Indonesia: 'IDN', Iran: 'IRN', Iraq: 'IRQ',
  Israel: 'ISR', Japan: 'JPN', Jordan: 'JOR', Kazakhstan: 'KAZ', Kuwait: 'KWT',
  Kyrgyzstan: 'KGZ', Laos: 'LAO', Lebanon: 'LBN', Malaysia: 'MYS', Maldives: 'MDV',
  Mongolia: 'MNG', Myanmar: 'MMR', Burma: 'MMR', Nepal: 'NPL', 'North Korea': 'PRK',
  Oman: 'OMN', Pakistan: 'PAK', Palestine: 'PSE', 'West Bank': 'PSE', Philippines: 'PHL',
  Qatar: 'QAT', 'Saudi Arabia': 'SAU', Singapore: 'SGP', 'South Korea': 'KOR',
  'Sri Lanka': 'LKA', Syria: 'SYR', Taiwan: 'TWN', Tajikistan: 'TJK', Thailand: 'THA',
  'Timor-Leste': 'TLS', Turkey: 'TUR', Türkiye: 'TUR', Turkmenistan: 'TKM',
  'United Arab Emirates': 'ARE', Uzbekistan: 'UZB', Vietnam: 'VNM', 'Viet Nam': 'VNM',
  Yemen: 'YEM',

  // Oceania
  Australia: 'AUS', Fiji: 'FJI', Kiribati: 'KIR', 'Marshall Is.': 'MHL',
  Micronesia: 'FSM', Nauru: 'NRU', 'New Zealand': 'NZL', Palau: 'PLW',
  'Papua New Guinea': 'PNG', Samoa: 'WSM', 'Solomon Is.': 'SLB', Tonga: 'TON',
  Tuvalu: 'TUV', Vanuatu: 'VUT', 'New Caledonia': 'NCL', 'Fr. Polynesia': 'PYF',

  // Americas
  'Antigua and Barb.': 'ATG', Argentina: 'ARG', Bahamas: 'BHS', 'The Bahamas': 'BHS',
  Barbados: 'BRB', Belize: 'BLZ', Bolivia: 'BOL', Brazil: 'BRA', Canada: 'CAN',
  Chile: 'CHL', Colombia: 'COL', 'Costa Rica': 'CRI', Cuba: 'CUB', Dominica: 'DMA',
  'Dominican Rep.': 'DOM', Ecuador: 'ECU', 'El Salvador': 'SLV', 'Falkland Is.': 'FLK',
  Greenland: 'GRL', Grenada: 'GRD', Guatemala: 'GTM', Guyana: 'GUY', Haiti: 'HTI',
  Honduras: 'HND', Jamaica: 'JAM', Mexico: 'MEX', Nicaragua: 'NIC', Panama: 'PAN',
  Paraguay: 'PRY', Peru: 'PER', 'Puerto Rico': 'PRI', 'St. Kitts and Nevis': 'KNA',
  'St. Lucia': 'LCA', 'St. Vin. and Gren.': 'VCT', Suriname: 'SUR',
  'Trinidad and Tobago': 'TTO', 'United States of America': 'USA', Uruguay: 'URY',
  Venezuela: 'VEN',
};

// Common alternate spellings / official names (World Bank, IMF, UN) that
// don't match Natural Earth's map labels but are worth resolving anyway —
// keeps this working even if a caller passes a "proper" name instead of
// the map's abbreviated one.
const ALIASES = {
  'united states': 'USA', usa: 'USA', us: 'USA', 'u.s.': 'USA', 'u.s.a.': 'USA',
  'democratic republic of the congo': 'COD', 'dr congo': 'COD', drc: 'COD',
  'congo, dem. rep.': 'COD', 'republic of the congo': 'COG', 'congo, rep.': 'COG',
  'south sudan': 'SSD', 'central african republic': 'CAF', 'russian federation': 'RUS',
  'republic of korea': 'KOR', 'korea, rep.': 'KOR', 'korea south': 'KOR',
  "democratic people's republic of korea": 'PRK', 'korea, dem. people’s rep.': 'PRK',
  'korea north': 'PRK', 'syrian arab republic': 'SYR', 'iran, islamic rep.': 'IRN',
  'islamic republic of iran': 'IRN', 'venezuela, rb': 'VEN',
  'bolivarian republic of venezuela': 'VEN', 'lao pdr': 'LAO', "lao people's democratic republic": 'LAO',
  'brunei darussalam': 'BRN', 'egypt, arab rep.': 'EGY', 'arab republic of egypt': 'EGY',
  'yemen, rep.': 'YEM', 'slovak republic': 'SVK', 'kyrgyz republic': 'KGZ',
  'gambia, the': 'GMB', 'bahamas, the': 'BHS', 'micronesia, fed. sts.': 'FSM',
  'st. kitts and nevis': 'KNA', 'st. lucia': 'LCA', 'st. vincent and the grenadines': 'VCT',
  'turkiye': 'TUR', turkey: 'TUR', 'cote d’ivoire': 'CIV', "cote d'ivoire": 'CIV',
  'holy see': 'VAT', 'united kingdom of great britain and northern ireland': 'GBR',
  'hong kong': 'HKG', 'hong kong sar, china': 'HKG', macao: 'MAC', 'macao sar, china': 'MAC',
};

function normalize(str) {
  return String(str || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '') // strip accents so "Türkiye" ~= "turkiye"
    .replace(/[.,]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// Lazily-built normalized index so repeated lookups don't re-walk the
// dictionaries every call.
let NORMALIZED_INDEX = null;
function getNormalizedIndex() {
  if (NORMALIZED_INDEX) return NORMALIZED_INDEX;
  NORMALIZED_INDEX = new Map();
  for (const [name, iso3] of Object.entries(NAME_TO_ISO3)) {
    NORMALIZED_INDEX.set(normalize(name), iso3);
  }
  for (const [name, iso3] of Object.entries(ALIASES)) {
    NORMALIZED_INDEX.set(normalize(name), iso3);
  }
  return NORMALIZED_INDEX;
}

// Resolve a country name (however spelled/cased/punctuated) to an ISO3
// code, or null if nothing matches. Never throws.
export function resolveIso3(name) {
  if (!name) return null;
  if (NAME_TO_ISO3[name]) return NAME_TO_ISO3[name];
  const idx = getNormalizedIndex();
  return idx.get(normalize(name)) || null;
}

export function isKnownCountryName(name) {
  return resolveIso3(name) !== null;
}
