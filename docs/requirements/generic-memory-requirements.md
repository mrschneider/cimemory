# Generic Memory Requirements — for Agent Evolution

**Scope.** This document specifies what *any* memory store must provide for the
continuous-improvement loop in this repo to work. It is deliberately
**database-agnostic**: it states requirements and conformance criteria, not
technology. Any store that passes the conformance suite in §7 may be plugged in.

The companion implementation is `cimemory/backend.py` (the contract),
`cimemory/backends/` (three reference adapters) and `cimemory/plugin.py` (the
semantic layer that consumes it).

---

## 0. Layer model

```
┌──────────────────────────────────────────────────────────────┐
│  KaizenLoop            engine: walks the 8 TBP steps          │
├──────────────────────────────────────────────────────────────┤
│  EvolutionMemory       semantics + ENFORCED DISCIPLINE        │
│                        (refuses unverified root causes,      │
│                         unreflected standards, etc.)         │
├──────────────────────────────────────────────────────────────┤
│  MemoryBackend         <-- THIS DOCUMENT specifies this layer │
│                        ten methods, capability-negotiated     │
├──────────────────────────────────────────────────────────────┤
│  SQLite │ Postgres │ Redis │ JSONL │ Vector DB │ object store │
└──────────────────────────────────────────────────────────────┘
```

**Rule of the boundary:** the backend stores opaque dicts addressed by
`(kind, record_id)`. It does *not* interpret semantics. The plugin does the
semantic work and the enforcement. This is what makes the whole thing swappable:
a backend that never heard of "root cause" can still serve the loop.

---

## 1. The ten-method contract

| # | Method | Required? | Purpose |
|---|---|---|---|
| 1 | `write(kind, record_id, payload)` | **required** | Insert or fully replace |
| 2 | `read(kind, record_id)` | **required** | Point lookup, `None` if absent |
| 3 | `query(kind, where, order_by, descending, limit)` | **required** | Enumerate a kind |
| 4 | `delete(kind, record_id)` | **required** | Remove (retention/compaction) |
| 5 | `capabilities()` | **required** | Truthful self-description |
| 6 | `close()` | **required** | Flush and release |
| 7 | `update(kind, record_id, patch)` | optional | Partial update |
| 8 | `append(entry)` / `journal(since, limit)` | optional\* | Append-only event log |
| 9 | `search_text(kind, text)` | optional | Keyword retrieval |
| 10 | `search_vector(kind, embedding, k)` | optional | Semantic retrieval |

\* **The journal is optional in the contract but mandatory in practice.** See R2.
`BaseBackend` supplies merge-and-write fallbacks for 7; 8–10 raise
`NotImplementedError` and must be advertised as unsupported in `capabilities()`.

---

## 2. Functional requirements

### R1 — Record identity and addressing
- **R1.1** Every record is addressed by a stable `(kind, record_id)` pair.
- **R1.2** `record_id` is stable across its lifetime and is never reused for a
  different record.
- **R1.3** `kind` is a small, closed, lowercase vocabulary (`observation`,
  `problem`, `target`, `why`, `root_cause`, `countermeasure`, `experiment`,
  `check`, `standard`, `spread`, `hansei`, `andon`). Adding a kind must not
  require a backend change.
- **R1.4** `write` is idempotent on `record_id`: writing twice yields one record.
- **R1.5** `read` on a missing id returns `None` — never raises.

*Why:* the loop references records across time (a standard points at the
experiment that produced it). Dangling or recycled ids break the lineage that
makes the evolution auditable.

### R2 — Append-only journal (the timeline)
- **R2.1** The store can append immutable entries with a monotonic timestamp.
- **R2.2** Entries are readable oldest-first, filterable by `since` and capped by
  `limit`.
- **R2.3** Appended entries are never mutated or reordered by later writes.
- **R2.4** The journal survives the mutation of the records it describes.

*Why:* Principle 12 and the andon mechanism. To know *what the agent actually
saw* — and to reconstruct a decision after the fact — you need a log that is not
rewritten by subsequent updates. A record store alone cannot answer "was the
standard drifting before we changed it?".

