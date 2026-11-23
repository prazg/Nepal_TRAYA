/**
 * Nepal TRĀYA (त्राय) — Bilingual Internationalization (EN | नेपाली)
 * Persisted in localStorage['traya.lang']; updates document.documentElement.lang.
 */

const STORAGE_KEY = 'traya.lang';

export const PROVINCE_NE = {
  'Koshi Province': 'कोशी प्रदेश',
  'Madhesh Province': 'मधेश प्रदेश',
  'Bagmati Province': 'बागमती प्रदेश',
  'Gandaki Province': 'गण्डकी प्रदेश',
  'Lumbini Province': 'लुम्बिनी प्रदेश',
  'Karnali Province': 'कर्णाली प्रदेश',
  'Sudurpashchim Province': 'सुदूरपश्चिम प्रदेश',
};

const DICT = {
  en: {
    skipToMap: 'Skip to interactive map',
    suiteLabel: 'Nepal Open-Science Suite',
    suiteHub: 'Observatory Hub',
    suiteNeuro: 'Open Neuro & AI Suite ↗',
    brandScope: '7-Day Risk Observatory',
    brandSub: 'Open-Data Multi-Hazard Screening — GLOFs · River Floods · Earthquakes · Landslides · Cascades · SAR EO',
    btnRefreshLive: '↻ Refresh live',
    btnRefreshing: '↻ Refreshing…',
    btnSourceHealth: 'Source Health',
    btnKpi: 'KPIs',
    btnTheme: '◐ Theme',
    btnLang: 'नेपाली',
    btnEmergency: 'Emergency · आपतकालीन',

    safetyTag: 'NOT AN OFFICIAL EARLY WARNING SYSTEM',
    safetyEn: 'TRĀYA is a 7-day open-data multi-hazard risk observatory & screening platform — not an operational warning service.',
    safetyConsult: 'Official warnings:',

    staleExpiredTitle: 'Expired forecast / stale weekly snapshot:',
    staleRefreshCta: 'Refresh live feeds now',
    compoundTitle: 'Compound Hazard Awareness:',

    kpiLakesLbl: 'Glacial Lakes Screened',
    kpiLakesSub: 'PFV ≥ 10 Mm³ screening set (Fujita 2013)',
    kpiRiversLbl: 'Fluvial Flood Watch (GloFAS)',
    kpiRiversSub: 'Ensemble discharge & Gumbel return levels',
    kpiLsLbl: 'Landslide Rainfall Watch',
    kpiLsSub: 'Dahal & Hasegawa (2008) liquid-rain I–D',
    kpiEqLbl: 'Official Alerts & Seismic',
    kpiEqSub: 'NDRRMA BIPAD · USGS live + GEM traces',
    kpiSatLbl: 'Cryosphere & SAR / S2 EO',
    kpiSatSub: '0 °C isotherm · Sentinel-1 SAR & S2',
    kpiCascLbl: 'Cascades & Isolation',
    kpiCascSub: '1 km corridor · hospital access · Tsho Rolpa',
    kpiValLbl: 'Validation & 7-Day Cycle',
    kpiValSub: 'Screening tool — not an operational warning',

    mobDetail: 'Inspector',
    mobControls: 'Filters',
    mobBottom: 'Tables',
    mobKpis: 'Summary',

    triageTitle: 'My District · मेरो जिल्ला',
    triageAllDistricts: 'Select any of 77 Nepal districts…',
    triageSearchPh: 'Find district (e.g. Kathmandu, Chitwan, Humla)…',
    triageNearMe: '◎ Near Me',
    triageNearMeBusy: 'Locating…',
    triageClear: 'Clear',
    triageGeoUnsupported: 'Browser geolocation is not supported on this device.',
    triageGeoDenied: 'Location permission denied or unavailable. Choose your district above.',
    triageOutsideNepal: 'Your location appears outside Nepal; showing nearest Nepal district:',

    secColourBy: 'Colour glacial lakes by',
    secFilters: 'Filter glacial lakes',
    btnReset: 'Reset',
    fPriority: 'Priority set only (PFV ≥ 10 Mm³)',
    fOnlyRouted: 'Routed flood path present (697)',
    fAva: 'Avalanche can reach lake',
    fSla: 'Steep lakefront (SLA > 10°)',
    fIce: 'Documented moraine ice core',
    fContact: 'Glacier ice contact on shore',
    fPast: 'Recorded historical GLOF',
    fAllProvs: 'All 7 provinces',
    fMinArea: 'Min lake area:',
    fSearchPh: 'Search lake, district, RGI… (/)',
    secLayers: 'Multi-hazard layers',
    lLakes: 'Glacial lakes (1,429)',
    lRoute: 'Selected GLOF path & ticks',
    lExp: 'Corridor exposure on path',
    lRivers: 'GloFAS river stations (10)',
    lFaults: 'Active faults — surface (GEM)',
    lNodes: 'Rainfall–landslide nodes (24)',
    lLandslides: 'Landslide inventory (5-type)',
    lEq: 'Live earthquakes (USGS)',
    lMmi: 'ShakeMap MMI contours',
    lEqHist: 'Historical earthquakes M≥6',
    lGlof: 'Recorded GLOFs (HMAGLOFDB)',
    lHydro: 'Hydropower plants (OSM)',
    lGdacs: 'GDACS regional alerts',

    secGibs: 'NASA GIBS satellite overlay',
    gibsNone: 'No live satellite overlay',
    gibsImerg: 'GPM IMERG Precipitation Rate',
    gibsSnow: 'MODIS Terra Snow Cover (NDSI)',
    gibsViirs: 'VIIRS SNPP True Colour (daily)',
    gibsNote: 'Keyless NASA EOSDIS WMTS tiles. Use 2–3 days prior if today is still processing.',
    secEqWin: 'Live earthquake window',
    eqWinDay: 'Past 24 hours (M≥2.0)',
    eqWinWeek: 'Past 7 days (M≥2.5)',
    eqWinMonth: 'Past 30 days (M≥3.5)',
    secScope: 'Scientific scope',
    scopeBody1: 'TRĀYA screens 1,429 glacial lakes, 10 major river basins, 70 GEM surface faults, and 24 physiographic rainfall zones across all 77 Nepal districts using published empirical methods.',
    scopeBody2: 'Not an operational early warning system. Always follow official bulletins from Nepal DHM, DMG/NEMRC, and NDRRMA.',

    hudControls: '☰ Controls',
    hudInspector: 'Inspector ▤',
    regAll: 'All Nepal',
    regKhumbu: 'Khumbu',
    regRolwaling: 'Rolwaling',
    regBarun: 'Barun',
    regAnnapurna: 'Annapurna–Manaslu',
    regLangtang: 'Langtang',
    regKarnali: 'Karnali',

    tabWatch: 'Glacial Lakes',
    tabFloods: 'Flood Watch (GloFAS)',
    tabLandslides: 'Landslide Watch',
    tabCascades: 'Cascades & Isolation',
    tabLive: 'Official Alerts & Quakes',
    tabSat: 'Satellite & SAR EO',
    tabGlof: 'Recorded GLOFs',
    tabCharts: 'Analytics',
    tabValid: 'Validation & Limits',
    tabMethods: 'Methods & Citations',

    tierVeryHigh: 'Very High',
    tierHigh: 'High',
    tierModerate: 'Moderate',
    tierLow: 'Low',
    tierNa: 'Not Assessed',

    riverNormal: 'Normal',
    riverElevated: 'Elevated (>Q90)',
    riverWatch: 'Watch (≥Q2)',
    riverWarning: 'Warning (≥Q5)',
    riverSevere: 'Severe (≥Q20)',
    riverUnassessed: 'Unassessed',

    dhLow: 'Low',
    dhElevated: 'Elevated',
    dhWatch: 'Watch',
    dhExceeded: 'Exceeded',

    emergTitle: 'Nepal Emergency Hotlines & Official Agencies',
    emergClose: 'Close',
    emergSubtitle: 'TRĀYA is a research and screening observatory, NOT an operational warning system. In an emergency, contact Nepal statutory services directly:',
    emergHotlinesHead: '1-Tap Nepal Emergency Hotlines',
    emergAgenciesHead: 'Official Statutory Portals & Live Feeds',
    emergPrepHead: 'Plain-Language Preparedness Reminders',
    emergPrep1: 'GLOF / River Flash Flood: If water turns suddenly muddy/debris-laden or river level drops abruptly and roars, move immediately to high ground perpendicular to the river valley — do not wait to cross bridges.',
    emergPrep2: 'Earthquake: Drop, Cover, and Hold On away from masonry walls and windows. After strong shaking (M≥5), stay alert for aftershocks, landslides on steep slopes, and sudden glacial/river surges.',
    emergPrep3: 'Monsoon Landslide: Watch for new ground cracks, bulging slopes, tilting trees, or muddy spring water after heavy 24–72 h rain; relocate early to safer open ground.',

    distBriefTitle: 'District Multi-Hazard Briefing',
    distRiverSec: 'Nearest GloFAS River Basin',
    distRainSec: 'Nearest Rainfall–Landslide Node',
    distEqSec: 'Recent USGS Earthquakes (≤100 km)',
    distLakeSec: 'Glacial Lakes & Routed GLOF Corridors',
    distGdacsSec: 'GDACS Regional Alerts',
    distInspectRiver: 'Inspect 60d hydrograph',
    distInspectNode: 'Inspect rainfall node',
    distFilterLakes: 'Filter lakes to district',
    distNoLakesInside: '0 glacial lakes lie inside this district. Multi-hazard exposure here is governed primarily by river floods, rainfall-induced landslides, earthquakes, and any upstream GLOF corridors listed below.',
    distNoEq100: 'No live USGS earthquakes within 100 km in the selected window.',

    liveSnapshot: 'Snapshot',
    liveFresh: 'Live',
    liveStale: 'Stale',
    liveOffline: 'Offline',
    unknownVal: 'Unknown',
    coolrZeroNotice: 'Data coverage notice: 0 NASA COOLR records are currently loaded (upstream endpoint returned no records or was unavailable). Displaying {n} undated OpenStreetMap mapped landslide scars only — absence of markers does not imply low landslide hazard.',
    gridSnapNotice: '{n} of 10 cached GloFAS stations have off-mainstem grid-cell warnings (flagged ⚠ below) until the next live 3×3 mainstem snap runs. Always verify with DHM real-time river gauges (hydrology.gov.np).',

    /* TRĀYA 2.0 Source Health & 6-State Provenance */
    shTitle: 'Source Health, Provenance & KPI Scorecard',
    shSubtitle: '6-state epistemic data classification, SLA freshness (NPT), fallback transparency & dataset licences',
    shLoading: 'Loading provenance manifest & KPI baseline…',
    shOverallHealth: 'Overall Feed Health',
    shHealthHealthy: 'Healthy',
    shHealthDegraded: 'Degraded',
    shHealthStale: 'Stale',
    shKpiFreshness: 'Feed Freshness SLA',
    shKpiProvenance: 'Provenance Completeness',
    shKpiLandslide: 'Landslide Maturity',
    shKpiExposure: 'Exposure & Cascade Coverage',
    shColDataset: 'Source / Dataset',
    shColClass: 'Data Class',
    shColUpdated: 'Updated (NPT)',
    shColSla: 'SLA Status',
    shColFallback: 'Delivery',
    shColRecords: 'Records',
    shColLicense: 'Licence',
    shDirect: 'Direct',
    shFallback: 'Fallback',
    shMouRequired: 'MOU Required',
    shViewLicenses: 'DATA_LICENSES.md ↗',
    dcLiveObservation: 'Live Observation',
    dcForecast: 'Forecast',
    dcHistorical: 'Historical',
    dcStaticAssessment: 'Static Assessment',
    dcCached: 'Cached',
    dcUnavailable: 'Unavailable',
    slaAvailable: 'Available',
    slaStale: 'Stale',
    slaUnavailable: 'Unavailable',

    /* Official Nepal Authority Feeds (BIPAD · DHM · NSC) */
    officialLaneTitle: 'Official Nepal Authority Feeds (NDRRMA BIPAD · DHM · NSC)',
    officialBadge: 'Official Observation',
    modelledBadge: 'Modelled Forecast',
    screeningBadge: 'Screening Layer',
    officialNotice: 'Official Government of Nepal NDRRMA/BIPAD records — kept structurally separate from modelled forecasts.',
    bipadAwaitingRefresh: 'BIPAD snapshot awaiting next live refresh',
    bipadAlertsHead: 'Verified BIPAD Alerts',
    bipadRiversHead: 'DHM River Gauges (via BIPAD)',
    bipadRainHead: 'DHM Rain Gauges (via BIPAD)',
    bipadEqHead: 'NSC / NEMRC Earthquakes (via BIPAD)',
    bipadLsHead: 'Verified BIPAD Landslide Incidents',
    openDataSeismicHead: 'Open-Data Seismic & Fault Screening (USGS FDSN · GEM Surface Faults)',

    /* Cascades & Isolation Tab */
    cascGraphTitle: 'Interpretable Directed Multi-Hazard Cascade Graph',
    cascInspectorTitle: 'Rule & Evidence Inspector',
    cascClickHint: 'Click any node or rule edge in the graph to inspect its physical trigger rule, evidence tier, confidence, and uncertainty bounds.',
    cascScenariosTitle: 'Multi-Hazard Cascade Pathways & Active Scenarios',
    evObserved: 'Observed',
    evForecast: 'Forecast',
    evModelled: 'Modelled',
    isoSectionTitle: 'Downstream Exposure & Road-Cut Hospital Isolation',
    isoCorridorBadge: '1 km screening search corridor — NOT a hydrodynamic inundation boundary',
    isoTabLakes: 'Priority Lakes & Corridors',
    isoTabDistricts: 'All 77 Districts (Isolation)',
    pilotTitle: 'Tsho Rolpa 2D Hydrodynamic Pilot Benchmark (TRAYA-011)',
    pilotBadge: 'Pre-simulation reference framework — NOT yet a 2D inundation map',
    pilotStudyPlanLink: 'Read Tsho Rolpa 2D Study Plan (docs/TSHO_ROLPA_2D_STUDY_PLAN.md) ↗',
    pilotFlyLake: 'Inspect Tsho Rolpa on map',

    /* Upgraded 5-Type Landslides Tab */
    lsTypeAll: 'All Records',
    lsTypeEvent: 'Dated Events (BIPAD/COOLR)',
    lsTypeScar: 'Undated OSM Scars',
    lsTypeSuscept: 'Susceptibility Zones',
    lsTypeReport: 'Hazard Reports',
    lsTypeCoseismic: 'Coseismic Failures',
    lsDownloadGeojson: '⬇ Download landslide_inventory.geojson (RFC 7946)',
    lsReviewQueueTitle: 'Duplicate-Candidate Review Queue',
    lsReviewPolicyBadge: 'Flag-Only · Never Auto-Merged',
    lsReviewEmpty: '0 duplicate candidates currently flagged across {n} scanned records. Cross-source candidate pairs (<= 1.5 km & <= 3 d dated, or <= 0.35 km undated cross-source) populate automatically for human review when live BIPAD/COOLR feeds load.',

    /* Sentinel-1 SAR Section */
    sarSectionTitle: 'Sentinel-1 SAR — All-Weather Monsoon Radar (Priority Glacial Lakes)',
    sarRadarBadge: 'All-Weather Cloud-Penetrating C-Band SAR (IW VV/VH)',
    sarAwaitingLive: 'Awaiting live Sentinel-1 STAC refresh',
    sarOpenBrowser: 'Open S1 SAR ↗',
    sarOpenS2: 'Open S2 ↗',
  },

  ne: {
    skipToMap: 'नक्सामा सिधै जानुहोस्',
    suiteLabel: 'नेपाल खुला-विज्ञान अवलोकन शृङ्खला',
    suiteHub: 'अवलोकन केन्द्र',
    suiteNeuro: 'ओपन न्यूरो र एआई सुइट ↗',
    brandScope: '७-दिने जोखिम अवलोकन',
    brandSub: 'खुला तथ्याङ्क बहु-प्रकोप मूल्याङ्कन — हिमताल · नदी बाढी · भूकम्प · पहिरो · शृङ्खला · SAR EO',
    btnRefreshLive: '↻ प्रत्यक्ष ताजा',
    btnRefreshing: '↻ ताजा हुँदै…',
    btnSourceHealth: 'स्रोत स्वास्थ्य',
    btnKpi: 'सारांश',
    btnTheme: '◐ थिम',
    btnLang: 'English',
    btnEmergency: 'आपतकालीन · Emergency',

    safetyTag: 'आधिकारिक पूर्वचेतावनी प्रणाली होइन',
    safetyEn: 'त्राय (TRĀYA) ७-दिने खुला तथ्याङ्कमा आधारित बहु-प्रकोप जोखिम अवलोकन तथा प्रारम्भिक मूल्याङ्कन प्लेटफर्म हो — आधिकारिक पूर्वचेतावनीका लागि जल तथा मौसम विज्ञान विभाग (DHM), राष्ट्रिय भूकम्प मापन केन्द्र (NEMRC) र NDRRMA हेर्नुहोस्।',
    safetyConsult: 'आधिकारिक सूचना:',

    staleExpiredTitle: 'म्याद सकिएको पूर्वानुमान / पुरानो साप्ताहिक तथ्याङ्क:',
    staleRefreshCta: 'अहिले प्रत्यक्ष तथ्याङ्क ताजा गर्नुहोस्',
    compoundTitle: 'संयुक्त प्रकोप सचेतना:',

    kpiLakesLbl: 'हिमताल मूल्याङ्कन',
    kpiLakesSub: 'PFV ≥ १० Mm³ प्राथमिकता सूची (Fujita 2013)',
    kpiRiversLbl: 'नदी बाढी निगरानी (GloFAS)',
    kpiRiversSub: '१० प्रमुख नदी प्रवाह र पुनरावृत्ति स्तर',
    kpiLsLbl: 'वर्षा–पहिरो निगरानी',
    kpiLsSub: 'दाहाल र हासेगावा (२००८) वर्षा सीमा',
    kpiEqLbl: 'आधिकारिक सूचना र भूकम्प',
    kpiEqSub: 'NDRRMA BIPAD · USGS प्रत्यक्ष + GEM फल्ट',
    kpiSatLbl: 'हिममण्डल र SAR / S2 EO',
    kpiSatSub: '० °C हिउँरेखा · सेन्टिनेल-१ SAR र S2',
    kpiCascLbl: 'शृङ्खला र विच्छेद',
    kpiCascSub: '१ कि.मि. करिडोर · अस्पताल पहुँच · छो रोल्पा',
    kpiValLbl: 'प्रमाणीकरण र ७-दिने चक्र',
    kpiValSub: 'प्रारम्भिक मूल्याङ्कन — आधिकारिक चेतावनी होइन',

    mobDetail: 'विवरण',
    mobControls: 'फिल्टर',
    mobBottom: 'तालिका',
    mobKpis: 'सारांश',

    triageTitle: 'मेरो जिल्ला · My District',
    triageAllDistricts: 'नेपालका ७७ मध्ये कुनै जिल्ला छान्नुहोस्…',
    triageSearchPh: 'जिल्ला खोज्नुहोस् (जस्तै: काठमाडौँ, चितवन, हुम्ला)…',
    triageNearMe: '◎ मेरो स्थान',
    triageNearMeBusy: 'स्थान खोजिँदै…',
    triageClear: 'हटाउनुहोस्',
    triageGeoUnsupported: 'यस उपकरणमा स्थान (Geolocation) सुविधा उपलब्ध छैन।',
    triageGeoDenied: 'स्थान अनुमति अस्वीकृत वा अनुपलब्ध भयो। कृपया माथिबाट जिल्ला छान्नुहोस्।',
    triageOutsideNepal: 'तपाईँको स्थान नेपाल बाहिर देखिन्छ; सबैभन्दा नजिकको नेपाली जिल्ला देखाइएको छ:',

    secColourBy: 'हिमताल रङको आधार',
    secFilters: 'हिमताल फिल्टर',
    btnReset: 'रिसेट',
    fPriority: 'प्राथमिकता हिमताल मात्र (PFV ≥ १० Mm³)',
    fOnlyRouted: 'तल्लो तटीय मार्ग भएका (६९७)',
    fAva: 'हिमपहिरो तालसम्म पुग्न सक्ने',
    fSla: 'भिरालो ताल किनार (SLA > १०°)',
    fIce: 'बरफ-युक्त मोरेन प्रमाणित',
    fContact: 'हिमनदी सिधा सम्पर्कमा रहेको',
    fPast: 'विगतमा हिमताल विस्फोट भएको',
    fAllProvs: 'सबै ७ प्रदेश',
    fMinArea: 'न्यूनतम ताल क्षेत्रफल:',
    fSearchPh: 'हिमताल, जिल्ला, RGI खोज्नुहोस्… (/)',
    secLayers: 'बहु-प्रकोप तहहरू',
    lLakes: 'हिमतालहरू (१,४२९)',
    lRoute: 'छानिएको बाढी मार्ग र दूरी',
    lExp: 'मार्ग वरपरको जोखिम क्षेत्र',
    lRivers: 'GloFAS नदी केन्द्रहरू (१०)',
    lFaults: 'सक्रिय सतही फल्टहरू (GEM)',
    lNodes: 'वर्षा–पहिरो केन्द्रहरू (२४)',
    lLandslides: 'पहिरो सूची (५-प्रकार)',
    lEq: 'प्रत्यक्ष भूकम्प (USGS)',
    lMmi: 'ShakeMap कम्पन रेखाहरू',
    lEqHist: 'ऐतिहासिक भूकम्प M≥६',
    lGlof: 'अभिलेखित हिमताल विस्फोट',
    lHydro: 'जलविद्युत आयोजनाहरू (OSM)',
    lGdacs: 'GDACS क्षेत्रीय सूचना',

    secGibs: 'NASA GIBS भू-उपग्रह तह',
    gibsNone: 'भू-उपग्रह तह बन्द',
    gibsImerg: 'GPM IMERG वर्षा दर',
    gibsSnow: 'MODIS हिउँ आवरण (NDSI)',
    gibsViirs: 'VIIRS दैनिक वास्तविक रङ',
    gibsNote: 'निःशुल्क NASA EOSDIS WMTS तह। आजको चित्र तयार नभए २–३ दिन अघिको मिति छान्नुहोस्।',
    secEqWin: 'प्रत्यक्ष भूकम्प अवधि',
    eqWinDay: 'पछिल्लो २४ घण्टा (M≥२.०)',
    eqWinWeek: 'पछिल्लो ७ दिन (M≥२.५)',
    eqWinMonth: 'पछिल्लो ३० दिन (M≥३.५)',
    secScope: 'वैज्ञानिक दायरा',
    scopeBody1: 'त्रायले नेपालका ७७ वटै जिल्लामा १,४२९ हिमताल, १० प्रमुख नदी, ७० सक्रिय सतही फल्ट र २४ वर्षा केन्द्रहरूको खुला तथ्याङ्कबाट प्रारम्भिक मूल्याङ्कन गर्दछ।',
    scopeBody2: 'यो आधिकारिक पूर्वचेतावनी प्रणाली होइन। आधिकारिक सूचनाका लागि सधैँ DHM, DMG/NEMRC र NDRRMA का बुलेटिन हेर्नुहोस्।',

    hudControls: '☰ नियन्त्रण',
    hudInspector: 'विवरण ▤',
    regAll: 'सम्पूर्ण नेपाल',
    regKhumbu: 'खुम्बु',
    regRolwaling: 'रोल्वालिङ',
    regBarun: 'बरुण',
    regAnnapurna: 'अन्नपूर्ण–मनास्लु',
    regLangtang: 'लाङटाङ',
    regKarnali: 'कर्णाली',

    tabWatch: 'हिमतालहरू',
    tabFloods: 'नदी बाढी (GloFAS)',
    tabLandslides: 'पहिरो निगरानी',
    tabCascades: 'शृङ्खला र विच्छेद',
    tabLive: 'आधिकारिक सूचना र भूकम्प',
    tabSat: 'भू-उपग्रह र SAR EO',
    tabGlof: 'ऐतिहासिक विस्फोट',
    tabCharts: 'विश्लेषण',
    tabValid: 'प्रमाणीकरण र सीमा',
    tabMethods: 'विधि र सन्दर्भ',

    tierVeryHigh: 'अति उच्च',
    tierHigh: 'उच्च',
    tierModerate: 'मध्यम',
    tierLow: 'न्यून',
    tierNa: 'मूल्याङ्कन नभएको',

    riverNormal: 'सामान्य',
    riverElevated: 'बढेको (>Q90)',
    riverWatch: 'सतर्कता (≥Q2)',
    riverWarning: 'चेतावनी (≥Q5)',
    riverSevere: 'गम्भीर बाढी (≥Q20)',
    riverUnassessed: 'मूल्याङ्कन बाँकी',

    dhLow: 'न्यून',
    dhElevated: 'मध्यम-उच्च',
    dhWatch: 'सतर्कता',
    dhExceeded: 'सीमा नाघेको',

    emergTitle: 'नेपाल आपतकालीन नम्बर र आधिकारिक निकायहरू',
    emergClose: 'बन्द गर्नुहोस्',
    emergSubtitle: 'त्राय (TRĀYA) अनुसन्धान र प्रारम्भिक मूल्याङ्कन प्लेटफर्म हो, आधिकारिक पूर्वचेतावनी प्रणाली होइन। आपतकालीन अवस्थामा सिधै आधिकारिक सेवामा सम्पर्क गर्नुहोस्:',
    emergHotlinesHead: '१-ट्याप नेपाल आपतकालीन नम्बरहरू',
    emergAgenciesHead: 'आधिकारिक सरकारी पोर्टल र प्रत्यक्ष सेवा',
    emergPrepHead: 'सरल पूर्वतयारी सुझावहरू',
    emergPrep1: 'हिमताल विस्फोट / आकस्मिक बाढी: नदी अचानक धमिलो भएमा, अनौठो आवाज आएमा वा पानी एक्कासी घटेमा तुरुन्तै खोलाको किनार छाडेर अग्लो सुरक्षित स्थानमा जानुहोस्।',
    emergPrep2: 'भूकम्प: कम्पन हुँदा झुक्नुहोस्, सुरक्षित आडमा लुक्नुहोस् र बलियोसँग समात्नुहोस्। ठुलो भूकम्प (M≥५) पछि परकम्प, पहिरो र नदी बहावमा अचानक परिवर्तनप्रति सचेत रहनुहोस्।',
    emergPrep3: 'वर्षात् र पहिरो: २४–७२ घण्टा लगातार भारी वर्षा भएमा जमिनमा चिरा पर्ने, रूख ढल्किने वा मूलको पानी धमिलो हुने लक्षण देखिए तुरुन्त सुरक्षित स्थानमा सर्नुहोस्।',

    distBriefTitle: 'जिल्ला बहु-प्रकोप सारांश',
    distRiverSec: 'नजिकको GloFAS नदी बेसिन',
    distRainSec: 'नजिकको वर्षा–पहिरो केन्द्र',
    distEqSec: 'हालका USGS भूकम्प (≤१०० कि.मि.)',
    distLakeSec: 'हिमताल र तल्लो तटीय बाढी मार्ग',
    distGdacsSec: 'GDACS क्षेत्रीय सूचना',
    distInspectRiver: '६०-दिने बहाव हेर्नुहोस्',
    distInspectNode: 'वर्षा केन्द्र हेर्नुहोस्',
    distFilterLakes: 'यस जिल्लाका हिमताल छान्नुहोस्',
    distNoLakesInside: 'यस जिल्लाभित्र कुनै हिमताल छैन। यहाँको मुख्य जोखिम नदी बाढी, वर्षाजन्य पहिरो, भूकम्प र तल उल्लिखित माथिल्लो तटीय हिमताल बाढी मार्गबाट रहन्छ।',
    distNoEq100: 'छानिएको अवधिमा १०० कि.मि. भित्र कुनै प्रत्यक्ष USGS भूकम्प अभिलेख छैन।',

    liveSnapshot: 'साप्ताहिक',
    liveFresh: 'प्रत्यक्ष',
    liveStale: 'पुरानो',
    liveOffline: 'अफलाइन',
    unknownVal: 'अज्ञात',
    coolrZeroNotice: 'तथ्याङ्क दायरा सूचना: हाल ० NASA COOLR अभिलेख लोड भएको छ (माथिल्लो स्रोत उपलब्ध नभएको)। मिति नखुलेका {n} OpenStreetMap पहिरो चिन्ह मात्र देखाइएको छ — चिन्ह नहुनुको अर्थ पहिरो जोखिम कम हुनु होइन।',
    gridSnapNotice: '१० मध्ये {n} साप्ताहिक GloFAS केन्द्रहरूमा ग्रिड-स्न्याप चेतावनी (⚠) छ। प्रत्यक्ष ताजा गरेपछि वा नेपाल DHM (hydrology.gov.np) बाट आधिकारिक नदी सतह अनिवार्य जाँच गर्नुहोस्।',

    /* TRĀYA 2.0 स्रोत स्वास्थ्य र ६-अवस्था तथ्याङ्क वर्गीकरण */
    shTitle: 'स्रोत स्वास्थ्य, तथ्याङ्क उत्पत्ति र KPI स्कोरकार्ड',
    shSubtitle: '६-अवस्था तथ्याङ्क वर्गीकरण, SLA ताजापन (NPT), विकल्प पारदर्शिता र इजाजतपत्र विवरण',
    shLoading: 'तथ्याङ्क उत्पत्ति म्यानिफेस्ट र KPI आधार लोड हुँदै…',
    shOverallHealth: 'समग्र फिड स्वास्थ्य',
    shHealthHealthy: 'स्वस्थ',
    shHealthDegraded: 'आंशिक',
    shHealthStale: 'पुरानो',
    shKpiFreshness: 'फिड ताजापन (SLA)',
    shKpiProvenance: 'उत्पत्ति पूर्णता',
    shKpiLandslide: 'पहिरो सूची परिपक्वता',
    shKpiExposure: 'जोखिम र शृङ्खला दायरा',
    shColDataset: 'स्रोत / डेटासेट',
    shColClass: 'तथ्याङ्क वर्ग',
    shColUpdated: 'अद्यावधिक (NPT)',
    shColSla: 'SLA स्थिति',
    shColFallback: 'प्राप्ति विधि',
    shColRecords: 'अभिलेख',
    shColLicense: 'इजाजतपत्र',
    shDirect: 'प्रत्यक्ष',
    shFallback: 'वैकल्पिक',
    shMouRequired: 'सम्झौता आवश्यक',
    shViewLicenses: 'DATA_LICENSES.md ↗',
    dcLiveObservation: 'प्रत्यक्ष अवलोकन',
    dcForecast: 'पूर्वानुमान',
    dcHistorical: 'ऐतिहासिक',
    dcStaticAssessment: 'स्थिर मूल्याङ्कन',
    dcCached: 'सञ्चित (Cached)',
    dcUnavailable: 'अनुपलब्ध',
    slaAvailable: 'उपलब्ध',
    slaStale: 'पुरानो',
    slaUnavailable: 'अनुपलब्ध',

    /* आधिकारिक नेपाल सरकारी निकाय फिड (BIPAD · DHM · NSC) */
    officialLaneTitle: 'आधिकारिक नेपाल सरकारी निकाय फिड (NDRRMA BIPAD · DHM · NSC)',
    officialBadge: 'आधिकारिक अवलोकन',
    modelledBadge: 'मोडेल पूर्वानुमान',
    screeningBadge: 'प्रारम्भिक मूल्याङ्कन तह',
    officialNotice: 'नेपाल सरकार NDRRMA/BIPAD का आधिकारिक अभिलेख — मोडेल पूर्वानुमानबाट संरचनात्मक रूपमा अलग राखिएको।',
    bipadAwaitingRefresh: 'BIPAD स्न्यापसट आगामी प्रत्यक्ष अद्यावधिकको प्रतीक्षामा छ',
    bipadAlertsHead: 'प्रमाणित BIPAD चेतावनीहरू',
    bipadRiversHead: 'DHM नदी गेज (BIPAD मार्फत)',
    bipadRainHead: 'DHM वर्षा गेज (BIPAD मार्फत)',
    bipadEqHead: 'राष्ट्रिय भूकम्प मापन केन्द्र (NSC) भूकम्प',
    bipadLsHead: 'प्रमाणित BIPAD पहिरो घटनाहरू',
    openDataSeismicHead: 'खुला तथ्याङ्क भूकम्प र फल्ट मूल्याङ्कन (USGS FDSN · GEM सतही फल्ट)',

    /* शृङ्खला र विच्छेद ट्याब */
    cascGraphTitle: 'व्याख्यात्मक बहु-प्रकोप शृङ्खला ग्राफ',
    cascInspectorTitle: 'नियम र प्रमाण निरीक्षक',
    cascClickHint: 'कुनै पनि बिन्दु वा नियम रेखामा क्लिक गरी भौतिक नियम, प्रमाण स्तर, विश्वास तह र अनिश्चितता हेर्नुहोस्।',
    cascScenariosTitle: 'बहु-प्रकोप शृङ्खला मार्ग र सक्रिय परिदृश्यहरू',
    evObserved: 'अवलोकित',
    evForecast: 'पूर्वानुमानित',
    evModelled: 'मोडेल गरिएको',
    isoSectionTitle: 'तल्लो तटीय जोखिम र सडक-विच्छेद अस्पताल पहुँच अवरोध',
    isoCorridorBadge: '१ कि.मि. प्रारम्भिक खोज करिडोर — २डी जलप्रवाह डुबान सीमा होइन',
    isoTabLakes: 'प्राथमिकता हिमताल करिडोर',
    isoTabDistricts: 'सबै ७७ जिल्ला (विच्छेद जोखिम)',
    pilotTitle: 'छो रोल्पा २डी जलप्रवाह पाइलट बेन्चमार्क (TRAYA-011)',
    pilotBadge: 'पूर्व-सिमुलेसन सन्दर्भ ढाँचा — २डी डुबान नक्सा अझै होइन',
    pilotStudyPlanLink: 'छो रोल्पा २डी अध्ययन योजना पढ्नुहोस् (docs/TSHO_ROLPA_2D_STUDY_PLAN.md) ↗',
    pilotFlyLake: 'नक्सामा छो रोल्पा हेर्नुहोस्',

    /* ५-प्रकार पहिरो सूची र दोहोरो समीक्षा पङ्क्ति */
    lsTypeAll: 'सबै अभिलेख',
    lsTypeEvent: 'मिति प्रमाणित घटना (BIPAD/COOLR)',
    lsTypeScar: 'मिति नखुलेका OSM दाग',
    lsTypeSuscept: 'संवेदनशीलता क्षेत्र',
    lsTypeReport: 'प्रकोप प्रतिवेदन',
    lsTypeCoseismic: 'भूकम्प-प्रेरित पहिरो',
    lsDownloadGeojson: '⬇ landslide_inventory.geojson डाउनलोड (RFC 7946)',
    lsReviewQueueTitle: 'सम्भावित दोहोरो अभिलेख समीक्षा पङ्क्ति',
    lsReviewPolicyBadge: 'झण्डा मात्र · स्वतः विलय नगरिने',
    lsReviewEmpty: 'जाँच गरिएका {n} अभिलेखमध्ये हाल ० सम्भावित दोहोरो जोडी भेटिएका छन्। प्रत्यक्ष BIPAD/COOLR अभिलेख लोड भएपछि मिल्दाजुल्दा जोडी मानवीय समीक्षाका लागि यहाँ सूचीबद्ध हुन्छन्।',

    /* सेन्टिनेल-१ SAR मनसुन राडार */
    sarSectionTitle: 'सेन्टिनेल-१ SAR — सबै मौसमको मनसुन राडार (प्राथमिकता हिमताल)',
    sarRadarBadge: 'बादल छेड्ने सबै-मौसम C-ब्यान्ड SAR राडार (IW VV/VH)',
    sarAwaitingLive: 'प्रत्यक्ष सेन्टिनेल-१ STAC अद्यावधिकको प्रतीक्षामा',
    sarOpenBrowser: 'S1 SAR खोल्नुहोस् ↗',
    sarOpenS2: 'S2 खोल्नुहोस् ↗',
  },
};

