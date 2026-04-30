AUDIT (
  name valid_to_state
);

-- Returns rows iff ``to_state`` is NULL or outside the lifecycle vocabulary.
-- Mirrors ``biibaa.domain.OpportunityState``: keep both lists in sync.
-- Used by ``staging.opportunity_transitions``.
SELECT to_state
FROM @this_model
WHERE to_state IS NULL
   OR to_state NOT IN ('new', 'acknowledged', 'resolved', 'rejected', 'duplicate');
