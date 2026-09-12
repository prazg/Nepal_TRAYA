"""
Hazard and downstream-impact classification for glacial lakes.

Implements the classification of

    Rounce, D.R., McKinney, D.C., Lala, J.M., Byers, A.C., Watson, C.S. (2016)
    Hydrol. Earth Syst. Sci. 20, 3455-3475, doi:10.5194/hess-20-3455-2016

Figure 4 (hazard) and Table 4 (downstream impact), with one explicit gap: the
presence of buried ice in the damming moraine cannot be determined from a DEM.
Rounce et al. identified it by inspecting satellite imagery and Google Earth for
ponds on the moraine or changes in the outlet. Here, ice-cored moraines are taken
only where they are documented in the literature; for every other lake the
attribute is "not assessed", and the resulting hazard class is therefore a LOWER
BOUND for any lake that in fact has an ice core.
"""
from __future__ import annotations

# Lakes with ice-cored moraines documented in the literature.
# Source: Rounce et al. (2016) Table 5, which cites Yamada (1998),
# Richardson & Reynolds (2000), ICIMOD (2011), Watanabe (1994).
# Matched to the inventory by approximate lake centre.
DOCUMENTED_ICE_CORED = [
    # (name, lon, lat, note)
    ("Imja Tsho", 86.925, 27.899, "ponds on moraine; outlet changes (Watanabe 1994)"),
    ("Lower Barun Tsho", 87.0950, 27.7983, "ponds on moraine; outlet changes"),
    ("Thulagi Tsho", 84.487, 28.492, "ponds on moraine; outlet changes (ICIMOD 2011)"),
    ("Tsho Rolpa", 86.475, 27.868, "outlet changes; ice core known (Yamada 1998)"),
    ("Chamlang South Tsho", 86.9583, 27.7550, "ponds on moraine"),
]

ORDER = {"low": 0, "moderate": 1, "high": 2, "very high": 3}

# Lakes named in the literature, so that the well known ones are recognisable in
# the interface rather than appearing only as inventory identifiers.
# Coordinates from Rounce et al. (2016) Sect. 2 and Fujita et al. (2013) Table 2.
NAMED_LAKES = [
    ("Tsho Rolpa", 86.4770, 27.8610), ("Imja Tsho", 86.9230, 27.8990),
    ("Dig Tsho", 86.5840, 27.8750), ("Thulagi Tsho", 84.4850, 28.4880),
    ("Lower Barun Tsho", 87.0960, 27.7970), ("Lumding Tsho", 86.6150, 27.7790),
    ("Chamlang North Tsho", 86.9570, 27.7830),
    ("Chamlang South Tsho (West Chamjang)", 86.9560, 27.7540),
    ("Tam Pokhari (Sabai Tsho)", 86.8450, 27.7430),
    ("Dudh Pokhari", 86.8590, 27.6880), ("Hunku", 86.9350, 27.8370),
    ("East Hungu 1", 86.9660, 27.7990), ("East Hungu 2", 86.9740, 27.8050),
    ("Nagma Pokhari", 87.8670, 27.8700),
]


def dynamic_hazard(avalanche: bool, rockfall: bool, upstream_glof: bool) -> str:
    """Rounce et al. (2016): a snow/ice avalanche that can reach the lake is the
    highest-ranked dynamic trigger because it is the most frequent cause of
    failure in the Himalaya; rockfall or an upstream GLOF rank moderate."""
    if avalanche:
        return "high"
    if rockfall or upstream_glof:
        return "moderate"
    return "low"


def self_destructive_hazard(sla_steep: bool, ice_cored: bool | None) -> str:
    """Hydrostatic pressure (via the steep lakefront area) and buried ice.

    ice_cored None means not assessed; it is treated as absent, which makes the
    result a lower bound.
    """
    if ice_cored and sla_steep:
        return "high"
    if ice_cored:
        return "moderate"
    if sla_steep:
        return "moderate"
    return "low"


def overall_hazard(avalanche: bool, rockfall: bool, upstream_glof: bool,
                   sla_steep: bool, ice_cored: bool | None) -> str:
    """Rounce et al. (2016) Figure 4, general reading (the default here).

    AMBIGUITY IN THE SOURCE. Section 4.2 of Rounce et al. (2016) states a general
    rule and then enumerates specific paths, and for two combinations the two
    disagree. The general rule is:

        "The most dangerous situation is a glacial lake that is susceptible to
         both dynamic and self-destructive failures, which would classify the
         lake as a very high hazard. Susceptibility is defined as a hazard
         greater than low; i.e., a lake that is considered a moderate hazard for
         dynamic failure and a moderate hazard for self-destructive failure is
         still classified as very high hazard."

    The enumeration then says that "any lake with a buried ice core that is
    susceptible to a rockfall or upstream GLOF, or has a steep SLA, is
    classified as a high hazard", and that a lake without an ice core in the
    same situation is moderate. Those two combinations - rockfall with an ice
    core, and rockfall with a steep lakefront - satisfy the general rule for very
    high while the enumeration calls them high and moderate respectively.

    We cannot resolve this from the published text (Figure 4 itself is the
    authority and we only have the prose), so we implement the general rule,
    which is stated with an explicit definition and a worked example and is the
    more conservative of the two. `overall_hazard_enumerated` implements the
    other reading, and validate.py reports how many lakes are affected.
    """
    dyn = dynamic_hazard(avalanche, rockfall, upstream_glof)
    sdf = self_destructive_hazard(sla_steep, ice_cored)
    if ORDER[dyn] > 0 and ORDER[sdf] > 0:
        return "very high"
    if ORDER[dyn] > 0:
        return "high" if avalanche else "moderate"
    if ORDER[sdf] > 0:
        return "moderate"
    return "low"


def overall_hazard_enumerated(avalanche: bool, rockfall: bool, upstream_glof: bool,
                              sla_steep: bool, ice_cored: bool | None) -> str:
    """The alternative reading: the specific paths enumerated in Sect. 4.2,
    taken literally and in the order given. Used only for sensitivity analysis.
    """
    other = rockfall or upstream_glof or sla_steep
    if ice_cored and avalanche:
        return "very high"
    if avalanche:
        return "high"
    if ice_cored and other:
        return "high"
    if other:
        return "moderate"
    if ice_cored:
        return "moderate"
    return "low"


def downstream_impact(n_settlements: int, n_hydropower: int,
                      n_bridges: int, n_health: int) -> str:
    """Rounce et al. (2016) Table 4, using OpenStreetMap objects as the evidence.

    very high  lives threatened without warning AND costly infrastructure lost
    high       lives threatened without warning OR costly infrastructure lost
    moderate   disruptive damage only (bridges, trails, agriculture)
    low        no impact on people or infrastructure
    """
    lives = (n_settlements > 0) or (n_health > 0)
    costly = n_hydropower > 0
    if lives and costly:
        return "very high"
    if lives or costly:
        return "high"
    if n_bridges > 0:
        return "moderate"
    return "low"


def risk(hazard: str, impact: str) -> str:
    """Rounce et al. (2016) Figure 5, after Worni et al. (2013)."""
    h, i = ORDER[hazard], ORDER[impact]
    if h == 3 and i == 3:
        return "very high"
    if (h >= 2 and i >= 2) or (h == 3 and i >= 1) or (i == 3 and h >= 1):
        return "high"
    if (h == 1 and i == 1) or (h <= 1 and i == 2) or (i <= 1 and h == 2) \
            or (h == 0 and i == 3) or (i == 0 and h == 3):
        return "moderate"
    return "low"
