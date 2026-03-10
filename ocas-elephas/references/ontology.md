# Elephas Ontology

This file extends spec-ocas-ontology.md with Chronicle-specific details.

## Chronicle Database
Engine: LadybugDB (embedded local).
Chronicle stores entities, places, events, relationships, signals, candidates, inferences, and artifact pointers. It does not store full documents — artifacts remain in external systems with Chronicle storing references.

## Node Type Hierarchy
Entity → Person, AI
Place → restaurant, office, city, venue, etc.
Concept → Event (TravelEvent, MeetingEvent, PurchaseEvent, etc.), Action, Idea
Thing → DigitalArtifact, PhysicalArtifact, Signal, Candidate

## Indexes
Required: Entity.id, Place.id, Event.id, Signal.id, Candidate.id, Place.name, Event.event_time

## Expected Scale
Nodes: 100k–500k. Edges: 5M–20M.
