# ADR-0006: redis-py Streams directly; no task-queue framework

**Status:** Accepted · 2026-07-10 · **Level:** L2

## Context
The inbox between Receiver and Intelligence needs at-least-once delivery, burst absorption,
and replayability. Research (2026-07-10) compared raw redis-py against taskiq, streaq, arq,
and celery.

## Decision
Use redis-py Streams + consumer groups directly (XADD/XREADGROUP/XACK/XAUTOCLAIM). No task
framework.

## Options considered
1. **redis-py direct (chosen)** — PEL gives at-least-once; XAUTOCLAIM recovers dead consumers.
2. taskiq (+taskiq-redis RedisStreamBroker) — maintained (MIT, 2026-05), adds retries,
   scheduling, FastAPI DI; the only credible framework option.
3. streaq — Streams-native but 153 stars; adoption risk. arq — Redis Lists, maintainers say
   it "needs love". celery — sync-era heavyweight. All rejected.

## Trade-offs accepted
- **We gave up** free retry/backoff/scheduling semantics — ack/claim/redelivery policy is
  ~200 lines we own and must get right (idempotency by `event.id` is the safety net).
- **We kept** exact control of consumer-group semantics (the Governor's storm brake
  manipulates dequeue policy directly — awkward through a framework's abstraction) and one
  less load-bearing dependency.

## Revisit when
We need cross-machine workers, per-task retry policies, or scheduled jobs beyond
APScheduler's comfort — taskiq is the pre-selected upgrade path.
