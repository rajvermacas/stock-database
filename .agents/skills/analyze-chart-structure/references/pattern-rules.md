# Pattern Rules

All tolerances are normalized by `max(ATR-14, close * 0.005)`.

| Pattern | Required pivots | Confirmation | Invalidation |
|---|---|---|---|
| Double bottom/top | Two comparable extrema with an intervening opposite pivot | Close beyond neckline by one tolerance | Close beyond the more extreme outer pivot by one tolerance |
| Head and shoulders/inverse | Five alternating pivots; head exceeds both shoulders; shoulders comparable | Close beyond neckline by one tolerance | Close beyond head by one tolerance |
| Ascending/descending triangle | Rising lows/flat highs or falling highs/flat lows | Close beyond flat boundary by one tolerance | Close beyond opposite boundary |
| Symmetrical triangle | Falling highs and rising lows | Close beyond either converging boundary | Close through opposite boundary |
| Ascending/descending channel | At least two aligned highs and lows with positive/negative slopes | Structure classification; breakout state is separate | Opposite-direction boundary break |
| Horizontal range | Flat highs and lows with sufficient width | Close beyond boundary by one tolerance | Re-entry beyond boundary after breakout |

Statuses: `developing`, `confirmed`, `invalidated`. Confidence is deterministic rule
agreement, not probability of future performance.