let currentLang = 'en';

export function initLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'en' || saved === 'ne') currentLang = saved;
  } catch {
    // ignore storage errors
  }
  document.documentElement.lang = currentLang;
  return currentLang;
}

export function getLang() {
  return currentLang;
}

export function setLang(lang) {
  currentLang = lang === 'ne' ? 'ne' : 'en';
  document.documentElement.lang = currentLang;
  try {
    localStorage.setItem(STORAGE_KEY, currentLang);
  } catch {
    // ignore storage errors
  }
  return currentLang;
}

export function t(key, params) {
  const table = DICT[currentLang] || DICT.en;
  let str = Object.prototype.hasOwnProperty.call(table, key)
    ? table[key]
    : (DICT.en[key] || key);
  if (params) {
    Object.keys(params).forEach(k => {
      str = str.replaceAll(`{${k}}`, String(params[k]));
    });
  }
  return str;
}

export function tTier(tier) {
  const k = String(tier || '').toLowerCase();
  if (k === 'very high') return t('tierVeryHigh');
  if (k === 'high') return t('tierHigh');
  if (k === 'moderate') return t('tierModerate');
  if (k === 'low') return t('tierLow');
  return t('tierNa');
}

export function tRiverStatus(st) {
  const k = String(st || 'normal').toLowerCase();
  if (k === 'q20_severe' || k === 'severe') return t('riverSevere');
  if (k === 'q5_warning' || k === 'warning') return t('riverWarning');
  if (k === 'q2_watch' || k === 'watch') return t('riverWatch');
  if (k === 'elevated') return t('riverElevated');
  if (k === 'unassessed') return t('riverUnassessed');
  return t('riverNormal');
}

