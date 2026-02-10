# Scoring Guide for Paper Ranking

## Philosophy

The goal is NOT a mechanical keyword-count score. The goal is to simulate what a knowledgeable colleague would highlight if they were reading arxiv for you. Use judgment. A paper about "neural network emulators for the matter power spectrum" is highly relevant to someone interested in {cosmology, ML, emulators} even if it doesn't literally contain the word "survey".

## Scoring Tiers

### Tier 1: "Read this today" (Top Picks)

A paper belongs in Tier 1 if it matches **2+ core interests** OR **1 core interest + 1 methods interest**, AND the paper has substance (not just a 2-page comment or erratum).

Examples of strong Tier 1 matches for a cosmology/surveys/ML user:
- "Simulation-based inference for galaxy cluster cosmology with Capish" → SBI + clusters + cosmology
- "Multiprobe analysis combining BOSS full-shape + DESI + Planck lensing" → surveys + inference + LSS
- "Bayesian model comparison with GPR for 21-cm recovery" → Bayesian + ML + systematics
- "Intrinsic alignment measurement in DES Y3" → galaxy survey + systematics

### Tier 2: "Interesting, skim the abstract" (Solid matches)

Matches 1 core interest + some methodological overlap, or is a major survey result:
- "DESI DR2 BAO measurements" → major survey result even if methods aren't novel
- "New constraint on neutrino mass from Planck" → cosmology but not methods-focused
- "Fisher forecasts for Roman Space Telescope" → survey forecasting

### Tier 3: "Boundary Expanders"

These are the papers you wouldn't normally read but should. They match on **method** but not **domain**, or introduce a **new technique** from another field:
- "Deep learning for out-of-domain detection in scientific inference" → ML method applicable to user's problems
- "New emulator architecture for expensive simulations" → emulation technique, different application
- "Bayesian model comparison in particle physics" → same stats, different field

### Tier 4: "Skip unless curious"

Papers that are purely in the user's category but don't match interests:
- "Modified gravity model with exotic scalar field" (if user is methods/data focused)
- "Analytical solution for primordial power spectrum" (if user doesn't do early universe)

## Scoring Signals — Detailed

### From Title
Titles are very informative. Watch for:
- Survey names: DESI, Euclid, Rubin/LSST, DES, HSC, KiDS, SPT, ACT, Planck, Roman, SKA
- Method keywords: inference, Bayesian, neural network, emulator, simulation-based, likelihood-free, MCMC, Fisher
- Topic keywords: match against core_interests
- "First measurement of..." or "New constraint on..." — often high-impact

### From Abstract
The abstract gives you the full picture. Look for:
- What data/simulations are used
- What method is applied
- What's the main result
- Is there a code release or public tool

### From Authors
If the user has `favorite_authors`, any match is a strong signal. Even without explicit favorites, you can learn from context: if the user keeps liking papers by the same group, suggest adding them.

### From Categories
Cross-listing is informative:
- `astro-ph.CO` + `astro-ph.IM` → methods paper applied to cosmology (good for methods users)
- `astro-ph.CO` + `stat.ML` → ML paper in cosmology (great for ML+cosmo users)
- `astro-ph.CO` + `hep-th` → very theoretical, less likely for data-oriented users

## Example Ranking Session

User profile: cosmology, galaxy surveys, systematics, SBI, ML

Papers on a given day:
1. "SBI for cluster cosmology with Capish" → **Tier 1** (SBI + clusters + cosmology)
2. "Multiprobe dark energy with EFTofLSS + angular Cℓ" → **Tier 1** (surveys + inference + DE)
3. "Bayesian GPR for 21-cm" → **Tier 1** (Bayesian + ML + systematics)
4. "Intrinsic alignment in DES Y3" → **Tier 1** (survey + IA systematic)
5. "Neutrino emulator Cosmic-Enu-II" → **Tier 1** (emulator + neutrinos + cosmology)
6. "PINN for Hubble tension" → **Tier 2** (ML + cosmology, but model-dependent)
7. "DM self-interaction via deep clustering" → **Tier 1** (ML + inference + robustness)
8. "Dark photons in radio sky" → **Tier 3** boundary expander (survey cross-correlation, new probe)
9. "Holographic dark matter" → **Tier 4** (pure theory, no data)
10. "Warm inflation composite dissipation" → **Tier 4** (early universe theory)
11. "Scalar field dark energy model" → **Tier 4** (model building)

Present: papers 1-7 as Top Picks, paper 8 as Boundary Expander. Mention 9-11 only if asked.

## Network-Aware Scoring

When a researcher profile is available, network signals should be layered on top of topic scoring. The network provides "social" relevance — papers from the user's research community.

### Co-author boost examples

User: cosmologist who frequently co-authors with Alice (SBI expert) and Bob (weak lensing).

| Paper | Topic score | Network signal | Final tier |
|-------|------------|----------------|------------|
| "New SBI method for clusters" by Alice et al. | High (SBI + clusters) | Active co-author | **Tier 1, top** |
| "Stellar evolution models" by Alice et al. | Low (off-topic) | Active co-author | **Tier 2** (surface because of Alice) |
| "Weak lensing systematics" by Charlie (collaborates with Bob) | High | 2nd-degree | **Tier 1** |
| "Galaxy morphology CNN" by unknown | Moderate (ML) | None | **Tier 2** |

### How to identify network matches

1. Load `network.active_coauthors` and `network.coauthor_rank` from the profile
2. For each paper's author list, check if any author matches a known name
3. Use fuzzy matching: "A. Smith" matches "Alice Smith", "Smith, A." matches too
4. For 2nd-degree matches, check `network.second_degree_rank`

### Presenting network context

When a paper is boosted by network signals, explain WHY to the user:
- "👥 Your co-author Alice Smith is on this paper"
- "🔗 This is by Charlie, who frequently collaborates with your co-author Bob"
- "📎 This paper appears to cite your work [2301.00001]"

This transparency helps the user trust the ranking and gives them useful social context.

## Anti-Patterns

Avoid these common mistakes:
- **Don't rank by recency of the topic in the news** — rank by match to user interests
- **Don't over-index on a single keyword** — "Bayesian" alone doesn't make a particle physics paper relevant to a cosmologist
- **Don't ignore cross-lists** — some of the best finds are cross-listed from other categories
- **Don't present too many papers** — 10-13 is the sweet spot. More than 15 becomes noise.
- **Don't copy the entire abstract** — summarize in your own words, focusing on what matters to this user
