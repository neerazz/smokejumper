# Incident scenarios S1–S4 — research receipt behind `architecture/scenarios/`

Date: 2026-08-29 · Companion to the four scenario diagrams. Every claim is READ (first-party page
fetched this session) or INFERRED (concordant secondary snippets; page blocked). 13 first-party
postmortems, 4 secondary, plus the AWS RDS metric reference and four product docs.

## 0. Verdict — three regularities across 16 incidents that shape the agent

1. **The first human signal was almost never the cause metric.** It was a synthetic / SLO / Apdex /
   5xx alert (Cloudflare ×3, GitLab, Slack) or a customer ticket / Sentry error (incident.io, Slack
   2022). Cause metrics were found 10–140 minutes later. → `symptom-classifier` and the hypothesis
   fan-out exist because the alert names the symptom, never the cause.
2. **The dominant red herring is "attack / traffic"** (Cloudflare 2019 and 2025 both suspected DDoS;
   GitLab 2017 spam; Roblox hardware), then **"scale up"** (Slack 2020: "didn't help at all";
   incident.io 2025: "net throughput regression"). → the verifier's first disproof is always "is
   RPS flat?"; the mitigation ranker never proposes scale-up before diagnosis.
3. **Fastest resolutions were reversions of a discrete change** (Cloudflare 2019 kill switch 2 min;
   GitHub Aug-2024 revert 36 min; Cloudflare 1.1.1.1 revert 19 min). **Slowest were saturation with
   no discrete trigger** (Roblox 73 h; incident.io pool 2 weeks / 24 deploys; CircleCI 2 weeks). →
   `change-correlator` first; `saturation-finder` must be able to say "no change happened".

**Weakest link, stated:** S1 has no first-party postmortem naming `BurstBalance` with a minute
timeline. The diagram is drawn from the AWS metric definitions (READ) and the closest analogs
(Honeycomb, GitLab 2026, Grafana Labs — all DB saturation by another mechanism) and says so in its
footer. Searched: danluu list (0 hits for burst|IOPS), Honeycomb archive, GitLab production tracker,
Sentry/Basecamp/Heroku, four web queries. Next probe: GitLab `gl-infra/production` search
`disk.*util|iops` (auth-gated views), SRE Weekly archive `burst balance`.

---

## S1 — API 5xx from DB I/O saturation

| Source | Status | What it gives |
|---|---|---|
| AWS RDS CloudWatch metric reference — https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-metrics.html | READ | exact names/units: `BurstBalance` (% gp2 credits), `EBSIOBalance%`, `EBSByteBalance%`, `ReadIOPS`/`WriteIOPS`, `ReadLatency`/`WriteLatency` (s), `DiskQueueDepth`, `DatabaseConnections`, `CPUCreditBalance` |
| Chen, RDS gp2 burst exhaustion, 2025-03-11 — https://chenyangl.medium.com/troubleshooting-an-aws-rds-outage-ebs-iops-to-the-rescue-1cce3fc9c3de | INFERRED (403) | balance dropped 10–12 h before; first signal = health-check crash loop; red herring CPU; fix gp2→gp3 |
| AWS re:Post, restart when EBS Bytes Balance exhausted — https://repost.aws/questions/QU991FNfi-S7Kg4p7dc6ifxg | INFERRED | throughput-credit variant |
| GitLab INC 2026-08-27 patroni-sec CPU — https://gitlab.com/gitlab-com/gl-infra/production/-/work_items/22807 | READ (partial) | seq scan over 483M rows → timeouts + 500s; fixed by `ANALYZE` (plan flip) |
| Honeycomb, RDS clogs & cache-refresh crash loops, 2023-07-25 — https://www.honeycomb.io/blog/postmortem-rds-clogs-cache-refresh-crash-loops | READ | SLO burn dismissed overnight; 13:40–14:48 (68 min); ladder used: circuit-break → failover → manual cache bump (introduced bad data) |
| Grafana Labs, tale of two incident responses — https://grafana.com/blog/a-tale-of-two-incident-responses-how-our-ai-assist-helped-us-find-the-cause-3-5x-faster/ | READ | unbounded join saturating connections + CPU; human 28 min, assistant 8 min |

