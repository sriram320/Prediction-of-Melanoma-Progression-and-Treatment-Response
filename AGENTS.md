# MelanoTrack — Agent Rules

- Before doing any work in this repository, read the project skill:
  `.agents/skills/melanotrack-platform/SKILL.md`. It holds the locked stack decisions, safety invariants,
  schema/API/model contracts and the implementation status table.
- After completing a phase or changing a locked decision, update the **Implementation status** and
  **Open questions** sections of that SKILL.md, and keep `docs/Implementation_Document.md` consistent.
- Never weaken the safety invariants (referral flag ⇒ no category, fail-safe to referral, patients see only
  released reports, hospital scoping, append-only audit). Ask the user first.
- Never commit `.env`, `storage/`, or model weights in `ml_service/models/`.
