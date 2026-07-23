# OpenStudio × Dutch Public Sector (Organisatie X) — Regulatory Compliance Mapping · v1
### Companion document to PROJECT_SPEC.md (v4) · Status of law verified 22 July 2026

> **Scope & disclaimer.** This document maps the OpenStudio platform (as specified in
> PROJECT_SPEC.md v4) to the regulatory stack applicable to Organisatie X as a Dutch ZBO deploying
> data/AI systems. It is an engineering compliance-by-design mapping, **not legal advice**;
> Organisatie X's FG (DPO), CISO, privacy office and legal counsel must validate every conclusion.
> Items marked ⏳ were in legislative motion in mid-2026 and must be re-verified before
> production use.

---

## 1. Organisatie X's regulatory stack (what applies and why)

| Instrument | Type | Why it applies to Organisatie X + this platform |
|---|---|---|
| **GDPR/AVG + UAVG** | EU regulation + NL implementation | Core processing of benefit recipients' personal data (incl. BSN, health-adjacent data for WIA/ZW) |
| **EU AI Act** (Reg. 2024/1689, as amended by the **Digital Omnibus on AI**, adopted June–July 2026) | EU regulation | Annex III 5(a) lists AI used by public authorities to evaluate eligibility for public assistance benefits — Organisatie X's core business. High-risk (Annex III) obligations now apply from **2 Dec 2027**; prohibitions + AI-literacy already apply since **2 Feb 2025**; GPAI rules since **2 Aug 2025** |
| **BIO2 v1.3** (Staatscourant 5 Mar 2026) | Government information-security baseline (ISO 27001:2023 / 27002:2022 elaboration) | Binding norm framework for all government layers; ZBOs bound via ministerraad besluit / circulaire even where exempt from Cbw |
| **Cyberbeveiligingswet (Cbw) + Wwke** (NIS2/CER implementation) | NL law, **in force 15 Aug 2026** | Zorgplicht (implemented for government via BIO2 in the Cyberbeveiligingsregeling sector Overheid), meldplicht, registration, board accountability |
| **ISO/IEC 42001:2023 (AIMS)** + ISO/IEC 23894, 42005:2025, 42006:2025 | Voluntary international management-system standard (certifiable) | The AI twin of the ISO 27001 ISMS underlying BIO2; leading certifiable AI-governance framework and audit anchor for the Algoritmekader route; **not** an AI Act harmonised standard — see §3.11 |
| **Wet SUWI + Besluit/Regeling SUWI** | NL law | Organisatie X's institutional law: task delineation, data exchange (Suwinet/GeVS), purpose binding, security & accountability requirements |
| **Materiewetten** (WW, WIA, WAO, ZW, Wajong, Toeslagenwet, IOW, WAZO…) | NL law | Define the decisions the platform's outputs may feed; determine lawful bases (Art 6(1)(c)/(e) AVG) |
| **Awb** (Algemene wet bestuursrecht) | NL law | Zorgvuldigheid (3:2), evenredigheid (3:4), **motivering** (3:46-47) for every besluit — including algorithm-supported ones; reconstructability of decisions |
| **Wabb** (BSN law) | NL law | Rules for processing the citizen service number |
| **Woo** (open government) + **Algoritmeregister** policy | NL law + cabinet policy | Active disclosure; Rijksoverheid commitment to register impactful algorithms **by end 2026**; privacy statements must mention automated risk selection **by 31 Dec 2026**. No statutory register duty (Sept 2025 decision) — instead an auditable Algoritmekader; ⏳ draft **Kaderwet Toetsing Algoritmen** (discrimination testing + publication) in consultation |
| **Archiefwet** | NL law | Retention/destruction per selectielijst; sustainable accessibility of records |
| **Besluit digitale toegankelijkheid / EN 301 549 (WCAG 2.1 AA)** | NL decree / EU standard | All government web interfaces — Studio (staff) and Hub (if citizen-facing, strictly) |
| **NORA + Forum Standaardisatie 'pas-toe-of-leg-uit'** | Binding architecture agreements + mandatory open standards | Reference architecture principles; mandatory standards (HTTPS/HSTS, TLS per NCSC, OpenAPI, REST-API Design Rules, NLGov OAuth/OIDC profiles, DNSSEC, Digikoppeling where chained) |
| **Rijksbreed cloudbeleid + implementatiekader** | Cabinet policy | Risk assessment before (public) cloud; data sovereignty direction — favors self-hosting |
| **ECHR Art 8 / EU Charter** + SyRI ruling (Rb. Den Haag 2020) | Fundamental rights case law | Hard limits on opaque risk profiling of benefit recipients |
| **CRA (Cyber Resilience Act)** ⏳ phased 2026-2027 | EU regulation | Relevant to OpenStudio as distributed software (open-source steward regime); light for Organisatie X as deployer |

