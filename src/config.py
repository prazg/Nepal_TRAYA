"""
Configuration and provenance for the Nepal Multi-Hazard Early Warning System.

Every numeric threshold and empirical relation used anywhere in this pipeline is
declared here with its source, so that the scientific basis of the outputs can be
audited from one file.

Nothing in this file is tuned or fitted by us. Values are as published.
"""
from __future__ import annotations
import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Everything lives under the repository, so a fresh clone plus fetch_inputs.py
# reproduces the build without depending on anything outside it.
RAW = os.environ.get("EWS_RAW", os.path.join(ROOT, "raw"))
DEM_DIR = os.path.join(RAW, "dem")
DATA = os.path.join(ROOT, "data")
CACHE = os.environ.get("EWS_CACHE", os.path.join(ROOT, "cache"))
LIT = os.path.join(ROOT, "lit")      # published data behind the fitted models
WORK = ROOT                          # retained for backwards compatibility

# ---------------------------------------------------------------------------
# Study area
# ---------------------------------------------------------------------------
NEPAL_BBOX = (79.9, 26.2, 88.3, 30.6)      # lon_min, lat_min, lon_max, lat_max

# ---------------------------------------------------------------------------
# GLOF: mass-movement source areas and runout
#   Rounce, D.R., McKinney, D.C., Lala, J.M., Byers, A.C., Watson, C.S. (2016)
#   "A new remote hazard and risk assessment framework for glacial lakes in the
#   Nepal Himalaya", Hydrol. Earth Syst. Sci. 20, 3455-3475.
#   doi:10.5194/hess-20-3455-2016
# Primary sources for the individual thresholds are named per entry.
# ---------------------------------------------------------------------------
AVALANCHE_SLOPE_MIN = 45.0    # deg, glacierised terrain; Alean (1985)
AVALANCHE_SLOPE_MAX = 60.0    # deg, mass unlikely to accumulate; Osti et al. (2011), Shea et al. (2015)
ROCKFALL_SLOPE_MIN = 30.0     # deg, non-glacierised terrain; Bolch et al. (2011)

# Average trajectory slope (reach angle / Fahrboeschung) runout thresholds
REACH_ANGLE_AVALANCHE = 17.0  # deg, large ice avalanches
REACH_ANGLE_ROCKFALL = 20.0   # deg

# Volume-dependent reach angle for avalanches below 6.67e6 m3:
#   tan(alpha) = 1.111 - 0.118 * log10(V)
#   Huggel, C., Haeberli, W., Kaeaeb, A., Bieri, D., Richardson, S. (2004)
#   'An assessment procedure for glacial hazards in the Swiss Alps',
#   Can. Geotech. J. 41(6), 1068-1083, doi:10.1139/T04-053
#   (this is Rounce et al.'s 'Huggel et al. 2004b', their Eq. 1 -- note it is NOT
#    the Kolka/Karmadon NHESS paper, which is Huggel et al. 2005)
HUGGEL_A = 1.111
HUGGEL_B = 0.118
HUGGEL_V_LIMIT = 6.67e6       # m3; above this the fixed 17 deg threshold applies

# Assumed avalanche release depths (m); Rounce et al. (2016) after Huggel et al.
# (2004, Can. Geotech. J.) and Huggel et al. (2005, NHESS 5, 173-187,
# doi:10.5194/nhess-5-173-2005, the Kolka/Karmadon rock/ice avalanche)
AVALANCHE_DEPTHS_M = (10.0, 30.0, 50.0)

# ---------------------------------------------------------------------------
# GLOF: moraine self-destruction
#   Steep Lakefront Area (SLA): mean slope between the lake and any point within
#   1000 m of the moraine. Lakes with SLA < 10 deg were not observed to fail.
#   Fujita, K. et al. (2013), via Rounce et al. (2016) Sect. 4.1.3
# ---------------------------------------------------------------------------
# Fujita et al. (2013) examine all terrain within 1000 m of the lake, with no
# inner exclusion; Rounce et al. (2016) additionally buffered the first 100 m to
# suppress ASTER GDEM artefacts between adjacent cells. We follow Fujita and
# instead require a contiguous patch of at least 4 cells, which serves the same
# purpose on the Copernicus DEM. sensitivity.py quantifies the difference.
SLA_BUFFER_INNER_M = 0.0
SLA_BUFFER_OUTER_M = 1000.0
SLA_MIN_PATCH_CELLS = 4
SLA_THRESHOLD_DEG = 10.0
HP_SEARCH_MAX_M = 300.0       # upper bound of the Hp bisection; PFV uses min[Hp, Dm]
                              # so a capped Hp does not distort PFV, but is flagged

# Fujita et al. (2013) identified 49 lakes across the Himalaya with a potential
# flood volume above 10 million m3, "a comparable volume to that of recorded
# major GLOFs", and propose PFV as the screening metric for prioritising which
# lakes need detailed investigation. We use the same threshold for triage.
PFV_PRIORITY_M3 = 10.0e6
PFV_REPORTED_UNCERTAINTY = 0.26   # Fujita et al. (2013): PFV uncertainty ~26%

