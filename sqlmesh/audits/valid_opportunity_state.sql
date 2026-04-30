AUDIT (
  name valid_opportunity_state
);

-- Returns rows iff ``state`` is NULL or outside the lifecycle vocabulary.
-- Mirrors ``biibaa.domain.OpportunityState``: keep both lists in sync.
-- Used by ``marts.opportunity_state``.
SELECT state
FROM @this_model
WHERE state IS NULL
   OR state NOT IN ('new', 'acknowledged', 'resolved', 'rejected', 'duplicate');