## 2. Role & risk analysis under the AI Act

**Platform vs. system.** OpenStudio itself is a general-purpose AI *toolchain*; the AI Act
attaches to the **AI systems built on it** (agents, models, risk-selection flows). Compliance
must therefore be enforced **per agent/model**, which is exactly how the platform's
certification, evaluation and deployment gates are scoped (SPEC §5c, §7 Phase 7).

**Organisatie X's roles.**
- *Deployer* of AI systems (Art 26 duties) — always.
- *Provider* (Art 16 ff.) — likely, wherever Organisatie X develops agents/models in-house for its own
  use in a high-risk context, or substantially modifies/fine-tunes third-party models
  (Art 25). Assume provider duties for anything touching benefit decisions.
- *GPAI*: upstream LLM vendors carry GPAI-provider duties; the platform must **record** which
  models/versions/providers were used per output (mesh ledger + traces make this automatic).

**Risk classes to expect at Organisatie X.**
- **Prohibited (design out, Art 5)**: social scoring; untargeted scraping; emotion recognition
  at work; the Omnibus adds a ban on AI-generated non-consensual intimate imagery/CSAM. The
  SyRI judgment and Organisatie X's own *Risicoscan Verblijf Buiten Nederland* affair (covert web
  tracking of WW recipients; AP-supervised remediation; 703 decisions reversed) define the
  bright lines: **no covert data collection, no profiling without a specific lawful basis,
  no opacity.** Platform enforcement: connections require a registered legal basis + purpose
  (CP-2); guardrail policies block scraping-type tools on citizen data by default.
- **High-risk (Annex III 5(a))**: anything evaluating eligibility, granting, reducing,
  revoking or reclaiming benefits — full Chapter III regime from **2 Dec 2027**.
- **Limited risk (Art 50)**: Answers/Hub chatbots → AI-interaction disclosure; generated
  content marking (legacy-system marking grace period to **2 Dec 2026**).
- **Minimal risk**: internal productivity agents — still under BIO2, AVG, Awb.

## 3. Framework-by-framework mapping
Legend: ✔ covered by SPEC v4 · ◐ partial · ✚ addition required (see §5 Compliance Pack).

### 3.1 GDPR / AVG + UAVG