### R3 — Enumeration and ordering
- **R3.1** `query` returns every record of a kind, or an equality-filtered subset.
- **R3.2** Ordering is **total and deterministic** for a given `order_by`; ties
  are broken deterministically.
- **R3.3** `where` is equality-only. Complex predicates are the plugin's job —
  backends must not need a query language to conform.

*Why:* "last version of this standard", "latest observation of this metric" are
the most common loop reads and must not depend on insertion luck.

### R4 — Update and delete
- **R4.1** Partial update returns the resulting record, or `None` if the id is
  absent.
- **R4.2** A backend without native partial update must implement read-merge-write
  and say `transactional: false` unless the merge is atomic.
- **R4.3** `delete` returns whether something was removed and is idempotent.

### R5 — Lineage and temporal versioning
- **R5.1** *Required at the schema level:* records carry enough fields for the
  plugin to reconstruct lineage — `supersedes`, `from_experiment`, `problem_id`,
  `check_id`, `root_cause_id`, `countermeasure_ids`.
- **R5.2** *Recommended at the storage level:* the backend can return the
  previous versions of a record (`temporal_versioning: true`). Without it, the
  plugin can still rebuild history from `standard.supersedes` chains, but cannot
  recover a mutated record's prior payload.
- **R5.3** Superseding a record must not delete its predecessor; supersession is
  a state change (`active: false`), not a removal.

*Why:* Act-step standardisation replaces a baseline. If history is destroyed,
"what did we believe last month and why did we change it?" becomes unanswerable —
and that question is the entire point of a learning organisation.

### R6 — Capability negotiation
- **R6.1** `capabilities()` is truthful and cheap: **never optimistic**.
- **R6.2** Capabilities cover at minimum: `durable`, `transactional`,
  `append_only_journal`, `temporal_versioning`, `full_text_search`,
  `vector_search`, `multi_tenant`.
- **R6.3** The plugin degrades gracefully: it checks `supports(feature)` and
  falls back rather than crashing or silently returning empty results.
- **R6.4** Calling an unsupported optional method raises `NotImplementedError` —
  never returns a plausible-looking empty value.

*Why:* a silent fallback that returns `[]` reads as "no memory of this", which
the agent will interpret as "safe to re-derive". That duplication is exactly the
waste the loop exists to eliminate. Fail loudly or degrade explicitly.

### R7 — Durability, atomicity, concurrency
- **R7.1** A durable backend must survive process restart with no record loss.
- **R7.2** A write that touches multiple records (standard + predecessor
  deactivation) must be atomic. If the backend cannot do it, the loop must be
  told (`transactional: false`) so it can order operations safely.
- **R7.3** Concurrent writers from sibling agents must not corrupt the store;
  last-writer-wins per record is acceptable if writes are atomic per record.
- **R7.4** `close()` flushes; calling it twice is safe.

### R8 — Provenance and trust
- **R8.1** Records carry provenance: `agent`, `source`, `ts`, and (for evidence)
  `verified_by`.
- **R8.2** The store must not strip unknown fields — forward compatibility for
  fields added by future plugin versions.
- **R8.3** Timestamps are stored in UTC epoch seconds (float). Display
  timezones are a presentation concern.

*Why:* a countermeasure is only as good as the evidence behind it. Provenance is
what lets the loop distinguish a measured fact from a self-report.

### R9 — Multi-agent scope (yokoten)
- **R9.1** Records are attributed to an agent but readable across the fleet, so a
  standard proven on one agent can be spread to siblings.
- **R9.2** Where isolation is required (`multi_tenant: true`), the backend must
  support a scope/namespace that still permits an explicitly granted cross-scope
  read for yokoten.
- **R9.3** A `spread` record must record both the source agent and the applied
  targets.

### R10 — Retention, compaction, and the eviction hazard
- **R10.1** The store must be able to delete or expire records without
  invalidating the journal.
