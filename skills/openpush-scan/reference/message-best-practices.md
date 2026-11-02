# Message best practices

Reviewed 2026-09-08. Apply alongside recommendation-quality.md to new suggestions,
refreshes and AI rewrites. These are conversion hypotheses and editorial checks,
not promises of uplift or new runtime capabilities. Preserve the approved card layout.

## Editorial foundations

Lead with value, use behavioral relevance, choose the correct destination and
measure downstream actions. For push, use a 50-character title and 14–25-word
body as flexible writing targets, not platform limits. Shorter complete copy is
fine; inspect rendered personalization branches.

Keep in-app audience eligibility, display triggers and repeat frequency distinct.
Account for overlapping campaigns. Verify every proposed setting against
OpenPush's implementation; record unsupported behavior as a capability gap.

## User-facing language

Present these as OpenPush guidance. Do not mention external messaging providers,
research vendors or their documentation in suggestions, explanations, previews,
review reports or skill responses. Internal attribution belongs in repository
research notes, not generated user-facing content.

## OpenPush editorial rules (our adaptation)

1. Define one desired action, eligible audience and concrete player benefit before
   writing. Reject suggestions whose only justification is an unused event.
2. Push titles state value immediately. Bodies add a reason and next action, not
   another headline. Prefer plain language, no vague hype, all-caps or guilt.
   Put essential meaning before truncation; preview iOS, Android and Web as applicable.
3. In-app messages use a short benefit headline, one or two brief sentences and one
   primary action with an outcome label. Keep dismissal easy and copy understandable
   without artwork. Do not present a carousel for a single simple ask.
4. Choose the channel by context: push for a useful return outside the app, in-app
   for help during a relevant screen or safe pause. Do not interrupt active play
   or checkout. Missing screen signals are prerequisites, not inferred triggers.
5. Personalize the decision using approved current state. Record field source,
   freshness and fallback. Neutral copy may cover missing cosmetic fields;
   uncertain eligibility, expiry or completed actions must block the send plan.
6. Require a destination matching the promise. Never invent a deep link, reward,
   item name, remaining lives, discount or deadline. Urgency must be factual.
7. Check existing manual/API/local sends before recommending anything. Coordinate
   overlapping channels; specify completion suppression, quiet hours and frequency
   intent. Do not choose a universal numeric cap or best send hour without evidence.
8. Journeys require behavioral checks or exits. Follow-ups need new context; stop
   after completion and verify user/entity correlation. Preserve these in AI edits.
9. Keep one concise game-specific impact sentence below the suggestion title.
   Store evidence and test plans in review notes; do not add a verbose checklist
   to the card or generate multiple player previews.
10. Define one conversion event, observation window and denominator before testing.
    Compare eligible cohorts and vary one major factor at a time. Use a holdout
    where supported; watch dismissals, opt-outs and repeat engagement. Do not infer
    causality from clicks, influenced opens, tiny samples or cross-channel CTR.

## Worked example: a casual puzzle game

- Daily puzzle unlock: encourage the first attempt; exclude players who already
  tried it. Use a supported puzzle-start/completion signal or mark the gap.
- Booster upgrade: invite the player to use the upgraded booster in their next level.
  Do not claim extra power or a specific item name unless verified and renderable.
- Hard level failed: suggest trying a different approach; no failure-shaming or
  invented reward. Suppress once the player retries or completes it, with the same
  level identity.
- In-app guidance belongs on a relevant menu after the level, not during play.
  An existing event does not prove that a corresponding display trigger exists.
- Purchase thank-you with a coupon duplicates the supplied program. Existing lives,
  daily-reward, streak and store reminders are coverage, not fresh ideas.

## Review decision

Before proposing or rewriting, check: grounded benefit; single action; correct
channel; renderable personalization; matching destination; eligibility/completion;
frequency overlap; useful measurement. Revise copy failures. Mark unsupported
behavior as setup required. Abstain when there is no additional user value.

Prompt guidance improves outputs but does not itself validate claims or enforce
suppression at delivery.