| Obligation | Platform mapping | Status |
|---|---|---|
| Lawfulness, purpose limitation (Art 5, 6) | Legal-basis + purpose registry on connections/datasets; purpose-compatibility check in recipes/tools | ✚ CP-2 |
| Data minimisation | Column-level selection in recipes; classification tags drive "need-to-use" prompts | ◐ CP-1 |
| Special categories (Art 9) & BSN (Wabb) | Classification tags (bijzonder/BSN); mesh policy: tagged data never leaves EU/local models; Presidio redaction in guardrails (SPEC §3.2) | ◐ CP-1/11 |
| Transparency (Art 13-14) + risicoselectie in privacyverklaring (per 31-12-2026) | Algorithm cards + register export feed the privacy statement | ✚ CP-5 |
| Data-subject rights (Art 15-22) | Lineage graph answers "where is this person's data"; DSAR export job | ◐ CP-3 |
| Art 22 + UAVG art 40 + Awb | No solely automated adverse decisions: human-approval nodes, override-with-reasons, meaningful-intervention evidence per AP's 2025 *Handvatten betekenisvolle menselijke tussenkomst* | ✔ + CP-10 |
| DPbD (Art 25) | Least-privilege tool broker, permission passthrough (§5c/§5e), sandbox without ambient creds | ✔ |
| RoPA (Art 30) | Auto-derived from projects/connections/datasets/purposes | ✚ CP-4 |
| Security (Art 32) | → BIO2 mapping (§3.3) | ✔/◐ |
| Breach (Art 33-34) | Incident & breach register with 72h timers | ✚ CP-8 |
| DPIA (Art 35; AP list incl. risk selection) | DPIA workflow object attached to projects/agents; gate before deploy | ✚ CP-4 |
| Processors/transfers (Art 28, 44+) | Self-hosted core = minimal processors; external LLM APIs are the transfer risk → sovereignty mode (EU/local-only per classification) | ◐ CP-11 |

### 3.2 EU AI Act (as amended by the Digital Omnibus on AI, 2026)

| Obligation (high-risk unless noted) | Platform mapping | Status |
|---|---|---|
| AI literacy — Art 4 (since 2-2-2025, all systems) | Role-based in-product training mode + competence attestation log | ✚ CP-10 |
| Prohibitions — Art 5 (since 2-2-2025; Omnibus adds NCII/CSAM ban) | Design-out list; guardrail policies; prohibited-pattern checks in agent review | ✔/◐ |
| Risk management — Art 9 | Agent lifecycle gates + risk classification field + linked FRIA/DPIA | ✚ CP-4 |
| Data & data governance — Art 10 | Lineage, dataset metrics & checks, quality gates, provenance in traces | ✔ |
| Technical documentation — Art 11/Annex IV | Auto-generated model/agent cards from spec metadata, evals, lineage | ✚ CP-5 |
| Record-keeping/logs — Art 12 + Art 19 | OTel trace store; append-only, hash-chained | ✔ + CP-7 |
| Transparency & instructions for use — Art 13 | Agent cards incl. capabilities/limitations; in-UI instructions | ✚ CP-5 |
| Human oversight — Art 14 | Human-approval nodes, 4-eyes config, override capture, blind-assessment mode | ✔ + CP-9/10 |
| Accuracy, robustness, cybersecurity — Art 15 | Eval framework (golden sets, judges), drift monitoring, injection red-team sets (§5d), BIO2 controls | ✔ |
| Deployer duties — Art 26 (incl. **log retention ≥ 6 months**, input-data control, monitoring, informing affected persons/workers) | Retention policies on traces/ledger (default ≥ 6 mo, configurable longer per Archiefwet), monitoring dashboards, notice templates | ✔ + CP-7 |
| **FRIA — Art 27** (public bodies, before first use) | FRIA workflow object (IAMA-compatible template) gating deployment; notification artifact for the market-surveillance authority | ✚ CP-4 |
| Registration — Art 49(3)/71 (public-authority deployers → EU database) | Register-export (EU DB fields + NL Algoritmeregister metadata standard v1.x) | ✚ CP-5 |
| Right to explanation — Art 86 | Motivering bundle: semantic plan + trace excerpt + model card per decision | ✔ + CP-5 |
| Limited-risk transparency — Art 50 (chatbot disclosure; content marking, legacy grace to 2-12-2026) | AI-interaction banners in Answers/Hub; marking hooks on generated artifacts | ✚ CP-6 |
| Timeline (Omnibus): Annex III → **2 Dec 2027**; Annex I embedded → 2 Aug 2028 | Compliance-pack items scheduled well before 2-12-2027 | plan |

