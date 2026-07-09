# Isolating a drought signal from two VOD antennas — methodology

**Script:** `dev/plot_galileo_vod_drought_diff.py`
**Context:** two antennas at the same site, each under a different tree. Lower
antenna = undisturbed reference. Upper antenna = subjected to (probable)
drought stress. Goal: isolate the part of the upper antenna's VOD signal
that's due to drought, not just "the upper antenna's tree is different."

## The problem with a plain difference

The first version of this analysis computed `reference - stressed` directly
(or `(reference - stressed) / reference`). That conflates two effects:

1. **A structural bias.** The two antennas observe different trees — different
   baseline biomass, canopy density, and geometry relative to the receiver.
   Even with zero drought stress, `stressed` would not equal `reference`.
2. **The drought signal** — the thing we actually want.

A plain difference contains both, with no way to tell them apart. Looking at
the two raw VOD timeseries side by side, they clearly share the same
*seasonal shape* (both rise through the growing season, both dip in winter)
but the stressed antenna sits systematically below the reference nearly
everywhere — that gap is (1), not (2).

## The assumption that makes separation possible

> The two trees' **relative dynamics are identical** — both respond to the
> same weather/seasonal drivers the same way — **except** for drought-induced
> vegetation water changes at the stressed antenna.

Under this assumption, the *relationship* between `reference` and `stressed`
should be a fixed, simple function of `reference` alone, as long as no drought
stress is acting. If that relationship holds, we can fit it, and whatever
doesn't fit the relationship on a given day is the drought signal.

## The model

Fit a straight line:

```
stressed(t) ≈ slope · reference(t) + intercept
```

- `slope` captures a **scale** difference between the trees (e.g. one canopy
  attenuates signal more per unit of biomass change than the other).
- `intercept` captures a fixed **offset** (e.g. different baseline biomass).
- Together, `slope · reference(t) + intercept` is the model's prediction for
  "what the stressed antenna should read on day `t`, given what the reference
  antenna read, if there were no drought."

This is fit using every day **within the analysis window** — not a
hand-picked "pre-drought" baseline sub-period. That matters because the point
isn't to know in advance which specific days had drought; it's to let the
data itself define the normal relationship, with drought showing up as
departure from it.

### Window: vegetated season only (default 2025-06-01 to 2025-08-31)

Both scripts default to this window rather than the whole record, for a
domain reason, not a statistical one: **the drought experiment is only
active during the vegetated season** — winter dormancy dynamics are
irrelevant to it, and including them doesn't just add noise, it actively
distorts the fit. Confirmed empirically: the bias relationship itself is
**not seasonally constant**.

| Fit scope | slope | intercept |
|---|---|---|
| Whole record (441 days) | 0.9526 | −0.0326 |
| Vegetated season only (92 days, Jun–Aug 2025) | 0.6702 | 0.2445 |

These are meaningfully different relationships, not just noisier estimates of
the same one (the 95% CIs barely overlap). Fitting on the whole record and
only *windowing the residual afterward* — the first version of this analysis
— would silently apply an out-of-season relationship to the season that
actually matters, corrupting the very separation this method exists to do.
Pass `--start "" --end ""` to either script to opt back into the whole-record
fit if a different comparison is ever needed.

## Why Theil-Sen instead of ordinary least squares

Ordinary least-squares (OLS) minimizes the sum of squared residuals — which
means large residuals (exactly what a drought period produces) pull the fit
line toward themselves. If a big chunk of the record is drought-affected, OLS
would partly fit *the drought*, not just the normal relationship, weakening
the very separation we're trying to achieve.

**Theil-Sen** (`scipy.stats.theilslopes`) estimates the slope as the **median**
of all pairwise slopes `(y_j - y_i) / (x_j - x_i)` between every pair of
points. The median has a **breakdown point of ~29%** — up to about 29% of the
data can be arbitrary outliers before the median-based estimate is pulled off
the true value. As long as the drought-affected days are a *minority* of the
analysis window (92 days by default), Theil-Sen's fit reflects the normal
(non-drought) relationship even though drought-day residuals were included in
the fit, not excluded from it.

## The residual = the drought signal

```
predicted(t)     = slope · reference(t) + intercept
residual(t)      = stressed(t) − predicted(t)
norm_residual(t) = residual(t) / predicted(t)
```

- `residual(t)` is the part of the stressed antenna's reading **not explained**
  by what the reference antenna was doing that day. Under the stated
  assumption, that's the drought-specific component.
- `residual ≈ 0` → the stressed antenna is behaving exactly as the reference
  predicts (no excess stress).
- `residual < 0` → the stressed antenna reads lower than predicted — i.e.
  *more* attenuation loss than the shared dynamics account for → drought
  signal.
- `norm_residual` expresses the same thing as a fraction of the predicted
  value (a rough "% below expected").

Both are smoothed with the same 7-day Savitzky-Golay filter used elsewhere in
this analysis, since the underlying daily values are noisy day-to-day.

## What was actually fit, on real data

**Vegetated-season window (current default, 2025-06-01 to 2025-08-31):**

```
stressed = 0.6702 · reference + 0.2445
slope 95% CI: [0.4897, 0.8696]
```

A slope well below 1.0 with a positive intercept — a different relationship
than the whole-record fit below, confirming the bias isn't seasonally
constant (see the window section above). Within this window, the residual
oscillates near zero with normal noise-level fluctuation (roughly ±0.02-0.03)
and no dramatic sustained departure — i.e. no strong drought signal *within*
Jun–Aug 2025 specifically, by this method.

**Whole-record fit (441 days, for comparison / historical reference):**

```
stressed = 0.9526 · reference + (-0.0326)
slope 95% CI: [0.9238, 0.9808]
```

A slope near 1.0 with a small negative intercept means the two trees are close
to a 1:1 scaled relationship (mild attenuation-scale difference) with a small
fixed offset across the *whole* record — i.e. the "identical relative
dynamics" assumption holds up reasonably well when winter is included too
(if the scatter plot in panel 1 of the figure were a diffuse cloud rather
than a tight line, that would be a warning sign that the assumption doesn't
hold at all). The resulting whole-record residual is centered near zero for
most of the record, with two notable sustained departures: a dip through
**January–April 2026** and a sharper one at the **very end of the record
(June–July 2026)** — both **outside** the vegetated-season default window,
which is exactly why they don't appear when the analysis is restricted to
Jun–Aug.

## Caveats

- This isolates a **relative** stress signal (departure from the reference),
  not an absolute measurement of drought severity — it says "more stressed
  than the shared dynamics explain," not "this much VOD lost to drought" in
  physical units without further calibration.
- The linear model assumes the scale/offset relationship is **constant over
  the whole record**. If the structural bias itself drifts over time (e.g.
  canopy growth changing the scale factor seasonally), a single fixed
  `slope`/`intercept` wouldn't capture that, and it would leak into the
  residual as a slow trend rather than being removed. The scatter plot panel
  is the sanity check for this — if points from different seasons cluster
  along visibly different lines rather than one, the constant-relationship
  assumption is suspect.
- Theil-Sen's robustness helps as long as drought is a **minority** of the
  record. If drought dominates the record (>~29% of days materially
  affected), the fit itself would start reflecting drought conditions as "the
  normal," and the residual would understate the true stress signal.
