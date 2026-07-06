// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun LSAT three-score math, ported from the Python source of truth
//! (`speedrun/scoring/{memory,performance,readiness}.py`) so desktop and phone
//! share one implementation. Pure and deterministic; a Python<->Rust parity test
//! guards against drift.

use std::collections::HashMap;

const Z_95: f64 = 1.96;
const SCALE_MIN: f64 = 120.0;
const SCALE_MAX: f64 = 180.0;
const MIN_ATTEMPTS_PER_SCHEMA: usize = 3;
// Section blend used by readiness (LR ~2/3, RC ~1/3).
const LR_SECTION_WEIGHT: f64 = 0.66;
const RC_SECTION_WEIGHT: f64 = 0.34;

/// One score with an honest range and give-up flag. When `gave_up` is true,
/// point/low/high are not meaningful.
#[derive(Debug, Clone, PartialEq)]
pub struct ScoreOut {
    pub gave_up: bool,
    pub point: f64,
    pub low: f64,
    pub high: f64,
    pub n: i32,
    pub reason: String,
}

impl ScoreOut {
    fn gave_up(n: i32, reason: String) -> Self {
        Self { gave_up: true, point: 0.0, low: 0.0, high: 0.0, n, reason }
    }
}

/// A graded attempt derived from the revlog.
#[derive(Debug, Clone, Copy)]
pub struct Attempt {
    pub correct: bool,
    pub on_budget: bool,
}

fn sample_stdev(values: &[f64], mean: f64) -> f64 {
    let n = values.len();
    if n < 2 {
        return 0.0;
    }
    let var = values.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / (n as f64 - 1.0);
    var.sqrt()
}

/// Point estimate + normal-approx CI for the mean of recall probabilities.
pub fn mean_ci(values: &[f64]) -> (f64, f64, f64) {
    let n = values.len();
    let point = values.iter().sum::<f64>() / n as f64;
    let half = if n >= 2 {
        Z_95 * sample_stdev(values, point) / (n as f64).sqrt()
    } else {
        0.5
    };
    (point, (point - half).max(0.0), (point + half).min(1.0))
}

/// Wilson score interval (center, low, high) for a binomial proportion.
pub fn wilson_interval(successes: usize, n: usize) -> (f64, f64, f64) {
    let n_f = n as f64;
    let p = successes as f64 / n_f;
    let z2 = Z_95 * Z_95;
    let denom = 1.0 + z2 / n_f;
    let center = (p + z2 / (2.0 * n_f)) / denom;
    let margin = (Z_95 * ((p * (1.0 - p) / n_f + z2 / (4.0 * n_f * n_f)).sqrt())) / denom;
    (center, (center - margin).max(0.0), (center + margin).min(1.0))
}

/// Memory score from per-card retrievabilities (None = not reviewed yet).
pub fn memory_score(retrievabilities: &[Option<f64>], min_reviewed: usize) -> ScoreOut {
    let reviewed: Vec<f64> = retrievabilities.iter().filter_map(|r| *r).collect();
    let n = reviewed.len();
    if n < min_reviewed {
        return ScoreOut::gave_up(
            n as i32,
            format!(
                "Not enough data: {n} reviewed card(s) < required {min_reviewed}. \
                 Review more cards to get a memory score."
            ),
        );
    }
    let (point, low, high) = mean_ci(&reviewed);
    ScoreOut {
        gave_up: false,
        point,
        low,
        high,
        n: n as i32,
        reason: format!("Mean FSRS recall over {n} reviewed card(s)."),
    }
}

/// Performance score for a group of attempts (latency-adjusted, on-budget hits).
pub fn performance_score(attempts: &[Attempt], min_attempts: usize) -> ScoreOut {
    let n = attempts.len();
    if n < min_attempts {
        return ScoreOut::gave_up(
            n as i32,
            format!("Not enough data: {n} attempt(s) < required {min_attempts}."),
        );
    }
    let on_budget = attempts.iter().filter(|a| a.on_budget).count();
    let (center, low, high) = wilson_interval(on_budget, n);
    ScoreOut {
        gave_up: false,
        point: center,
        low,
        high,
        n: n as i32,
        reason: "Latency-adjusted accuracy on graded attempts.".to_string(),
    }
}

fn is_rc(schema: &str) -> bool {
    schema.starts_with("rc.")
}