### 3.3 BIO2 v1.3 + Cbw (NIS2)

BIO2 = the government elaboration of ISO 27001:2023 (ISMS) + ISO 27002:2022 (controls); under
the Cbw (in force **15 Aug 2026**) it becomes the statutory fill-in of the zorgplicht via the
Cyberbeveiligingsregeling sector Overheid. Platform mapping to the control families that an
assessment will probe first:

| BIO2/ISO 27002:2022 area | Platform mapping | Status |
|---|---|---|
| 5.9-5.14 Asset mgmt & information classification | Dataset/column classification labels (BBN/persoonsgegevens/BSN) surfaced across UI, exports, tools | ✚ CP-1 |
| 5.15-5.18, 8.2-8.5 Access control & privileged access | OIDC (Keycloak), project RBAC, per-tool scopes, permission passthrough, periodic access-recertification report | ✔ + CP-2 |
| 5.19-5.23 Supplier relationships (incl. OSS) | License policy (SPEC §3.1), SBOM per release, signed images, dependency/vuln scanning, VDP/security.txt | ✚ CP-12 |
| 5.24-5.28 Incident management (+ Cbw meldplicht: early warning 24h / notification 72h / final report) | Incident & breach register with timers + export to the central meldloket; security-event webhooks | ✚ CP-8 |
| 5.29-5.30, 8.13-8.14 Continuity & backup | Versioned datasets, Postgres/object-store backup runbooks, restore drills in ops docs | ◐ |
| 8.8-8.9 Vulnerability & configuration mgmt | Pinned deps, CI scanning, hardened compose/Helm baselines, NCSC TLS presets | ✚ CP-12/14 |
| 8.12 Data leakage prevention | Guardrail pipeline (Presidio PII, denylists) on every mesh call; egress allowlists on tools. **Phase 2 note:** the ✔ excludes v1 Python code-recipes until container isolation lands — the subprocess sandbox denies network (`unshare -n`, Linux) but is not a hard boundary, so a compensating control blocks Python recipes on `bsn`/`bijzonder`/`bbn3`-labelled inputs (ADR-0007 §5). | ◐ |
| 8.15-8.17 Logging, monitoring, clock sync | Append-only audit + ledger + traces; SIEM/syslog export; NTP in infra baseline | ✔ + CP-7 |
| 8.24 Cryptography | TLS everywhere, secrets encrypted at rest (Fernet→KMS option), hashed tokens | ✔/◐ |
| 8.25-8.31 Secure development | SPEC §8 conventions, ADRs, code review, e2e + injection test sets | ✔ |
| ISMS (27001): scope, risk assessment, Statement of Applicability, management review | Organisational — platform supplies evidence (control dashboards, audit exports) | org |

### 3.4 NORA + open standards (pas-toe-of-leg-uit) + Wdo