- **R10.2** Compaction must never silently drop a record that an *active*
  standard depends on.
- **R10.3** If the store evicts records by TTL/size, eviction must emit a
  journal entry — the loop must be able to detect that memory was lost.
- **R10.4** The "cache eviction invalidates the memory record" pattern must be
  expressible: an eviction is an event, and the corresponding record is
  invalidated explicitly, not left as a stale truth.

*Why:* this is the *subject* of Experiment 001. The failure mode we are trying
to design out is "context/memory drops a fact, the agent silently re-derives it".
A store that evicts without telling anyone recreates the very waste the loop is
supposed to remove. Eviction must be visible (jidoka) — that is the mizen-boushi
countermeasure, implemented at the storage layer.

### R11 — Retrieval quality
- **R11.1** Minimum viable: exact lookup by id and equality filtering by field.
- **R11.2** Expected: substring/keyword search over record contents.
- **R11.3** Advanced: vector/embedding nearest-neighbour search, returning
  `(record, score)` pairs, for "have I seen this before?" before acting.
- **R11.4** `search_vector`, when present, must be deterministic for equal scores
  and must not return records the caller is not allowed to read.

*Why:* the strongest countermeasure from Experiment 001 — "consult memory before
any re-read" — is only cheap if retrieval is cheap. Retrieval latency is on the
agent's critical path, so it is a *functional* requirement, not a nice-to-have.

### R12 — Observability
- **R12.1** The store exposes cheap counters: record counts per kind, journal
  size, backend name and capabilities.
- **R12.2** Journal entries are structured (event name + fields), not free text.
- **R12.3** A status call must be O(1) or O(kinds), never a full scan of the
  corpus.

*Why:* `EvolutionMemory.status()` feeds the visual control that makes problems
visible (Principle 7).

### R13 — Schema evolution
- **R13.1** Adding a field to a record kind requires no migration and no backend
  change.
- **R13.2** Removing/renaming a field is handled by the plugin's
  `from_dict`/`_plain` layer, not the backend.
- **R13.3** Unknown fields read back from an older deployment are preserved.

### R14 — Security and isolation
- **R14.1** Credentials are supplied to the adapter, never stored in records.
- **R14.2** A record's trust/provenance is data, but must not be forgeable by the
  agent itself: `verified_by` is set by the evidence-producing layer, not by the
  claim-making agent.
- **R14.3** If multiple agents share a store, a compromised agent must not be
  able to overwrite another's *standard* without producing a passing check —
  the discipline is enforced in the plugin, but the store must at least not
  offer a bypass that skips the plugin.

### R15 — Read-only observation (consuming a store the loop must not change)

The loop is not the only consumer of memory. An improvement *board* observes a
running fleet, and observing must never be able to mutate production. This is
a first-class requirement, not a deployment detail.

- **R15.1 — The adapter may be read-only.** An adapter may implement the read
  path and refuse the write path. Refusal must be loud (raise), never a silent
  no-op: a caller that believes it standardised something must not be told
  nothing happened.
- **R15.2 — Read-only is enforced by the substrate, not by convention.** The
  credential used must lack write grants. A guard must verify this at connect
  time and refuse to run otherwise, so a future edit cannot quietly promote an
  observer to a writer.
- **R15.3 — Reads are paged and bounded.** An observer may not depend on
  holding the store in memory: `select` with `limit`/`offset`, or a cursor.
- **R15.4 — Observation is derived, never invented.** Every figure shown must
  be recomputable from records. If a quantity cannot be derived (a root cause,
  a target, a deadline), the answer is *absent*, and absence is displayed as
  such. A board that fabricates a plausible cause is worse than one that shows
  a blank.
- **R15.5 — A read-only observer performs no cycle step that requires an
  actor.** Clarify and break down the gap: yes, that is measurement. Set a
  target, act, check, standardise: no — those write improvement work back.
  The consumer must report the steps it did not perform, so the dashboard
  cannot be mistaken for a completed loop.