/// Section-weighted expected fraction for a `which` selector (0=point,1=low,2=high),
/// plus overall weight-based coverage.
fn overall_fraction(
    per_schema: &HashMap<String, ScoreOut>,
    weights: &HashMap<String, f64>,
    which: u8,
) -> (Option<f64>, f64) {
    let sections = [("LR", LR_SECTION_WEIGHT), ("RC", RC_SECTION_WEIGHT)];
    let (mut num, mut denom, mut cov_num, mut cov_denom) = (0.0, 0.0, 0.0, 0.0);
    for (section, sw) in sections {
        let mut covered_weight = 0.0;
        let mut total_weight = 0.0;
        let mut acc = 0.0;
        for (sid, w) in weights {
            let in_section = if section == "RC" { is_rc(sid) } else { !is_rc(sid) };
            if !in_section {
                continue;
            }
            total_weight += w;
            if let Some(score) = per_schema.get(sid) {
                if !score.gave_up {
                    let value = match which {
                        1 => score.low,
                        2 => score.high,
                        _ => score.point,
                    };
                    acc += w * value;
                    covered_weight += w;
                }
            }
        }
        cov_denom += sw;
        if covered_weight > 0.0 {
            num += sw * (acc / covered_weight);
            denom += sw;
        }
        if total_weight > 0.0 {
            cov_num += sw * (covered_weight / total_weight);
        }
    }
    let fraction = if denom > 0.0 { Some(num / denom) } else { None };
    let coverage = if cov_denom > 0.0 { cov_num / cov_denom } else { 0.0 };
    (fraction, coverage)
}

fn scaled_from_fraction(fraction: f64) -> f64 {
    let f = fraction.clamp(0.0, 1.0);
    SCALE_MIN + f * (SCALE_MAX - SCALE_MIN)
}

/// Covered fraction of each scored section's exam weight (schemas with a
/// non-give-up per-schema score). Sections with no taxonomy weight are skipped
/// so they impose no gate. Mirrors Python `_section_coverages`: this is the
/// per-section give-up precondition (PRD §10/§8.3).
fn section_coverages(
    per_schema: &HashMap<String, ScoreOut>,
    weights: &HashMap<String, f64>,
) -> Vec<(&'static str, f64)> {
    let mut out = Vec::new();
    for section in ["LR", "RC"] {
        let (mut total, mut covered) = (0.0, 0.0);
        for (sid, w) in weights {
            let in_section = if section == "RC" { is_rc(sid) } else { !is_rc(sid) };
            if !in_section {
                continue;
            }
            total += w;
            if let Some(s) = per_schema.get(sid) {
                if !s.gave_up {
                    covered += w;
                }
            }
        }
        if total > 0.0 {
            out.push((section, covered / total));
        }
    }
    out
}

/// Readiness (120-180) from per-schema performance + exam weights.
pub fn readiness_score(
    per_schema: &HashMap<String, ScoreOut>,
    weights: &HashMap<String, f64>,
    n_attempts: i32,
    min_attempts: usize,
    min_coverage: f64,
) -> ScoreOut {
    let (point_frac, coverage) = overall_fraction(per_schema, weights, 0);
    // PRD §10/§8.3: coverage must clear the line in *each* scored section, not
    // just on the blended average, so a section-skipping deck can never read
    // "ready".
    let sec_cov = section_coverages(per_schema, weights);
    let under: Vec<(&str, f64)> = sec_cov.iter().copied().filter(|(_, c)| *c < min_coverage).collect();
    if (n_attempts as usize) < min_attempts
        || coverage < min_coverage
        || !under.is_empty()
        || point_frac.is_none()
    {
        let reason = if !under.is_empty() {
            let detail = under
                .iter()
                .map(|(s, c)| format!("{s} {:.0}%", c * 100.0))
                .collect::<Vec<_>>()
                .join(", ");
            format!(
                "No score yet: need >= {min_attempts} graded attempts (have {n_attempts}) \
                 and >= {:.0}% schema coverage in each of LR and RC (short: {detail}).",
                min_coverage * 100.0
            )
        } else {
            format!(
                "No score yet: need >= {min_attempts} graded attempts (have {n_attempts}) \
                 and >= {:.0}% coverage (have {:.0}%).",
                min_coverage * 100.0,
                coverage * 100.0
            )
        };
        return ScoreOut::gave_up(n_attempts, reason);
    }
    let pf = point_frac.unwrap();
    let (low_frac, _) = overall_fraction(per_schema, weights, 1);
    let (high_frac, _) = overall_fraction(per_schema, weights, 2);
    ScoreOut {
        gave_up: false,
        point: scaled_from_fraction(pf),
        low: scaled_from_fraction(low_frac.unwrap_or(pf)),
        high: scaled_from_fraction(high_frac.unwrap_or(pf)),
        n: n_attempts,
        reason: "Projected from per-schema performance via a stated linear map.".to_string(),
    }
}