| Requirement | Platform mapping | Status |
|---|---|---|
| HTTPS+HSTS, TLS per NCSC guidelines, DNSSEC | Infra presets in compose/Helm + deployment checklist | ✚ CP-14 |
| OpenAPI + NL REST-API Design Rules (ADR) | OpenAPI already the source of truth (SPEC §3.2); ADR-linting in CI for public APIs | ✚ CP-14 |
| NLGov OAuth/OIDC profiles | Keycloak realm preset conforming to NL profiles; DigiD/eHerkenning reachable via OIDC brokering (e.g., routing through the government's brokering services) if citizen/company login is ever needed | ✚ CP-14 |
| Digikoppeling / ketenkoppelingen | Out of core scope; connector layer (dlt/custom) can implement per integration | note |
| NORA principles (reuse, standard-where-possible, transparent, secure, accountable services) | Open-source reuse, open standards, audit trail, algorithm cards, published documentation | ✔/◐ |

### 3.5 Wet SUWI / Suwinet & Wabb (BSN)

| Requirement | Platform mapping | Status |
|---|---|---|
| Doelbinding of SUWI-domain data; only task-necessary consultation | Purpose codes on connections/datasets enforced at query time; agents/tools carry allowed-purpose sets | ✚ CP-2 |
| Suwinet-style accountability: logging of consultations, authorization matrices, usage reports | Query-reason capture on person-level lookups; per-user consultation reports; access recertification exports | ✚ CP-2 |
| BSN processing (Wabb) | BSN tag class; pseudonymization service (BSN → surrogate) for analytics/ML; raw BSN never to LLMs (mesh policy) | ✚ CP-1/11 |

### 3.6 Awb — algorithm-supported besluiten

| Requirement | Platform mapping | Status |
|---|---|---|
| Motivering (3:46-47) & reconstructability | Decision bundle per output: semantic **plan** (never model-written SQL, §5e), trace excerpt, model/agent card version, data lineage snapshot | ✔ + CP-5 |
| Zorgvuldigheid/evenredigheid; meaningful human intervention (AP 2025 handvatten) | Approval nodes with full context, override-with-reasons, competence attestation, workload analytics (detect rubber-stamping) | ✚ CP-10 |
| Non-discrimination in risk selection (College toetsingskader; ⏳ Kaderwet Toetsing Algoritmen) | Fairness grader pack (group metrics, reference-group tests), **blind-assessment mode** (configurable % random injection into worker queues — the practice the Algemene Rekenkamer highlighted positively at Organisatie X's Risicoscan Verwijtbare Werkloosheid) | ✚ CP-9 |

### 3.7 Woo + Algoritmeregister · 3.8 Archiefwet · 3.9 Toegankelijkheid

| Requirement | Platform mapping | Status |
|---|---|---|
| Register impactful algorithms (Rijk: by end 2026); metadata standard | One-click export of agent/model cards to the Algoritmeregister schema; publication-safe redaction (anti-gaming fields) | ✚ CP-5 |
| Woo active disclosure & requests | Algorithm cards, DPIA/FRIA summaries and eval reports maintained Woo-ready | ◐ CP-4/5 |
| Archiefwet retention/destruction (selectielijst) & sustainable access | Retention schedules per dataset/trace class; automated destruction with signed verslag; open export formats | ✚ CP-3 |
| WCAG 2.1 AA / EN 301 549 + toegankelijkheidsverklaring | SPEC §6.4 already mandates AA + keyboard-complete; add automated a11y test suite in CI and a statement generator | ✔ + CP-13 |

### 3.10 Cloud, sovereignty & CRA

Self-hosting on permissive OSS is itself the compliance feature: it satisfies the rijksbrede
cloudbeleid risk posture, removes third-country processors from the core, and the mesh's
**sovereignty mode** (CP-11: provider allowlists keyed to data classification; local vLLM/
Ollama for anything tagged personal/BSN/special-category) contains the only genuinely
transfer-risky flow — external LLM APIs. CRA ⏳: as an open-source project OpenStudio falls
under the light "open-source steward" regime; if Organisatie X (or anyone) commercializes distribution,
manufacturer duties (CE, vulnerability handling, reporting) attach — record this in an ADR.

### 3.11 ISO/IEC 42001 — AI management system (AIMS)

**Status in the EU landscape (verified July 2026).** ISO/IEC 42001:2023 is the certifiable
management-system standard for AI (clauses 4-10 plan-do-check-act + Annex A: 38 controls in
nine objective areas). It is being adopted as a European standard (prEN ISO/IEC 42001,
enquiry ran 20 Nov 2025 – 12 Feb 2026) — but it is **not** the AI Act harmonised standard:
the Commission judged its goals and definitions not aligned with the Act's quality-management
requirements and requested a dedicated standard, **prEN 18286** ("AI — Quality management
system for EU AI Act regulatory purposes", publication expected by Q4 2026), which builds on
42001 and includes mapping annexes to ISO/IEC 42001 and ISO 9001. The first JTC 21 harmonised
standards are expected in 2026, and only after Commission review + citation in the Official
Journal do they confer presumption of conformity (Art 40). Practical consequence for Organisatie X:
implement 42001 **now** as the governance umbrella (it is certifiable today under accredited
schemes per ISO/IEC 42006:2025, with ISO/IEC 23894 for AI risk management and ISO/IEC
42005:2025 for AI impact assessment plugging into it), and treat EN 18286 + the harmonised
set (risk management, data governance, record-keeping, transparency, human oversight,
accuracy, robustness, cybersecurity, QMS, conformity assessment) as the
compliance-presumption layer to adopt once cited.

**Why it fits Organisatie X.** BIO2 already presumes an ISO 27001-style ISMS; 42001 is designed to
integrate with 27001 into one management system — one governance rhythm (risk assessment,
Statement of Applicability, internal audit, management review) covering information security
AND AI. It is also the natural audit anchor for the Dutch "auditable Algoritmekader" route
(§1), giving IT-auditors a recognized normative baseline.

| 42001 Annex A objective area | Platform mapping | Status |
|---|---|---|
| A.2 AI policies | Guardrail & mesh policies as enforceable objects; platform policy docs via ADRs | ✔/org |
| A.3 Internal organization (roles, reporting of concerns) | §6 operating model; approvals queue; append-only audit | org + ✔ |
| A.4 Resources (data, tooling, compute, human competence) | Mesh model registry, code envs, dataset catalog; competence attestation | ✔ + CP-10 |
| A.5 Assessing impacts of AI systems | DPIA/FRIA/IAMA workflow objects, 42005-aligned templates, deployment gates | ✚ CP-4 |
| A.6 AI system life cycle | Agent lifecycle (draft→review→approved→deployed), versioning, evals/golden sets, traces, drift monitoring, incident register | ✔ + CP-8 |
| A.7 Data for AI systems (provenance, quality, preparation) | Lineage graph, dataset metrics & checks, classification/purpose tags | ✔ + CP-1/2 |
| A.8 Information for interested parties | Algorithm cards + register export, Art 50 disclosures, breach communications | ✚ CP-5/6/8 |
| A.9 Responsible use of AI (intended use, human oversight) | Human-approval nodes, four-eyes, override-with-reasons, prohibited-pattern review | ✔ + CP-10 |
| A.10 Third-party & customer relationships | Mesh provider/model-version records (GPAI upstream), SBOM & supplier controls | ✔ + CP-12 |

## 4. Consolidated compliance matrix

| Framework | Bite date | Heaviest obligations | Platform readiness (with Compliance Pack) |
|---|---|---|---|
| AVG/UAVG | in force | DPIA, Art 22/40, RoPA, transfers | Strong: passthrough, guardrails, lineage + CP-1/2/3/4/11 |
| AI Act — prohibitions & literacy | 2 Feb 2025 | Art 5 design-out, Art 4 literacy | Strong + CP-10 |
| AI Act — Art 50 transparency | (legacy marking grace to 2 Dec 2026) | Chat disclosure, content marking | CP-6 |
| AI Act — Annex III high-risk | **2 Dec 2027** | Art 9-15, 26, 27 FRIA, 49 registration, 86 explanation | Core evidence machinery exists (traces, evals, gates); CP-4/5/7 close the gaps |
| BIO2 v1.3 | now (verplichtende zelfregulering) | ISMS + 27002 controls | Good technical-control coverage; CP-1/7/8/12/14 + ISMS (org) |
| Cbw/NIS2 | **15 Aug 2026** | Zorgplicht (=BIO2), meldplicht 24h/72h, board accountability | CP-8 + org processes |
| ISO/IEC 42001 (+23894/42005/42006) | voluntary; certifiable now | AIMS clauses 4-10, Annex A controls, AI risk & impact assessment | Platform is the evidence layer; CP-15 packages it; integrate with the BIO2/27001 ISMS |
| Wet SUWI/Suwinet, Wabb | in force | Doelbinding, consultation logging, BSN discipline | CP-1/2 |
| Awb | in force | Motivering, meaningful human intervention | Native (plans/traces/approvals) + CP-9/10 |
| Woo/Algoritmeregister | Rijk deadlines end 2026 | Registration of impactful algorithms; privacy-statement mention of risk selection | CP-5 |
| Archiefwet | in force | Retention/destruction, sustainable access | CP-3 |
| Toegankelijkheid | in force | WCAG 2.1 AA/EN 301 549 | §6.4 + CP-13 |
| NORA/Forum Standaardisatie, Wdo | in force | Open standards, NL API/OIDC profiles | CP-14 |

## 5. The Compliance Pack — additions to PROJECT_SPEC.md

Fourteen concrete features; suggested phase placement in brackets. Add to SPEC as a new
**§3.2 block "Compliance (LOCKED)"** plus per-phase AC lines; none of them conflict with
existing LOCKED choices — most extend objects that already exist.

- **CP-1 Classification & tagging** [P1]: dataset/column labels (persoonsgegevens, bijzonder,
  BSN, BBN-level, confidentiality); propagate through lineage; surfaced in UI, exports, tools.
- **CP-2 Purpose binding & legal-basis registry** [P1]: connections/datasets carry legal basis
  + purpose codes; recipes/tools declare purposes; incompatible use blocks with an explained
  error; person-level lookups capture a query reason (Suwinet-style); recertification reports.
- **CP-3 Retention & disposal engine** [P8]: retention class per dataset/trace/audit stream
  (selectielijst code); scheduled destruction jobs producing signed vernietigingsverslagen;
  DSAR export job.
- **CP-4 Assessment workflows** [P7]: DPIA / FRIA / IAMA objects with templates, owners,
  status; linked to projects/agents; deployment gate: high-risk agents require approved
  FRIA + DPIA + passing eval. RoPA auto-generated from metadata.
- **CP-5 Algorithm cards & register export** [P7]: Annex IV-shaped technical documentation
  auto-assembled (purpose, data, lineage, evals, oversight config, versions); exporters:
  NL Algoritmeregister metadata standard + EU AI database fields; publication-safe redaction;
  per-decision motivering bundle (plan + trace + card version) via API.
- **CP-6 AI transparency surfaces** [P4]: AI-interaction disclosure in Answers/Hub;
  machine-readable marking hooks for generated artifacts.
- **CP-7 Evidence-grade logging** [P0/P3]: hash-chained append-only audit; retention policies
  on traces/ledger (default ≥ 6 months, Archiefwet-configurable); SIEM/syslog(CEF) export;
  clock-sync note in infra baseline.
- **CP-8 Incident & breach register** [P8]: security events + datalek records with AVG 72h and
  Cbw 24h/72h/1-month timers, decision log, export to the central meldloket format.
- **CP-9 Fairness & blind assessment** [P7]: fairness graders (group metrics per the College
  voor de Rechten van de Mens toetsingskader risicoprofilering) as first-class eval graders;
  **blind-assessment mode** for risk-selection agents: configurable random-injection % into
  reviewer queues, with uplift reporting.
- **CP-10 Oversight conformance** [P7]: four-eyes configuration, reviewer competence
  attestation (AI-literacy log), override-with-reasons capture, rubber-stamping analytics
  (approval latency/variance), evidence export for "betekenisvolle menselijke tussenkomst".
- **CP-11 Sovereignty mode** [P3]: mesh policy engine keyed to data classification — e.g.,
  BSN/special-category prompts may only route to local (vLLM/Ollama) or EU-resident
  connections; per-connection residency metadata; hard-block with audit event.
- **CP-12 Supply-chain integrity** [P0/CI]: CycloneDX SBOM per release; cosign-signed images;
  dependency + license scan gates; security.txt + coordinated vulnerability disclosure policy.
- **CP-13 Accessibility conformance** [P0/§6]: automated EN 301 549/WCAG checks in CI on Hub
  and key Studio flows; toegankelijkheidsverklaring generator.
- **CP-14 NL standards presets** [P0/P3]: NCSC-conformant TLS config; NLGov OIDC/OAuth realm
  preset; REST-API Design Rules linting for public APIs; HSTS/DNSSEC deployment checklist.
- **CP-15 AIMS evidence pack (ISO/IEC 42001)** [P7]: control-to-evidence mapping (Annex A ↔
  platform artifacts) exportable for auditors; Statement-of-Applicability helper;
  internal-audit and management-review dashboards (AI risk register, incidents, eval
  regressions, drift, quota/guardrail events); designed to merge with the BIO2/27001 ISMS
  into one integrated management system, forward-compatible with prEN 18286 once cited.

**Gate for Organisatie X production**: a consolidated "Compliance hardening" milestone — all CP items
done, ISMS evidence exports live, FRIA/DPIA approved per deployed high-risk agent — must
complete before any citizen-affecting use, and in any case before **2 Dec 2027**.

## 6. Operating model — platform vs. organisation

The platform produces evidence; people own compliance. Minimum role wiring: FG/DPO (DPIA
approval, Art 22 oversight), CISO (BIO2/ISMS, Cbw meldplicht), AI-governance board (FRIA
sign-off, agent certification, register publication), business owner per agent (Art 26
deployer duties, worker/affected-person notices), auditors (ADR/IT-audit against the
Algoritmekader — the platform's control dashboards and exports are their working material).
If Organisatie X pursues ISO/IEC 42001 certification, the AI-governance board doubles as AIMS owner,
running one integrated 27001+42001 management cycle with shared internal audits.

## 7. Timeline of hard dates (verified 22 July 2026)

| Date | Event |
|---|---|
| 2 Feb 2025 | AI Act prohibitions + AI-literacy duty apply (in effect) |
| 2 Aug 2025 | GPAI obligations apply (in effect) |
| 5 Mar 2026 | BIO2 v1.3 in Staatscourant (verplichtende zelfregulering Rijk/provincies/waterschappen) |
| Jun–Jul 2026 | Digital Omnibus on AI adopted (EP 16 Jun, Council 29 Jun, signed 8 Jul); entry into force upon OJ publication |
| **15 Aug 2026** | Cbw + Wwke in force; BIO2 becomes statutory zorgplicht-invulling for government |
| 2 Dec 2026 | Art 50(2) marking applies to legacy systems; Rijk: impactful algorithms in Algoritmeregister + risicoselectie in privacy statements (31 Dec 2026) |
| **2 Dec 2027** | Annex III high-risk obligations apply (Organisatie X benefit-eligibility AI) |
| 2 Aug 2028 | Annex I embedded high-risk obligations apply |

## 8. Open items to re-verify (feed for deep research)
OJ publication date + final consolidated text of the Digital Omnibus; whether Organisatie X falls
directly under Cbw as public-administration entity or via the ZBO-circulaire route; Regeling
SUWI security/verantwoording details and current Suwinet normenkader version; status of the
Kaderwet Toetsing Algoritmen; Algoritmeregister metadata standard current version; AP
guidance updates (RAN 2026, meaningful-intervention handvatten); rijkscloudbeleid updates and
any sovereignty mandates affecting external LLM APIs; EN 301 549 revision status; CRA
steward-regime dates; publication and OJ-citation status of prEN 18286 and the first JTC 21
harmonised standards, plus NEN adoption of EN ISO/IEC 42001; Organisatie X-specific frameworks (Organisatie X
informatieplan, SZW selectielijst).
