# LinkedIn post drafts

Fill the `[ ]` slots with your own words; the numbers come from the synthetic demo dataset, so say so. Attach the demo video
(native upload) or `apps/dashboard/public/og.png` / `docs/screenshots/overview-dark.png`. Put links in the **first comment**,
not the post body (LinkedIn reach is better that way). Do not paste the same text everywhere: pick one draft.

## Draft A: the insight (recommended)

AI agents are already shopping on your site. Your analytics cannot see them.

ChatGPT agent, Claude, Gemini and Perplexity browse and buy for people, and most never run your GA4 tag. So I built
AgentLens: it reads server logs, tells verified agents from humans (Web Bot Auth signatures), follows each agent through
the funnel, finds the blocker that ended every failed session, proves it with a replay, and puts a rupee value on it.

On my demo store (synthetic traffic):
- 25.6% of sessions were AI agents, converting at 2.5% vs 3.6% for humans
- A login/OTP wall before the cart alone put about ₹12 L a month at risk
- After three fixes, agent conversion went from 0% to 5.1% (significant, p < 0.001)

[One sentence on why you built it / what you learned.]

It is open source, with a live read-only demo. Link in the first comment.

#AgenticCommerce #AIAgents #Ecommerce #Analytics #OpenSource

**First comment:** Live demo: https://agentlens.ptlabs.in | Code: https://github.com/prateektyagi2203/AgentLens
The data is synthetic; agents that run inside a shopper's own browser look like humans in logs, which is the main limitation.

## Draft B: the build story

I spent [N weeks] building AgentLens, a tool that shows how AI shopping agents experience an online store.

What it does: log ingestion -> agent identification (verified / declared / suspected) -> funnel -> 16 blocker types ->
replay proof -> ₹ at risk -> before/after with a significance test.
What I learned: [1-2 honest lessons, e.g. most agents fetch without JavaScript, so JS-only content and image-only size guides are invisible to them].

Try it (synthetic data, read-only): link in the first comment. Feedback welcome, especially from ecommerce and platform teams.

## Draft C: short

If an AI agent tried to buy from your store today, where would it get stuck?

I built AgentLens to answer that from server logs alone. 2-minute demo below, live link in the comments.

## Posting checklist

- Video uploaded natively, captions on, first 2 lines of the post carry the hook.
- Test the live link on mobile and in a private window before posting; check the link preview shows the og.png card.
- Say "synthetic demo data" in the post or the first comment.
- Be ready to answer comments in the first hour; pin the first comment.