export function tDhLevel(lv) {
  const k = String(lv || 'low').toLowerCase();
  if (k === 'exceeded') return t('dhExceeded');
  if (k === 'watch') return t('dhWatch');
  if (k === 'elevated') return t('dhElevated');
  return t('dhLow');
}

export function tDataClass(dc) {
  const k = String(dc || 'unavailable').toLowerCase();
  if (k === 'live_observation') return t('dcLiveObservation');
  if (k === 'forecast') return t('dcForecast');
  if (k === 'historical') return t('dcHistorical');
  if (k === 'static_assessment') return t('dcStaticAssessment');
  if (k === 'cached') return t('dcCached');
  return t('dcUnavailable');
}

export function tSlaStatus(st) {
  const k = String(st || 'unavailable').toLowerCase();
  if (k === 'available') return t('slaAvailable');
  if (k === 'stale') return t('slaStale');
  return t('slaUnavailable');
}

export function tHealthState(h) {
  const k = String(h || 'degraded').toLowerCase();
  if (k === 'healthy') return t('shHealthHealthy');
  if (k === 'stale') return t('shHealthStale');
  return t('shHealthDegraded');
}

export function tEvidenceType(ev) {
  const k = String(ev || 'modelled_static').toLowerCase();
  if (k === 'observed') return t('evObserved');
  if (k === 'forecast') return t('evForecast');
  return t('evModelled');
}

