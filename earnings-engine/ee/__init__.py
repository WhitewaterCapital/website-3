"""WW-EARNINGS — the earnings-calendar + pre-print positioning engine.

Answers one narrow, honest question: for a fixed universe, which names have
a confirmed earnings print inside a lookahead window, and what do this
repo's OWN already-real signals (WW-Insider's SEC EDGAR net buy/sell,
WW-Factor's momentum beta) say about each name going into that print.

Deliberately NOT a surprise-direction predictor. That's the harder model
research/equity-model-research-dossier.md scopes as Phase 2 ("earnings-
surprise direction... Medium confidence... needs analyst estimate data with
poor free coverage") — this engine ships the part of that research that's
honestly buildable on data this repo already has real access to, and
abstains rather than fabricates the rest. See README.md.
"""