- **R15.6 — The standard may be established but unverified.** When the
  baseline is derived from fleet statistics rather than a passing experiment,
  it must be marked as such (`from_experiment: None`), so nobody reads a
  median as proof.
- **R15.7 — Statistics must state their population.** A rate over a small
  sample must not set a target. The consumer declares a minimum evidence
  threshold, and stations below it are reported but excluded from the standard
  and from the goal.
- **R15.8 — Degradation is announced.** If the observed store is unreachable,
  the consumer must not silently substitute a fixture for production. It falls
  back visibly, naming the source it actually served.

---

## 3. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| N1 | Point read latency | ≤ 5 ms p95 (local store) |
| N2 | Query of one kind | ≤ 50 ms p95 at 10⁵ records |
| N3 | Write latency | ≤ 10 ms p95 |
| N4 | Retrieval before action | ≤ 100 ms p95 end-to-end (the agent's path) |
| N5 | Durability | no loss on restart (if `durable`) |
| N6 | Footprint | journal and corpus must be independently compactable |
| N7 | Zero required deps | the reference implementation runs on the stdlib alone |
| N8 | Concurrency | safe for one writer per agent; multi-writer per kind must not corrupt |

---

## 4. What the memory must NOT be

- **Not a chat log.** Conversation transcripts are not observations. The loop
  needs measured facts with a `metric` and a `source`.
- **Not a self-report store.** An agent's claim of success is not a `Check`. The
  Check requires an `after_value` to be evaluated against the target.
- **Not a blob store without ids.** Lineage requires addressable records.
- **Not eventually-consistent-only.** "Read your own write" is required: the loop
  standardises a countermeasure and must immediately see the new standard.
- **Not a silent-eviction cache.** See R10.3.
- **Not a query language.** Equality filters plus ordering is the contract;
  anything richer is the plugin's concern.

---

## 5. Capability matrix of the reference adapters

| Feature | `memory` | `sqlite` | `jsonl` |
|---|---|---|---|
| durable | ✗ | ✓ (file) | ✓ |
| transactional | ✓ | ✓ | ✗ |
| append_only_journal | ✓ | ✓ | ✓ |
| temporal_versioning | ✗ | ✓ | ✗ |
| full_text_search | ✓ | ✓ | ✓ |
| vector_search | ✗ | ✗ | ✗ |
| multi_tenant | ✗ | ✗ | ✗ |

The three adapters are deliberately different in capability. The conformance
suite (§7) runs against all three, which is how "DB-agnostic" is *proved* rather
than asserted.

---

## 6. Mapping to production stores

| Store | Serves the contract as | Gaps to bridge |
|---|---|---|
| SQLite / libSQL | direct | none for single-node |
| PostgreSQL | direct + JSONB + tsvector | vector via pgvector for R11.3 |
| Redis | direct (hashes + streams) | durability config; no native temporal versioning |
| MongoDB | direct (documents + capped collections) | journal via capped collection |
| DuckDB / Parquet | direct, read-mostly | weak concurrent writes |
| S3 / object store | direct with a write-ahead journal | no partial update; must append |
| pgvector / Qdrant | `search_vector` + records | pair with a record store for R1–R5 |
| Neo4j | direct, and lineage as edges | overkill unless graph queries are needed for yokoten |

A production deployment commonly pairs two: a record store (R1–R10) plus a vector
index (R11.3), with the journal living in the record store.

### The observed store: Ratiocore agent memory (Tarantool)

The live board reads a store that was not built for this contract, which makes
it the useful test of R15. `box.space.agent_memory` holds one tuple per turn,
`[turn_id, profile, role, content, embedding, metadata]`, and maps onto the
requirements as follows:

| Contract need | How the store serves it | Verdict |
|---|---|---|
| R1 identity | `turn_id` (primary key) | served |
| R2 journal | append-only in practice; `ts` in metadata gives the timeline | served by convention, not by a declared journal |
| R3 enumeration | `select(nil, {limit, offset})` paging; `by_profile` index | served |
| R8 provenance | `metadata.source`, `status`, `importance` | served |
| R11 retrieval | `embedding` column, no vector index declared here | not used by the board |
| R6 capabilities | not declared anywhere | **gap** — the adapter must state them |
| R12 observability | no counters | **gap** |
| R15 read-only | `guest` role has no space grants; reads are plain `select` | served |
| — | **no write path is used at all**: the board never calls `insert`/`replace`/`update` | by design |

The two gaps are exactly the kind the contract predicts: a store written for a
different purpose will lack a declared capability descriptor and counters. The
board works because it needs neither — and it says so rather than pretending
the memory implements R6 or R12.

Roles, not kinds, are the mapping seam: `tool` carries the defect signal
(`status`), `lesson` the documented countermeasures, `outcome` the verdicts
with their attempt traces. A store that keeps these as separate record *kinds*
(as this repo's `models.py` does) satisfies the same requirement more cleanly
under R1 and R3.

---

## 7. Conformance suite (acceptance criteria)

An adapter is conformant when it passes `tests/test_plugin.py` under the shared
fixture parametrisation. The suite asserts, per backend:

1. `write`/`read` round-trip and idempotent overwrite (R1.4).
2. `read` of a missing id returns `None` and does not raise (R1.5).
3. `query` enumeration, equality filtering, deterministic ordering (R3).
4. `update` merge semantics and `None` on missing id (R4.1).
5. `delete` returns True once, False thereafter (R4.3).
6. Journal append/read/filter *if* `capabilities().append_only_journal` (R2).
7. `capabilities()` matches reality for `durable`/`transactional`/
   `temporal_versioning` (R6.1).
8. A full TBP cycle reaches the same outcome (`improved`, `check_passed`,
   `standard_version`, active-standard count) on every backend (portability).
9. Every discipline guard fires identically on every backend.
10. `close()` is idempotent and flushing.

For a read-only adapter (R15) the suite asserts instead:

1. The module contains no mutation call (`insert`/`replace`/`update`/`delete`/
   `truncate`/`upsert`) — asserted against the source, not by review.
2. No write method is exposed on the reader's public surface.
3. A credential holding a write grant is refused at connect time.
4. Reads are paged, and a read pass makes exactly one pass over the store.
5. Every figure produced is recomputable from the records read; quantities that
   cannot be derived are absent, not guessed.
6. A store with fewer records than the evidence threshold cannot set the
   standard or the goal.
7. An unreachable store is reported as unreachable; the consumer does not
   silently serve a fixture.
8. The steps of the cycle that need an actor are reported as not performed.

Adding a backend means: implement ten methods, register it with
`register_backend(name, factory)`, add it to the fixture parametrisation. Nothing
in the plugin or the loop changes. A read-only observer is a *consumer*, not a
backend: it implements no write path at all and therefore never claims to be a
store.

---

## 8. Traceability — requirement → Toyota principle

| Requirement | Toyota source |
|---|---|
| R1, R8 | Standard work; visual control (Principle 6, 7) |
| R2, R12 | Genchi genbutsu; andon (Principle 12, 5) |
| R3, R5 | Hansei and kaizen need a baseline and its history (Principle 14) |
| R6, R7 | Reliable technology that serves the process (Principle 8) |
| R9 | Yokoten, respect for partners (Principle 11) |
| R10 | Mizen-boushi: design the failure mode out; jidoka |
| R11 | Genchi genbutsu before acting: look before you leap |
| R13, N7 | Long-term philosophy: the store must outlive one release (Principle 1) |
| R14 | Nemawashi and honest reporting: evidence over assertion (Principle 13) |
| R15.1, R15.2 | Jidoka: a process that cannot act must not pretend to (Principle 5) |
| R15.4, R15.6 | Genchi genbutsu and hansei: see what is there, admit what is not (Principle 12, 14) |
| R15.5 | Standard work: the observer's job is defined, and excludes acting |
| R15.7 | Muda discipline: do not let a small sample set a target |
| R15.8 | Visual control: a degraded signal must be visible, never hidden |