export function tLandslideType(ft) {
  const k = String(ft || '').toLowerCase();
  if (k === 'landslide_event') return t('lsTypeEvent');
  if (k === 'landslide_scar') return t('lsTypeScar');
  if (k === 'susceptibility_zone') return t('lsTypeSuscept');
  if (k === 'hazard_report') return t('lsTypeReport');
  if (k === 'coseismic_failure') return t('lsTypeCoseismic');
  return t('lsTypeAll');
}

export function tProvince(prov, districtsMeta) {
  if (!prov) return '—';
  if (currentLang !== 'ne') return prov;
  if (districtsMeta && Array.isArray(districtsMeta.provinces)) {
    const match = districtsMeta.provinces.find(p => p.name === prov);
    if (match && match.name_ne) return match.name_ne;
  }
  return PROVINCE_NE[prov] || prov;
}

export function tDistrict(name, districtsMeta) {
  if (!name) return '—';
  if (currentLang !== 'ne') return name;
  if (districtsMeta && Array.isArray(districtsMeta.districts)) {
    const match = districtsMeta.districts.find(d => d.name === name);
    if (match && match.name_ne) return match.name_ne;
  }
  return name;
}

export function applyStaticTranslations(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key) el.textContent = t(key);
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key) el.setAttribute('placeholder', t(key));
  });
  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (key) el.setAttribute('title', t(key));
  });
  root.querySelectorAll('[data-i18n-aria]').forEach(el => {
    const key = el.getAttribute('data-i18n-aria');
    if (key) el.setAttribute('aria-label', t(key));
  });
  // Hide the companion static Nepali notice in Nepali mode so the banner never
  // displays two duplicate Nepali disclaimers side by side.
  root.querySelectorAll('.safety-ne').forEach(el => {
    el.hidden = currentLang === 'ne';
  });
}