**Causal chain (observable, in order):** balance ↓ for hours → IOPS flat at ceiling (gp2 3×GiB, min
100) → `DiskQueueDepth` ↑, latency ms→100s ms → `pg_stat_activity` wait `IO:DataFileRead`, mean
exec time up *uniformly* → `DatabaseConnections` → cap, pool wait ↑ → 504 / 503 / 500 → health
fails → restart → reconnect storm.

| Hypothesis | Validates | Invalidates |
|---|---|---|
| H1 storage credit exhaustion | balance ≈ 0 ∧ IOPS flat at ceiling ∧ latency up | balance > 20%; IOPS below ceiling |
| H2 single bad query / plan flip | one statement dominates `total_exec_time` delta; CPU high; queue depth normal | latency uniform across statements |
| H3 lock queue | `pg_locks` not granted; wait `Lock`; low CPU/IO | no lock waits |
| H4 connection storm (→ S3) | connections spike *before* IO latency | IO latency precedes connections |
| H5 T-class CPU credits | `CPUCreditBalance` = 0, CPU pinned at baseline | non-T class |

**Discriminating queries.** CloudWatch 1-min: the metrics above. SQL:
`SELECT wait_event_type, wait_event, state, count(*) FROM pg_stat_activity GROUP BY 1,2,3 ORDER BY 4 DESC;`
· `SELECT queryid, calls, mean_exec_time, shared_blks_read FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;`
· `SELECT count(*) FROM pg_locks WHERE NOT granted;`. PromQL: 5xx ratio, p99 histogram,
`hikaricp_connections_pending`, `rate(pg_stat_database_blks_read[5m])`.

**Mitigation ladder (reversible first):** shed / circuit-break → cancel statements, `ANALYZE` →
failover to replica → gp2→gp3 / provisioned IOPS (online, one-way) → scale class (restart).

---

## S2 — Bad deploy / config change → rollback

| Source | Status | Timeline |
|---|---|---|
| Cloudflare 2019-07-02 WAF regex — https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/ | READ | 13:42 deploy · 13:45 PagerDuty (synthetic) · 14:00 attack hypothesis dropped · 14:07 global kill · 14:09 recovered |
| Cloudflare 2025-11-18 Bot Management file — https://blog.cloudflare.com/18-november-2025-outage/ | READ | 11:05 permission change · 11:20 5xx · 11:31 detected · 13:37 cause · 14:30 restored; DDoS red herring; Rust `unwrap` panic |
| GitHub 2024-08-14 DB config — https://github.blog/news-insights/company-news/github-availability-report-august-2024/ | READ | 22:59 rollout · 23:02 detect · 23:38 revert · 36 min |
| GitHub 2024-03-15 framework upgrade — https://github.blog/news-insights/company-news/github-availability-report-march-2024/ | READ | 42 min; rollback; Mar-11 rollback partially failed in one DC |
| incident.io 2024-07-09 — https://status.incident.io/incidents/01J2C07AX938WEX1R0WDGF9KPM | READ | 15:21 deploy · 15:28 rollback · **15:56 pipeline re-deployed the bad change** · 16:00 |

**Causal chain:** change marker → 5xx step within 1–15 min → process symptom (CPU pinned / panic /
health-check failure) → errors segregate by version label, not traffic → dependents degrade (the
red herring).

| Hypothesis | Validates | Invalidates |
|---|---|---|
| H1 the change at T0 | errors by version; onset after marker; rollback restores | uniform across versions; onset precedes marker |
| H2 attack / surge | RPS or unique IPs step up first | RPS flat (both Cloudflare cases) |
| H3 dependency (S4) | dependency latency first | dependency healthy from other callers |
| H4 artifact drift, no code deploy | config hash/size changed at T0 | artifact unchanged |
| H5 rollback didn't take | fleet still on new version | fleet shows old |