# ---------------------------------------------------------------------------
# GLOF magnitude: lake depth, volume, peak discharge
#   Veh, G., Korup, O., Walz, A. (2020) "Hazard from Himalayan glacier lake
#   outburst floods", PNAS 117(2), 907-912. doi:10.1073/pnas.1914898117
#   Supplementary data (CC-BY-4.0): doi:10.5281/zenodo.3523213
#   Code (GPL-3): https://github.com/geveh/GLOFhazard
#
#   depth:  log10(d) = beta0 + beta1 * log10(A)     (24 bathymetric surveys, Himalaya)
#   volume: half-ellipsoid, V = (2/3) * A * d
#   Qp:     Walder & O'Connor (1997) dimensionless formulation, piecewise
#           regression on 63 natural dam breaks (O'Connor & Beebee, 2009)
# ---------------------------------------------------------------------------
G = 9.81                      # m s-2, as used in the original scripts
STUDENT_T_NU = 10             # robust noise dof, as in Veh et al. (2020)

# Breach rates k (m s-1) reported for natural dam failures,
# O'Connor & Beebee (2009) pp. 148-162, as compiled by Veh et al. (2020).
PUBLISHED_BREACH_RATES = (
    3.7e-4, 1.4e-3, 1.9e-3, 1.11e-2, 1.5e-3, 2.54e-2, 6.0e-4, 2.5e-2,
    3.4e-3, 1.13e-2, 1.7e-3, 2.2e-3, 2.5e-3, 3.2e-3, 1.1e-1, 3.8e-3,
    4.3e-3, 3.17e-2, 3.7e-4,
)
# Veh et al. allow twice the largest documented rate to admit unobserved mechanisms
BREACH_RATE_MAX_FACTOR = 2.0

# Breach-depth scenarios as a fraction of total lake depth
BREACH_FRACTIONS = (0.10, 0.30, 0.50, 1.00)

MIN_LAKE_AREA_KM2 = 0.01      # Veh et al. (2020) discard lakes below this area

# ---------------------------------------------------------------------------
# Downstream propagation
#   Observed mean surge-front velocity for the 1985 Dig Tsho GLOF was 4-5 m s-1
#   (Vuichard, D. & Zimmermann, M., 1987, Mt. Res. Dev. 7(2), 91-110, as reported
#   by Bajracharya, S.R. & Mool, P., 2009, Ann. Glaciol. 50(53), 81-86).
#   We propagate a bracketing range rather than a single value; these are
#   first-order travel-time estimates, not hydrodynamic simulations.
# ---------------------------------------------------------------------------
FRONT_VELOCITY_MS = (2.0, 5.0, 10.0)     # slow / observed / fast bracket
ROUTING_MAX_DISTANCE_KM = 120.0          # beyond ~60-120 km downstream effects diminish
                                         # (Vuichard & Zimmermann, 1987, via Rounce et al. 2016)
EXPOSURE_CORRIDOR_M = 1000.0             # search radius around the routed channel

# ---------------------------------------------------------------------------
# Seismic
#   No triggering model is fitted here. The live layer consumes the USGS
#   ShakeMap and ground-failure products directly; the catalogue below supplies
#   descriptive statistics of observed seismicity near each lake.
# ---------------------------------------------------------------------------
EQ_CATALOGUE_START = "1900-01-01"
EQ_CATALOGUE_MIN_MAG = 4.0
USGS_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# Live browser feeds (verified to send Access-Control-Allow-Origin: *)
USGS_LIVE_FEEDS = {
    "hour": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
    "day": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
    "week": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
    "month": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson",
}
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# ---------------------------------------------------------------------------
# Data sources, for the provenance panel in the dashboard
# ---------------------------------------------------------------------------
SOURCES = [
    dict(name="Copernicus DEM GLO-30", detail="30 m global DEM, 1x1 deg COG tiles",
         url="https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
         licence="Copernicus DEM licence (free use with attribution)"),
    dict(name="Nepal Cryosphere Inventory", detail="1,429 glacial lakes and 4,679 RGI 7.0 glacier outlines for Nepal",
         url="https://prazg.github.io/Nepal_Cryosphere_Inventory/", licence="derived from RGI 7.0 (CC-BY-4.0) and published lake inventories"),
    dict(name="HMAGLOFDB v4.0", detail="ICIMOD High Mountain Asia GLOF database, 766 records",
         url="https://rds.icimod.org/", licence="ICIMOD terms"),
    dict(name="HydroRIVERS v1.0", detail="river network with downstream topology",
         url="https://www.hydrosheds.org/products/hydrorivers", licence="HydroSHEDS licence (free for non-commercial use)"),
    dict(name="OpenStreetMap", detail="settlements, hospitals, hydropower, bridges (via Overpass)",
         url="https://www.openstreetmap.org/copyright", licence="ODbL 1.0"),
    dict(name="USGS earthquake catalogue and real-time feeds", detail="FDSN event service and GeoJSON summary feeds",
         url="https://earthquake.usgs.gov/", licence="public domain"),
    dict(name="Esri ArcGIS Online basemaps",
         detail="World Dark Gray Base, World Hillshade and World Imagery tiles, used keyless with attribution",
         url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
         licence="Esri terms of use; free with attribution, confirm before commercial or high-traffic deployment"),
    dict(name="OpenTopoMap", detail="alternative topographic basemap",
         url="https://opentopomap.org/", licence="map style CC-BY-SA 3.0; data ODbL 1.0"),
    dict(name="Open-Meteo", detail="past and forecast precipitation",
         url="https://open-meteo.com/", licence="CC-BY-4.0"),
    dict(name="Veh, Korup & Walz (2020) supplementary data", detail="lake depth-area bathymetry sample and natural dam-break compilation",
         url="https://doi.org/10.5281/zenodo.3523213", licence="CC-BY-4.0"),
]
