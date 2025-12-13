from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.models import ForceGuidance, ForceLever, ForceProfile, Message


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, round(value, 3)))


@dataclass
class ForceGuidanceResult:
    guidance: ForceGuidance
    message: Message


class ForceGuidanceCircuit:
    """Deterministic guidance producing a strict JSON schema (no metaphors)."""

    TENSION_CUES = ["liikaa", "paljon", "kuormit", "kiire", "stress", "paine"]
    UNCERTAINTY_CUES = ["epäselvä", "epävarma", "en tiedä", "häh", "ehkä", "sumu"]
    INERTIA_CUES = ["jumissa", "en jaksa", "laiska", "hidasta", "jumi", "seisoo"]
    POLARITY_CUES = ["riita", "vastaan", "konflikt", "vastakkain", "pakko", "väänn"]
    LOW_AGENCY_CUES = ["en voi", "ei pysty", "ei onnistu", "ei resursseja", "ei mahda"]

    def __init__(self) -> None:
        pass

    def run(
        self,
        run_id: str,
        user_message: str,
        override_profile: Optional[ForceProfile] = None,
    ) -> ForceGuidanceResult:
        profile, reason_codes = self._infer_profile(user_message, override_profile)
        state_pattern = self._map_state_pattern(profile)
        summary = self._summarize(state_pattern)
        primary = self._primary_lever(reason_codes)
        adjacent = self._adjacent_options(profile, primary)

        guidance = ForceGuidance(
            situation_summary=summary,
            primary_lever=primary,
            adjacent_options=adjacent,
            profile=profile,
            reason_codes=reason_codes,
            state_pattern=state_pattern,
        )
        message = Message(
            run_id=run_id,
            sender="ForceGuidanceCircuit",
            recipient="SpeakerAgent",
            role="force_guidance",
            payload={"force_guidance": guidance.as_dict()},
        )
        return ForceGuidanceResult(guidance=guidance, message=message)

    def _infer_profile(
        self,
        text: str,
        override_profile: Optional[ForceProfile],
    ) -> tuple[ForceProfile, List[str]]:
        lower = text.lower()
        profile = ForceProfile()
        reason_codes: List[str] = []

        def bump(attr: str, delta: float = 0.18) -> None:
            value = getattr(profile, attr)
            setattr(profile, attr, _clamp(value + delta))

        def drop(attr: str, delta: float = 0.18) -> None:
            value = getattr(profile, attr)
            setattr(profile, attr, _clamp(value - delta))

        for cue in self.TENSION_CUES:
            if cue in lower:
                bump("tension")
        for cue in self.INERTIA_CUES:
            if cue in lower:
                bump("inertia")
        for cue in self.UNCERTAINTY_CUES:
            if cue in lower:
                bump("uncertainty")
        for cue in self.POLARITY_CUES:
            if cue in lower:
                bump("polarity")
        for cue in self.LOW_AGENCY_CUES:
            if cue in lower:
                drop("agency", 0.24)

        if override_profile:
            profile = self._merge_profile(profile, override_profile)

        if profile.tension >= 0.65:
            reason_codes.append("high_tension")
        if profile.uncertainty >= 0.6:
            reason_codes.append("high_uncertainty")
        if profile.inertia >= 0.6:
            reason_codes.append("high_inertia")
        if profile.polarity >= 0.55:
            reason_codes.append("high_polarity")
        if profile.agency <= 0.45:
            reason_codes.append("low_agency")
        if not reason_codes:
            reason_codes.append("balanced")
        return profile, reason_codes

    def _merge_profile(self, base: ForceProfile, override: ForceProfile) -> ForceProfile:
        return ForceProfile(
            tension=_clamp((base.tension + override.tension) / 2),
            uncertainty=_clamp((base.uncertainty + override.uncertainty) / 2),
            inertia=_clamp((base.inertia + override.inertia) / 2),
            polarity=_clamp((base.polarity + override.polarity) / 2),
            agency=_clamp((base.agency + override.agency) / 2),
        )

    def _map_state_pattern(self, profile: ForceProfile) -> str:
        if profile.tension > 0.7 and profile.inertia > 0.55:
            return "overload"
        if profile.uncertainty > 0.65:
            return "fog"
        if profile.polarity > 0.6:
            return "standoff"
        if profile.inertia > 0.65:
            return "drift"
        if profile.tension > 0.6:
            return "friction"
        return "steady"

    def _summarize(self, pattern: str) -> str:
        summaries = {
            "fog": "Tilanne on epäselvä ja päätös puuttuu.",
            "overload": "Kuormaa on liikaa ja liike pysähtyy.",
            "standoff": "Näkemykset vetävät eri suuntiin.",
            "drift": "Eteneminen on hidasta ja jumiutuu.",
            "friction": "Työ hidastuu häiriöiden vuoksi.",
            "steady": "Tilanne on hallittavissa mutta tarvitsee seuraavan siirron.",
        }
        return summaries.get(pattern, summaries["steady"])

    def _primary_lever(self, reason_codes: List[str]) -> ForceLever:
        if "high_uncertainty" in reason_codes:
            return ForceLever(
                name="Kynnyskysymys ensin",
                rationale="Epäselvyys hidastaa kaikkea muuta; yksi kynnyskysymys kirkastaa suunnan.",
                first_step="Kirjaa yksi kynnyskysymys ja sovi kuka vastaa siihen tänään.",
            )
        if "high_inertia" in reason_codes:
            return ForceLever(
                name="Pienin askel",
                rationale="Jumitus purkautuu liikkeellä; pienin askel vähentää kitkaa.",
                first_step="Valitse 10 minuutin askel, joka poistaa yhden kitkalähteen.",
            )
        if "high_tension" in reason_codes:
            return ForceLever(
                name="Kevennä kuormaa",
                rationale="Ylikuorma pysäyttää etenemisen; poista yksi vaatimus.",
                first_step="Poista tai siirrä yksi pakollinen asia pois tältä viikolta.",
            )
        if "high_polarity" in reason_codes:
            return ForceLever(
                name="Yhteinen tavoite",
                rationale="Vastakkainasettelu laukeaa, kun tavoite on jaettu.",
                first_step="Nimeä yhteinen päämäärä ja ehdota yhtä reilua kompromissia.",
            )
        if "low_agency" in reason_codes:
            return ForceLever(
                name="Nosta toimijuutta",
                rationale="Alhainen toimijuus pysäyttää muutoksen; pyydä tukea tai päätösvaltaa.",
                first_step="Etsi yksi päättäjä tai tukihenkilö ja tee pyyntö nyt.",
            )
        return ForceLever(
            name="Selkeytä seuraava siirto",
            rationale="Selkeä seuraava askel pitää liikkeen yllä.",
            first_step="Sovi yksi 10 minuutin tehtävä ja aloita se heti.",
        )

    def _adjacent_options(self, profile: ForceProfile, primary: ForceLever) -> List[ForceLever]:
        options: List[ForceLever] = []

        def add_option(name: str, first_step: str) -> None:
            if all(opt.name != name for opt in options) and name != primary.name:
                options.append(ForceLever(name=name, rationale="", first_step=first_step))

        if profile.uncertainty > 0.5:
            add_option("Rajaa päätös", "Valitse yksi päätös joka on pakko tehdä tänään.")
        if profile.inertia > 0.5:
            add_option("Poista este", "Poista yksi lupa- tai työkalueste nyt.")
        if profile.tension > 0.55:
            add_option("Supista tehtävälista", "Pudota yksi vähiten tärkeä tehtävä tältä päivältä.")
        if profile.polarity > 0.45:
            add_option("Sovi kriteeri", "Sovi yhdestä päätöskriteeristä ja testaa vaihtoehdot sitä vasten.")
        if profile.agency < 0.55:
            add_option("Hae tuki", "Pingaa sponsori tai kollega ja pyydä päätös yhdestä esteestä.")

        filler_pool = [
            ForceLever("Hae datapiste", "", "Hae yksi fakta, joka vahvistaa tai kumoaa oletuksen."),
            ForceLever("Tee tilannekierros", "", "Sovi 10 minuutin kierros ja kysy suurin este jokaiselta."),
            ForceLever("Jaa työ", "", "Delegoi yksi tehtävä ja vahvista vastuu."),
        ]
        for opt in filler_pool:
            if len(options) >= 3:
                break
            if all(existing.name != opt.name for existing in options) and opt.name != primary.name:
                options.append(opt)
        return options[:3]
