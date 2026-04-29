AUDIT (
  name score_in_range
);

SELECT *
FROM @this_model
WHERE score IS NULL
   OR score < 0
   OR score > 1;
