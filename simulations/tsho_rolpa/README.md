# Tsho Rolpa 2D Hydrodynamic HPC Reproducibility Pack (`LISFLOOD-FP v8.1` & `BASEMENT v4`)

> **Non-Operational Safety & Epistemic Notice (गैर-सञ्चालनात्मक सूचना):**
> This directory provides ready-to-run external 2D shallow-water solver templates for upgrading Nepal TRĀYA 2.0's screening-resolution (~90 m Copernicus DEM GLO-30) Tsho Rolpa GLOF simulation (`src/tsho_rolpa_2d_sim.py`) to **design-grade (`<= 2–5 m` bare-earth LiDAR / UAV DEM)** engineering runs on a workstation or HPC cluster. Outputs are research products and **NOT an operational early warning system or statutory flood-zoning map** until reviewed by **DHM** and **NDRRMA**.

---

## 1. Contents of This Pack

| File | Target Engine | Role |
| --- | --- | --- |
| `tsho_rolpa_10pct.par` | `LISFLOOD-FP v8.1` | `TR-S1-PARTIAL-10PCT` (`8.0 Mm³`, peak `1,100 m³/s`) |
| `tsho_rolpa_30pct.par` | `LISFLOOD-FP v8.1` | `TR-S2-MODERATE-30PCT` (`26.0 Mm³`, peak `5,800 m³/s`, primary Shrestha & Nakagawa 2014 benchmark) |
| `tsho_rolpa_50pct.par` | `LISFLOOD-FP v8.1` | `TR-S3-SEVERE-50PCT` (`43.0 Mm³`, peak `9,800 m³/s`) |
| `tsho_rolpa_100pct.par` | `LISFLOOD-FP v8.1` | `TR-S4-EXTREME-100PCT` (`78.0 Mm³`, peak `13,500 m³/s`, physical ceiling constrained to `80 Mm³` surveyed bathymetry) |
| `tsho_rolpa.bci` | `LISFLOOD-FP v8.1` | Boundary conditions in **EPSG:32645 (UTM Zone 45N)**: moraine outlet `QVAR`, Tama Koshi lateral baseflow `QFIX`, southern `FREE` exit below Singati |
| `tsho_rolpa_30pct.bdy` | `LISFLOOD-FP v8.1` | Exact 5-minute gamma breach inflow hydrograph (`0–19,800 s`, `26.0 Mm³`, peak `5,800 m³/s`, shape `m = 2.5`) matching `src/tsho_rolpa_2d_sim.py` |
| `basement_v4_model.json` | `BASEMENT v4` (ETH Zürich) | Unstructured 2D finite-volume `BASEplane` (`HLLC` Riemann solver) setup with spatially zoned Strickler friction and checkpoint monitoring `STRINGDEF`s |

---

## 2. Coordinate System, Boundary Locations & Roughness Zones

All spatial coordinates in `.bci` and `basement_v4_model.json` are projected in **EPSG:32645 (WGS 84 / UTM Zone 45N, metres)**:

| Feature / Checkpoint | River km | WGS 84 (Lat, Lon) | EPSG:32645 (E, N m) | Hydraulic Role |
| --- | --- | --- | --- | --- |
| Tsho Rolpa Terminal Moraine Outlet | `0.0` | `27.8696° N, 86.4621° E` | `447048.3, 3082873.6` | Upstream `QVAR` / `uniform_in` breach inflow (immediately below 2000 spillway) |
| Na Village | `6.3` | `27.8815° N, 86.4268° E` | `443579.5, 3084207.6` | Near-field alpine settlement cross-section (`cp_na`) |
| Beding Village | `12.2` | `27.9028° N, 86.3755° E` | `438541.9, 3086591.8` | Middle Rolwaling valley settlement (`cp_beding`) |
| Tama Koshi Lateral Baseflow | `~28.0` | `27.8820° N, 86.2235° E` | `423568.2, 3084373.2` | Dry-season `60 m³/s` (or monsoon `350 m³/s`) `QFIX` above Chetchet |
| Gongar & Upper Tamakoshi HPP (456 MW) Tailrace | `31.6` | `27.8459° N, 86.2178° E` | `422981.6, 3080377.7` | Confluence floodway, NH28 bridges & tailrace outfall (`cp_gongar`, `cp_upper_tamakoshi_hpp`) |
| Singati Bridge & Community Hospital | `46.3` | `27.7362° N, 86.1639° E` | `417591.5, 3068260.3` | Road-cut hospital isolation hub (`cp_singati`) |
| Southern Free-Outflow Exit | `~47.8` | `27.7238° N, 86.1575° E` | `416951.3, 3066891.0` | Open `FREE` / `zero_gradient` boundary (`lat <= 27.725° N`, `S0 = 0.015`) |

**Spatially Distributed Roughness Zones** (aligned with `src/tsho_rolpa_2d_sim.py`):
- **Zone 1 — Steep Alpine Rolwaling Gorge (`> 2,200 m a.s.l.`, channel):** Manning `n = 0.060` (Strickler `k_st = 16.67 m^(1/3)/s`)
- **Zone 2 — Tama Koshi Mainstem Channel (`<= 2,200 m a.s.l.`, channel):** Manning `n = 0.045` (Strickler `k_st = 22.22 m^(1/3)/s`)
- **Zone 3 — Valley Banks, Terraces & Overbank Floodplains:** Manning `n = 0.080` (Strickler `k_st = 12.50 m^(1/3)/s`)

---

## 3. Step-by-Step Execution with a 2–5 m LiDAR / UAV Bare-Earth DEM