**Queries:** deploy list / `kubectl rollout history` / flag audit;
`sum by(version)(rate(http_requests_total{code=~"5.."}[2m])) / sum by(version)(rate(http_requests_total[2m]))`;
`changes(kube_deployment_status_observed_generation[30m])`; `increase(kube_pod_container_status_restarts_total[10m])`;
`sum(rate(http_requests_total[1m]))` flat ⇒ not attack; logs `panic|unwrap|FATAL`.

**Ladder:** kill switch / flag → roll back artifact/config → roll back code **and verify fleet
version** → restart → forward-fix last.

---

## S3 — Connection / thread-pool exhaustion

| Source | Status | What it gives |
|---|---|---|
| incident.io, database-performance, 2023 — https://incident.io/blog/database-performance | READ | 2 weeks, 24 deploys; 20 s pool wait found by monkey-patching `database/sql`; cause: needless transaction on Slack modal |
| incident.io, clouds caches connections, 2023 — https://incident.io/blog/clouds-caches-and-connection-conundrums | READ | ~200 new conns/s; N+1 join → GKE `anetd` CPU; pool-tuning red herrings made it worse |
| Slack 2020-05-12 — https://slack.engineering/a-terrible-horrible-no-good-very-bad-day-at-slack/ | READ | DB alert 08:30 → 503s 16:45; scale-up "didn't help at all"; HAProxy slot sync |
| Slack 2022-02-22 — https://slack.engineering/slacks-incident-on-2-22-22/ | READ | cache flush → scatter query → metastable; throttle boots |
| Heroku lock-queue gist — https://gist.github.com/dwbutler/1034446c1aba231ca8d8639d3be78c6b | READ | 08:00:15 ALTER waits behind pg_dump → 08:06 pool exhausted → 08:25 cancel backup |
| GitLab 2023-10-30 — https://gitlab.com/gitlab-com/gl-infra/production/-/issues/17057 | READ | Apdex SLO alert; UPDATE storm on merge_requests; 48 min; admin toggle |
| CircleCI Mar 26–Apr 10 — https://discuss.circleci.com/t/postmortem-march-26-april-10-workflow-delay-incidents/30060 | READ | JVM minor upgrade shrank pools, masking Mongo lock contention |
| incident.io PGAudit 2025 — https://status.incident.io/incidents/01JRDFKAGE07YYDY0KZR137BX3/write-up | READ | extension ignored timeouts; primary restart |

**Causal chain:** trigger → per-request hold time ↑ → pool at cap, **pool wait** appears →
`cl_waiting` / `FATAL too many connections` → threads block → 502/503/504, `context canceled` →
retries amplify.

| Hypothesis | Validates | Invalidates |
|---|---|---|
| H1 lock queue | `pg_locks` ungranted, one blocker pid, low CPU/IO | none |
| H2 slow query / plan | one statement dominates; CPU up | uniform latency |
| H3 many small holds / N+1 / needless txn | pool wait high while every query fast; span count per request ↑ | few long queries |
| H4 pool config regression | runtime/config change; cap lower; DB idle | cap unchanged |
| H5 downstream / IO slow | wait `IO` or outbound latency first | DB waits fine |

**Queries:** `pg_stat_activity` by wait_event with `xact_age`; blocked/blocking `pg_locks` join;
pgbouncer `SHOW POOLS` (`cl_waiting`, `maxwait`); `hikaricp_connections_pending`,
`hikaricp_connections_acquire_seconds` p99; Go `go_sql_wait_duration_seconds_total`;
`pgbouncer_pools_client_waiting_connections`; `pg_stat_activity_count{state="idle in transaction"}`;
per-trace DB span count.

**Ladder:** throttle/shed → cancel blocker (`pg_cancel_backend`) → disable flag/job → rolling restart →
restart primary (last) → raise pool caps only after diagnosis (usually worsens).

---

## S4 — Upstream dependency / cert / DNS

