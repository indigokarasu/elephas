# Elephas Ingestion Pipeline

## Journal Reading
During ingestion passes, Elephas reads newly written journal entries from all skills. It processes Observation, Action, and Research journals.

## Signal Creation
Each relevant journal entry produces one or more Signals. Signals are immutable records capturing the raw observation.

## Candidate Creation
Signals that reference identifiable entities produce Candidates — proposed additions to Chronicle.

## Confidence Scoring
Candidate confidence increases when: multiple signals corroborate, cross-domain confirmation exists, or identity matches strengthen. Confidence decreases when: contradicting signals appear or sources degrade.

## Promotion Criteria
A candidate becomes a confirmed Chronicle fact when: confidence meets threshold, at least one supporting signal exists, no contradicting evidence of higher confidence.

## Deduplication
During consolidation: detect duplicate entity records, flag as possible_match, auto-merge if above threshold, preserve merge history for reversal.

## Inference Generation
During deep passes: analyze patterns across confirmed facts. Generate inference records (habit patterns, social opportunities, recurring behaviors). Inferences are tagged with confidence and supporting nodes. They never overwrite facts.
