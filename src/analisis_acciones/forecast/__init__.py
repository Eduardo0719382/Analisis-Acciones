"""Statistical price projections (ranges, not predictions). Must not import Qt.

Every projection is a range with stated assumptions, and each method can be
calibrated on the series' own history (walk-forward, no look-ahead) so the
user can see how often such ranges contained the actual price.
"""