| Source | Status | Timeline |
|---|---|---|
| AWS us-east-1 2025-10-19 DynamoDB DNS — https://aws.amazon.com/message/101925/ | READ | 23:48 onset · 00:38 root cause · 01:15 mitigations · 02:25 DNS restored; EC2 impaired to 13:50 |
| Cloudflare 1.1.1.1 2025-07-14 — https://blog.cloudflare.com/cloudflare-1-1-1-1-incident-on-july-14-2025/ | READ | 21:48 withdraw · 21:52 traffic drop · 22:01 alert · 22:20 revert · 22:54 restored; BGP hijack unrelated |
| Google Voice 2021-02-15 cert — via https://www.bleepingcomputer.com/news/google/recent-google-voice-outage-caused-by-expired-certificates/ | READ (secondary) | 4 h 22 min; only new SIP connections failed |
| Epic Games 2021-04-06 wildcard cert — https://www.epicgames.com/site/en-US/expiration-date-4-6-2021 | INFERRED | 12:00 expiry · 12:12 identified · 12:37 reissued; autoscaling deployed wrong version |
| Microsoft Teams 2020-02-03 cert — https://www.exoprise.com/2020/02/04/teams-outage-expired-certificate/ | INFERRED | alert 13:44 · diagnosed 13:56 · status post 14:13 |
| incident.io 2025-10-20 — https://incident.io/blog/service-disruption-october-20th-2025 | READ via summary | hit through transitive vendors (telecom queue ×30, Docker Hub) |

**Causal chain:** vendor change at T0, zero internal markers → **new** connections fail, keep-alives
survive → error rate ramps, not steps → `x509 expired` / `ENOTFOUND` / connect timeout in logs before
metrics → all callers of that host fail together → retries amplify → vendor status lags 20–40 min.

| Hypothesis | Validates | Invalidates |
|---|---|---|
| H1 vendor endpoint down / unresolvable | `dig` fails from multiple vantage points; status page; other tenants | resolves externally |
| H2 cert expired | `openssl s_client` `notAfter` < now; only new sessions fail | cert valid |
| H3 our egress / resolver / SG | one VPC/AZ only | global across our vantage points |
| H4 our deploy (S2) | marker at T0 | none |
| H5 vendor rate limit | 429 + `Retry-After` | connect / 5xx errors |

**Queries:** `dig +short host @1.1.1.1` and `@8.8.8.8`; `openssl s_client -connect host:443 -servername host | openssl x509 -noout -dates`;
`curl -sv` from ≥2 regions; `probe_ssl_earliest_cert_expiry - time()`; `probe_success`;
`sum by(host)(rate(http_client_requests_seconds_count{status=~"5..|0"}[2m]))`; logs
`x509|certificate has expired|ENOTFOUND|EAI_AGAIN`; change events: confirm zero.

**Ladder:** fail open / flag off → route around (secondary vendor, pinned IP) → renew cert if ours →
widen timeouts, retry budgets → wait on vendor, freeze autoscaling actions.

**Contract consequence:** the correct verdict here is `not_actionable`, which B6 does not have today
(see `2026-08-29-reference-architecture-analysis.md` §4).

---

## How the four surveyed products describe these cases (READ)

- **Grafana Assistant Investigations** — hypothesis states `open / root cause / symptom / disproven /
  blocked`; example prompt "check for database locks"; the blog's real incident was an unbounded join
  (8 min vs 28 min). Harness post (INFERRED, blocked): "The harness asks for the trigger (deploy,
  config change, credential expiry, capacity exhaustion, dependency outage)" — a taxonomy that maps
  1:1 onto S2 / S4 / S1 / S3.
- **Datadog Bits** — hypotheses validated / invalidated / inconclusive; sources include Change
  Tracking, GitHub, database monitoring; published worked example is Kafka, where 12 correlated
  signals were non-causal.
- **Cleric** — worked S3: "Connection pool at 95/100 capacity … error logs show connection failures
  starting exactly when pool usage hit 95%"; warns that a deploy correlating with CPU was *not* the
  cause once.
- **Resolve AI** — worked S2+S3: latency 120 ms → 1.8 s; "connection pool utilization at 96%";
  recommendation "roll back the deployment or adjust the connection pool configuration".

None publishes an IOPS / burst-balance example. Resolve and Cleric centre "pool at 9x%"; the pool
*wait* metric is sharper and rarer. Grafana alone forces a trigger classification. Those two gaps
are the S1 and S3 lanes Smokejumper owns.
