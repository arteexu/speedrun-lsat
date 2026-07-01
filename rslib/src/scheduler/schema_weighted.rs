// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Schema-weighted "points-at-stake" ordering for the LSAT Speedrun build.
//!
//! The LSAT is a transfer problem: the unit of mastery is the *schema* (a flaw,
//! trap, question-type procedure, or RC structure), not the individual card.
//! This module orders due cards so the highest-value schema practice comes
//! first, using
//!
//! ```text
//! priority = schema_weight * student_weakness * time_pressure_factor
//! ```
//!
//! The core [`schema_weighted_order`] function is pure (no database access) so
//! it can be unit-tested directly; the RPC layer in `scheduler::service`
//! supplies it with card/schema metadata read from the collection.

use std::collections::HashMap;
use std::collections::HashSet;

/// A due card together with the schema it trains (read from a note tag).
#[derive(Debug, Clone, PartialEq)]
pub struct SchemaCard {
    pub card_id: i64,
    pub note_id: i64,
    /// Schema id (the note-tag suffix), or empty if the card has no schema tag.
    pub schema: String,
}

/// Parameters controlling the ordering. `schema_weight` and `schema_weakness`
/// are keyed by schema id; missing schemas fall back to the `default_*` values.
#[derive(Debug, Clone)]
pub struct SchemaWeightParams {
    pub schema_weight: HashMap<String, f64>,
    pub schema_weakness: HashMap<String, f64>,
    pub time_pressured: HashSet<String>,
    pub time_pressure_factor: f64,
    pub default_weight: f64,
    pub default_weakness: f64,
}

impl Default for SchemaWeightParams {
    fn default() -> Self {
        Self {
            schema_weight: HashMap::new(),
            schema_weakness: HashMap::new(),
            time_pressured: HashSet::new(),
            // Neutral multiplier unless the caller opts in.
            time_pressure_factor: 1.0,
            // Unknown-schema fallbacks: assume some weight and maximal weakness so
            // uncovered/unseen schemas still surface rather than vanishing.
            default_weight: 0.0,
            default_weakness: 1.0,
        }
    }
}

/// A scored card, ready to hand back to the caller.
#[derive(Debug, Clone, PartialEq)]
pub struct ScoredSchemaCard {
    pub card_id: i64,
    pub note_id: i64,
    pub schema: String,
    pub schema_weight: f64,
    pub weakness: f64,
    pub priority: f64,
}

impl SchemaWeightParams {
    fn weight_for(&self, schema: &str) -> f64 {
        self.schema_weight
            .get(schema)
            .copied()
            .unwrap_or(self.default_weight)
    }

    fn weakness_for(&self, schema: &str) -> f64 {
        self.schema_weakness
            .get(schema)
            .copied()
            .unwrap_or(self.default_weakness)
    }

    fn factor_for(&self, schema: &str) -> f64 {
        if self.time_pressured.contains(schema) {
            self.time_pressure_factor
        } else {
            1.0
        }
    }
}

/// Order `cards` by descending points-at-stake priority.
///
/// Ties are broken by ascending `card_id`, making the ordering fully
/// deterministic (important for reproducible tests and stable review sessions).
/// If `limit` is `Some(n)`, at most `n` cards are returned.
pub fn schema_weighted_order(
    cards: impl IntoIterator<Item = SchemaCard>,
    params: &SchemaWeightParams,
    limit: Option<usize>,
) -> Vec<ScoredSchemaCard> {
    let mut scored: Vec<ScoredSchemaCard> = cards
        .into_iter()
        .map(|c| {
            let weight = params.weight_for(&c.schema);
            let weakness = params.weakness_for(&c.schema);
            let priority = weight * weakness * params.factor_for(&c.schema);
            ScoredSchemaCard {
                card_id: c.card_id,
                note_id: c.note_id,
                schema: c.schema,
                schema_weight: weight,
                weakness,
                priority,
            }
        })
        .collect();

    scored.sort_by(|a, b| {
        b.priority
            .total_cmp(&a.priority)
            .then_with(|| a.card_id.cmp(&b.card_id))
    });

    if let Some(n) = limit {
        scored.truncate(n);
    }
    scored
}

#[cfg(test)]
mod test {
    use super::*;

    fn card(card_id: i64, schema: &str) -> SchemaCard {
        SchemaCard {
            card_id,
            note_id: card_id * 10,
            schema: schema.to_string(),
        }
    }

    fn params() -> SchemaWeightParams {
        let mut p = SchemaWeightParams::default();
        p.schema_weight.insert("flaw.causal".into(), 0.5);
        p.schema_weight.insert("flaw.conditional".into(), 0.2);
        p.schema_weakness.insert("flaw.causal".into(), 0.4);
        p.schema_weakness.insert("flaw.conditional".into(), 0.9);
        p
    }

    #[test]
    fn orders_by_points_at_stake_descending() {
        let p = params();
        // causal: 0.5 * 0.4 = 0.20 ; conditional: 0.2 * 0.9 = 0.18
        let out = schema_weighted_order(
            vec![card(1, "flaw.conditional"), card(2, "flaw.causal")],
            &p,
            None,
        );
        assert_eq!(out[0].card_id, 2, "higher points-at-stake card comes first");
        assert_eq!(out[1].card_id, 1);
        assert!((out[0].priority - 0.20).abs() < 1e-9);
        assert!((out[1].priority - 0.18).abs() < 1e-9);
    }

    #[test]
    fn ties_break_by_card_id_for_determinism() {
        let p = params();
        // Both cards share a schema, so identical priority; ids must decide order.
        let out = schema_weighted_order(
            vec![
                card(30, "flaw.causal"),
                card(10, "flaw.causal"),
                card(20, "flaw.causal"),
            ],
            &p,
            None,
        );
        let ids: Vec<i64> = out.iter().map(|c| c.card_id).collect();
        assert_eq!(ids, vec![10, 20, 30]);
    }

    #[test]
    fn unknown_schema_uses_defaults() {
        let mut p = params();
        p.default_weight = 0.1;
        p.default_weakness = 1.0;
        // unknown: 0.1 * 1.0 = 0.10, which is below causal (0.20) but nonzero,
        // so uncovered schemas still surface.
        let out = schema_weighted_order(
            vec![card(1, "totally.unknown"), card(2, "flaw.causal")],
            &p,
            None,
        );
        assert_eq!(out[0].card_id, 2);
        assert_eq!(out[1].schema, "totally.unknown");
        assert!((out[1].priority - 0.10).abs() < 1e-9);
    }

    #[test]
    fn time_pressure_factor_boosts_flagged_schemas() {
        let mut p = params();
        p.time_pressure_factor = 2.0;
        p.time_pressured.insert("flaw.conditional".into());
        // conditional now: 0.2 * 0.9 * 2.0 = 0.36 > causal 0.20
        let out = schema_weighted_order(
            vec![card(2, "flaw.causal"), card(1, "flaw.conditional")],
            &p,
            None,
        );
        assert_eq!(out[0].card_id, 1, "time-pressured schema is boosted ahead");
        assert!((out[0].priority - 0.36).abs() < 1e-9);
    }

    #[test]
    fn limit_truncates_after_sorting() {
        let p = params();
        let out = schema_weighted_order(
            vec![
                card(1, "flaw.conditional"),
                card(2, "flaw.causal"),
                card(3, "flaw.conditional"),
            ],
            &p,
            Some(1),
        );
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].card_id, 2, "keeps the highest-priority card");
    }
}