/// Group attempts by schema and compute per-schema performance (for readiness).
pub fn per_schema_performance(
    by_schema: &HashMap<String, Vec<Attempt>>,
) -> HashMap<String, ScoreOut> {
    by_schema
        .iter()
        .map(|(s, atts)| (s.clone(), performance_score(atts, MIN_ATTEMPTS_PER_SCHEMA)))
        .collect()
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn mean_ci_single_value_is_wide() {
        let (p, lo, hi) = mean_ci(&[0.8]);
        assert!((p - 0.8).abs() < 1e-9);
        assert!((lo - 0.3).abs() < 1e-9);
        assert!((hi - 1.0).abs() < 1e-9); // 0.8 + 0.5 clamped to 1
    }

    #[test]
    fn mean_ci_identical_values_zero_width() {
        let (p, lo, hi) = mean_ci(&[0.8, 0.8, 0.8]);
        assert!((p - 0.8).abs() < 1e-9);
        assert!((hi - lo).abs() < 1e-9);
    }

    #[test]
    fn memory_gives_up_below_threshold() {
        let s = memory_score(&[Some(0.9), None], 2);
        assert!(s.gave_up);
        assert_eq!(s.n, 1);
    }

    #[test]
    fn memory_reports_range_above_threshold() {
        let s = memory_score(&[Some(0.9), Some(0.8), Some(0.7), None], 2);
        assert!(!s.gave_up);
        assert_eq!(s.n, 3);
        assert!(s.low <= s.point && s.point <= s.high);
    }

    #[test]
    fn wilson_shrinks_small_samples() {
        let (c, _lo, _hi) = wilson_interval(1, 1);
        assert!(c < 1.0, "a single hit must not read as 100%");
    }

    #[test]
    fn performance_gives_up_and_scores() {
        let miss = Attempt { correct: false, on_budget: false };
        let hit = Attempt { correct: true, on_budget: true };
        assert!(performance_score(&[hit; 2], 3).gave_up);
        let s = performance_score(&[hit, hit, hit, miss], 3);
        assert!(!s.gave_up && s.n == 4 && s.low <= s.point && s.point <= s.high);
    }

    #[test]
    fn readiness_gives_up_without_attempts() {
        let mut per = HashMap::new();
        per.insert(
            "flaw.causal.post_hoc".to_string(),
            ScoreOut { gave_up: false, point: 0.8, low: 0.7, high: 0.9, n: 5, reason: String::new() },
        );
        let mut w = HashMap::new();
        w.insert("flaw.causal.post_hoc".to_string(), 1.0);
        let r = readiness_score(&per, &w, 5, 200, 0.5);
        assert!(r.gave_up);
    }

    #[test]
    fn readiness_abstains_when_a_section_is_skipped() {
        // LR fully covered, RC present in the taxonomy but never practiced: the
        // blended average clears 50%, yet a skipped section must force give-up.
        let mut per = HashMap::new();
        let mut w = HashMap::new();
        for i in 0..4 {
            let sid = format!("flaw.lr.n{i}");
            per.insert(
                sid.clone(),
                ScoreOut { gave_up: false, point: 0.6, low: 0.5, high: 0.7, n: 50, reason: String::new() },
            );
            w.insert(sid, 1.0);
        }
        // RC schemas exist (weight present) but have no non-give-up score.
        w.insert("rc.structure.main_point".to_string(), 2.0);
        let r = readiness_score(&per, &w, 300, 200, 0.5);
        assert!(r.gave_up, "a skipped RC section must abstain: {}", r.reason);
        assert!(r.reason.contains("RC"), "reason names the short section: {}", r.reason);
    }

    #[test]
    fn readiness_scales_into_120_180() {
        let mut per = HashMap::new();
        let mut w = HashMap::new();
        for i in 0..5 {
            let sid = format!("flaw.x.n{i}");
            per.insert(
                sid.clone(),
                ScoreOut { gave_up: false, point: 0.5, low: 0.4, high: 0.6, n: 50, reason: String::new() },
            );
            w.insert(sid, 1.0);
        }
        let r = readiness_score(&per, &w, 300, 200, 0.5);
        assert!(!r.gave_up);
        assert!((r.point - 150.0).abs() < 1e-6); // 120 + 0.5*60
        assert!(r.low >= SCALE_MIN && r.high <= SCALE_MAX);
    }
}
