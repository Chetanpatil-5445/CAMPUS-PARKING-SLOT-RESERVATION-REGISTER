# KLE Technological University — Department of BCA
## Course: 24BCAP205 Foundation Integration Course (Mini Project Framework)
### Theme 1: Rule-Checked Records Register
**Core Viva Review Challenge:** *"Where is this rule checked, and what stops someone skipping it?"*

---

## Developer Deliverable Dossier: Week 1 (Gate 0: Problem Formulation & Scaffolding)

| Field | Detail |
| :--- | :--- |
| **Developer Name** | **Chetan Patil** |
| **Institutional USN** | `01FE24BCA299` |
| **Team Role** | **Member 2 (Logic Lead)** |
| **Assigned Engine** | **Engine 2: Logic & Rule (DS & Programming)** |
| **Subject Alignment** | **Data Structures & Programming (DSP / DSA)** |
| **Academic Week** | **Week 1** (Gate 0: Problem Formulation & Scaffolding) |
| **Review Gate & Marks** | **Gate 0: Problem Formulation & Scaffolding** — Weight: 05 / 50 Marks |
| **Git Milestone Tag** | `v0.1.0` |
| **Feature Branch** | `feature/dev2-w1-logic-scaffolding` |
| **Standardized Commit** | `[Dev-2] P1: Scaffold Engine 2 rule definitions and non-short-circuiting accumulator interfaces` |

---

### 1. Primary Technical Deliverables
FailureReason dataclasses, business rule interfaces, initial temporal boundary evaluation drafts.

### 2. File Ownership & Artifacts Included in this Submission
- `cpsrr-core-engine/app/rules/__init__.py`
- `cpsrr-core-engine/app/rules/engine.py`

---

### 3. Multi-Tier Anti-Bypass Triad Verification
- **Tier 1 (Interface Layer):** Client-side form validations and feedback preventing invalid submissions before reaching the network.
- **Tier 2 (Logic Layer):** Engine 2 non-short-circuiting ReasonList accumulator evaluating business constraints with comprehensive diagnostic reporting.
- **Tier 3 (Data Layer):** Relational 3NF SQLite database constraints, foreign key restrictions (`ON DELETE RESTRICT`), and append-only immutable audit triggers.

---

### 4. Viva Defense Key Questions & Answers for Chetan Patil (Dev-2)
**Q: What is your primary architectural responsibility in CPSRR?**  
*A: I lead Engine 2: Logic & Rule (DS & Programming), aligned with Data Structures & Programming (DSP / DSA). My responsibility for Week 1 was to deliver FailureReason dataclasses, business rule interfaces, initial temporal boundary evaluation drafts.*

**Q: Where is your rule checked, and what stops someone skipping it?**  
*A: The system implements an unbypassable Multi-Tier Anti-Bypass Triad. Even if an attacker circumvents the client UI and invokes the REST API directly or opens a database session, Tier 2 (ReasonList accumulator) and Tier 3 (database foreign keys and check constraints) reject the invalid state.*

---
*Generated: 2026-10-04 15:00:42 · KLE Technological University, Hubballi*
