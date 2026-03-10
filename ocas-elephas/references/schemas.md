# Elephas Schemas

## Core Node Types

See spec-ocas-ontology.md for the shared type hierarchy: Entity (Person, AI), Place, Concept (Event, Action, Idea), Thing (DigitalArtifact, PhysicalArtifact, Signal, Candidate).

## Signal
```json
{"signal_id":"string","source_skill":"string","source_journal_type":"string — Observation|Action|Research","payload":{"type":"string","data":"object"},"timestamp":"string","status":"string — active|consumed"}
```

## Candidate
```json
{"candidate_id":"string","timestamp":"string","proposed_node":{"type":"string","data":"object"},"supporting_signals":["string"],"confidence":"string — high|med|low","status":"string — pending|confirmed|rejected|merged"}
```

## Inference
```json
{"inference_id":"string","type":"string — habit_pattern|social_opportunity|recurring_behavior","confidence":"string","supporting_nodes":["string"],"creation_time":"string"}
```

Inferences never overwrite Chronicle facts. They are separate interpretive records.

## DecisionRecord
Extends shared DecisionRecord. Elephas-specific types: candidate_promoted, candidate_rejected, identity_merged, identity_separated, inference_generated.
