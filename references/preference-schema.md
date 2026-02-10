# Preference Schema Reference

## Full Schema (v2)

```json
{
  "version": 2,
  "core_interests": [],
  "methods_interests": [],
  "positive_signals": [],
  "negative_signals": [],
  "favorite_authors": [],
  "arxiv_categories": [],
  "last_updated": "YYYY-MM-DD",
  "history": []
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | Schema version for future migration |
| `core_interests` | string[] | Primary research topics (e.g., "cosmology", "weak lensing", "galaxy clustering") |
| `methods_interests` | string[] | Preferred techniques/methods (e.g., "simulation-based inference", "neural networks", "MCMC") |
| `positive_signals` | string[] | Specific keywords or subtopics that boost relevance (learned from feedback) |
| `negative_signals` | string[] | Topics to deprioritize (e.g., "warm inflation", "string cosmology") |
| `favorite_authors` | string[] | Author last names to watch for |
| `arxiv_categories` | string[] | Arxiv category codes to fetch (e.g., "astro-ph.CO", "stat.ML") |
| `last_updated` | string | ISO date of last preference update |
| `history` | object[] | Log of feedback sessions for transparency |

### History Entry Schema

Each time preferences are updated from user feedback, append an entry:

```json
{
  "date": "2025-11-14",
  "liked_papers": ["2511.10616", "2511.09660"],
  "disliked_topics": ["holographic dark matter"],
  "new_positive_signals": ["EFTofLSS", "out-of-domain detection"],
  "new_negative_signals": ["holographic dark matter"],
  "notes": "User strongly prefers methods/inference papers over pure theory"
}
```

### Category Reference

Common arxiv categories for cosmology/astrophysics users:

| Category | Description |
|----------|-------------|
| `astro-ph.CO` | Cosmology and Nongalactic Astrophysics |
| `astro-ph.GA` | Astrophysics of Galaxies |
| `astro-ph.IM` | Instrumentation and Methods for Astrophysics |
| `astro-ph.HE` | High Energy Astrophysical Phenomena |
| `stat.ML` | Machine Learning (Statistics) |
| `stat.ME` | Methodology (Statistics) |
| `cs.LG` | Machine Learning (CS) |
| `hep-ph` | High Energy Physics - Phenomenology |
| `gr-qc` | General Relativity and Quantum Cosmology |

For users in other fields, adjust accordingly. The user should have 2-5 primary categories.

### Default Profile (Cosmology Example)

When a user says something like "I'm interested in cosmology, galaxy surveys, systematics, inference, and ML", create:

```json
{
  "version": 2,
  "core_interests": [
    "cosmology",
    "galaxy surveys",
    "large-scale structure",
    "weak lensing",
    "galaxy clustering",
    "cosmic shear"
  ],
  "methods_interests": [
    "simulation-based inference",
    "Bayesian inference",
    "MCMC",
    "neural networks",
    "machine learning",
    "emulators",
    "Gaussian processes",
    "likelihood-free inference"
  ],
  "positive_signals": [
    "systematics",
    "photometric redshifts",
    "intrinsic alignments",
    "covariance estimation",
    "selection effects",
    "forward modeling",
    "power spectrum",
    "bispectrum",
    "field-level inference"
  ],
  "negative_signals": [],
  "favorite_authors": [],
  "arxiv_categories": [
    "astro-ph.CO",
    "astro-ph.GA",
    "astro-ph.IM",
    "stat.ML"
  ],
  "last_updated": "2025-11-14",
  "history": []
}
```

### Updating Rules

When updating preferences from feedback:

1. **Liked papers** → Extract 1-2 specific keywords from their abstracts and add to `positive_signals` (avoid duplicates). If a topic appears in liked papers 3+ times across sessions, consider promoting to `core_interests`.

2. **Disliked topics** → Add to `negative_signals`. These are soft filters — papers with negative signals are ranked lower but not hidden. A paper can still surface if it has strong positive signals.

3. **Authors** → Add to `favorite_authors` by last name. Papers by favorite authors get a relevance boost.

4. **Category adjustment** → If the user consistently likes papers from a cross-listed category not in their list, suggest adding it.

5. **Decay** → Negative signals don't decay. Positive signals should be refreshed periodically — if a user hasn't shown interest in a positive signal for 10+ sessions, it may be worth asking if it's still relevant.
