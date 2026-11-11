"""Mobile-game A/B test on D1/D7 retention (real Cookie Cats data, 90,189 players).

Test: the first progress gate moved from level 30 (control) to level 40 (treatment).
Checks: sample-ratio mismatch, retention lift with Wilson CIs, two-proportion z-test,
bootstrap CI on the D7 difference, minimum detectable effect, engagement (game rounds).
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_game" / "cookie_cats.csv"


def wilson(k, n, z=1.96):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def two_prop_z(k1, n1, k2, n2):
    p = (k1 + k2) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (k2 / n2 - k1 / n1) / se
    return z, 2 * stats.norm.sf(abs(z))


def mde(p, n1, n2, alpha=0.05, power=0.8):
    return (stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)) * np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))


def analyze(df: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    df = df.copy()
    for c in ("retention_1", "retention_7"):
        df[c] = df[c].astype(str).str.lower().eq("true") if df[c].dtype == object else df[c].astype(bool)
    a, b = df[df.version == "gate_30"], df[df.version == "gate_40"]
    n_a, n_b = len(a), len(b)
    srm_p = stats.chisquare([n_a, n_b]).pvalue
    out = {"players": len(df), "n_control": n_a, "n_treatment": n_b, "srm_p": srm_p}
    rng = np.random.default_rng(seed)
    for m in ("retention_1", "retention_7"):
        ka, kb = a[m].sum(), b[m].sum()
        z, p = two_prop_z(ka, n_a, kb, n_b)
        out[m] = {
            "control": ka / n_a, "treatment": kb / n_b, "diff_pp": (kb / n_b - ka / n_a) * 100,
            "control_ci": wilson(ka, n_a), "treatment_ci": wilson(kb, n_b), "z": z, "p": p,
            "mde_pp": mde(df[m].mean(), n_a, n_b) * 100,
        }
    ya, yb = a.retention_7.to_numpy(), b.retention_7.to_numpy()
    boots = [rng.choice(yb, n_b).mean() - rng.choice(ya, n_a).mean() for _ in range(n_boot)]
    out["retention_7"]["boot_ci_pp"] = tuple(np.percentile(boots, [2.5, 97.5]) * 100)
    out["retention_7"]["prob_control_better"] = float(np.mean(np.array(boots) < 0))
    # D7 among players who came back on D1 (where the gate change bites)
    ra, rb = a[a.retention_1], b[b.retention_1]
    z, p = two_prop_z(ra.retention_7.sum(), len(ra), rb.retention_7.sum(), len(rb))
    out["d7_given_d1"] = {"control": ra.retention_7.mean(), "treatment": rb.retention_7.mean(), "z": z, "p": p}
    out["rounds"] = {
        "median_control": float(a.sum_gamerounds.median()), "median_treatment": float(b.sum_gamerounds.median()),
        "max_rounds": int(df.sum_gamerounds.max()),
        "mann_whitney_p": float(stats.mannwhitneyu(a.sum_gamerounds, b.sum_gamerounds).pvalue),
        "zero_round_share": float((df.sum_gamerounds == 0).mean()),
    }
    return out


if __name__ == "__main__":
    import json
    d = pd.read_csv(RAW)
    r = analyze(d)
    print(json.dumps(r, indent=1, default=float))