### Step A — Prepare the Bare-Earth DEM & Roughness Raster
1. Acquire a `2–5 m` bare-earth DEM covering Rolwaling Khola to Singati (`E 413,000–452,000`, `N 3,066,000–3,088,000`, `EPSG:32645`), or mosaic **HMA 8 m DEM** (Shean, 2017) with Copernicus GLO-30 void-fill.
2. Perform **hydrological conditioning**: remove bridge-deck artifacts at Chetchet, Gongar, Jagat, and Singati Bridge, and verify continuous downhill thalweg connectivity through narrow canyon overhangs (`14–28 km`).
3. Reproject and export as ESRI ASCII grid (`AAIGrid`) with `NODATA_value -9999`:
   ```bash
   gdalwarp -t_srs EPSG:32645 -tr 5 5 -r bilinear -of AAIGrid \
     raw_lidar_bare_earth.tif tsho_rolpa_dem_5m_utm45n.asc
   ```
4. Generate the matching Manning roughness ASCII grid `tsho_rolpa_manning_n.asc` (same extent/resolution) using the 3 roughness zones above, or remove the `manningfile` line in `.par` to run uniform `fpfric 0.060`.

### Step B — Generate Remaining Scenario Hydrographs (`10%`, `50%`, `100%`)
`tsho_rolpa_30pct.bdy` is pre-generated for the primary benchmark (`26.0 Mm³`, `Q_p = 5,800 m³/s`). To emit matching `.bdy` tables for `10pct`, `50pct`, and `100pct` using the exact same gamma formulation (`m = 2.5`) as TRĀYA 2.0:
```bash
python -B -c "
import sys; sys.path.insert(0, '../../src')
import tsho_rolpa_2d_sim as sim
for tag, vol, qp in [('10pct', 8e6, 1100.0), ('50pct', 43e6, 9800.0), ('100pct', 78e6, 13500.0)]:
    tp, qpe, m = sim.build_gamma_hydrograph_params(vol, qp)
    with open(f'tsho_rolpa_{tag}.bdy', 'w', encoding='utf-8') as f:
        f.write(f'# Tsho Rolpa {tag} gamma breach hydrograph\nbreach_inflow\n67 seconds\n')
        for s in range(0, 19801, 300):
            f.write(f'{sim.eval_gamma_hydrograph(s, tp, qpe, m):.2f}\t{s}\n')
"
```
*Note on inflow width:* `tsho_rolpa.bci` uses a point inflow `P ... QVAR breach_inflow` (total `m³/s`). On `<= 5 m` grids, distribute inflow across a `25–50 m` spillway transect (dividing `Q(t)` by transect width in metres for `E`/`W` line `QVAR` in `m²/s`) to avoid single-cell supercritical jetting.

### Step C — Run `LISFLOOD-FP v8.1`
```bash
# Primary Shrestha & Nakagawa (2014) design-basis benchmark (CPU OpenMP or GPU CUDA):
lisflood -v tsho_rolpa_30pct.par

# Full 4-scenario ensemble:
for s in 10pct 30pct 50pct 100pct; do
    lisflood -v "tsho_rolpa_${s}.par"
done
```
*Tip:* The `.par` files default to `fv1` (first-order Godunov finite-volume shock-capturing shallow-water solver) recommended for supercritical `5–15%` gorge slopes. Replace `fv1` with `acceleration` to run a direct local-inertial parity check against `src/tsho_rolpa_2d_sim.py`.

### Step D — Cross-Validate with `BASEMENT v4` (ETH Zürich)
1. Build a quality-refined triangular `.2dm` mesh (`tsho_rolpa_2m_5m_mesh_utm45n.2dm`) from the `2–5 m` bare-earth DEM using **BASEmesh** (`3–5 m` channel thalweg/bridges/tailrace, `15–25 m` terraces, `50 m` upper canyon sidewalls) with material indices `1, 2, 3` matching `basement_v4_model.json`.
2. Convert `tsho_rolpa_30pct.bdy` to two-column `(time_s, Q_m3s)` format (`tsho_rolpa_30pct_basement_inflow.txt`, swapping column order).
3. Execute `BASEMENT v4`:
   ```bash
   BMv4_BASEplane_setup -f basement_v4_model.json
   BMv4_BASEplane_omp   -f basement_v4_model.json
   ```
4. For hyperconcentrated/debris-flow sensitivity (`B1.3` / `B1.6` per `docs/TSHO_ROLPA_2D_STUDY_PLAN.md`), enable `BASEmorph` steep-slope bedload transport (Smart & Jäggi) and/or bulked inflow hydrographs.

---

## 4. Mandatory Validation & Acceptance Gates (`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`)

Before publishing high-resolution `<= 5 m` footprints to TRĀYA or institutional portals, verify all 6 gates:
1. **Mass conservation:** Global mass-balance error `< 1.0%` across every scenario in both `LISFLOOD-FP` and `BASEMENT`.
2. **Dual-solver agreement:** Clear-water `Q_p(x)` within `±15%` and wave arrival time `t_arr(x)` within `±20%` between `LISFLOOD-FP` and `BASEMENT` from Chetchet (`28.8 km`) through Singati (`46.3 km`).
3. **Screening baseline comparison:** Compare `<= 5 m` results against TRĀYA's ~90 m screening envelope (`data/tsho_rolpa_2d_inundation.json`) and Shrestha & Nakagawa (2014).
4. **Sensitivity audit:** Document spread across `Manning n ± 25%`, dry vs. monsoon Tama Koshi baseflow (`60` vs. `350 m³/s`), and sediment bulking (`B1.0`, `B1.3`, `B1.6`).
5. **1 km screening buffer audit:** Quantify false-positive terrace settlements and false-negative OSM infrastructure gaps (Upper Tamakoshi HPP 456 MW tailrace).
6. **Statutory review:** Technical sign-off with **DHM**, **NDRRMA**, and **ICIMOD** prior to any operational or zoning use.
