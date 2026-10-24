"""Ядро планировщика: справочники, скоринг, обучение, рекомендация, ссылки. Без БД и без сети."""
from .affinity import compute_affinity, decision_weight, describe_affinity, describe_affinity_text, learning_bonus
from .catalog import ALL_CATS, CATS, DEFAULT_PROFILE, REASONS, VALUE_MAP, VALUES, default_profile, interests_from_values
from .config import scoring_config
from .links import gcal_url, ics_text, outlook_url, plan_text, share_text, tg_share_url
from .recommend import Digest, SlotPick, build_digest, horizon_picks, kind_bonus, recommend_slots
from .scoring import ScoreResult, Why, score, score_events, trim_why
from .timeutil import is_free, is_horizon, reco_slot, slot_of, trim_past, weekend_for, weekend_iso, weekend_title

__all__ = [n for n in dir() if not n.startswith("_")]
